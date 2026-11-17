#!/usr/bin/env python3
"""I 10 titoli della settimana: un algoritmo trasparente, verificato sul passato, con
quando entrare, quando vendere e la probabilità storica di guadagno.

COSA FA
  1. Scarica 10 anni di candele giornaliere (corrette per dividendi e split, Yahoo) per
     ~100 grandi titoli USA (l'S&P 100) più SPY come riferimento di mercato.
  2. Punteggio di ogni titolo (regola nota in letteratura, parametri standard, non ottimizzati):
       momentum 12-1 = rendimento da 12 mesi fa a 1 mese fa (Jegadeesh e Titman, 1993)
       diviso per la volatilità degli ultimi 3 mesi, solo sopra la media a 200 giorni e con
     volatilità almeno del 10 % annuo (sotto, il prezzo è di solito bloccato da un'offerta di
     acquisto). Sceglie i 10 punteggi più alti. Mercati: USA (S&P 100) e Italia (FTSE MIB).
  3. Per ogni titolo una REGOLA precisa:
       entrata  ordine limite per la prossima seduta a ultima chiusura + 0,5 ATR (se non si
                esegue, niente operazione: non si insegue il prezzo)
       uscita   la prima tra: stop-loss (entrata - 3 ATR), target (entrata + 2 volte il
                rischio), oppure alla chiusura della 21a seduta.
     ATR = oscillazione media giornaliera degli ultimi 14 giorni. Le date sono giorni di
     borsa veri (festività NYSE 2026-2027).
  4. PROBABILITÀ: la stessa regola rifatta su ogni volta che quel titolo era in condizioni
     simili nel passato (tra il 20 % migliore del punteggio e sopra la media a 200 giorni),
     e su tutte le scelte passate dell'algoritmo. Per 39 varianti della regola (stop, target,
     durata, anche senza stop o senza target), così l'app può mostrarle tutte.
  5. VERIFICA: la scelta rifatta ogni settimana degli ultimi ~9 anni con i soli dati di allora.

COSA NON FA
  Non prevede il futuro: le probabilità sono frequenze del passato. L'universo è l'S&P 100
  di OGGI (bias di sopravvivenza: la verifica è ottimistica). Non è consulenza finanziaria.

Esempi:
    python3 settimana.py                    # i 10 titoli di questa settimana
    python3 settimana.py --asof 2025-06-30  # cosa avrebbe scelto a quella data
    python3 app.py                          # tutto nell'app: trader/app.html

Solo libreria standard, Python 3.8+.
"""

import argparse
import datetime
import importlib.util
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

# S&P 100 (composizione recente). BRK-B nel formato di Yahoo; BNY Mellon oggi è BNY.
UNIVERSE = """AAPL ABBV ABT ACN ADBE AIG AMD AMGN AMT AMZN AVGO AXP BA BAC BKNG BLK BMY BNY BRK-B C CAT
CHTR CL CMCSA COF COP COST CRM CSCO CVS CVX DE DHR DIS DUK EMR F FDX GD GE GILD GM GOOGL GS HD HON IBM
INTC INTU ISRG JNJ JPM KHC KO LIN LLY LMT LOW MA MCD MDLZ MDT MET META MMM MO MRK MS MSFT NEE NFLX NKE
NOW NVDA ORCL PEP PFE PG PLTR PM PYPL QCOM RTX SBUX SCHW SO SPG T TGT TMO TMUS TSLA TXN UBER UNH UNP UPS
USB V VZ WFC WMT XOM""".split()
MARKET = "SPY"

# FTSE MIB (composizione recente), più qualche grande titolo vicino all'indice. Suffisso .MI di Yahoo.
UNIVERSE_IT = """A2A.MI AMP.MI AZM.MI BAMI.MI BMED.MI BMPS.MI BPE.MI BZU.MI CPR.MI DIA.MI ENEL.MI ENI.MI ERG.MI FBK.MI
G.MI HER.MI IG.MI INW.MI ISP.MI IP.MI IVG.MI LDO.MI MB.MI MONC.MI NEXI.MI PIRC.MI PRY.MI PST.MI RACE.MI REC.MI
SPM.MI SRG.MI STLAM.MI STMMI.MI TEN.MI TIT.MI TRN.MI UCG.MI UNI.MI BC.MI BGN.MI LTMC.MI AVIO.MI""".split()

MERCATI = {
    "usa": {"nome": "USA", "universo": UNIVERSE, "indice": "SPY", "indice_nome": "SPY (S&P 500)", "indice_breve": "SPY",
            "universo_nome": "S&P 100", "valuta": "$", "valuta_nome": "dollari", "costo": 0.1,
            "fuso": "America/New_York", "citta": "New York", "chiusura": (16, 0), "borsa": "NYSE"},
    # Costo 0,2 %: 0,1 % di Tobin tax italiana sugli acquisti + commissioni e spread.
    "italia": {"nome": "Italia", "universo": UNIVERSE_IT, "indice": "FTSEMIB.MI", "indice_nome": "FTSE MIB (senza dividendi)", "indice_breve": "FTSE MIB",
               "universo_nome": "FTSE MIB", "valuta": "€", "valuta_nome": "euro", "costo": 0.2,
               "fuso": "Europe/Rome", "citta": "Milano", "chiusura": (17, 30), "borsa": "Borsa Italiana"},
}

HORIZONS = [("7 giorni", 5), ("1 mese", 21), ("1 anno", 252)]
LOOKBACK = 252     # 12 mesi di borsa
SKIP = 21          # salta l'ultimo mese (inversione di breve periodo)
VOL_WIN = 63       # 3 mesi per la volatilità
SMA_WIN = 200      # media mobile del filtro di trend
ATR_WIN = 14       # oscillazione media giornaliera
STEP = 5           # ribilanciamento settimanale
TOP = 10
TOP_PCT = 0.20     # "condizioni simili" = nel 20 % migliore del punteggio
MIN_VOL = 0.10     # sotto il 10 % annuo il prezzo è quasi fermo: di solito un'offerta di acquisto lo blocca

# la regola di entrata e uscita, con le varianti che l'app permette di provare
LIMIT_ATR = 0.5            # entrata: limite a ultima chiusura + 0,5 ATR
STOPS_ATR = (1.5, 2.0, 3.0, 0)     # 0 = nessuno stop (si esce solo alla data)
TARGETS_R = (1.5, 2.0, 3.0, 0)     # 0 = nessun target (si lascia correre fino a stop o data)
HOLDS = (10, 21, 63)               # 2 settimane, 1 mese, 3 mesi di borsa
# Stop a 3 ATR: lo standard per operazioni di qualche settimana. Sui dati, gli stop più stretti
# scattano spesso per rumore (con 2 ATR quasi una volta su due): l'app mostra tutte le varianti.
DEFAULT_RULE = (3.0, 2.0, 21)
MC_BARS = 252              # candele usate dalla Macchina del Tempo dell'app


class FetchError(Exception):
    pass


def rule_key(ks, rr, hold):
    return "%g|%g|%d" % (ks, rr, hold)


def all_rules():
    """Tutte le varianti: senza stop non c'è un rischio su cui misurare il target, quindi
    'nessuno stop' va solo con 'nessun target' (uscita alla data)."""
    return [(ks, rr, h) for h in HOLDS for ks in STOPS_ATR for rr in TARGETS_R if ks or not rr]


# ------------------------------------------------------------------ calendario

def _nyse_holidays():
    path = os.path.join(ROOT, ".claude", "skills", "trader-alerts", "alerts.py")
    try:
        spec = importlib.util.spec_from_file_location("trader_alerts_cal", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return set(mod.NYSE_HOLIDAYS), set(mod.NYSE_EARLY_CLOSE)
    except Exception:
        return set(), set()


def easter(year):
    """Domenica di Pasqua (calendario gregoriano, algoritmo anonimo)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    return datetime.date(year, month, (h + l - 7 * m + 114) % 31 + 1)


def borsa_italiana_holidays(year):
    """Chiusure di Borsa Italiana: confermate sui giorni mancanti del FTSE MIB 2017-2026."""
    e = easter(year)
    fixed = ["01-01", "05-01", "08-15", "12-24", "12-25", "12-26", "12-31"]
    return {"%d-%s" % (year, x) for x in fixed} | {(e - datetime.timedelta(days=2)).isoformat(),
                                                    (e + datetime.timedelta(days=1)).isoformat()}


def trading_days_after(day, n, mercato="usa"):
    """I prossimi n giorni di borsa dopo `day` (YYYY-MM-DD), con le festività del mercato."""
    d = datetime.date.fromisoformat(day)
    if mercato == "italia":
        hol = set()
        for y in range(d.year, d.year + 3):
            hol |= borsa_italiana_holidays(y)
    else:
        hol, _ = _nyse_holidays()
    out = []
    while len(out) < n:
        d += datetime.timedelta(days=1)
        if d.weekday() < 5 and d.isoformat() not in hol:
            out.append(d.isoformat())
    return out


def now_in(tz):
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo(tz)).replace(tzinfo=None)
    except Exception:
        off = 1 if tz == "Europe/Rome" else -5
        return datetime.datetime.utcnow() + datetime.timedelta(hours=off)


def now_new_york():
    return now_in("America/New_York")


# ------------------------------------------------------------------ dati

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


def parse(text, cut=None, tz="America/New_York", close=(16, 0)):
    """-> (meta, {data: chiusura corretta}, {data: (apertura, massimo, minimo, chiusura) corretti}).
    Scarta la barra di oggi se la borsa non ha ancora chiuso, e tutto ciò che è dopo `cut`."""
    res = json.loads(text)["chart"]["result"][0]
    meta = res.get("meta", {})
    ts = res.get("timestamp") or []
    ind = res.get("indicators", {})
    q = (ind.get("quote") or [{}])[0]
    raw_c = q.get("close") or []
    adj = (ind.get("adjclose") or [{}])[0].get("adjclose") or raw_c
    o_, h_, l_ = q.get("open") or [], q.get("high") or [], q.get("low") or []
    off = meta.get("gmtoffset", -18000)
    closes, ohlc = {}, {}
    for k, t in enumerate(ts):
        c = adj[k] if k < len(adj) else None
        if c is None or c <= 0:
            continue
        d = datetime.datetime.fromtimestamp(t + off, datetime.timezone.utc).strftime("%Y-%m-%d")
        closes[d] = float(c)
        rc = raw_c[k] if k < len(raw_c) else None
        f = c / rc if rc else 1.0                      # fattore di correzione del giorno
        vals = [x[k] if k < len(x) else None for x in (o_, h_, l_)]
        if None in vals or not rc:
            ohlc[d] = (c, c, c, c)
        else:
            o, h, lo = (v * f for v in vals)
            ohlc[d] = (o, max(h, o, c), min(lo, o, c), c)
    now = now_in(tz)
    today = now.strftime("%Y-%m-%d")
    if today in closes and (now.hour, now.minute) < tuple(close):
        del closes[today]                       # barra di oggi ancora in formazione
        ohlc.pop(today, None)
    if cut:
        closes = {d: c for d, c in closes.items() if d <= cut}
        ohlc = {d: v for d, v in ohlc.items() if d <= cut}
    return meta, closes, ohlc


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


def align_ohlc(series, calendar):
    """Come align, ma un giorno mancante diventa una candela piatta all'ultima chiusura."""
    out = {}
    for sym, s in series.items():
        row, last = [], None
        for d in calendar:
            if d in s:
                row.append(s[d])
                last = s[d][3]
            else:
                row.append(None if last is None else (last, last, last, last))
        out[sym] = row
    return out


# ------------------------------------------------------------------ indicatori

class Stock:
    """Prezzi allineati + somme prefisse per media mobile e volatilità in O(1)."""

    def __init__(self, sym, prices, name="", ohlc=None):
        self.sym, self.p, self.name = sym, prices, name
        n = len(prices)
        if ohlc is None:
            ohlc = [None if x is None else (x, x, x, x) for x in prices]
        self.o = [b[0] if b else None for b in ohlc]
        self.h = [b[1] if b else None for b in ohlc]
        self.l = [b[2] if b else None for b in ohlc]
        self.first = next((i for i, x in enumerate(prices) if x is not None), n)
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

    def atr(self, i):
        """Media del true range degli ultimi ATR_WIN giorni fino a i compreso."""
        if i - self.first < ATR_WIN:
            return None
        tot = 0.0
        for k in range(i - ATR_WIN + 1, i + 1):
            pc = self.p[k - 1]
            tot += max(self.h[k] - self.l[k], abs(self.h[k] - pc), abs(self.l[k] - pc))
        return tot / ATR_WIN

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
                "vs_sma": self.p[i] / sma - 1, "frozen": v < MIN_VOL}


def rank_day(stocks, i, top=TOP):
    """Classifica del giorno i: (scelti, insieme 'condizioni simili', segnali)."""
    sig = {}
    for s in stocks:
        x = s.signal(i)
        if x is not None:
            sig[s.sym] = x
    order = sorted(sig, key=lambda k: -sig[k]["score"])
    cut = max(1, int(round(len(order) * TOP_PCT)))
    ok = lambda k: sig[k]["above"] and not sig[k]["frozen"]
    similar = {k for k in order[:cut] if ok(k)}
    picks = [k for k in order if ok(k)][:top]
    return picks, similar, sig


# ------------------------------------------------------------------ la regola

def trade(s, i, ks, rr, hold, cost=0.0):
    """La regola, rifatta sul passato dal segnale alla chiusura del giorno i.

    Entrata: limite a chiusura(i) + LIMIT_ATR x ATR per la seduta i+1 (all'apertura se
    l'apertura è sotto il limite, altrimenti al limite se il minimo lo tocca, altrimenti
    niente operazione). Uscita: stop = entrata - ks x ATR, target = entrata + rr x ks x ATR,
    oppure alla chiusura della seduta numero `hold` (ks = 0: nessuno stop; rr = 0: nessun
    target). Un'apertura oltre lo stop o il target
    esce all'apertura (gap). Se nello stesso giorno si toccano entrambi, conta lo stop.

    -> None se mancano dati, {"filled": False} se il limite non si esegue, altrimenti
       {"filled": True, "outcome": target|stop|tempo, "ret": rendimento netto, "days": n}.
    """
    n = len(s.p)
    if i + hold >= n or s.p[i] is None:
        return None
    a = s.atr(i)
    if not a:
        return None
    limit = s.p[i] + LIMIT_ATR * a
    d = i + 1
    if s.o[d] <= limit:
        fill = s.o[d]
    elif s.l[d] <= limit:
        fill = limit
    else:
        return {"filled": False}
    stop = fill - ks * a if ks else -math.inf
    target = fill + rr * ks * a if (ks and rr) else math.inf

    def out(kind, price, k):
        return {"filled": True, "outcome": kind, "ret": price / fill - 1 - cost, "days": k - d + 1}

    for k in range(d, d + hold):
        if k > d:
            if s.o[k] <= stop:
                return out("stop", s.o[k], k)
            if s.o[k] >= target:
                return out("target", s.o[k], k)
        if s.l[k] <= stop:
            return out("stop", stop, k)
        if s.h[k] >= target:
            return out("target", target, k)
    return out("tempo", s.p[d + hold - 1], d + hold - 1)


def trade_stats(results, hold):
    """results: lista di (indice del segnale, esito di trade)."""
    done = [(i, r) for i, r in results if r and r.get("filled")]
    unfilled = sum(1 for _, r in results if r and not r.get("filled"))
    rets = [r["ret"] for _, r in done]
    if not rets:
        return {"n": 0, "non_eseguiti": unfilled, "indipendenti": 0}
    st = stats(rets)
    st.update({
        "non_eseguiti": unfilled,
        "p_target": sum(1 for _, r in done if r["outcome"] == "target") / len(done),
        "p_stop": sum(1 for _, r in done if r["outcome"] == "stop") / len(done),
        "p_tempo": sum(1 for _, r in done if r["outcome"] == "tempo") / len(done),
        "giorni": sum(r["days"] for _, r in done) / len(done),
        "indipendenti": independent(sorted({i for i, _ in done}), hold),
    })
    return st


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


def r4(x):
    return None if x is None else round(x, 4)


def slim(st):
    return {k: (r4(v) if isinstance(v, float) else v) for k, v in st.items()}


# ------------------------------------------------------------------ analisi

def run(stocks, market, calendar, cost_rt, top=TOP, mercato="usa"):
    last = len(calendar) - 1
    start = min(s.first for s in stocks) + LOOKBACK
    sched = list(range(last, start - 1, -STEP))[::-1]       # settimanale, allineato a oggi
    by_day = {i: rank_day(stocks, i, top) for i in sched}
    smap = {s.sym: s for s in stocks}
    rules = all_rules()

    picks, _, sig_now = by_day[last]

    # 1. verifica settimanale: i titoli scelti, tenuti una settimana, contro paniere e SPY
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
        net = g - len(set(pk) - prev) / len(pk) * cost_rt
        prev = set(pk)
        b = sum(smap[k].fwd(i, STEP) for k in sig) / len(sig)
        spy = market.fwd(i, STEP)
        eq["strategia"].append(eq["strategia"][-1] * (1 + net))
        eq["paniere"].append(eq["paniere"][-1] * (1 + b))
        eq["spy"].append(eq["spy"][-1] * (1 + spy))
        dates.append(calendar[i + STEP])
        weekly.append((net, b, calendar[i + STEP][:4]))

    # 2. comprare e tenere: track record per orizzonte
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
        record[label] = {"algoritmo": slim(stats(pk_r)), "paniere": slim(stats(bench_r)),
                         "batte_paniere": r4(sum(beat) / len(beat)) if beat else None,
                         "settimane": len(beat),
                         "indipendenti": independent([i for i in sched if i + h <= last], h)}

    # 3. la regola su tutte le scelte passate dell'algoritmo (ogni variante)
    pooled = {}
    for ks, rr, h in rules:
        res = []
        for i in sched:
            if i + h >= last:
                break
            for k in by_day[i][0]:
                res.append((i, trade(smap[k], i, ks, rr, h, cost_rt)))
        pooled[rule_key(ks, rr, h)] = slim(trade_stats(res, h))

    # 4. ogni titolo scelto: regola in condizioni simili, comprare e tenere, dati per l'app
    future = trading_days_after(calendar[last], max(HOLDS) + 1, mercato)
    detail = []
    for k in picks:
        s = smap[k]
        sim_idx = [i for i in sched if i < last and k in by_day[i][1]]
        grid = {}
        for ks, rr, h in rules:
            res = [(i, trade(s, i, ks, rr, h, cost_rt)) for i in sim_idx if i + h < last]
            st = trade_stats(res, h)
            st["affidabilita"] = confidence(st.get("indipendenti", 0))
            grid[rule_key(ks, rr, h)] = slim(st)
        hold_stats = {}
        for label, h in HORIZONS:
            idx = [i for i in sim_idx if i + h <= last]
            n_ind = independent(idx, h)
            hold_stats[label] = {"simili": slim(stats([s.fwd(i, h) for i in idx])),
                                 "indipendenti": n_ind, "affidabilita": confidence(n_ind)}
        lo = max(s.first + 1, last - MC_BARS + 1)
        bars = [[round(s.o[i] / s.p[i - 1], 5), round(s.h[i] / s.p[i - 1], 5),
                 round(s.l[i] / s.p[i - 1], 5), round(s.p[i] / s.p[i - 1], 5)] for i in range(lo, last + 1)]
        c0 = max(s.first, last - 129)
        detail.append({
            "symbol": k, "name": s.name, "price": round(s.p[last], 2), "atr": round(s.atr(last), 4),
            "signal": slim(sig_now[k]), "rule": grid, "hold": hold_stats, "bars": bars,
            "chart": {"dates": calendar[c0:last + 1], "close": [round(x, 2) for x in s.p[c0:last + 1]],
                      "sma": [round(s.sma(i), 2) if i - s.first >= SMA_WIN else None
                              for i in range(c0, last + 1)]},
        })

    # 5. metriche della verifica
    def curve_stats(c):
        years = max(1e-9, (len(c) - 1) * STEP / 252)
        peak, dd = c[0], 0.0
        for x in c:
            peak = max(peak, x)
            dd = min(dd, x / peak - 1)
        return {"cagr": r4(c[-1] ** (1 / years) - 1), "max_drawdown": r4(dd), "totale": r4(c[-1] - 1)}

    metrics = {k: curve_stats(v) for k, v in eq.items()}
    metrics["settimane"] = len(weekly)
    metrics["settimane_positive"] = r4(sum(1 for n, _, _ in weekly if n > 0) / max(1, len(weekly)))
    metrics["settimane_sopra_paniere"] = r4(sum(1 for n, b, _ in weekly if n > b) / max(1, len(weekly)))
    ex = [n - b for n, b, _ in weekly]
    if len(ex) > 2:
        mu = sum(ex) / len(ex)
        sd = math.sqrt(sum((x - mu) ** 2 for x in ex) / (len(ex) - 1))
        metrics["eccesso_annuo"] = r4(mu * 52)
        metrics["t_eccesso"] = r4(mu / sd * math.sqrt(len(ex))) if sd > 0 else None
    years = {}
    for n, b, y in weekly:
        a = years.setdefault(y, [1.0, 1.0, 0])
        a[0] *= 1 + n
        a[1] *= 1 + b
        a[2] += 1
    metrics["anni"] = [{"anno": y, "strategia": r4(v[0] - 1), "paniere": r4(v[1] - 1), "settimane": v[2]}
                       for y, v in sorted(years.items())]

    m_i = market.signal(last)
    regime = {"spy_sopra_media200": m_i["above"], "spy_vs_media200": r4(m_i["vs_sma"])} if m_i else None
    return {
        "asof": calendar[last], "future_days": future, "picks": detail, "record": record, "pooled": pooled,
        "backtest": {"dates": dates, "curves": {k: [round(x, 4) for x in v] for k, v in eq.items()},
                     "metrics": metrics, "da": dates[0], "a": dates[-1], "costo_andata_ritorno": cost_rt},
        "universo": len(stocks), "regime": regime, "top": top,
        "rules": {"stops_atr": STOPS_ATR, "targets_r": TARGETS_R, "holds": HOLDS, "default": DEFAULT_RULE,
                  "limit_atr": LIMIT_ATR, "atr_win": ATR_WIN},
        "classifica": [dict(symbol=k, **slim(sig_now[k])) for k in
                       sorted(sig_now, key=lambda x: -sig_now[x]["score"])][:25],
        "metodo": {"lookback": LOOKBACK, "skip": SKIP, "vol_win": VOL_WIN, "sma_win": SMA_WIN,
                   "step": STEP, "top": top, "top_pct": TOP_PCT},
    }


def analizza(tickers=None, asof=None, cost_pct=None, top=TOP, workers=4, log=print, mercato="usa"):
    """Scarica, allinea e analizza un mercato. -> il dizionario dei risultati (vedi run)."""
    cfg = MERCATI[mercato]
    MARKET = cfg["indice"]
    if cost_pct is None:
        cost_pct = cfg["costo"]
    if tickers:
        syms = [x.strip().upper() for x in tickers]
        syms = [x if x.endswith(".MI") else x.replace(".", "-") for x in syms]
    else:
        syms = cfg["universo"]
    syms = [s for s in dict.fromkeys(syms) if s and s != MARKET]
    log("[settimana] %s: scarico %d titoli + %s (10 anni, giornaliero; cache 12 ore)..."
        % (cfg["nome"], len(syms), MARKET))

    def get(sym):
        try:
            return sym, fetch(sym), None
        except FetchError as e:
            return sym, None, str(e)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        got = list(ex.map(get, syms + [MARKET]))
    errors = [e for _, t, e in got if e]
    texts = {s: t for s, t, _ in got if t}
    if MARKET not in texts:
        raise FetchError("non riesco a scaricare %s: %s" % (MARKET, "; ".join(errors)))

    parsed = {s: parse(t, asof, cfg["fuso"], cfg["chiusura"]) for s, t in texts.items()}
    calendar = sorted(parsed[MARKET][1])
    closes = align({s: v[1] for s, v in parsed.items()}, calendar)
    ohlc = align_ohlc({s: v[2] for s, v in parsed.items()}, calendar)
    stocks = [Stock(s, closes[s], parsed[s][0].get("shortName") or parsed[s][0].get("longName") or "", ohlc[s])
              for s in syms if s in closes]
    short = [s.sym for s in stocks if s.first >= len(calendar) - LOOKBACK]
    errors += ["%s: meno di 1 anno di dati" % x for x in short]
    stocks = [s for s in stocks if s.first < len(calendar) - LOOKBACK]
    for e in errors:
        log("[settimana] saltato: " + e)
    if len(stocks) < top:
        raise FetchError("servono almeno %d titoli con 1 anno di storia" % top)

    r = run(stocks, Stock(MARKET, closes[MARKET], cfg["indice_nome"], ohlc[MARKET]), calendar, cost_pct / 100,
            top, mercato)
    r["saltati"] = errors
    r["mercato"] = {k: cfg[k] for k in ("nome", "indice_nome", "indice_breve", "universo_nome", "valuta",
                                         "valuta_nome", "citta", "borsa", "costo")}
    r["mercato"]["id"] = mercato
    live = {}
    for p in r["picks"]:
        m = parsed[p["symbol"]][0]
        if m.get("regularMarketPrice") and m.get("regularMarketTime") and not asof:
            live[p["symbol"]] = {"price": m["regularMarketPrice"], "time": datetime.datetime.fromtimestamp(
                m["regularMarketTime"] + m.get("gmtoffset", -18000), datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")}
    r["live"] = live
    r["generato"] = now_in(cfg["fuso"]).strftime("%Y-%m-%d %H:%M")
    return r


# ------------------------------------------------------------------ stampa

def f_pct(x, d=1, sign=True):
    if x is None:
        return "n/d"
    s = ("%+." if sign else "%.") + str(d) + "f %%"
    return (s % (x * 100)).replace(".", ",")


def plan_for(p, r, rule=DEFAULT_RULE):
    """Livelli e date della regola per un titolo scelto, dal prezzo di riferimento (ultima chiusura)."""
    ks, rr, hold = rule
    ref, a = p["price"], p["atr"]
    return {"entrata_giorno": r["future_days"][0], "limite": ref + r["rules"]["limit_atr"] * a,
            "stop": ref - ks * a if ks else None, "target": ref + rr * ks * a if (ks and rr) else None,
            "uscita_giorno": r["future_days"][hold - 1]}


def print_report(r):
    ks, rr, hold = DEFAULT_RULE
    mk = r.get("mercato", {"nome": "USA", "indice_nome": "SPY", "valuta": "$"})
    print("\nI %d TITOLI DELLA SETTIMANA - %s  (dati fino al %s, universo %d titoli, prezzi in %s)"
          % (r["top"], mk["nome"].upper(), r["asof"], r["universo"], mk["valuta"]))
    if r["regime"]:
        g = r["regime"]
        print("Indice %s: %s la media a 200 giorni (%s)" % (mk["indice_nome"],
            "sopra" if g["spy_sopra_media200"] else "SOTTO", f_pct(g["spy_vs_media200"])))
    print("Regola: entrata con limite a chiusura + %g ATR, stop %g ATR, target %gR, uscita dopo %d sedute.\n"
          % (LIMIT_ATR, ks, rr, hold))
    num = lambda x: "%9s" % "-" if x is None else "%9.2f" % x
    print("  #  %-6s %9s %9s %9s %9s  %-10s %8s %8s %10s" % (
        "titolo", "chiusura", "limite", "stop", "target", "esci il", "prob. +", "tipico", "casi"))
    key = rule_key(*DEFAULT_RULE)
    for n, p in enumerate(r["picks"], 1):
        pl = plan_for(p, r)
        st = p["rule"][key]
        print(" %2d  %-6s %9.2f %9.2f %s %s  %-10s %8s %8s %10s" % (
            n, p["symbol"].replace(".MI", ""), p["price"], pl["limite"], num(pl["stop"]), num(pl["target"]),
            pl["uscita_giorno"],
            f_pct(st.get("p_gain"), 0, False), f_pct(st.get("median")),
            "%d (%d)" % (st.get("n", 0), st.get("indipendenti", 0))))
    pool = r["pooled"][key]
    print("\n  Entrata: seduta del %s. prob. + = quante volte la stessa regola, in condizioni simili," % r["future_days"][0])
    print("  ha chiuso in guadagno (costi inclusi). Su tutte le scelte passate dell'algoritmo: %s in guadagno,"
          % f_pct(pool.get("p_gain"), 0, False))
    print("  tipico %s, target %s / stop %s / a tempo %s." % (
        f_pct(pool.get("median")), f_pct(pool.get("p_target"), 0, False), f_pct(pool.get("p_stop"), 0, False),
        f_pct(pool.get("p_tempo"), 0, False)))

    b = r["backtest"]["metrics"]
    print("\nVERIFICA (%s - %s, %d settimane): annuo %s contro paniere %s e " % (
        r["backtest"]["da"], r["backtest"]["a"], b["settimane"], f_pct(b["strategia"]["cagr"]),
        f_pct(b["paniere"]["cagr"])) + "%s %s" % (mk["indice_nome"], f_pct(b["spy"]["cagr"])))
    if b.get("t_eccesso") is not None:
        t = b["t_eccesso"]
        print("  vantaggio sul paniere %s l'anno, t = %.2f: %s" % (
            f_pct(b["eccesso_annuo"]), t, "significativo (t > 2)" if t > 2 else "NON distinguibile dal caso"))
    print("\nFrequenze del passato, non previsioni. Bias di sopravvivenza. Non è consulenza finanziaria.")


# ------------------------------------------------------------------ main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mercato", choices=sorted(MERCATI), default="usa", help="usa (S&P 100) o italia (FTSE MIB)")
    ap.add_argument("--tickers", help="lista separata da virgole al posto dell'universo del mercato")
    ap.add_argument("--asof", help="usa solo i dati fino a questa data (YYYY-MM-DD)")
    ap.add_argument("--top", type=int, default=TOP, help="quanti titoli (default 10)")
    ap.add_argument("--costo", type=float, default=None,
                    help="costo in %% per operazione, andata e ritorno (default 0,1 USA, 0,2 Italia)")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    try:
        r = analizza(a.tickers.split(",") if a.tickers else None, a.asof, a.costo, a.top, a.workers,
                     mercato=a.mercato)
    except FetchError as e:
        print("[settimana] " + str(e))
        return 1
    print_report(r)
    os.makedirs(TRADER, exist_ok=True)
    name = "settimana.json" if a.mercato == "usa" else "settimana-%s.json" % a.mercato
    with open(os.path.join(TRADER, name), "w", encoding="utf-8") as fh:
        json.dump(r, fh)
    print("\n[settimana] scritto trader/%s  (per l'app: python3 app.py)" % name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
