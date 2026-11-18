#!/usr/bin/env python3
"""Le regole dei libri di trading, messe alla prova sui prezzi veri.

    python3 libri.py          # scrive libri.json, che app.py mette nella sezione "Dai libri"

Ogni regola è presa da un libro o da uno studio, con i parametri scritti lì (non ottimizzati sui
nostri dati) e fissata prima di guardare i risultati. Tre prove:

  1. Candele giornaliere (fino a 25 anni, azioni USA e italiane, ETF azionari): figure giapponesi e
     regole di breve periodo. Si giudica sul periodo fino al 2015 e si controlla dal 2016.
  2. Il momento di entrata per gli strumenti che l'app consiglia (sopra la media a 200 giorni):
     comprare subito o aspettare il segnale del libro? Stessa data di vendita, quindi conta solo il
     prezzo pagato. E, lo stesso giorno, quelli in un piccolo ribasso contro gli altri.
  3. Candele orarie (2 anni): crypto, azioni USA ed ETF. Primo anno contro secondo.

Una regola "regge" se, dopo i costi, fa meglio del semplice tenere lo strumento per gli stessi giorni
(che i costi non li paga) sia nel primo periodo sia nel secondo, con t >= 2 (raggruppando per mese,
perché le operazioni vicine si somigliano), e se dopo i costi resta in guadagno. Una figura di candele
deve anche fare meglio dello stesso ribasso senza figura. Per le candele orarie "tenere" vale zero. Solo libreria standard + numpy. Non è consulenza finanziaria.

Fonti
  Nison, Japanese Candlestick Charting Techniques (1991): engulfing, martello, piercing line,
      stella del mattino, harami, tre soldati bianchi (dopo un ribasso).
  Bulkowski, Encyclopedia of Candlestick Charts (2008): le figure misurate sui 10 giorni dopo.
  Marshall, Young, Rose, "Candlestick technical trading strategies", J. Banking & Finance (2006).
  Connors, Alvarez, Short Term Trading Strategies That Work (2008): RSI a 2 giorni sotto 10 sopra la
      media a 200, uscita sopra la media a 5.
  Pagonidis, "The IBS Effect: Mean Reversion in Equity ETFs" (2014): chiusura vicino al minimo.
  Williams, Long-Term Secrets to Short-Term Trading (1999): rottura di volatilità.
  Crabel, Day Trading with Short Term Price Patterns and Opening Range Breakout (1990): NR7, primo intervallo.
  Faith, Way of the Turtles (2007): massimo a 20 giorni, uscita al minimo a 10.
  Lakonishok, Smidt (1988); Ariel (1987): il giro di fine mese.
  Gao, Han, Li, Zhou, "Market intraday momentum", J. Financial Economics (2018).
  Zarattini, Aziz, "Can Day Trading Really Be Profitable?" (2023): rottura del primo intervallo.
"""

import datetime
import json
import math
import os
import sys
import time
import urllib.request

import numpy as np

import intraday
import settimana
import simula

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "libri.json")
CACHE_H = os.path.join(ROOT, "trader", "cache", "orarie")
UA = "Mozilla/5.0 (compatible; finanza/1.0)"
TAGLIO = "2016-01-01"                     # prima: periodo di prova; da qui: periodo di controllo
HOLD = {"usa": 21, "italia": 21, "etf": 63, "bond": 63, "oro": 63}
INDICI_USA = ["SPY", "QQQ", "IWM", "DIA"]


# ---------------------------------------------------------------- dati

def giornaliere(sym):
    """Candele giornaliere corrette per dividendi e split: date, O, H, L, C (numpy)."""
    text = simula.fetch_max(sym)
    _, dts, _ = simula.series(text)
    ok = set(dts)
    res = json.loads(text)["chart"]["result"][0]
    q, off = res["indicators"]["quote"][0], res.get("meta", {}).get("gmtoffset", 0)
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q["close"]
    rows = {}
    for t, o, h, l, c, a in zip(res["timestamp"], q["open"], q["high"], q["low"], q["close"], adj):
        if None in (o, h, l, c, a) or min(o, h, l, c, a) <= 0:
            continue
        d = datetime.datetime.fromtimestamp(t + off, datetime.timezone.utc).strftime("%Y-%m-%d")
        if d in ok:
            f = a / c
            rows[d] = (o * f, max(h, o, c) * f, min(l, o, c) * f, a)
    d = sorted(rows)
    x = np.array([rows[k] for k in d])
    return d, x[:, 0], x[:, 1], x[:, 2], x[:, 3]


def orarie(sym, max_age=12 * 3600):
    """2 anni di candele orarie da Yahoo (solo quelle già chiuse)."""
    os.makedirs(CACHE_H, exist_ok=True)
    path = os.path.join(CACHE_H, sym + ".json")
    if not os.path.exists(path) or time.time() - os.path.getmtime(path) > max_age:
        url = "https://query2.finance.yahoo.com/v8/finance/chart/%s?range=730d&interval=1h" % sym
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=40) as r:
            text = r.read().decode("utf-8", "replace")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    letto = os.path.getmtime(path)
    with open(path, encoding="utf-8") as fh:
        res = json.load(fh)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    return [(t, o, h, l, c) for t, o, h, l, c in zip(res["timestamp"], q["open"], q["high"], q["low"], q["close"])
            if None not in (o, h, l, c) and t + 1800 <= letto]


# ---------------------------------------------------------------- indicatori

def sma(x, n):
    c = np.concatenate([[0.0], np.cumsum(x)])
    out = np.full(len(x), np.nan)
    out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def rsi(c, n=2):
    """RSI di Wilder."""
    d = np.diff(c, prepend=c[0])
    g, l = np.maximum(d, 0), np.maximum(-d, 0)
    ag, al = np.zeros(len(c)), np.zeros(len(c))
    ag[n], al[n] = g[1:n + 1].mean(), l[1:n + 1].mean()
    for i in range(n + 1, len(c)):
        ag[i] = (ag[i - 1] * (n - 1) + g[i]) / n
        al[i] = (al[i - 1] * (n - 1) + l[i]) / n
    out = np.where(al > 0, 100 - 100 / (1 + ag / np.where(al > 0, al, 1)), 100.0)
    out[:n] = 50
    return out


def atr(H, L, C, n=14):
    tr = np.maximum(H - L, np.maximum(abs(H - np.roll(C, 1)), abs(L - np.roll(C, 1))))
    tr[0] = H[0] - L[0]
    return sma(tr, n)


def figure(O, H, L, C):
    """Le figure rialziste di Nison, dopo un ribasso (chiusura di ieri sotto la media a 10 giorni).
    -> dict nome -> array booleano (la figura si completa alla chiusura del giorno i)."""
    n = len(C)
    body, rng = abs(C - O), H - L
    up, dn = C > O, C < O
    top, bot = np.maximum(O, C), np.minimum(O, C)
    m10 = sma(C, 10)
    giu = np.zeros(n, bool)
    giu[1:] = C[:-1] < m10[:-1]
    s = lambda a, k: np.concatenate([np.full(k, a[0] * 0 if a.dtype != bool else False), a[:-k]])
    lungo = body >= 0.6 * rng
    ok = rng > 0
    f = {}
    f["Engulfing rialzista"] = giu & s(dn, 1) & up & (O <= s(C, 1)) & (C >= s(O, 1)) & (body > s(body, 1))
    f["Martello"] = giu & ok & (body > 0) & ((bot - L) >= 2 * body) & ((H - top) <= 0.1 * rng)
    f["Piercing line"] = (giu & s(dn & lungo, 1) & up & (O < s(L, 1)) & (C > (s(O, 1) + s(C, 1)) / 2) & (C < s(O, 1)))
    gs = np.zeros(n, bool)
    gs[2:] = C[1:-1] < m10[1:-1]
    f["Stella del mattino"] = (gs & s(dn & lungo, 2) & (s(body, 1) <= 0.3 * s(body, 2)) & (s(top, 1) <= s(C, 2)) &
                               up & (C > (s(O, 2) + s(C, 2)) / 2))
    f["Harami rialzista"] = giu & s(dn & lungo, 1) & up & (O > s(C, 1)) & (C < s(O, 1)) & (body < 0.5 * s(body, 1))
    alto = (H - C) <= 0.25 * rng
    sol = up & alto & ok
    g3 = np.zeros(n, bool)
    g3[3:] = C[2:-1] < m10[2:-1]
    f["Tre soldati bianchi"] = (g3 & sol & s(sol, 1) & s(sol, 2) & (C > s(C, 1)) & (s(C, 1) > s(C, 2)) &
                                (O > s(O, 1)) & (O <= s(C, 1)) & (s(O, 1) > s(O, 2)) & (s(O, 1) <= s(C, 2)))
    for k in f:
        f[k][:12] = False
    return f


# ---------------------------------------------------------------- prova 1: regole giornaliere

REGOLE_GIORNO = [
    {"id": "candele", "nome": "Figure giapponesi (Nison)", "fonte": "Nison 1991; Bulkowski 2008",
     "desc": "Dopo un ribasso, una delle sei figure rialziste: compra all'apertura del giorno dopo, vendi dopo 10 giorni.",
     "controllo": "ribasso"},
    {"id": "ribasso", "nome": "Controllo: dopo un ribasso, senza figura", "fonte": "Jegadeesh 1990; Lehmann 1990",
     "desc": "Lo stesso, in ogni giorno chiuso sotto la media a 10 giorni, che ci sia una figura o no: dice se conta la figura o il ribasso."},
    {"id": "rsi2", "nome": "RSI a 2 giorni sotto 10", "fonte": "Connors, Alvarez 2008",
     "desc": "Sopra la media a 200 giorni, RSI(2) sotto 10: compra in chiusura, vendi alla prima chiusura sopra la media a 5 (al massimo 10 giorni)."},
    {"id": "ibs", "nome": "Chiusura vicino al minimo (IBS)", "fonte": "Pagonidis 2014",
     "desc": "Chiusura nel 20 % più basso della giornata: compra in chiusura, vendi alla chiusura del giorno dopo."},
    {"id": "williams", "nome": "Rottura di volatilità", "fonte": "Williams 1999",
     "desc": "Compra se il prezzo supera l'apertura di 0,6 volte l'escursione di ieri; vendi in chiusura."},
    {"id": "nr7", "nome": "Giornata più stretta di 7 (NR7)", "fonte": "Crabel 1990",
     "desc": "Dopo la giornata con l'escursione più piccola degli ultimi 7, compra sopra il suo massimo; vendi in chiusura."},
    {"id": "donchian", "nome": "Massimo a 20 giorni (Turtles)", "fonte": "Faith 2007",
     "desc": "Chiusura sopra il massimo di 20 giorni: compra all'apertura dopo, vendi alla chiusura sotto il minimo di 10 giorni (al massimo 60)."},
    {"id": "mese", "nome": "Giro di fine mese", "fonte": "Lakonishok, Smidt 1988; Ariel 1987",
     "desc": "Compra alla chiusura del penultimo giorno del mese, vendi alla chiusura del terzo giorno del mese dopo."},
]


def operazioni_giorno(d, O, H, L, C, regola):
    """-> lista di (data d'entrata, giorni, rendimento lordo)."""
    n, out = len(C), []
    if regola in ("candele", "ribasso"):
        segnale = np.zeros(n, bool)
        if regola == "candele":
            for v in figure(O, H, L, C).values():
                segnale |= v
        else:
            segnale[12:] = (C < sma(C, 10))[12:]
        for i in np.nonzero(segnale)[0]:
            if i + 11 < n:
                out.append((d[i + 1], 10, C[i + 10] / O[i + 1] - 1))
    elif regola == "rsi2":
        r, m200, m5 = rsi(C), sma(C, 200), sma(C, 5)
        i = 200
        while i < n - 1:
            if C[i] > m200[i] and r[i] < 10:
                k = next((j for j in range(i + 1, min(i + 11, n)) if C[j] > m5[j]), min(i + 10, n - 1))
                out.append((d[i], k - i, C[k] / C[i] - 1))
                i = k
            i += 1
    elif regola == "ibs":
        rng = H - L
        for i in range(1, n - 1):
            if rng[i] > 0 and (C[i] - L[i]) / rng[i] < 0.2:
                out.append((d[i], 1, C[i + 1] / C[i] - 1))
    elif regola == "williams":
        for i in range(1, n):
            liv = O[i] + 0.6 * (H[i - 1] - L[i - 1])
            if H[i - 1] > L[i - 1] and H[i] >= liv:
                out.append((d[i], 0, C[i] / max(O[i], liv) - 1))
    elif regola == "nr7":
        rng = H - L
        for i in range(7, n - 1):
            if rng[i] > 0 and rng[i] <= rng[i - 6:i + 1].min() and H[i + 1] > H[i]:
                out.append((d[i + 1], 0, C[i + 1] / max(O[i + 1], H[i]) - 1))
    elif regola == "donchian":
        i = 21
        while i < n - 1:
            if C[i] > H[i - 20:i].max():
                k = next((j for j in range(i + 2, min(i + 61, n)) if C[j] < L[j - 10:j].min()), min(i + 60, n - 1))
                out.append((d[i + 1], k - i, C[k] / O[i + 1] - 1))
                i = k
            i += 1
    elif regola == "mese":
        mese = [x[:7] for x in d]
        for i in range(2, n - 4):
            if mese[i + 1] == mese[i] and mese[i + 2] != mese[i + 1]:      # i = penultimo giorno del mese
                out.append((d[i], 4, C[i + 4] / C[i] - 1))
    return out


def riassunto(ops, costo):
    """ops: (data, giorni, netto, deriva) -> volte in guadagno e media dopo i costi, e il di più
    rispetto a tenere lo strumento per gli stessi giorni (che non paga costi), t raggruppato per mese."""
    if len(ops) < 30:
        return {"n": len(ops)}
    netto = np.array([o[2] - costo for o in ops])
    extra = np.array([o[2] - o[3] for o in ops])
    mesi = {}
    for o, e in zip(ops, extra):
        mesi.setdefault(o[0][:7], []).append(e)
    m = np.array([np.mean(v) for v in mesi.values()])
    t = float(m.mean() / (m.std(ddof=1) / math.sqrt(len(m)))) if len(m) > 2 and m.std() > 0 else 0.0
    return {"n": len(ops), "p_gain": round(float(np.mean(netto > 0)), 4), "media": round(float(netto.mean()), 5),
            "extra": round(float(extra.mean()), 5), "t": round(t, 2), "mesi": len(m)}


def regge(a, b):
    return bool(a.get("n", 0) >= 30 and b.get("n", 0) >= 30 and a["extra"] > 0 and b["extra"] > 0
                and a["t"] >= 2 and b["t"] >= 2 and b["media"] > 0)


def prova_giorno(dati, log):
    out = []
    for reg in REGOLE_GIORNO:
        parti = {"prima": [], "dopo": []}
        for sym, (m, d, O, H, L, C) in dati.items():
            if m not in ("usa", "italia", "etf"):
                continue
            lr = np.diff(np.log(C))
            dd = np.array(d[1:])
            mu = {"prima": lr[dd < TAGLIO].mean() if (dd < TAGLIO).any() else 0.0,
                  "dopo": lr[dd >= TAGLIO].mean() if (dd >= TAGLIO).any() else 0.0}
            costo = settimana.MERCATI[m]["costo"] / 100
            for data, giorni, lordo in operazioni_giorno(d, O, H, L, C, reg["id"]):
                p = "prima" if data < TAGLIO else "dopo"
                parti[p].append((data, giorni, lordo - costo, math.expm1(mu[p] * max(giorni, 1))))
        a, b = riassunto(parti["prima"], 0.0), riassunto(parti["dopo"], 0.0)
        out.append(dict(reg, prima=a, dopo=b, regge=regge(a, b)))
    for r in out:                                            # una figura conta solo se fa meglio del controllo
        c = next((x for x in out if x["id"] == r.get("controllo")), None)
        if c and r["regge"]:
            r["regge"] = all(r[p].get("extra", 0) > c[p].get("extra", 0) for p in ("prima", "dopo"))
        log("[libri] %-40s prima: %s | dopo: %s%s" % (r["nome"], fmt(r["prima"]), fmt(r["dopo"]), " · REGGE" if r["regge"] else ""))
    return out


# ---------------------------------------------------------------- prova 2: il momento di entrata

ENTRATE = [
    {"id": "subito", "nome": "Compra subito", "desc": "All'apertura del giorno dopo (come fa l'app)."},
    {"id": "rsi2", "nome": "Aspetta un RSI(2) sotto 10", "fonte": "Connors, Alvarez 2008",
     "desc": "Fino a 10 giorni; compra in chiusura il giorno del segnale, altrimenti al decimo giorno."},
    {"id": "ibs", "nome": "Aspetta una chiusura vicino al minimo", "fonte": "Pagonidis 2014",
     "desc": "Fino a 5 giorni; compra in chiusura il giorno del segnale, altrimenti al quinto."},
    {"id": "candele", "nome": "Aspetta una figura rialzista", "fonte": "Nison 1991",
     "desc": "Fino a 10 giorni; compra all'apertura dopo la figura, altrimenti all'undicesimo giorno."},
    {"id": "limite05", "nome": "Ordine limite mezza escursione sotto", "fonte": "",
     "desc": "Chiusura meno mezza escursione media (ATR 14), valido 5 giorni; altrimenti compra al sesto."},
    {"id": "limite1", "nome": "Ordine limite un'escursione sotto", "fonte": "",
     "desc": "Chiusura meno un'escursione media, valido 10 giorni; altrimenti compra all'undicesimo."},
    {"id": "williams", "nome": "Aspetta la rottura di volatilità", "fonte": "Williams 1999",
     "desc": "Fino a 5 giorni compra se il prezzo supera l'apertura di 0,6 escursioni di ieri; altrimenti al sesto."},
]


def prova_entrata(dati, log, passo=5):
    """Per ogni strumento sopra la media a 200 giorni, ogni 5 sedute: quanto si paga in meno (o in più)
    rispetto a comprare subito, a parità di data di vendita."""
    res = {e["id"]: {"prima": [], "dopo": []} for e in ENTRATE[1:]}
    segn = {e["id"]: {"prima": 0, "dopo": 0} for e in ENTRATE[1:]}
    tot = {"prima": 0, "dopo": 0}
    for sym, (m, d, O, H, L, C) in dati.items():
        n = len(C)
        m200, r2, a14 = sma(C, 200), rsi(C), atr(H, L, C)
        rng = H - L
        fig = np.zeros(n, bool)
        for v in figure(O, H, L, C).values():
            fig |= v
        for t in range(200, n - 13, passo):
            if not C[t] > m200[t] or rng[t] <= 0:
                continue
            p = "prima" if d[t] < TAGLIO else "dopo"
            tot[p] += 1
            base = O[t + 1]
            prezzi = {}
            k = next((j for j in range(t + 1, t + 11) if r2[j] < 10), None)
            prezzi["rsi2"] = (C[k], True) if k else (C[t + 10], False)
            k = next((j for j in range(t + 1, t + 6) if rng[j] > 0 and (C[j] - L[j]) / rng[j] < 0.2), None)
            prezzi["ibs"] = (C[k], True) if k else (C[t + 5], False)
            k = next((j for j in range(t + 1, t + 11) if fig[j]), None)
            prezzi["candele"] = (O[k + 1], True) if k else (O[t + 11], False)
            for nome, mult, giorni in (("limite05", 0.5, 5), ("limite1", 1.0, 10)):
                lim = C[t] - mult * a14[t]
                k = next((j for j in range(t + 1, t + 1 + giorni) if L[j] <= lim), None)
                prezzi[nome] = (min(O[k], lim), True) if k else (O[t + 1 + giorni], False)
            k = next((j for j in range(t + 1, t + 6) if rng[j - 1] > 0 and H[j] >= O[j] + 0.6 * rng[j - 1]), None)
            prezzi["williams"] = (max(O[k], O[k] + 0.6 * rng[k - 1]), True) if k else (O[t + 6], False)
            for e, (prezzo, ok) in prezzi.items():
                res[e][p].append((d[t], base / prezzo - 1))
                segn[e][p] += ok
    out = [dict(ENTRATE[0], prima={"n": tot["prima"]}, dopo={"n": tot["dopo"]}, regge=False)]
    for e in ENTRATE[1:]:
        r = {}
        for p in ("prima", "dopo"):
            x = res[e["id"]][p]
            r[p] = riassunto([(dd, 0, v, 0.0) for dd, v in x], 0.0)
            r[p]["segnale"] = round(segn[e["id"]][p] / max(1, len(x)), 4)
            r[p]["meglio"] = round(float(np.mean([v > 0 for _, v in x])), 4) if x else None
        ok = bool(r["prima"].get("extra", 0) > 0 and r["dopo"].get("extra", 0) > 0 and r["prima"]["t"] >= 2 and r["dopo"]["t"] >= 2)
        out.append(dict(e, prima=r["prima"], dopo=r["dopo"], regge=ok))
        log("[libri] entrata %-38s prima: %+.2f%% (t %.1f) | dopo: %+.2f%% (t %.1f)" % (
            e["nome"], 100 * r["prima"].get("extra", 0), r["prima"].get("t", 0), 100 * r["dopo"].get("extra", 0), r["dopo"].get("t", 0)))
    return out


# ---------------------------------------------------------------- prova 2b: un piccolo ribasso, tra i consigliati

NOMI_CAT = {"usa": "Azioni USA", "italia": "Azioni italiane", "etf": "ETF azionari", "bond": "ETF obbligazionari",
            "oro": "Oro e materie prime"}


def prova_momento(dati, log, top=10):
    """Tra gli strumenti che l'app può consigliare (sopra la media a 200 giorni; per le azioni i primi 10
    per forza, come nella classifica), nello stesso giorno: quelli in un piccolo ribasso (chiusura sotto la
    media a 10 giorni) contro gli altri, comprati all'apertura dopo e tenuti il periodo dell'app."""
    out = []
    for m, h in HOLD.items():
        per_data = {}
        for sym, (mm, d, O, H, L, C) in dati.items():
            if mm != m:
                continue
            m200, m10 = sma(C, 200), sma(C, 10)
            lr = np.diff(np.log(C), prepend=np.log(C[0]))
            for t in range(260, len(C) - h - 1):
                if not C[t] > m200[t]:
                    continue
                vol = lr[t - 251:t + 1].std() * math.sqrt(252)
                forza = (C[t - 21] / C[t - 252] - 1) / max(vol, 1e-6)
                per_data.setdefault(d[t], []).append((C[t] < m10[t], C[t + h] / O[t + 1] - 1, forza))
        r = {}
        for p in ("prima", "dopo"):
            mesi, nd, nn = {}, 0, 0
            for dt, xs in per_data.items():
                if (dt < TAGLIO) != (p == "prima"):
                    continue
                if m in ("usa", "italia"):
                    xs = sorted(xs, key=lambda x: -x[2])[:top]
                a = [x[1] for x in xs if x[0]]
                b = [x[1] for x in xs if not x[0]]
                if a and b:
                    mesi.setdefault(dt[:7], []).append(np.mean(a) - np.mean(b))
                    nd, nn = nd + len(a), nn + len(b)
            v = np.array([np.mean(x) for x in mesi.values()])
            r[p] = ({"n": 0} if len(v) < 12 else
                    {"n": nd + nn, "ribasso": nd, "differenza": round(float(v.mean()), 5),
                     "t": round(float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v)))), 2), "mesi": len(v)})
        ok = all(r[p].get("n", 0) and r[p]["differenza"] > 0 and r[p]["t"] >= 2 for p in ("prima", "dopo"))
        out.append({"categoria": m, "nome": NOMI_CAT[m], "hold": h, "prima": r["prima"], "dopo": r["dopo"], "regge": ok})
        log("[libri] piccolo ribasso, %-20s prima: %s | dopo: %s%s" % (NOMI_CAT[m], *(
            ("%+.2f%% (t %.1f)" % (100 * r[p]["differenza"], r[p]["t"]) if r[p].get("n") else "pochi dati") for p in ("prima", "dopo")),
            " · REGGE" if ok else ""))
    return out


# ---------------------------------------------------------------- prova 3: candele orarie

REGOLE_ORA = [
    {"id": "orb", "nome": "Rottura del primo intervallo", "fonte": "Crabel 1990; Zarattini, Aziz 2023",
     "desc": "Se la prima ora chiude in rialzo, compra alla sua chiusura; protezione al minimo della prima ora; vendi in chiusura."},
    {"id": "momentum", "nome": "Momento della giornata", "fonte": "Gao, Han, Li, Zhou 2018",
     "desc": "Se dalla chiusura di ieri alla fine della prima ora il prezzo è salito, compra nell'ultima mezz'ora (ultima ora per le crypto) e vendi in chiusura."},
    {"id": "williams", "nome": "Rottura di volatilità", "fonte": "Williams 1999",
     "desc": "Compra se il prezzo supera l'apertura di 0,5 volte l'escursione di ieri; vendi in chiusura."},
    {"id": "candele", "nome": "Figure giapponesi sull'ora", "fonte": "Nison 1991",
     "desc": "Una delle sei figure rialziste su una candela oraria: compra all'apertura dell'ora dopo, vendi dopo 24 ore (crypto) o in chiusura."},
    {"id": "rsi2", "nome": "RSI(2) orario sotto 10", "fonte": "Connors, Alvarez 2008",
     "desc": "Sopra la media di 200 ore, RSI(2) sotto 10: compra, vendi alla prima chiusura sopra la media di 5 ore (al massimo 24)."},
]


def giornate(B, crypto):
    """Raggruppa le candele orarie per giornata: per le crypto il giorno UTC, per la borsa USA la seduta."""
    g = {}
    for b in B:
        dt = datetime.datetime.fromtimestamp(b[0], datetime.timezone.utc)
        if not crypto:
            dt -= datetime.timedelta(hours=5)                 # ora di New York (circa: basta per separare le sedute)
        g.setdefault(dt.strftime("%Y-%m-%d"), []).append(b)
    return [(k, v) for k, v in sorted(g.items()) if len(v) >= (24 if crypto else 7)]


def operazioni_ora(B, crypto, regola):
    """-> lista di (data, lordo)."""
    out = []
    if regola in ("candele", "rsi2"):
        A = np.array([b[1:] for b in B])
        O, H, L, C = A[:, 0], A[:, 1], A[:, 2], A[:, 3]
        giorno = [datetime.datetime.fromtimestamp(b[0] - (0 if crypto else 5 * 3600), datetime.timezone.utc).strftime("%Y-%m-%d") for b in B]
        if regola == "candele":
            s = np.zeros(len(C), bool)
            for v in figure(O, H, L, C).values():
                s |= v
            for i in np.nonzero(s)[0]:
                if crypto and i + 25 < len(C):
                    out.append((giorno[i], C[i + 24] / O[i + 1] - 1))
                elif not crypto and i + 1 < len(C) and giorno[i + 1] == giorno[i]:
                    k = max(j for j in range(i + 1, min(i + 8, len(C))) if giorno[j] == giorno[i])
                    out.append((giorno[i], C[k] / O[i + 1] - 1))
        else:
            r, m200, m5 = rsi(C), sma(C, 200), sma(C, 5)
            i = 200
            while i < len(C) - 1:
                if C[i] > m200[i] and r[i] < 10:
                    lim = min(i + 25, len(C))
                    if not crypto:
                        lim = min(lim, max(j for j in range(i, min(i + 8, len(C))) if giorno[j] == giorno[i]) + 1)
                    k = next((j for j in range(i + 1, lim) if C[j] > m5[j]), lim - 1)
                    if k > i:
                        out.append((giorno[i], C[k] / C[i] - 1))
                    i = k
                i += 1
        return out
    G = giornate(B, crypto)
    for (g0, ieri), (g, oggi) in zip(G, G[1:]):
        o, c = oggi[0][1], oggi[-1][4]
        prima = oggi[0]
        if regola == "orb":
            if prima[4] > prima[1]:
                stop, entr = prima[3], prima[4]
                uscita = next((stop for b in oggi[1:] if b[3] <= stop), c)
                out.append((g, uscita / entr - 1))
        elif regola == "momentum":
            if prima[4] > ieri[-1][4]:
                ultima = oggi[-1]
                out.append((g, ultima[4] / ultima[1] - 1))
        elif regola == "williams":
            rng = max(b[2] for b in ieri) - min(b[3] for b in ieri)
            liv = o + 0.5 * rng
            k = next((b for b in oggi if b[2] >= liv), None)
            if k is not None:
                out.append((g, c / max(k[1], liv) - 1))
    return out


def prova_ora(log):
    gruppi = {"crypto": (simula.CRYPTO, True, 2 * intraday.COSTO),
              "usa": (INDICI_USA + settimana.MERCATI["usa"]["universo"], False, settimana.MERCATI["usa"]["costo"] / 100)}
    out = []
    for nome_g, (simboli, crypto, costo) in gruppi.items():
        dati = {}
        for s in simboli:
            try:
                B = intraday.candele(s) if crypto else orarie(s)
            except Exception as e:                                   # rete, dati mancanti
                log("[libri] %s saltato: %s" % (s, e))
                continue
            if len(B) > 1000:
                dati[s] = B
        primo = min(B[0][0] for B in dati.values())
        meta = datetime.datetime.fromtimestamp(primo + 365 * 86400, datetime.timezone.utc).strftime("%Y-%m-%d")
        for reg in REGOLE_ORA:
            parti = {"prima": [], "dopo": []}
            for s, B in dati.items():
                for g, lordo in operazioni_ora(B, crypto, reg["id"]):
                    parti["prima" if g < meta else "dopo"].append((g, 0, lordo - costo, 0.0))
            a, b = riassunto(parti["prima"], 0.0), riassunto(parti["dopo"], 0.0)
            out.append(dict(reg, gruppo=nome_g, strumenti=len(dati), prima=a, dopo=b, regge=regge(a, b)))
            log("[libri] %-6s %-30s anno 1: %s | anno 2: %s" % (nome_g, reg["nome"], fmt(a), fmt(b)))
    return out


def fmt(s):
    if s.get("n", 0) < 30:
        return "troppo poche (%d)" % s.get("n", 0)
    return "%6d op, %2.0f%% in guadagno, media netta %+.2f%%, rispetto a tenere %+.2f%% (t %.1f)" % (
        s["n"], 100 * s["p_gain"], 100 * s["media"], 100 * s["extra"], s["t"])


def analizza(log=print):
    dati = {}
    for m in ("usa", "italia", "etf", "bond", "oro"):
        for s in settimana.MERCATI[m]["universo"]:
            try:
                d, O, H, L, C = giornaliere(s)
            except Exception as e:                                   # rete, dati mancanti
                log("[libri] %s saltato: %s" % (s, e))
                continue
            if len(C) > 400:
                dati[s] = (m, d, O, H, L, C)
    log("[libri] %d strumenti con candele giornaliere" % len(dati))
    return {"generato": datetime.date.today().isoformat(), "taglio": TAGLIO,
            "giorno": prova_giorno(dati, log), "entrata": prova_entrata(dati, log),
            "momento": prova_momento(dati, log), "ora": prova_ora(log)}


def main():
    r = analizza()
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(r, fh, indent=1)
    reggono = [x["nome"] for k in ("giorno", "entrata", "momento", "ora") for x in r[k] if x.get("regge")]
    print("[libri] reggono: %s · scritto libri.json" % (", ".join(reggono) or "nessuna"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
