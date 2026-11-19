#!/usr/bin/env python3
"""Dati a grana fine per la rete neurale: ogni scambio delle 12 crypto su Kraken, in euro.

    python3 rete_dati.py                  # scarica gli ultimi 400 giorni (riprende da dove era arrivato)
    python3 rete_dati.py --giorni 60      # solo gli ultimi 60 giorni
    python3 rete_dati.py --stato          # cosa c'è già in cache

Perché gli scambi e non le candele: Kraken dà solo le ultime 720 candele per ogni passo (12 ore a un minuto), ma
conserva ogni scambio dalla nascita della coppia. Dagli scambi si ricostruisce qualsiasi passo, e si ha anche il
verso (acquisto o vendita a mercato) di ogni scambio. Sono dati pubblici e gratuiti, uno scambio ogni tanto
(Bitcoin circa 740 all'ora, le altre molto meno): il prezzo in euro non cambia ogni secondo.

Un file per crypto e per giorno UTC, in trader/cache/rete/scambi/<SIMBOLO>/<AAAA-MM-GG>.npz, con le colonne
t (secondi), p (prezzo), v (quantità), s (+1 acquisto, -1 vendita), m (1 mercato, 0 limite).
Si parte dai giorni più recenti; i giorni già scaricati si saltano. Solo libreria standard e numpy.
"""

import argparse
import datetime
import json
import os
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "trader", "cache", "rete", "scambi")
UA = "Mozilla/5.0 (finanza-rete)"
URL = "https://api.kraken.com/0/public/Trades?pair=%s&since=%d"
# le stesse 12 crypto dell'app (crypto_live.COPPIE), con il nome della coppia su Kraken
COPPIE = {"BTC-EUR": "XBTEUR", "ETH-EUR": "ETHEUR", "SOL-EUR": "SOLEUR", "XRP-EUR": "XRPEUR", "BNB-EUR": "BNBEUR",
          "ADA-EUR": "ADAEUR", "DOGE-EUR": "DOGEEUR", "LTC-EUR": "LTCEUR", "DOT-EUR": "DOTEUR",
          "LINK-EUR": "LINKEUR", "AVAX-EUR": "AVAXEUR", "TRX-EUR": "TRXEUR"}
GIORNO = 86400


class Ritmo:
    """Un limite di richieste al secondo, comune a tutti i fili; rallenta se Kraken chiede di rallentare."""

    def __init__(self, al_secondo=3.0, massimo=4.0):
        self.passo, self.massimo, self.prossima = 1.0 / al_secondo, massimo, 0.0
        self.lock = threading.Lock()
        self.ok = 0

    def attendi(self):
        with self.lock:
            adesso = time.time()
            self.prossima = max(self.prossima, adesso) + self.passo
            pausa = self.prossima - self.passo - adesso
        if pausa > 0:
            time.sleep(pausa)

    def rallenta(self):
        with self.lock:
            self.passo = min(2.0, self.passo * 1.7)
            self.ok = 0

    def accelera(self):
        with self.lock:
            self.ok += 1
            if self.ok >= 200 and self.passo > 1.0 / self.massimo:
                self.passo = max(1.0 / self.massimo, self.passo * 0.9)
                self.ok = 0


def chiedi(coppia, since_ns, ritmo, tentativi=8):
    """Una pagina di al più 1000 scambi dopo since_ns: (scambi, ultimo). Riprova con pazienza."""
    err = None
    for k in range(tentativi):
        ritmo.attendi()
        try:
            req = urllib.request.Request(URL % (coppia, since_ns), headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
            if d.get("error"):
                err = "; ".join(d["error"])
                if "rate" in err.lower() or "many" in err.lower() or "limit" in err.lower():
                    ritmo.rallenta()
                    time.sleep(min(60, 4 * (k + 1)))
                    continue
                raise RuntimeError(err)
            res = d["result"]
            chiave = next(x for x in res if x != "last")
            ritmo.accelera()
            return res[chiave], int(res["last"])
        except (OSError, ValueError) as e:                   # rete, JSON a metà: si riprova
            err = str(e)
            time.sleep(min(30, 2 * (k + 1)))
    raise RuntimeError("Kraken %s: %s" % (coppia, err))


def scarica_da(sym, da_s, ritmo=None, cursore=None):
    """Gli scambi dopo `da_s` (secondi UTC), anche del giorno ancora a metà, fino a adesso: serve a chi segue il mercato dal
    vivo. Se si passa il `cursore` di una chiamata prima, riparte da lì. Ritorna (t, p, v, s, cursore): array e dove riprendere."""
    ritmo = ritmo or Ritmo()
    since = int(cursore) if cursore else int(da_s * 1e9)
    t, p, v, s = [], [], [], []
    while True:
        scambi, ultimo = chiedi(COPPIE[sym], since, ritmo)
        if not scambi:
            break
        for x in scambi:
            if x[2] > da_s:
                t.append(x[2]); p.append(float(x[0])); v.append(float(x[1])); s.append(1 if x[3] == "b" else -1)
        if len(scambi) < 1000 or ultimo <= since:
            since = max(since, ultimo)
            break
        since = ultimo
    return (np.array(t, dtype=np.float64), np.array(p, dtype=np.float64), np.array(v, dtype=np.float64),
            np.array(s, dtype=np.int8), since)


def percorso(sym, giorno):
    return os.path.join(CACHE, sym, "%s.npz" % giorno)


def scarica_giorno(sym, giorno, ritmo, cartella=None):
    """Tutti gli scambi di un giorno UTC (giorno = 'AAAA-MM-GG'). Salva il file e ritorna quanti scambi."""
    inizio = datetime.datetime.strptime(giorno, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc).timestamp()
    fine = inizio + GIORNO
    since, t, p, v, s, m = int((inizio - 1) * 1e9), [], [], [], [], []
    while True:
        scambi, ultimo = chiedi(COPPIE[sym], since, ritmo)
        if not scambi:
            break
        for x in scambi:
            if x[2] >= fine:
                break
            if x[2] >= inizio:
                t.append(x[2]); p.append(float(x[0])); v.append(float(x[1]))
                s.append(1 if x[3] == "b" else -1); m.append(1 if x[4] == "m" else 0)
        if scambi[-1][2] >= fine or ultimo <= since:
            break
        since = ultimo
    destinazione = percorso(sym, giorno) if cartella is None else os.path.join(cartella, sym, giorno + ".npz")
    os.makedirs(os.path.dirname(destinazione), exist_ok=True)
    tmp = destinazione + ".tmp.npz"
    np.savez_compressed(tmp, t=np.array(t, dtype=np.float64), p=np.array(p, dtype=np.float64),
                        v=np.array(v, dtype=np.float64), s=np.array(s, dtype=np.int8), m=np.array(m, dtype=np.int8))
    os.replace(tmp, destinazione)
    return len(t)


def giorni_da_fare(n_giorni, adesso=None):
    """I giorni UTC completi degli ultimi n_giorni, dal più recente (oggi è ancora a metà: non si scarica)."""
    oggi = datetime.datetime.fromtimestamp(time.time() if adesso is None else adesso, datetime.timezone.utc).date()
    return [(oggi - datetime.timedelta(days=k)).isoformat() for k in range(1, n_giorni + 1)]


def scarica(n_giorni, simboli=None, fili=4, log=print, al_secondo=3.0, massimo=4.0):
    ritmo = Ritmo(al_secondo, massimo)
    simboli = simboli or list(COPPIE)
    # prima i giorni più recenti, dentro lo stesso giorno le crypto più attive (più chiamate)
    lavori = [(sym, g) for g in giorni_da_fare(n_giorni) for sym in simboli if not os.path.exists(percorso(sym, g))]
    pesi = {"BTC-EUR": 0, "SOL-EUR": 1, "ETH-EUR": 2}
    lavori.sort(key=lambda w: (-int(w[1].replace("-", "")), pesi.get(w[0], 9)))
    log("[rete_dati] %d giorni x %d crypto da scaricare (%d già in cache)" % (
        n_giorni, len(simboli), n_giorni * len(simboli) - len(lavori)))
    fatti, t0, lock = [0], time.time(), threading.Lock()

    def uno(w):
        sym, g = w
        n = scarica_giorno(sym, g, ritmo)
        with lock:
            fatti[0] += 1
            if fatti[0] % 25 == 0 or fatti[0] == len(lavori):
                log("[rete_dati] %d/%d · ultimo %s %s (%d scambi) · %.0f minuti" % (
                    fatti[0], len(lavori), sym, g, n, (time.time() - t0) / 60))
        return n

    with ThreadPoolExecutor(max_workers=fili) as ex:
        totale = sum(ex.map(uno, lavori))
    log("[rete_dati] finito: %d scambi in %.0f minuti" % (totale, (time.time() - t0) / 60))


def stato():
    out = {}
    for sym in COPPIE:
        d = os.path.join(CACHE, sym)
        giorni = sorted(f[:-4] for f in os.listdir(d) if f.endswith(".npz") and not f.endswith(".tmp.npz")) if os.path.isdir(d) else []
        out[sym] = (len(giorni), giorni[0] if giorni else None, giorni[-1] if giorni else None)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--giorni", type=int, default=400)
    ap.add_argument("--fili", type=int, default=4)
    ap.add_argument("--al-secondo", type=float, default=3.0, help="richieste al secondo di partenza")
    ap.add_argument("--massimo", type=float, default=4.0, help="richieste al secondo al massimo (se Kraken non chiede di rallentare)")
    ap.add_argument("--stato", action="store_true")
    a = ap.parse_args(argv)
    if a.stato:
        for sym, (n, p, u) in stato().items():
            print("%-9s %4d giorni  %s … %s" % (sym, n, p, u))
        return 0
    scarica(a.giorni, fili=a.fili, al_secondo=a.al_secondo, massimo=a.massimo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
