#!/usr/bin/env python3
"""Verifica su 25 anni della probabilità di guadagno e del giudizio dell'app.

    python3 verifica.py          # scrive verifica.json, che app.py mette nella sezione Funziona?

Per ogni strumento dell'app (azioni, ETF, obbligazionari, oro, crypto) e per ogni mese degli
ultimi ~25 anni (dal terzo anno di storia in poi) rifà la stima prudente della probabilità di
guadagno nel periodo consigliato, usando SOLO i prezzi disponibili quel giorno, e la confronta
con com'è andata davvero. Misura:
  - la calibrazione: quando la stima diceva X %, quante volte è successo davvero;
  - il giudizio: Sì / Con cautela / Per ora no, con le stesse regole dell'app;
  - le alternative provate per migliorare la stima (miscela con la frequenza del gruppo,
    ricalibratura imparata dagli anni precedenti), valutate solo su anni non visti.

La stima è quella della Macchina del Tempo: le finestre storiche reali di h giorni, con la
crescita passata sostituita da quella prudente. Per periodi fino a un mese è esattamente la
simulazione dell'app; per 3 mesi le finestre reali al posto di 3 mesi presi a caso.

Richiede numpy (solo questo script: l'app usa la libreria standard). Senza costi né tasse.
"""

import bisect
import datetime
import json
import math
import os
import sys

import numpy as np

import settimana
import simula

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "verifica.json")
GRUPPO = {"usa": "azioni", "italia": "azioni", "etf": "ETF azionari", "bond": "ETF obbligazionari",
          "oro": "oro e materie prime", "crypto": "crypto"}
HOLD = {"usa": 21, "italia": 21, "etf": 63, "bond": 63, "oro": 63, "crypto": 91}


def prudente(mu, sd, n, A):
    mu_a, sd_a = mu * A, sd * math.sqrt(A)
    prior = math.log(1 + simula.PRIOR_GROWTH)
    se = sd_a / math.sqrt(n / A)
    w = simula.PRIOR_SD ** 2 / (simula.PRIOR_SD ** 2 + se ** 2)
    return (prior + w * (mu_a - prior)) / A


def previsioni(log=print, orizzonti=False):
    """Una previsione al mese per strumento. Con orizzonti=False sul periodo consigliato della sua
    categoria; con orizzonti=True su tutte le durate della Macchina del Tempo (campo "h": 0..4)."""
    cat = {}
    for m in ("usa", "italia", "etf", "bond", "oro"):
        for s in settimana.MERCATI[m]["universo"]:
            cat[s] = m
    for s in simula.CRYPTO:
        cat[s] = "crypto"
    rows = []
    for sym, m in cat.items():
        try:
            meta, dates, closes = simula.series(simula.fetch_max(sym))
        except (simula.SimError, ValueError, KeyError) as e:
            log("[verifica] %s saltato: %s" % (sym, e))
            continue
        A = 365 if m == "crypto" else 252
        c = np.array(closes[-(simula.YEARS_MAX * A + 1):])
        dts = dates[-len(c):]
        lr = np.diff(np.log(c))
        N = len(lr)
        S = np.concatenate([[0.0], np.cumsum(lr)])
        S2 = np.concatenate([[0.0], np.cumsum(lr * lr)])
        durate = [h for _, h in simula.CALENDARI["sempre" if m == "crypto" else "borsa"]["orizzonti"]] if orizzonti else [HOLD[m]]
        for k, h in enumerate(durate):
            W = S[h:] - S[:-h]                               # rendimento (log) di h giorni che parte da k
            for t in range(3 * A, N - h, 21 if A == 252 else 30):
                mu = S[t] / t
                sd = math.sqrt(max(1e-12, (S2[t] - t * mu * mu) / (t - 1)))
                shifted = W[:t - h + 1] - mu * h + prudente(mu, sd, t, A) * h   # solo finestre concluse al giorno t
                rows.append({"g": GRUPPO[m], "h": k, "d": dts[t], "fine": dts[t + h], "p": float(np.mean(shifted > 0)),
                             "p10": float(np.percentile(shifted, 10)), "y": float(W[t] > 0), "r": float(math.expm1(W[t]))})
    return rows


def per_durata(rows):
    """Per ogni durata: probabilità detta e vera, e se le stime più alte sono andate meglio delle più basse."""
    out = []
    for k, (nome, _) in enumerate(simula.HORIZONS):
        R = [r for r in rows if r["h"] == k]
        if not R:
            continue
        p, y = np.array([r["p"] for r in R]), np.array([r["y"] for r in R])
        q1, q2 = np.quantile(p, [1 / 3, 2 / 3])
        lo, hi = p < q1, p >= q2
        out.append({"durata": nome, "n": len(R), "da": min(r["d"] for r in R), "a": max(r["d"] for r in R),
                    "stimata": round(float(p.mean()), 4), "vera": round(float(y.mean()), 4),
                    "basse": {"stimata": round(float(p[lo].mean()), 4), "vera": round(float(y[lo].mean()), 4)},
                    "alte": {"stimata": round(float(p[hi].mean()), 4), "vera": round(float(y[hi].mean()), 4)},
                    "gruppi": [{"gruppo": g, "stimata": round(float(p[m].mean()), 4), "vera": round(float(y[m].mean()), 4),
                                "n": int(m.sum())}
                               for g in sorted({r["g"] for r in R}) for m in [np.array([r["g"] == g for r in R])]]})
    return out


def pav(x, y):
    o = np.argsort(x)
    blocks = []
    for xi, yi in zip(np.asarray(x)[o], np.asarray(y, float)[o]):
        blocks.append([yi, 1.0, xi])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            a, b = blocks[-2], blocks[-1]
            blocks[-2] = [(a[0] * a[1] + b[0] * b[1]) / (a[1] + b[1]), a[1] + b[1], b[2]]
            blocks.pop()
    return [b[2] for b in blocks], [b[0] for b in blocks], [b[1] for b in blocks]


def alternative(rows):
    """Le idee provate per migliorare la stima, valutate anno per anno su anni non visti."""
    rows = sorted(rows, key=lambda r: r["d"])
    fine = {}
    for g in {r["g"] for r in rows}:
        R = sorted([r for r in rows if r["g"] == g], key=lambda r: r["fine"])
        fine[g] = ([r["fine"] for r in R], np.cumsum([r["y"] for r in R]))
    for r in rows:                                                       # frequenza del gruppo nota alla data
        f, cy = fine[r["g"]]
        j = bisect.bisect_left(f, r["d"])
        r["pg"] = (cy[j - 1] + 50 * r["p"]) / (j + 50) if j else r["p"]
    preds = {"attuale": [], "miscela con il gruppo": [], "ricalibratura": []}
    ys = []
    for Y in sorted({r["d"][:4] for r in rows}):
        test = [r for r in rows if r["d"][:4] == Y]
        train = [r for r in rows if r["fine"] < Y + "-01-01"]
        if len(train) < 2000:
            continue
        xs, vs, ns = pav([r["p"] for r in train], [r["y"] for r in train])
        for r in test:
            j = min(bisect.bisect_left(xs, r["p"]), len(xs) - 1)
            preds["attuale"].append(r["p"])
            preds["miscela con il gruppo"].append(0.5 * r["p"] + 0.5 * r["pg"])
            preds["ricalibratura"].append((vs[j] * ns[j] + r["p"] * 200) / (ns[j] + 200))
            ys.append(r["y"])
    y = np.array(ys)
    base = float(np.mean((y.mean() - y) ** 2))
    return [{"nome": k, "skill": round(1 - float(np.mean((np.array(v) - y) ** 2)) / base, 4), "n": len(v)}
            for k, v in preds.items()]


def riassunto(rows):
    y = np.array([r["y"] for r in rows])
    p = np.array([r["p"] for r in rows])
    ret = np.array([r["r"] for r in rows])
    p10 = np.array([r["p10"] for r in rows])
    cal = []
    for lo, hi in ((0, .5), (.5, .55), (.55, .6), (.6, .65), (.65, .7), (.7, 1.01)):
        m = (p >= lo) & (p < hi)
        if m.sum():
            cal.append({"da": lo, "a": min(hi, 1), "stimata": round(float(p[m].mean()), 4),
                        "vera": round(float(y[m].mean()), 4), "n": int(m.sum())})
    pr = np.round(p, 2)
    si = (pr >= .6) & (p10 >= -.1)
    no = (pr < .5) | (p10 < -.2)
    giud = []
    for lab, m in (("Sì", si), ("Con cautela", ~si & ~no), ("Per ora no", no)):
        if m.sum():
            giud.append({"giudizio": lab, "n": int(m.sum()), "in_guadagno": round(float(y[m].mean()), 4),
                         "rendimento_medio": round(float(ret[m].mean()), 4),
                         "rendimento_tipico": round(float(np.median(ret[m])), 4),
                         "p10": round(float(np.percentile(ret[m], 10)), 4)})
    gruppi = []
    for g in sorted({r["g"] for r in rows}):
        m = np.array([r["g"] == g for r in rows])
        gruppi.append({"gruppo": g, "n": int(m.sum()), "stimata": round(float(p[m].mean()), 4),
                       "vera": round(float(y[m].mean()), 4)})
    return {"n": len(rows), "da": min(r["d"] for r in rows), "a": max(r["d"] for r in rows),
            "stimata": round(float(p.mean()), 4), "vera": round(float(y.mean()), 4),
            "calibrazione": cal, "giudizio": giud, "gruppi": gruppi}


def main():
    rows = previsioni()
    out = {"generato": datetime.date.today().isoformat(), "tutto": riassunto(rows),
           "prima_2017": riassunto([r for r in rows if r["d"] < "2017"]),
           "dal_2017": riassunto([r for r in rows if r["d"] >= "2017"]),
           "alternative": alternative(rows),
           "durate": per_durata(previsioni(log=lambda m: None, orizzonti=True))}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    t = out["tutto"]
    print("[verifica] %d previsioni dal %s al %s: stimata %.1f%%, vera %.1f%%" % (
        t["n"], t["da"], t["a"], 100 * t["stimata"], 100 * t["vera"]))
    for g in t["giudizio"]:
        print("  %-12s %5d casi: in guadagno %.1f%%, rendimento medio %+.2f%%, 1 su 10 sotto %+.1f%%" % (
            g["giudizio"], g["n"], 100 * g["in_guadagno"], 100 * g["rendimento_medio"], 100 * g["p10"]))
    for a in out["alternative"]:
        print("  alternativa %-22s precisione rispetto alla media: %+.2f%%" % (a["nome"], 100 * a["skill"]))
    for d in out["durate"]:
        print("  a %-12s detta %.1f%%, vera %.1f%% · stime più basse %.0f%% -> %.0f%%, più alte %.0f%% -> %.0f%%" % (
            d["durata"], 100 * d["stimata"], 100 * d["vera"], 100 * d["basse"]["stimata"], 100 * d["basse"]["vera"],
            100 * d["alte"]["stimata"], 100 * d["alte"]["vera"]))
    print("[verifica] scritto verifica.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
