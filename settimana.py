#!/usr/bin/env python3
"""I 5 titoli della settimana: un algoritmo trasparente, verificato sul passato.

COSA FA
  1. Scarica 10 anni di prezzi giornalieri (chiusure corrette per dividendi e split, Yahoo)
     per ~100 grandi titoli USA (l'S&P 100) più SPY come riferimento di mercato.
  2. Dà un punteggio a ogni titolo con una regola nota in letteratura:
       momentum 12-1   = rendimento da 12 mesi fa a 1 mese fa (Jegadeesh e Titman, 1993)
       diviso per la volatilità degli ultimi 3 mesi (momentum "corretto per il rischio")
       e solo se il prezzo è sopra la sua media a 200 giorni (filtro di trend).
  3. Sceglie i 5 punteggi più alti.
  4. VERIFICA: rifà la stessa scelta ogni settimana degli ultimi ~9 anni, usando solo i dati
     disponibili in quel momento, e misura cosa è successo dopo 7 giorni, 1 mese e 1 anno.
  5. Per ogni titolo scelto calcola probabilità di guadagno e guadagno tipico in % a
     7 giorni, 1 mese e 1 anno: è la frequenza storica di quando QUEL titolo si trovava in
     condizioni simili (tra il 20 % migliore del punteggio e sopra la media a 200 giorni).

COSA NON FA
  Non prevede il futuro. Le probabilità sono frequenze del passato. L'universo è l'S&P 100
  di OGGI: nel passato contiene solo aziende che sono sopravvissute e cresciute (bias di
  sopravvivenza), quindi la verifica storica è ottimistica. Per 1 anno ci sono pochissimi
  casi indipendenti: quel numero è il più fragile. Non è consulenza finanziaria.

Esempi:
    python3 settimana.py                    # i 5 titoli di questa settimana + report HTML
    python3 settimana.py --asof 2025-06-30  # cosa avrebbe scelto a quella data
    python3 settimana.py --tickers AAPL,MSFT,NVDA,KO,XOM,JPM

Solo libreria standard, Python 3.8+.
"""

import argparse
import datetime
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
TRADER = os.path.join(ROOT, "trader")
CACHE = os.path.join(TRADER, "cache", "daily")
UA = "Mozilla/5.0 (compatible; finanza/1.0)"

# S&P 100 (composizione recente). BRK-B nel formato di Yahoo.
UNIVERSE = """AAPL ABBV ABT ACN ADBE AIG AMD AMGN AMT AMZN AVGO AXP BA BAC BKNG BLK BMY BNY BRK-B C CAT
CHTR CL CMCSA COF COP COST CRM CSCO CVS CVX DE DHR DIS DUK EMR F FDX GD GE GILD GM GOOGL GS HD HON IBM
INTC INTU ISRG JNJ JPM KHC KO LIN LLY LMT LOW MA MCD MDLZ MDT MET META MMM MO MRK MS MSFT NEE NFLX NKE
NOW NVDA ORCL PEP PFE PG PLTR PM PYPL QCOM RTX SBUX SCHW SO SPG T TGT TMO TMUS TSLA TXN UBER UNH UNP UPS
USB V VZ WFC WMT XOM""".split()
MARKET = "SPY"

HORIZONS = [("7 giorni", 5), ("1 mese", 21), ("1 anno", 252)]
LOOKBACK = 252     # 12 mesi di borsa
SKIP = 21          # salta l'ultimo mese (inversione di breve periodo)
VOL_WIN = 63       # 3 mesi per la volatilità
SMA_WIN = 200      # media mobile del filtro di trend
STEP = 5           # ribilanciamento settimanale
TOP = 5
TOP_PCT = 0.20     # "condizioni simili" = nel 20 % migliore del punteggio


class FetchError(Exception):
    pass


# ------------------------------------------------------------------ dati

def now_new_york():
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)
    except Exception:
        return datetime.datetime.utcnow() - datetime.timedelta(hours=5)


def fetch(sym, max_age_hours=12):
    """Il JSON del grafico Yahoo a 10 anni, con una cache in trader/cache/daily."""
    path = os.path.join(CACHE, sym + ".json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < max_age_hours * 3600:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    last = None
    for host in ("query2", "query1"):
        url = ("https://%s.finance.yahoo.com/v8/finance/chart/%s?range=10y&interval=1d"
               "&includeAdjustedClose=true" % (host, sym))
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    text = r.read().decode("utf-8", "replace")
                os.makedirs(CACHE, exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
                return text
            except urllib.error.HTTPError as e:
                last = "HTTP %d" % e.code
                if e.code == 429:
                    time.sleep(2 * (attempt + 1))
                    continue
                if e.code == 404:
                    raise FetchError("%s: Yahoo non ha questo ticker" % sym)
                break
            except (urllib.error.URLError, OSError) as e:
                last = str(getattr(e, "reason", e))
                time.sleep(1)
    raise FetchError("%s: %s" % (sym, last))


def parse(text, cut=None):
    """-> (meta, {data 'YYYY-MM-DD': chiusura corretta}). Scarta la barra di oggi se la
    borsa non ha ancora chiuso, e tutto ciò che è dopo `cut` (per --asof)."""
    res = json.loads(text)["chart"]["result"][0]
    meta = res.get("meta", {})
    ts = res.get("timestamp") or []
    ind = res.get("indicators", {})
    closes = ((ind.get("adjclose") or [{}])[0].get("adjclose")
              or (ind.get("quote") or [{}])[0].get("close") or [])
    off = meta.get("gmtoffset", -18000)
    out = {}
    for t, c in zip(ts, closes):
        if c is None or c <= 0:
            continue
        out[datetime.datetime.fromtimestamp(t + off, datetime.timezone.utc).strftime("%Y-%m-%d")] = float(c)
    now = now_new_york()
    today = now.strftime("%Y-%m-%d")
    if today in out and now.hour < 16:
        del out[today]                       # barra di oggi ancora in formazione
    if cut:
        out = {d: c for d, c in out.items() if d <= cut}
    return meta, out


def align(series, calendar):
    """Allinea ogni serie al calendario di SPY; i buchi dopo il primo prezzo si riempiono
    con l'ultimo prezzo noto, prima del primo prezzo restano None."""
    out = {}
    for sym, s in series.items():
        row, last = [], None
        for d in calendar:
            if d in s:
                last = s[d]
            row.append(last)
        out[sym] = row
    return out


# ------------------------------------------------------------------ indicatori

class Stock:
    """Prezzi allineati + somme prefisse per media mobile e volatilità in O(1)."""

    def __init__(self, sym, prices, name=""):
        self.sym, self.p, self.name = sym, prices, name
        self.first = next((i for i, x in enumerate(prices) if x is not None), len(prices))
        n = len(prices)
        self.P = [0.0] * (n + 1)             # somme prefisse dei prezzi
        self.S1 = [0.0] * (n + 1)            # dei rendimenti log
        self.S2 = [0.0] * (n + 1)            # dei loro quadrati
        for i in range(n):
            x = prices[i] or 0.0
            r = math.log(prices[i] / prices[i - 1]) if i > self.first else 0.0
            self.P[i + 1] = self.P[i] + x
            self.S1[i + 1] = self.S1[i] + r
            self.S2[i + 1] = self.S2[i] + r * r

    def ok(self, i):
        return i - self.first >= LOOKBACK and i < len(self.p)

    def sma(self, i):
        return (self.P[i + 1] - self.P[i + 1 - SMA_WIN]) / SMA_WIN

    def vol(self, i):
        n = VOL_WIN
        s1 = self.S1[i + 1] - self.S1[i + 1 - n]
        s2 = self.S2[i + 1] - self.S2[i + 1 - n]
        var = max(0.0, (s2 - s1 * s1 / n) / (n - 1))
        return math.sqrt(var) * math.sqrt(252)

    def mom(self, i):
        return self.p[i - SKIP] / self.p[i - LOOKBACK] - 1

    def fwd(self, i, h):
        if i + h >= len(self.p):
            return None
        return self.p[i + h] / self.p[i] - 1

    def signal(self, i):
        """Il punteggio al giorno i, usando SOLO prezzi fino al giorno i."""
        if not self.ok(i):
            return None
        v = self.vol(i)
        if v <= 0:
            return None
        m = self.mom(i)
        sma = self.sma(i)
        return {"score": m / v, "mom": m, "vol": v, "above": self.p[i] > sma,
                "vs_sma": self.p[i] / sma - 1}


def rank_day(stocks, i):
    """Classifica del giorno i: (scelti, insieme 'condizioni simili', segnali)."""
    sig = {}
    for s in stocks:
        x = s.signal(i)
        if x is not None:
            sig[s.sym] = x
    order = sorted(sig, key=lambda k: -sig[k]["score"])
    cut = max(1, int(round(len(order) * TOP_PCT)))
    similar = {k for k in order[:cut] if sig[k]["above"]}
    picks = [k for k in order if sig[k]["above"]][:TOP]
    return picks, similar, sig


# ------------------------------------------------------------------ statistiche

def pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    f = int(math.floor(k))
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def stats(xs):
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "p_gain": sum(1 for x in xs if x > 0) / len(xs), "median": pct(xs, 0.5),
            "mean": sum(xs) / len(xs), "p10": pct(xs, 0.10), "p90": pct(xs, 0.90)}


def independent(idx, h):
    """Quanti casi NON sovrapposti ci sono: finestre di h giorni che non si toccano."""
    n, last = 0, -10 ** 9
    for i in idx:
        if i >= last + h:
            n, last = n + 1, i
    return n


def confidence(n_ind):
    return "alta" if n_ind >= 30 else ("media" if n_ind >= 10 else "bassa")


# ------------------------------------------------------------------ analisi

def run(stocks, market, calendar, cost_rt):
    last = len(calendar) - 1
    start = min(s.first for s in stocks) + LOOKBACK
    sched = list(range(last, start - 1, -STEP))[::-1]       # settimanale, allineato a oggi

    by_day = {}
    for i in sched:
        by_day[i] = rank_day(stocks, i)
    smap = {s.sym: s for s in stocks}

    # 1. le scelte di oggi
    picks, _, sig_now = by_day[last]

    # 2. verifica settimanale: equity della strategia, del paniere equipesato e di SPY
    eq = {"strategia": [1.0], "paniere": [1.0], "spy": [1.0]}
    dates = [calendar[sched[0]]]
    weekly, prev = [], set()
    for i in sched:
        if i + STEP > last:
            break
        pk, _, sig = by_day[i]
        if not pk:
            continue
        g = sum(smap[k].fwd(i, STEP) for k in pk) / len(pk)
        turnover = len(set(pk) - prev) / TOP
        net = g - turnover * cost_rt
        prev = set(pk)
        bench = [smap[k].fwd(i, STEP) for k in sig]
        b = sum(bench) / len(bench)
        spy = market.fwd(i, STEP)
        eq["strategia"].append(eq["strategia"][-1] * (1 + net))
        eq["paniere"].append(eq["paniere"][-1] * (1 + b))
        eq["spy"].append(eq["spy"][-1] * (1 + spy))
        dates.append(calendar[i + STEP])
        weekly.append((net, b, calendar[i + STEP][:4]))

    # 3. track record dell'algoritmo per orizzonte
    record = {}
    for label, h in HORIZONS:
        pk_r, bench_r, beat = [], [], []
        for i in sched:
            if i + h > last:
                break
            pk, _, sig = by_day[i]
            if not pk:
                continue
            fr = [smap[k].fwd(i, h) for k in pk]
            br = [smap[k].fwd(i, h) for k in sig]
            pk_r += fr
            bench_r += br
            beat.append(sum(fr) / len(fr) > sum(br) / len(br))
        record[label] = {"algoritmo": stats(pk_r), "paniere": stats(bench_r),
                         "batte_paniere": (sum(beat) / len(beat)) if beat else None,
                         "settimane": len(beat), "indipendenti": independent(
                             [i for i in sched if i + h <= last], h)}

    # 4. per ogni titolo scelto: condizioni simili nel passato + storia completa
    detail = []
    for k in picks:
        s = smap[k]
        row = {"symbol": k, "name": s.name, "price": s.p[last], "signal": sig_now[k], "horizons": {}}
        for label, h in HORIZONS:
            idx = [i for i in sched if i < last and i + h <= last and k in by_day[i][1]]
            cond = [s.fwd(i, h) for i in idx]
            base = [s.fwd(i, h) for i in range(s.first, last - h + 1)]
            n_ind = independent(idx, h)
            row["horizons"][label] = {"simili": stats(cond), "indipendenti": n_ind,
                                      "affidabilita": confidence(n_ind), "storia": stats(base)}
        detail.append(row)

    # 5. metriche della curva
    def curve_stats(c, w):
        years = max(1e-9, (len(c) - 1) * STEP / 252)
        peak, dd = c[0], 0.0
        for x in c:
            peak = max(peak, x)
            dd = min(dd, x / peak - 1)
        return {"cagr": c[-1] ** (1 / years) - 1, "max_drawdown": dd, "totale": c[-1] - 1}

    metrics = {k: curve_stats(v, None) for k, v in eq.items()}
    metrics["settimane_positive"] = sum(1 for n, _, _ in weekly if n > 0) / max(1, len(weekly))
    metrics["settimane_sopra_paniere"] = sum(1 for n, b, _ in weekly if n > b) / max(1, len(weekly))
    metrics["settimane"] = len(weekly)

    # il vantaggio sul paniere è distinguibile dal caso? t sui rendimenti settimanali in eccesso
    ex = [n - b for n, b, _ in weekly]
    if len(ex) > 2:
        mu = sum(ex) / len(ex)
        sd = math.sqrt(sum((x - mu) ** 2 for x in ex) / (len(ex) - 1))
        metrics["eccesso_annuo"] = mu * 52
        metrics["t_eccesso"] = mu / sd * math.sqrt(len(ex)) if sd > 0 else None

    # anno per anno
    years = {}
    for n, b, y in weekly:
        a = years.setdefault(y, [1.0, 1.0, 0])
        a[0] *= 1 + n
        a[1] *= 1 + b
        a[2] += 1
    metrics["anni"] = [{"anno": y, "strategia": v[0] - 1, "paniere": v[1] - 1, "settimane": v[2]}
                       for y, v in sorted(years.items())]

    m_i = market.signal(last)
    regime = {"spy_sopra_media200": m_i["above"], "spy_vs_media200": m_i["vs_sma"]} if m_i else None

    return {"asof": calendar[last], "picks": detail, "record": record,
            "backtest": {"dates": dates, "curves": eq, "metrics": metrics, "da": dates[0], "a": dates[-1],
                         "costo_andata_ritorno": cost_rt},
            "universo": len(stocks), "regime": regime,
            "classifica": [{"symbol": k, **sig_now[k]} for k in
                           sorted(sig_now, key=lambda x: -sig_now[x]["score"])][:15]}


# ------------------------------------------------------------------ stampa

def f_pct(x, d=1, sign=True):
    if x is None:
        return "n/d"
    s = ("%+." if sign else "%.") + str(d) + "f %%"
    return (s % (x * 100)).replace(".", ",")


def print_report(r):
    print("\nI 5 TITOLI DELLA SETTIMANA  (dati fino al %s, universo %d titoli)" % (r["asof"], r["universo"]))
    if r["regime"]:
        g = r["regime"]
        print("Mercato (SPY): %s la media a 200 giorni (%s)" % (
            "sopra" if g["spy_sopra_media200"] else "SOTTO", f_pct(g["spy_vs_media200"])))
    for n, p in enumerate(r["picks"], 1):
        s = p["signal"]
        print("\n%d. %s  %s  -  prezzo %.2f" % (n, p["symbol"], p["name"], p["price"]))
        print("   momentum 12-1 %s, volatilità %s, %s sopra la media 200" % (
            f_pct(s["mom"]), f_pct(s["vol"], sign=False), f_pct(s["vs_sma"])))
        print("   %-9s %10s %12s %22s %8s %12s" % ("", "prob. +", "tipico", "range 10-90 %", "casi", "affidabilità"))
        for label, _ in HORIZONS:
            h = p["horizons"][label]
            st = h["simili"]
            if not st["n"]:
                print("   %-9s %10s" % (label, "n/d"))
                continue
            print("   %-9s %10s %12s %22s %8s %12s" % (
                label, f_pct(st["p_gain"], 0, False), f_pct(st["median"]),
                "%s / %s" % (f_pct(st["p10"]), f_pct(st["p90"])), "%d (%d)" % (st["n"], h["indipendenti"]),
                h["affidabilita"]))
    print("\n   prob. + = quante volte, in condizioni simili, il titolo era in guadagno dopo quel periodo.")
    print("   tipico = guadagno mediano. casi = finestre storiche (tra parentesi quelle che non si sovrappongono).")

    b = r["backtest"]["metrics"]
    print("\nVERIFICA SUL PASSATO (%s - %s, %d settimane, costi %s a cambio)" % (
        r["backtest"]["da"], r["backtest"]["a"], b["settimane"], f_pct(r["backtest"]["costo_andata_ritorno"], 2, False)))
    print("   %-26s %10s %12s %10s" % ("", "annuo", "calo max", "totale"))
    for k, lab in (("strategia", "5 titoli, ogni settimana"), ("paniere", "tutti i titoli, stesso peso"),
                   ("spy", "SPY (S&P 500)")):
        m = b[k]
        print("   %-26s %10s %12s %10s" % (lab, f_pct(m["cagr"]), f_pct(m["max_drawdown"]), f_pct(m["totale"], 0)))
    print("   settimane in guadagno %s, settimane meglio del paniere %s" % (
        f_pct(b["settimane_positive"], 0, False), f_pct(b["settimane_sopra_paniere"], 0, False)))
    if b.get("t_eccesso") is not None:
        t = b["t_eccesso"]
        print("   vantaggio medio sul paniere %s l'anno, t = %.2f: %s" % (
            f_pct(b["eccesso_annuo"]), t,
            "statisticamente significativo (t > 2)" if t > 2 else
            "NON distinguibile dal caso (servirebbe t > 2)"))
    print("\n   anno   5 titoli   paniere")
    for y in b["anni"]:
        print("   %s %10s %9s%s" % (y["anno"], f_pct(y["strategia"], 0), f_pct(y["paniere"], 0),
                                 "   (parziale)" if y["settimane"] < 40 else ""))
    print("\n   %-9s %22s %22s %16s" % ("", "scelte: prob. + / tipico", "paniere: prob. + / tipico", "batte il paniere"))
    for label, _ in HORIZONS:
        x = r["record"][label]
        a, p = x["algoritmo"], x["paniere"]
        print("   %-9s %22s %22s %16s" % (
            label, "%s / %s" % (f_pct(a.get("p_gain"), 0, False), f_pct(a.get("median"))),
            "%s / %s" % (f_pct(p.get("p_gain"), 0, False), f_pct(p.get("median"))),
            f_pct(x["batte_paniere"], 0, False)))
    print("\nATTENZIONE: frequenze del passato, non previsioni. Universo = S&P 100 di oggi (bias di")
    print("sopravvivenza: la verifica è ottimistica). A 1 anno i casi indipendenti sono pochissimi.")
    print("Non è consulenza finanziaria.")


# ------------------------------------------------------------------ main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickers", help="lista separata da virgole al posto dell'S&P 100")
    ap.add_argument("--asof", help="usa solo i dati fino a questa data (YYYY-MM-DD)")
    ap.add_argument("--costo", type=float, default=0.1,
                    help="costo in %% per ogni titolo cambiato, andata e ritorno (default 0.1)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--no-html", action="store_true")
    a = ap.parse_args(argv)

    syms = [x.strip().upper().replace(".", "-") for x in a.tickers.split(",")] if a.tickers else UNIVERSE
    syms = [s for s in dict.fromkeys(syms) if s != MARKET]
    print("[settimana] scarico %d titoli + %s (10 anni, giornaliero; cache 12 ore)..." % (len(syms), MARKET),
          flush=True)

    def get(sym):
        try:
            return sym, fetch(sym), None
        except FetchError as e:
            return sym, None, str(e)

    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        got = list(ex.map(get, syms + [MARKET]))
    errors = [e for _, t, e in got if e]
    texts = {s: t for s, t, _ in got if t}
    if MARKET not in texts:
        print("[settimana] non riesco a scaricare %s: %s" % (MARKET, "; ".join(errors)))
        return 1
    for e in errors:
        print("[settimana] saltato: " + e)

    parsed = {s: parse(t, a.asof) for s, t in texts.items()}
    calendar = sorted(parsed[MARKET][1])
    aligned = align({s: v[1] for s, v in parsed.items()}, calendar)
    stocks = [Stock(s, aligned[s], parsed[s][0].get("shortName") or parsed[s][0].get("longName") or "")
              for s in syms if s in aligned]
    short = [s.sym for s in stocks if s.first >= len(calendar) - LOOKBACK]
    if short:
        print("[settimana] saltati (meno di 1 anno di dati): " + ", ".join(short))
        errors += ["%s: meno di 1 anno di dati" % x for x in short]
    stocks = [s for s in stocks if s.first < len(calendar) - LOOKBACK]
    market = Stock(MARKET, aligned[MARKET])
    if len(stocks) < TOP:
        print("[settimana] servono almeno %d titoli con 1 anno di storia." % TOP)
        return 1

    r = run(stocks, market, calendar, a.costo / 100)
    r["metodo"] = {"lookback": LOOKBACK, "skip": SKIP, "vol_win": VOL_WIN, "sma_win": SMA_WIN,
                   "step": STEP, "top": TOP, "top_pct": TOP_PCT}
    r["saltati"] = errors
    print_report(r)

    os.makedirs(TRADER, exist_ok=True)
    with open(os.path.join(TRADER, "settimana.json"), "w", encoding="utf-8") as fh:
        json.dump(r, fh, indent=1)
    print("\n[settimana] scritto trader/settimana.json")
    if not a.no_html:
        import settimana_report
        out = os.path.join(TRADER, "settimana.html")
        settimana_report.write(out, r)
        print("[settimana] report: trader/settimana.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
