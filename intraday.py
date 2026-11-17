#!/usr/bin/env python3
"""Crypto intraday: entrate e uscite per le prossime 24 ore, con la verifica delle stesse regole
sugli ultimi 2 anni di candele orarie (Yahoo Finance).

    python3 intraday.py        # stampa i piani di oggi e la verifica; app.py li mette nella sezione Crypto

Due regole, fissate prima di guardare i risultati, più il confronto "compra e vendi dopo 24 ore":
  Ribasso  ordine limite sotto il prezzo attuale (ultima chiusura oraria - 3 ATR orari);
           protezione 3 ATR sotto l'entrata, obiettivo il prezzo di partenza.
  Rottura  ordine che scatta se il prezzo supera il massimo delle ultime 24 ore;
           protezione 1,5 ATR sotto, obiettivo il doppio del rischio sopra.
  Il piano vale 24 ore: se l'ordine non scatta, niente operazione; se scatta, si chiude al più
  tardi 24 ore dopo l'inizio del piano. Costi 0,2 % per lato. ATR = escursione media di una
  candela oraria nelle ultime 24 ore.
La verifica rifà il piano alle 17 e alle 21 UTC (quando si aggiorna l'app) di ogni giorno degli
ultimi 2 anni, per tutte e 12 le crypto, e separa il primo anno dal secondo.
Solo libreria standard. Non è consulenza finanziaria.
"""

import datetime
import json
import os
import sys
import time
import urllib.request

import simula

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "trader", "cache", "intraday")
UA = "Mozilla/5.0 (compatible; finanza/1.0)"
COSTO = 0.002                      # per lato
ORE = 24
REGOLE = [
    {"id": "ribasso", "nome": "Compra il ribasso",
     "desc": "Ordine limite 3 escursioni orarie sotto il prezzo; protezione 3 escursioni sotto l'entrata; obiettivo il prezzo di partenza."},
    {"id": "rottura", "nome": "Compra la rottura",
     "desc": "Ordine che scatta sopra il massimo delle ultime 24 ore; protezione 1,5 escursioni sotto; obiettivo il doppio del rischio."},
    {"id": "tempo", "nome": "Compra ora, vendi tra 24 ore", "desc": "Il confronto: nessun livello, solo il tempo."},
]


def candele(sym, max_age=3600):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, sym + ".json")
    if not os.path.exists(path) or time.time() - os.path.getmtime(path) > max_age:
        url = "https://query2.finance.yahoo.com/v8/finance/chart/%s?range=730d&interval=1h" % sym
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=40) as r:
            text = r.read().decode("utf-8", "replace")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(path, encoding="utf-8") as fh:
        res = json.load(fh)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = [(t, o, h, l, c) for t, o, h, l, c in zip(res["timestamp"], q["open"], q["high"], q["low"], q["close"])
           if None not in (o, h, l, c)]
    return out[:-1]                                          # l'ultima candela è ancora in corso


def atr(B, i, n=24):
    return sum(max(B[k][2] - B[k][3], abs(B[k][2] - B[k - 1][4]), abs(B[k][3] - B[k - 1][4]))
               for k in range(i - n + 1, i + 1)) / n


def livelli(B, i, regola):
    """Entrata, protezione e obiettivo del piano fatto alla chiusura della candela i."""
    c, a = B[i][4], atr(B, i)
    if regola == "ribasso":
        e = c - 3 * a
        return {"entrata": e, "tipo": "limite", "protezione": e - 3 * a, "obiettivo": c}
    if regola == "rottura":
        e = max(b[2] for b in B[i - 23:i + 1])
        return {"entrata": e, "tipo": "sopra", "protezione": e - 1.5 * a, "obiettivo": e + 3 * a}
    return {"entrata": c, "tipo": "subito", "protezione": None, "obiettivo": None}


def esito(B, i, regola):
    """Rendimento netto del piano fatto alla candela i, 'no' se l'ordine non scatta, None senza dati."""
    win = B[i + 1:i + 1 + ORE]
    if len(win) < ORE:
        return None
    lv = livelli(B, i, regola)
    if regola == "tempo":
        return win[-1][4] / B[i][4] - 1 - 2 * COSTO
    e, stop, tgt = lv["entrata"], lv["protezione"], lv["obiettivo"]
    trig = None
    for k, b in enumerate(win):
        if (regola == "ribasso" and b[3] <= e) or (regola == "rottura" and b[2] >= e):
            trig = k
            fill = min(e, b[1]) if regola == "ribasso" else max(e, b[1])
            break
    if trig is None:
        return "no"
    for k in range(trig, len(win)):
        b = win[k]
        if k > trig and b[1] <= stop:
            return b[1] / fill - 1 - 2 * COSTO
        if k > trig and b[1] >= tgt:
            return b[1] / fill - 1 - 2 * COSTO
        if b[3] <= stop:
            return stop / fill - 1 - 2 * COSTO
        if b[2] >= tgt:
            return tgt / fill - 1 - 2 * COSTO
    return win[-1][4] / fill - 1 - 2 * COSTO


def stat(xs):
    done = sorted(x for x in xs if x != "no")
    if not done:
        return {"n": 0, "eseguite": 0}
    return {"n": len(done), "eseguite": round(len(done) / len(xs), 4),
            "p_gain": round(sum(1 for x in done if x > 0) / len(done), 4),
            "media": round(sum(done) / len(done), 5), "tipico": round(done[len(done) // 2], 5),
            "p10": round(done[len(done) // 10], 5), "p90": round(done[9 * len(done) // 10], 5)}


def analizza(log=print):
    per, tutti = {}, {r["id"]: {"anno1": [], "anno2": []} for r in REGOLE}
    for sym in simula.CRYPTO:
        try:
            B = candele(sym)
        except Exception as e:                               # rete, dati mancanti
            log("[intraday] %s saltato: %s" % (sym, e))
            continue
        storia = {r["id"]: [] for r in REGOLE}
        for i in range(200, len(B) - ORE - 1):
            h = datetime.datetime.fromtimestamp(B[i][0] + 3600, datetime.timezone.utc).hour
            if h not in (17, 21):
                continue
            meta = "anno1" if B[i][0] < B[0][0] + 365 * 86400 else "anno2"
            for r in REGOLE:
                x = esito(B, i, r["id"])
                if x is not None:
                    storia[r["id"]].append(x)
                    tutti[r["id"]][meta].append(x)
        i = len(B) - 1
        ora = datetime.datetime.fromtimestamp(B[i][0] + 3600, datetime.timezone.utc)
        per[sym] = {"prezzo": round(B[i][4], 6), "ora": ora.strftime("%Y-%m-%d %H:%M UTC"),
                    "fino": (ora + datetime.timedelta(hours=ORE)).strftime("%Y-%m-%d %H:%M UTC"),
                    "piani": {r["id"]: {k: (round(v, 6) if isinstance(v, float) else v)
                                        for k, v in livelli(B, i, r["id"]).items()} for r in REGOLE},
                    "storia": {k: stat(v) for k, v in storia.items()}}
    verifica = {k: {"anno1": stat(v["anno1"]), "anno2": stat(v["anno2"]), "tutto": stat(v["anno1"] + v["anno2"])}
                for k, v in tutti.items()}
    return {"regole": REGOLE, "costo_per_lato": COSTO, "ore": ORE, "crypto": per, "verifica": verifica}


def main():
    r = analizza()
    f = lambda s: ("%3.0f%% eseguite, %3.0f%% in guadagno, media %+.2f%%, 1 su 10 sotto %+.1f%%" % (
        100 * s["eseguite"], 100 * s["p_gain"], 100 * s["media"], 100 * s["p10"])) if s.get("n") else "nessuna"
    print("VERIFICA (2 anni, 12 crypto, piani alle 17 e alle 21 UTC, costi 0,2 % per lato)")
    for reg in REGOLE:
        v = r["verifica"][reg["id"]]
        print("  %-30s anno 1: %s\n  %-30s anno 2: %s" % (reg["nome"], f(v["anno1"]), "", f(v["anno2"])))
    print("\nPIANI PER LE PROSSIME 24 ORE")
    for sym, x in r["crypto"].items():
        p = x["piani"]["ribasso"]
        print("  %-9s %12s · ribasso: compra a %s, protezione %s, obiettivo %s · fino a %s" % (
            sym, x["prezzo"], round(p["entrata"], 6), round(p["protezione"], 6), round(p["obiettivo"], 6), x["fino"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
