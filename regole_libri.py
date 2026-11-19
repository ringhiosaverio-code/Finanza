#!/usr/bin/env python3
"""Le regole intraday di due testi indicati dall'utente, scritte in codice e verificate sui dati, con i costi.

    python3 regole_libri.py          # scarica 2 anni di barre orarie (Yahoo), prova le regole, scrive regole_libri.json

Dalla tesi di Claudio Sperti, "Silloge di metodi operativi per il trading azionario intraday" (Università di Bologna,
relatore Emilio Tomasini, a.a. 2009/2010), provate lì sui titoli del FTSE MIB con barre da 5 e 60 minuti:
  gap_sperti   apre più dell'1 % sotto la chiusura di ieri: compra all'apertura; obiettivo la chiusura di ieri +2 %,
               stop -1 % dall'entrata, altrimenti si chiude in chiusura (Opening Gap, lato acquisti);
  altucher     come sopra ma con un'apertura almeno 2 % sotto (Opening Gap di James Altucher);
  connors_8020 ieri ha aperto nel 20 % alto della barra e chiuso nel 20 % basso; oggi apre sotto il minimo di ieri di
               almeno l'1 %: compra se il prezzo risale al minimo di ieri; obiettivo +4 %, stop -1 % (80-20 di Connors);
  oops         ieri escursione sotto la media di 14 giorni e media di 9 giorni sopra quella di 18; oggi apre sotto il
               minimo di ieri: compra se risale al minimo di ieri; obiettivo il massimo di ieri, stop -1 % (Oops di
               Larry Williams, versione della tesi).
Da Corey Rosenbloom, "Guida completa al trading" (cap. 10), sulle barre orarie:
  impulse_buy  trend al rialzo (media esponenziale a 20 sopra quella a 50) e nelle ultime 10 barre un nuovo massimo
               di 20 barre sia del prezzo sia del momentum (oscillatore MACD 3/10); compra quando il prezzo torna sulla
               media a 20; stop sotto la media a 50, obiettivo il massimo dell'impulso;
  cradle       incrocio rialzista delle medie a 20 e 50 nelle ultime 10 barre; compra quando il prezzo torna
               sull'incrocio (la media a 20); stop 1 % sotto, obiettivo 2 volte il rischio (il rapporto di almeno 2 a 1
               che il libro raccomanda).
Azioni: tutto si chiude in chiusura, costi 0,1 % per lato. Crypto (solo Rosenbloom: non hanno apertura né chiusura):
uscita al più tardi dopo 24 ore, costi 0,2 % per lato. Se nella stessa barra si toccano stop e obiettivo, vale lo stop
(il caso peggiore). Niente leva. Non è consulenza finanziaria.
"""

import datetime
import json
import math
import os
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "trader", "cache", "regole_libri")
USCITA = os.path.join(ROOT, "regole_libri.json")
ROMA = ZoneInfo("Europe/Rome")
UA = "Mozilla/5.0 (finanza-regole)"
COSTO_AZIONI, COSTO_CRYPTO = 0.001, 0.002
REGOLE_AZIONI = ("gap_sperti", "altucher", "connors_8020", "oops", "impulse_buy", "cradle")
REGOLE_CRYPTO = ("impulse_buy", "cradle")
NOMI = {"gap_sperti": "Opening Gap all'1 % (tesi di Sperti)", "altucher": "Opening Gap al 2 % di James Altucher (tesi di Sperti)",
        "connors_8020": "80-20 di Larry Connors (tesi di Sperti)", "oops": "Oops di Larry Williams, versione della tesi",
        "impulse_buy": "Impulse buy di Rosenbloom", "cradle": "Bullish cradle di Rosenbloom"}


def orarie(sym, max_age=12 * 3600):
    """Barre da 60 minuti degli ultimi 2 anni (Yahoo): array t, o, h, l, c (barre vuote tolte)."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, "%s-1h.json" % sym)
    if not os.path.exists(path) or time.time() - os.path.getmtime(path) > max_age:
        url = "https://query2.finance.yahoo.com/v8/finance/chart/%s?range=730d&interval=60m" % sym
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=40) as r:
            testo = r.read().decode("utf-8", "replace")
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            fh.write(testo)
        os.replace(path + ".tmp", path)
    with open(path, encoding="utf-8") as fh:
        res = json.load(fh)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    righe = [(t, o, h, l, c) for t, o, h, l, c in zip(res["timestamp"], q["open"], q["high"], q["low"], q["close"])
             if None not in (o, h, l, c) and h >= l > 0]
    a = np.array(righe, dtype=np.float64).reshape(-1, 5)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4]


def ema(x, n):
    out, k = np.empty(len(x)), 2.0 / (n + 1)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = out[i - 1] + k * (x[i] - out[i - 1])
    return out


def esci(o, h, l, c, i, fine, entrata, stop, obiettivo, entrata_in_barra=False, ordine_stop=False):
    """Segue la posizione dalla barra i (in cui si entra) fino alla barra `fine` compresa: stop prima dell'obiettivo
    nella stessa barra (il caso peggiore); se nessuno dei due, si esce alla chiusura della barra `fine`. Nella barra
    d'entrata con un ordine limite (si compra mentre il prezzo scende) si guarda solo lo stop: il minimo viene dopo
    l'entrata, il massimo forse prima. Con un ordine stop (si compra mentre il prezzo risale) in quella barra non si
    guarda niente: il minimo è venuto prima dell'entrata e non si sa cosa sia venuto dopo."""
    for k in range(i + 1 if ordine_stop else i, fine + 1):
        if l[k] <= stop:
            return min(stop, o[k]) if k > i else stop, k, "stop"
        if h[k] >= obiettivo and not (entrata_in_barra and k == i):
            return max(obiettivo, o[k]) if k > i else obiettivo, k, "obiettivo"
    return c[fine], fine, "chiusura"


def giornate(t, o, h, l, c, tz):
    """Le barre raggruppate per giorno (nel fuso del mercato): lista di (giorno, primo indice, ultimo indice) e le
    barre giornaliere o, h, l, c."""
    giorni = [datetime.datetime.fromtimestamp(x, tz).date() for x in t]
    gruppi, a = [], 0
    for i in range(1, len(t) + 1):
        if i == len(t) or giorni[i] != giorni[a]:
            gruppi.append((giorni[a], a, i - 1))
            a = i
    G = np.array([(o[a], h[a:b + 1].max(), l[a:b + 1].min(), c[b]) for _, a, b in gruppi])
    return gruppi, G


def regole_tesi(t, o, h, l, c, costo):
    """Le quattro regole della tesi di Sperti su un titolo: operazioni (regola, giorno, rendimento netto, uscita)."""
    gruppi, G = giornate(t, o, h, l, c, ROMA)
    out = []
    if len(gruppi) < 20:
        return out
    gO, gH, gL, gC = G.T
    tr = np.maximum.reduce([gH - gL, np.abs(gH - np.r_[gC[0], gC[:-1]]), np.abs(gL - np.r_[gC[0], gC[:-1]])])
    for d in range(19, len(gruppi)):
        giorno, a, b = gruppi[d]
        if b - a < 2:                                                    # seduta troppo corta (dati mancanti)
            continue
        ieri = d - 1
        pc, pH, pL, pO = gC[ieri], gH[ieri], gL[ieri], gO[ieri]
        ap = o[a]
        netto = lambda u, e: (1 - costo) ** 2 * u / e - 1
        # Opening Gap e Altucher: compra all'apertura
        for nome, soglia in (("gap_sperti", 0.01), ("altucher", 0.02)):
            if ap < pc * (1 - soglia):
                u, k, m = esci(o, h, l, c, a, b, ap, ap * 0.99, pc * 1.02)
                out.append((nome, str(giorno), netto(u, ap), m))
        # 80-20 di Connors e Oops: ordine stop al minimo di ieri, dopo un'apertura sotto
        rng = pH - pL
        cond_8020 = rng > 0 and (pO - pL) > 0.8 * rng and (pc - pL) < 0.2 * rng and ap < 0.99 * pL
        atr14 = tr[ieri - 13:ieri + 1].mean()
        cond_oops = tr[ieri] < atr14 and gC[ieri - 8:ieri + 1].mean() > gC[ieri - 17:ieri + 1].mean() and ap < pL
        for nome, cond, obiettivo in (("connors_8020", cond_8020, None), ("oops", cond_oops, pH)):
            if not cond:
                continue
            for k in range(a, b + 1):
                if h[k] >= pL:                                           # il prezzo risale al minimo di ieri: si entra lì
                    e = max(pL, o[k])
                    ob = e * 1.04 if obiettivo is None else obiettivo
                    u, kk, m = esci(o, h, l, c, k, b, e, e * 0.99, ob, entrata_in_barra=True, ordine_stop=True)
                    out.append((nome, str(giorno), netto(u, e), m))
                    break
    return out


def regole_rosenbloom(t, o, h, l, c, costo, tz=None, ore_max=None):
    """Impulse buy e bullish cradle sulle barre orarie. Azioni (tz): uscita entro la chiusura del giorno; crypto
    (ore_max): entro ore_max barre. Una posizione alla volta per regola."""
    n = len(c)
    out = []
    if n < 80:
        return out
    e20, e50 = ema(c, 20), ema(c, 50)
    osc = ema(c, 3) - ema(c, 10)                                         # l'oscillatore MACD 3/10
    if tz is not None:
        gruppi, _ = giornate(t, o, h, l, c, tz)
        fine_giorno = np.empty(n, dtype=int)
        for _, a, b in gruppi:
            fine_giorno[a:b + 1] = b
    libero = {"impulse_buy": 0, "cradle": 0}
    for i in range(60, n):
        fine = fine_giorno[i] if tz is not None else min(n - 1, i + ore_max - 1)
        if fine <= i and tz is not None:
            continue                                                     # ultima barra della seduta: niente entrate
        g = datetime.datetime.fromtimestamp(t[i], datetime.timezone.utc).date().isoformat()
        netto = lambda u, e: (1 - costo) ** 2 * u / e - 1
        # impulse buy: trend su, impulso recente (nuovo massimo di prezzo e di momentum), ritorno sulla media a 20
        if i >= libero["impulse_buy"] and e20[i - 1] > e50[i - 1]:
            j0 = i - 10
            mx = max(range(j0, i), key=lambda j: h[j])
            impulso = h[mx] >= h[mx - 20:mx].max() and osc[mx] >= osc[mx - 20:mx].max()
            if impulso and l[i] <= e20[i - 1] < o[i] and h[mx] > e20[i - 1] * 1.003:
                e = e20[i - 1]
                u, k, m = esci(o, h, l, c, i, fine, e, e50[i - 1] * 0.998, h[mx], entrata_in_barra=True)
                out.append(("impulse_buy", g, netto(u, e), m))
                libero["impulse_buy"] = k + 1
        # bullish cradle: incrocio 20/50 al rialzo nelle ultime 10 barre, ritorno sull'incrocio
        if i >= libero["cradle"]:
            incrocio = any(e20[j - 1] <= e50[j - 1] and e20[j] > e50[j] for j in range(i - 10, i))
            if incrocio and e20[i - 1] > e50[i - 1] and l[i] <= e20[i - 1] < o[i]:
                e = e20[i - 1]
                stop = e * 0.99
                u, k, m = esci(o, h, l, c, i, fine, e, stop, e + 2 * (e - stop), entrata_in_barra=True)
                out.append(("cradle", g, netto(u, e), m))
                libero["cradle"] = k + 1
    return out


def riassunto(ops, giorno_meta):
    """Per regola: operazioni, quante in guadagno, media, totale (somma), t, e le due metà del periodo separate."""
    per = {}
    for nome, g, r, m in ops:
        per.setdefault(nome, []).append((g, r, m))
    out = {}
    for nome, v in per.items():
        r = np.array([x[1] for x in v])
        meta = [np.array([x[1] for x in v if (x[0] < giorno_meta) == prima]) for prima in (True, False)]
        out[nome] = {"nome": NOMI[nome], "n": int(len(r)), "vinte": float((r > 0).mean()), "media": float(r.mean()),
                     "somma": float(r.sum()), "t": float(r.mean() / (r.std() / math.sqrt(len(r)) + 1e-12)) if len(r) > 1 else 0.0,
                     "uscite": {m: sum(1 for x in v if x[2] == m) for m in ("stop", "obiettivo", "chiusura")},
                     "meta": [{"n": int(len(x)), "media": float(x.mean()) if len(x) else 0.0} for x in meta]}
    return out


def studia(log=print):
    import settimana
    import rete_dati
    t0 = time.time()
    azioni, crypto, primi, ultimi = [], [], [], []
    for sym in settimana.MERCATI["italia"]["universo"]:
        try:
            t, o, h, l, c = orarie(sym)
        except Exception as e:                                           # rete o titolo: si salta
            log("[regole_libri] %s saltato: %s" % (sym, str(e)[:60]))
            continue
        if len(t) < 200:
            continue
        primi.append(t[0]); ultimi.append(t[-1])
        azioni += regole_tesi(t, o, h, l, c, COSTO_AZIONI)
        azioni += regole_rosenbloom(t, o, h, l, c, COSTO_AZIONI, tz=ROMA)
    for sym in rete_dati.COPPIE:
        try:
            t, o, h, l, c = orarie(sym)
        except Exception as e:
            log("[regole_libri] %s saltato: %s" % (sym, str(e)[:60]))
            continue
        crypto += regole_rosenbloom(t, o, h, l, c, COSTO_CRYPTO, ore_max=24)
    da = datetime.datetime.fromtimestamp(min(primi), ROMA).date()
    a = datetime.datetime.fromtimestamp(max(ultimi), ROMA).date()
    meta = (da + (a - da) / 2).isoformat()
    ris = {"creato": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "dati": {"da": da.isoformat(), "a": a.isoformat(), "meta": meta, "barre": "Yahoo Finance, 60 minuti",
                    "titoli": len(primi)},
           "costi": {"azioni": COSTO_AZIONI, "crypto": COSTO_CRYPTO},
           "azioni": riassunto(azioni, meta), "crypto": riassunto(crypto, meta),
           "fonti": ["Claudio Sperti, Silloge di metodi operativi per il trading azionario intraday, tesi di laurea, "
                     "Università di Bologna, a.a. 2009/2010 (relatore Emilio Tomasini)",
                     "Corey Rosenbloom, Guida completa al trading. Strategie operative e tecniche d'intervento nei mercati "
                     "finanziari (ed. it. di The Complete Trading Course, Wiley 2011), cap. 10"]}
    with open(USCITA, "w", encoding="utf-8") as fh:
        json.dump(ris, fh, separators=(",", ":"))
    log("[regole_libri] scritto %s in %.0f s" % (os.path.basename(USCITA), time.time() - t0))
    return ris


def main():
    r = studia()
    for mercato in ("azioni", "crypto"):
        print("\n%s, dal %s al %s, costi %.1f %% per lato" % (mercato, r["dati"]["da"], r["dati"]["a"], 100 * r["costi"][mercato]))
        for k, x in r[mercato].items():
            print("  %-48s %5d op. · in guadagno %3.0f %% · media %+.3f %% · t %+.1f · prima metà %+.3f %% (%d), seconda %+.3f %% (%d)" % (
                x["nome"], x["n"], 100 * x["vinte"], 100 * x["media"], x["t"], 100 * x["meta"][0]["media"], x["meta"][0]["n"],
                100 * x["meta"][1]["media"], x["meta"][1]["n"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
