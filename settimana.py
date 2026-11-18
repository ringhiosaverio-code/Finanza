#!/usr/bin/env python3
"""I titoli consigliati della settimana, in ordine di probabilità di riuscita.

COSA FA
  1. Scarica 10 anni di candele giornaliere (corrette per dividendi e split, Yahoo) per i
     titoli dell'S&P 100 (USA) o del FTSE MIB (Italia) e per l'indice del mercato.
  2. CANDIDATI: i titoli sopra la loro media a 200 giorni e con volatilità almeno del 10 %
     annuo (sotto, il prezzo è di solito bloccato da un'offerta di acquisto).
  3. LA REGOLA, uguale per tutti: entrata con ordine limite alla prossima seduta a ultima
     chiusura + 0,5 ATR (se non si esegue, niente operazione); uscita alla prima tra
     protezione (stop), obiettivo (target) e una data. Quattro stili (Prudente, Equilibrato,
     Lascia correre, Solo data) e tre durate (2 settimane, 1 mese, 3 mesi).
     ATR = oscillazione media giornaliera degli ultimi 14 giorni.
  4. LA PROBABILITÀ DI RIUSCITA (= l'operazione chiude in guadagno, costi inclusi): un modello
     lineare con sei indizi noti in letteratura, misurati come posizione in classifica tra i
     candidati del giorno:
       forza dell'ultimo anno (momentum 12-1 / volatilità, Jegadeesh e Titman 1993),
       ultimo mese (inversione di breve periodo), vicinanza al massimo annuale (George e Hwang
       2004), calma del prezzo (bassa volatilità), distanza dalla media a 200 giorni, e se il
       mercato è sopra la sua media a 200 giorni.
     Il modello impara dalla storia di tutti i candidati di ogni settimana degli ultimi ~9 anni.
  5. VERIFICA WALK-FORWARD: ogni anno il modello è allenato solo sugli anni precedenti (con
     gli esiti già noti) e giudicato su quello dopo. Si misura se le probabilità stimate
     corrispondono a quelle osservate, e se i 10 con la probabilità più alta hanno fatto meglio
     di tutti i candidati e del vecchio algoritmo (i 10 con il momentum più alto).
  6. CLASSIFICA: i 10 candidati di oggi con la probabilità di riuscita più alta.

COSA NON FA
  Non prevede il futuro: le probabilità sono stime dal passato. L'universo è la composizione
  di OGGI degli indici (bias di sopravvivenza). Non è consulenza finanziaria.

Esempi:
    python3 settimana.py                     # USA
    python3 settimana.py --mercato italia    # Italia
    python3 settimana.py --asof 2025-06-30   # cosa avrebbe consigliato a quella data
    python3 app.py                           # tutto nell'app: trader/app.html

Solo libreria standard, Python 3.8+.
"""


import argparse
import bisect
import datetime
import importlib.util
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import deque
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

UNIVERSE_ETF = [s + ".MI" for s in "SWDA CSSPX CSNDX EIMI VWRL SMEA CSEMU IMIB VHYL IDVY SJPA".split()]
UNIVERSE_BOND = [s + ".MI" for s in
                 "IEAG IEAC IHYG IBCI AGGH IBTM IBGS IBGM CSBGE7 ITPS BTP10 VETY SEML IGLT IBTS XG7S".split()]
UNIVERSE_ORO = [s + ".MI" for s in "SGLD PHAG CMOD".split()]

MERCATI = {
    "usa": {"nome": "USA", "universo": UNIVERSE, "indice": "SPY", "indice_nome": "SPY (S&P 500)", "indice_breve": "SPY",
            "universo_nome": "S&P 100", "valuta": "$", "valuta_nome": "dollari", "costo": 0.1,
            "fuso": "America/New_York", "citta": "New York", "chiusura": (16, 0), "borsa": "NYSE"},
    # Costo 0,2 %: 0,1 % di Tobin tax italiana sugli acquisti + commissioni e spread.
    "italia": {"nome": "Italia", "universo": UNIVERSE_IT, "indice": "FTSEMIB.MI", "indice_nome": "FTSE MIB (senza dividendi)", "indice_breve": "FTSE MIB",
               "universo_nome": "FTSE MIB", "valuta": "€", "valuta_nome": "euro", "costo": 0.2,
               "fuso": "Europe/Rome", "citta": "Milano", "chiusura": (17, 30), "borsa": "Borsa Italiana"},
    # ETF UCITS e ETC quotati su Borsa Italiana: acquistabili da chi investe dall'Italia (gli ETF USA
    # di solito no, per la regola europea sui documenti KID). Un solo ETF per indice, senza doppioni.
    # Niente Tobin tax sugli ETF: costo 0,1 %. La soglia del prezzo fermo scende con la volatilità
    # tipica della categoria (un ETF di titoli di Stato a breve oscilla dell'1-2 % l'anno).
    "etf": {"nome": "ETF azionari", "universo": UNIVERSE_ETF, "indice": "FTSEMIB.MI", "indice_nome": "FTSE MIB (senza dividendi)",
            "indice_breve": "FTSE MIB", "universo_nome": "ETF azionari su Borsa Italiana", "valuta": "€",
            "valuta_nome": "euro", "costo": 0.1, "fuso": "Europe/Rome", "citta": "Milano", "chiusura": (17, 30),
            "borsa": "Borsa Italiana", "min_vol": 0.05},
    "bond": {"nome": "ETF obbligazionari", "universo": UNIVERSE_BOND, "indice": "FTSEMIB.MI", "indice_nome": "FTSE MIB (senza dividendi)",
             "indice_breve": "FTSE MIB", "universo_nome": "ETF obbligazionari su Borsa Italiana", "valuta": "€",
             "valuta_nome": "euro", "costo": 0.1, "fuso": "Europe/Rome", "citta": "Milano", "chiusura": (17, 30),
             "borsa": "Borsa Italiana", "min_vol": 0.01},
    "oro": {"nome": "Oro e materie prime", "universo": UNIVERSE_ORO, "indice": "FTSEMIB.MI", "indice_nome": "FTSE MIB (senza dividendi)",
            "indice_breve": "FTSE MIB", "universo_nome": "ETC e ETF su Borsa Italiana", "valuta": "€",
            "valuta_nome": "euro", "costo": 0.1, "fuso": "Europe/Rome", "citta": "Milano", "chiusura": (17, 30),
            "borsa": "Borsa Italiana", "min_vol": 0.05},
}


LOOKBACK = 252     # 12 mesi di borsa
SKIP = 21          # salta l'ultimo mese (inversione di breve periodo)
VOL_WIN = 63       # 3 mesi per la volatilità
SMA_WIN = 200      # media mobile del filtro di trend
ATR_WIN = 14       # oscillazione media giornaliera
STEP = 5           # una decisione a settimana
TOP = 10
MIN_VOL = 0.10     # sotto il 10 % annuo il prezzo è quasi fermo: di solito un'offerta di acquisto lo blocca

# la regola di entrata e uscita
LIMIT_ATR = 0.5    # entrata: limite a ultima chiusura + 0,5 ATR
STYLES = [
    {"id": "prudente", "nome": "Prudente", "ks": 2.0, "rr": 1.5,
     "desc": "Protezione e obiettivo vicini: si esce presto, in guadagno o in perdita."},
    {"id": "equilibrato", "nome": "Equilibrato", "ks": 3.0, "rr": 2.0,
     "desc": "Protezione a 3 oscillazioni giornaliere sotto l'entrata, obiettivo al doppio di quanto rischi."},
    {"id": "corsa", "nome": "Lascia correre", "ks": 3.0, "rr": 0,
     "desc": "Stessa protezione, nessun obiettivo: se non scatta la protezione, vendi alla data."},
    {"id": "data", "nome": "Solo data", "ks": 0, "rr": 0,
     "desc": "Niente protezione né obiettivo: vendi alla data, qualunque cosa succeda."},
]
HOLDS = (10, 21, 63)
HOLD_NAMES = {10: "2 settimane", 21: "1 mese", 63: "3 mesi"}
DEFAULT_STYLE, DEFAULT_HOLD = "equilibrato", 21

# gli indizi del modello di probabilità (misurati come posizione in classifica tra i candidati)
FEATURES = [
    {"id": "forza", "nome": "Forza dell'ultimo anno", "alto": "tra i più forti dell'ultimo anno",
     "basso": "tra i meno forti dell'ultimo anno"},
    {"id": "mese", "nome": "Ultimo mese", "alto": "salito molto nell'ultimo mese",
     "basso": "fermo o in calo nell'ultimo mese"},
    {"id": "massimo", "nome": "Vicinanza al massimo dell'anno", "alto": "vicino al massimo dell'anno",
     "basso": "lontano dal massimo dell'anno"},
    {"id": "calma", "nome": "Calma del prezzo", "alto": "prezzo più calmo degli altri",
     "basso": "prezzo più nervoso degli altri"},
    {"id": "trend", "nome": "Distanza dalla media a 200 giorni", "alto": "molto sopra la media a 200 giorni",
     "basso": "appena sopra la media a 200 giorni"},
    {"id": "mercato", "nome": "Mercato in salita", "alto": "mercato sopra la sua media a 200 giorni",
     "basso": "mercato sotto la sua media a 200 giorni"},
]
GROUPS = 5                 # quinti di forza ("titoli simili")
MAX_LOSS_P10 = 0.10        # regola consigliata: nel 10 % dei casi peggiori non si perde più del 10 %
K_SHRINK = 100             # quanto restringere ogni quinto verso la media
MIN_TRAIN_WEEKS = 104      # almeno 2 anni di storia prima di giudicare un anno
MC_BARS = 252              # candele usate dalla Macchina del Tempo dell'app


class FetchError(Exception):
    pass


def vkey(style_id, hold):
    return "%s|%d" % (style_id, hold)


def style(style_id):
    return next(s for s in STYLES if s["id"] == style_id)


def variants():
    return [(s["id"], h) for h in HOLDS for s in STYLES]


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
    if mercato != "usa":
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

FINE_SEDUTA = re.compile(r'"regular":\{[^{}]*?"end":(\d+)')


def cache_valida(path, max_age_hours, adesso=None):
    """Il grafico in cache, se è abbastanza recente e nessuna seduta è finita dopo che è stato scritto;
    altrimenti None. Yahoo scrive nei metadati quando finisce la seduta che descrive: una cache scritta
    a seduta aperta (per esempio alle 18:10 per le azioni USA) non vale più dopo la chiusura (5 minuti
    dopo, quando c'è l'asta), anche se ha meno di max_age_hours."""
    if not os.path.exists(path):
        return None
    adesso = time.time() if adesso is None else adesso
    scritto = os.path.getmtime(path)
    if adesso - scritto >= max_age_hours * 3600:
        return None
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = FINE_SEDUTA.search(text)
    if m and scritto < int(m.group(1)) + 300 <= adesso:
        return None
    return text


def fetch(sym, max_age_hours=12):
    """Il JSON del grafico Yahoo a 10 anni, con una cache in trader/cache/daily."""
    path = os.path.join(CACHE, sym + ".v2.json")          # v2: con i dividendi
    text = cache_valida(path, max_age_hours)
    if text is not None:
        return text
    last = None
    for host in ("query2", "query1"):
        url = ("https://%s.finance.yahoo.com/v8/finance/chart/%s?range=10y&interval=1d"
               "&includeAdjustedClose=true&events=div" % (host, sym))
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


def div_yield(text):
    """Dividendi o cedole pagati negli ultimi 12 mesi, in percentuale dell'ultimo prezzo.
    0 se non ha distribuito nulla (per esempio un ETF ad accumulo, che reinveste)."""
    try:
        res = json.loads(text)["chart"]["result"][0]
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    ts = res.get("timestamp") or []
    raw = ((res.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    last = next((c for c in reversed(raw) if c), None)
    if not ts or not last:
        return None
    divs = ((res.get("events") or {}).get("dividends") or {}).values()
    tot = sum(d.get("amount", 0) for d in divs if ts[-1] - 365 * 86400 < d.get("date", 0) <= ts[-1])
    return round(tot / last, 4)


def seduta_in_corso(meta, d, adesso=None):
    """La seduta del giorno d (data della borsa) è ancora aperta? Durante la seduta Yahoo dà come
    chiusura della barra di oggi il prezzo del momento. Dopo la chiusura a volte descrive già la seduta
    di domani: allora quella di oggi è finita."""
    adesso = time.time() if adesso is None else adesso
    off = meta.get("gmtoffset", 0)
    giorno = lambda x: datetime.datetime.fromtimestamp(x + off, datetime.timezone.utc).strftime("%Y-%m-%d")
    reg = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    start, end = reg.get("start"), reg.get("end")
    return d == giorno(adesso) and (not start or not end or (giorno(start) == d and adesso < end))


def chiusura_mancante(meta, ultima, adesso=None):
    """Yahoo a volte lascia vuota la barra dell'ultima seduta (prezzo None) ma ne dà la chiusura nei
    metadati. -> (data, prezzo, massimo, minimo) se quella seduta è finita ed è più recente di `ultima`,
    altrimenti None. Il prezzo non è corretto per i dividendi: per l'ultimo giorno coincide."""
    t, p = meta.get("regularMarketTime"), meta.get("regularMarketPrice")
    if not t or not p or p <= 0:
        return None
    off = meta.get("gmtoffset", 0)
    giorno = lambda x: datetime.datetime.fromtimestamp(x + off, datetime.timezone.utc).strftime("%Y-%m-%d")
    d = giorno(t)
    if ultima and d <= ultima:
        return None
    if seduta_in_corso(meta, d, adesso):                         # è un prezzo in corso, non la chiusura
        return None
    h, lo = meta.get("regularMarketDayHigh") or p, meta.get("regularMarketDayLow") or p
    return d, float(p), float(max(h, p)), float(min(lo, p))


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
    extra = chiusura_mancante(meta, max(closes) if closes else None)
    if extra:
        d, c, h, lo = extra
        closes[d], ohlc[d] = c, (c, h, lo, c)
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

def rolling_max(prices, w):
    """Massimo mobile su w giorni (deque monotona, O(n))."""
    out, dq = [None] * len(prices), deque()
    for i, x in enumerate(prices):
        if x is None:
            continue
        while dq and prices[dq[-1]] <= x:
            dq.pop()
        dq.append(i)
        while dq[0] <= i - w:
            dq.popleft()
        out[i] = prices[dq[0]]
    return out


class Stock:
    """Prezzi allineati + somme prefisse per media mobile e volatilità in O(1)."""

    def __init__(self, sym, prices, name="", ohlc=None, min_vol=MIN_VOL):
        self.sym, self.p, self.name, self.min_vol = sym, prices, name, min_vol
        n = len(prices)
        if ohlc is None:
            ohlc = [None if x is None else (x, x, x, x) for x in prices]
        self.o = [b[0] if b else None for b in ohlc]
        self.h = [b[1] if b else None for b in ohlc]
        self.l = [b[2] if b else None for b in ohlc]
        self.first = next((i for i, x in enumerate(prices) if x is not None), n)
        self.hi = rolling_max(prices, LOOKBACK)
        self._atr = {}
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
        if i in self._atr:
            return self._atr[i]
        v = None
        if i - self.first >= ATR_WIN:
            tot = 0.0
            for k in range(i - ATR_WIN + 1, i + 1):
                pc = self.p[k - 1]
                tot += max(self.h[k] - self.l[k], abs(self.h[k] - pc), abs(self.l[k] - pc))
            v = tot / ATR_WIN
        self._atr[i] = v
        return v

    def fwd(self, i, h):
        if i + h >= len(self.p):
            return None
        return self.p[i + h] / self.p[i] - 1

    def signal(self, i):
        """Gli indicatori del giorno i, usando SOLO prezzi fino al giorno i."""
        if not self.ok(i):
            return None
        v = self.vol(i)
        if v <= 0:
            return None
        m = self.mom(i)
        sma = self.sma(i)
        return {"score": m / v, "mom": m, "vol": v, "above": self.p[i] > sma,
                "vs_sma": self.p[i] / sma - 1, "frozen": v < self.min_vol}


def raw_features(s, i):
    """Gli indizi grezzi del giorno i (solo prezzi fino a i), o None se il titolo non è candidato.
    Ordine come FEATURES, senza il mercato: più alto = più 'alto' nella descrizione."""
    sg = s.signal(i)
    if sg is None or not sg["above"] or sg["frozen"]:
        return None, sg
    return [sg["score"], s.p[i] / s.p[i - 21] - 1, s.p[i] / s.hi[i] - 1, -sg["vol"], sg["vs_sma"]], sg


def rank_scale(rows):
    """Per ogni colonna, la posizione in classifica tra i candidati del giorno: da -0,5 (ultimo)
    a +0,5 (primo). Così gli indizi sono confrontabili tra titoli, anni e mercati."""
    n = len(rows)
    if not n:
        return []
    out = [[0.0] * len(rows[0]) for _ in rows]
    if n == 1:
        return out
    for j in range(len(rows[0])):
        for pos, r in enumerate(sorted(range(n), key=lambda r: rows[r][j])):
            out[r][j] = pos / (n - 1) - 0.5
    return out


def candidates_day(stocks, market, i):
    """I candidati del giorno i con il vettore del modello: [1, 5 indizi in classifica, mercato]."""
    info = []
    for s in stocks:
        raw, sg = raw_features(s, i)
        if raw is not None:
            info.append((s, sg, raw))
    xs = rank_scale([raw for _, _, raw in info])
    ms = market.signal(i)
    m = 0.0 if ms is None else (0.5 if ms["above"] else -0.5)
    return [{"s": s, "sig": sg, "raw": raw, "x": [1.0] + x + [m]} for (s, sg, raw), x in zip(info, xs)]


# ------------------------------------------------------------------ la stima di probabilità

def group_of(c):
    """Il quinto di forza del candidato nel suo giorno: 0 = i meno forti, 4 = i più forti."""
    return min(GROUPS - 1, int((c["x"][1] + 0.5) * GROUPS))


def pav_increasing(vals, weights):
    """Regressione isotonica crescente (pool adjacent violators): la sequenza non decrescente
    più vicina ai valori, pesata."""
    blocks = [[v, w, 1] for v, w in zip(vals, weights)]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] > blocks[i + 1][0] + 1e-12:
            (v1, w1, c1), (v2, w2, c2) = blocks[i], blocks[i + 1]
            blocks[i] = [(v1 * w1 + v2 * w2) / (w1 + w2), w1 + w2, c1 + c2]
            del blocks[i + 1]
            i = max(0, i - 1)
        else:
            i += 1
    out = []
    for v, _, c in blocks:
        out += [v] * c
    return out


def estimate(wins, n):
    """Probabilità di riuscita per quinto di forza: la frequenza osservata, ristretta verso la
    media (K_SHRINK casi fittizi alla media) e resa non decrescente con la forza, perché in
    letteratura i titoli più forti non fanno peggio dei più deboli: un effetto contrario nei
    dati è trattato come rumore e appiattito."""
    W, N = sum(wins), sum(n)
    if N == 0:
        return [None] * GROUPS
    base = W / N
    raw = [(w + K_SHRINK * base) / (m + K_SHRINK) for w, m in zip(wins, n)]
    return pav_increasing(raw, [m + K_SHRINK for m in n])


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

def group_stats(rets):
    return slim(stats(rets))


def outcome_stats(items):
    """items: esiti di trade() eseguiti -> statistiche con come sono finiti."""
    rets = [t["ret"] for t in items]
    if not rets:
        return {"n": 0}
    st = stats(rets)
    st.update({k: sum(1 for t in items if t["outcome"] == o) / len(items)
               for k, o in (("p_target", "target"), ("p_stop", "stop"), ("p_tempo", "tempo"))})
    return slim(st)


def consigliata(models, max_loss=MAX_LOSS_P10):
    """La regola consigliata per una categoria: la probabilità di guadagno più alta (poi il guadagno
    medio) tra le regole in cui, nel 10 % dei casi peggiori, non si è perso più di max_loss."""
    ok = [(k, m) for k, m in models.items() if (m["tutti"].get("p10") or -1) >= -max_loss]
    key = max(ok or list(models.items()), key=lambda km: (km[1]["tutti"].get("p_gain", 0), km[1]["tutti"].get("mean", 0)))[0]
    return {"key": key, "max_perdita_p10": max_loss,
            "criterio": "la probabilità di guadagno più alta tra le regole in cui, nel 10 %% dei casi peggiori, "
                        "non si è perso più del %d %%" % round(max_loss * 100)}


def run(stocks, market, calendar, cost_rt, top=TOP, mercato="usa"):
    last = len(calendar) - 1
    start = min(s.first for s in stocks) + LOOKBACK
    sched = list(range(last, start - 1, -STEP))[::-1]       # una decisione a settimana, allineata a oggi
    days = {i: candidates_day(stocks, market, i) for i in sched}
    today = days[last]
    rank = lambda p, c: (-p, -c["x"][1])                   # per probabilità, poi per forza
    models = {}

    for sid, hold in variants():
        sty, key = style(sid), vkey(sid, hold)
        # 1. l'esito della regola per ogni candidato di ogni settimana con esito già noto
        cohorts = []
        for i in sched:
            if i + hold > last:
                break
            res = [(c, trade(c["s"], i, sty["ks"], sty["rr"], hold, cost_rt)) for c in days[i]]
            cohorts.append((i, [(c, t) for c, t in res if t is not None]))
        if not cohorts:
            continue
        # 2. conteggi cumulati per quinto di forza, settimana dopo settimana
        wins, cnt, cum = [0] * GROUPS, [0] * GROUPS, []
        for i, res in cohorts:
            for c, t in res:
                if t["filled"]:
                    g = group_of(c)
                    cnt[g] += 1
                    wins[g] += t["ret"] > 0
            cum.append((wins[:], cnt[:]))
        ci = [i for i, _ in cohorts]

        # 3. verifica walk-forward: ogni anno la stima usa solo esiti noti prima del suo inizio
        rows, preds = [], []
        for Y in sorted({calendar[i][:4] for i in ci}):
            test = [(i, res) for i, res in cohorts if calendar[i][:4] == Y]
            j = bisect.bisect_left(ci, test[0][0] - hold) - 1     # ultima settimana con i + hold < inizio
            if j + 1 < MIN_TRAIN_WEEKS:
                continue
            est = estimate(*cum[j])
            for i, res in test:
                scored = sorted(((est[group_of(c)], c, t) for c, t in res), key=lambda z: rank(z[0], z[1]))
                pick = lambda part: [t["ret"] for p, c, t in part if t["filled"]]
                rows.append({"i": i, "anno": Y, "top": pick(scored[:top]), "bottom": pick(scored[-top:]),
                             "tutti": pick(scored)})
                preds += [(p, group_of(c), 1.0 if t["ret"] > 0 else 0.0, t["ret"]) for p, c, t in scored if t["filled"]]
        oos = None
        if rows:
            flat = lambda g: [x for r in rows for x in r[g]]
            years = []
            for Y in sorted({r["anno"] for r in rows}):
                ry = [r for r in rows if r["anno"] == Y]
                years.append({"anno": Y, "settimane": len(ry),
                              **{g: group_stats([x for r in ry for x in r[g]]) for g in ("top", "tutti", "bottom")}})
            step = max(1, math.ceil(hold / STEP))                 # settimane che non si sovrappongono
            diffs = [sum(r["top"]) / len(r["top"]) - sum(r["tutti"]) / len(r["tutti"])
                     for r in rows[::step] if r["top"] and r["tutti"]]
            t_stat = None
            if len(diffs) > 2:
                mu = sum(diffs) / len(diffs)
                sd = math.sqrt(sum((d - mu) ** 2 for d in diffs) / (len(diffs) - 1))
                t_stat = mu / sd * math.sqrt(len(diffs)) if sd > 0 else None
            cal = []
            for g in range(GROUPS):
                pg = [z for z in preds if z[1] == g]
                if pg:
                    cal.append({"gruppo": g, "stimata": r4(sum(z[0] for z in pg) / len(pg)),
                                "osservata": r4(sum(z[2] for z in pg) / len(pg)), "n": len(pg)})
            oos = {"da": calendar[rows[0]["i"]], "a": calendar[rows[-1]["i"]], "settimane": len(rows),
                   "calibrazione": cal, "top": group_stats(flat("top")), "tutti": group_stats(flat("tutti")),
                   "bottom": group_stats(flat("bottom")), "anni": years, "t": r4(t_stat), "casi_t": len(diffs)}

        # 4. la stima di oggi (tutta la storia con esito noto) e com'è andata ogni quinto
        est = estimate(*cum[-1])
        by_g = [[] for _ in range(GROUPS)]
        for i, res in cohorts:
            for c, t in res:
                if t["filled"]:
                    by_g[group_of(c)].append(t)
        all_t = [t for g in by_g for t in g]
        models[key] = {"p": [r4(x) for x in est], "base": r4(sum(cum[-1][0]) / max(1, sum(cum[-1][1]))),
                       "gruppi": [outcome_stats(g) for g in by_g], "tutti": outcome_stats(all_t), "oos": oos}

    # 5. i candidati di oggi, dal più probabile (la stima cresce con la forza, quindi l'ordine
    #    è lo stesso per ogni regola: cambia solo la probabilità)
    dkey = vkey(DEFAULT_STYLE, DEFAULT_HOLD)
    cands = []
    for c in sorted(today, key=lambda c: rank(models[dkey]["p"][group_of(c)], c)):
        s, sg, raw = c["s"], c["sig"], c["raw"]
        cands.append({
            "symbol": s.sym, "name": s.name, "price": round(s.p[last], 4), "atr": r4(s.atr(last)),
            "g": group_of(c), "forza": r4(c["x"][1] + 0.5), "punteggio": r4(sg["score"]),   # crescita / oscillazione
            "info": {"anno": r4(s.p[last] / s.p[last - LOOKBACK] - 1), "mese": r4(raw[1]),
                     "dal_massimo": r4(raw[2]), "vol": r4(sg["vol"]), "sopra_media": r4(sg["vs_sma"])}})

    # 6. per i primi: grafico e candele per la simulazione dell'app
    smap = {s.sym: s for s in stocks}
    details = {}
    for c in cands[:top]:
        s = smap[c["symbol"]]
        lo = max(s.first + 1, last - MC_BARS + 1)
        c0 = max(s.first, last - 129)
        details[s.sym] = {
            "bars": [[round(s.o[i] / s.p[i - 1], 5), round(s.h[i] / s.p[i - 1], 5),
                      round(s.l[i] / s.p[i - 1], 5), round(s.p[i] / s.p[i - 1], 5)] for i in range(lo, last + 1)],
            "chart": {"dates": calendar[c0:last + 1], "close": [round(x, 4) for x in s.p[c0:last + 1]],
                      "sma": [round(s.sma(i), 4) if i - s.first >= SMA_WIN else None for i in range(c0, last + 1)]},
        }

    # verifica del filtro "in salita": la regola consigliata su chi era sopra e su chi era sotto la media
    cons = consigliata(models)
    sid, hold = cons["key"].split("|")
    sty, hold = style(sid), int(hold)
    sopra, sotto = [], []
    for i in sched:
        if i + hold > last:
            break
        for s in stocks:
            sg = s.signal(i)
            if sg is None or sg["frozen"]:
                continue
            t = trade(s, i, sty["ks"], sty["rr"], hold, cost_rt)
            if t and t["filled"]:
                (sopra if sg["above"] else sotto).append(t["ret"])
    trend = {"key": cons["key"], "sopra": group_stats(sopra), "sotto": group_stats(sotto)}

    m_i = market.signal(last)
    regime = {"sopra_media200": m_i["above"], "vs_media200": r4(m_i["vs_sma"])} if m_i else None
    return {
        "asof": calendar[last], "future_days": trading_days_after(calendar[last], max(HOLDS) + 1, mercato),
        "universo": len(stocks), "regime": regime, "top": top, "costo": cost_rt,
        "rules": {"limit_atr": LIMIT_ATR, "atr_win": ATR_WIN, "styles": STYLES, "holds": list(HOLDS),
                  "hold_names": {str(h): n for h, n in HOLD_NAMES.items()},
                  "default": {"style": DEFAULT_STYLE, "hold": DEFAULT_HOLD}},
        "groups": GROUPS, "models": models, "candidates": cands, "details": details,
        "consigliata": cons, "trend": trend,
        "min_vol": stocks[0].min_vol if stocks else MIN_VOL,
    }


def analizza(tickers=None, asof=None, cost_pct=None, top=TOP, workers=4, log=print, mercato="usa"):
    """Scarica, allinea e analizza un mercato. -> il dizionario dei risultati (vedi run)."""
    cfg = MERCATI[mercato]
    index = cfg["indice"]
    if cost_pct is None:
        cost_pct = cfg["costo"]
    if tickers:
        syms = [x.strip().upper() for x in tickers]
        syms = [x if x.endswith(".MI") else x.replace(".", "-") for x in syms]
    else:
        syms = cfg["universo"]
    syms = [s for s in dict.fromkeys(syms) if s and s != index]
    log("[settimana] %s: scarico %d titoli + %s (10 anni, giornaliero; cache 12 ore)..."
        % (cfg["nome"], len(syms), index))

    def get(sym):
        try:
            return sym, fetch(sym), None
        except FetchError as e:
            return sym, None, str(e)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        got = list(ex.map(get, syms + [index]))
    errors = [e for _, t, e in got if e]
    texts = {s: t for s, t, _ in got if t}
    if index not in texts:
        raise FetchError("non riesco a scaricare %s: %s" % (index, "; ".join(errors)))

    parsed = {s: parse(t, asof, cfg["fuso"], cfg["chiusura"]) for s, t in texts.items()}
    calendar = sorted(parsed[index][1])
    closes = align({s: v[1] for s, v in parsed.items()}, calendar)
    ohlc = align_ohlc({s: v[2] for s, v in parsed.items()}, calendar)
    def nome(meta):
        if meta.get("instrumentType") in ("ETF", "MUTUALFUND"):
            return meta.get("longName") or meta.get("shortName") or ""
        return meta.get("shortName") or meta.get("longName") or ""

    stocks = [Stock(s, closes[s], nome(parsed[s][0]), ohlc[s], cfg.get("min_vol", MIN_VOL))
              for s in syms if s in closes]
    short = [s.sym for s in stocks if s.first >= len(calendar) - LOOKBACK]
    errors += ["%s: meno di 1 anno di dati" % x for x in short]
    stocks = [s for s in stocks if s.first < len(calendar) - LOOKBACK]
    for e in errors:
        log("[settimana] saltato: " + e)
    if len(stocks) < 2:
        raise FetchError("servono almeno 2 titoli con 1 anno di storia")
    top = min(top, len(stocks))

    log("[settimana] %s: stima e verifica walk-forward su %d varianti della regola..." % (cfg["nome"], len(variants())))
    r = run(stocks, Stock(index, closes[index], cfg["indice_nome"], ohlc[index]), calendar, cost_pct / 100,
            top, mercato)
    r["saltati"] = errors
    r["mercato"] = {k: cfg[k] for k in ("nome", "indice_nome", "indice_breve", "universo_nome", "valuta",
                                         "valuta_nome", "citta", "borsa", "costo")}
    r["mercato"]["id"] = mercato
    live = {}
    for sym in r["details"]:
        m = parsed[sym][0]
        if m.get("regularMarketPrice") and m.get("regularMarketTime") and not asof:
            live[sym] = {"price": m["regularMarketPrice"], "time": datetime.datetime.fromtimestamp(
                m["regularMarketTime"] + m.get("gmtoffset", -18000), datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")}
    r["live"] = live
    rend = {s: div_yield(t) for s, t in texts.items()}
    for c in r["candidates"]:
        c["rendimento"] = rend.get(c["symbol"])
        c["tipo"] = parsed[c["symbol"]][0].get("instrumentType") or ""
    r["generato"] = now_in(cfg["fuso"]).strftime("%Y-%m-%d %H:%M")
    return r


# ------------------------------------------------------------------ stampa

def f_pct(x, d=1, sign=True):
    if x is None:
        return "n/d"
    s = ("%+." if sign else "%.") + str(d) + "f %%"
    return (s % (x * 100)).replace(".", ",")


def plan_for(c, r, style_id=DEFAULT_STYLE, hold=DEFAULT_HOLD):
    """Livelli e date della regola per un candidato, dal prezzo di riferimento (ultima chiusura)."""
    sty = style(style_id)
    ref, a = c["price"], c["atr"]
    ks, rr = sty["ks"], sty["rr"]
    return {"entrata_giorno": r["future_days"][0], "limite": ref + r["rules"]["limit_atr"] * a,
            "stop": ref - ks * a if ks else None, "target": ref + rr * ks * a if (ks and rr) else None,
            "uscita_giorno": r["future_days"][hold - 1]}


def print_report(r, style_id=DEFAULT_STYLE, hold=DEFAULT_HOLD):
    mk = r["mercato"]
    key = vkey(style_id, hold)
    m = r["models"][key]
    sty = style(style_id)
    print("\nTITOLI CONSIGLIATI - %s, in ordine di probabilità di riuscita" % mk["nome"].upper())
    print("Dati fino al %s · %d titoli · %d candidati oggi (sopra la media a 200 giorni) · prezzi in %s" % (
        r["asof"], r["universo"], len(r["candidates"]), mk["valuta"]))
    if r["regime"]:
        g = r["regime"]
        print("Indice %s: %s la media a 200 giorni (%s)" % (
            mk["indice_nome"], "sopra" if g["sopra_media200"] else "SOTTO", f_pct(g["vs_media200"])))
    print("Stile %s, durata %s. Riuscita = l'operazione chiude in guadagno, costi inclusi." % (sty["nome"], HOLD_NAMES[hold]))
    print("Probabilità per quinto di forza, dal più debole al più forte: %s\n" % " · ".join(f_pct(p, 0, False) for p in m["p"]))
    num = lambda x: "%9s" % "-" if x is None else "%9.2f" % x
    print("  #  %-6s %7s %9s %9s %9s %9s  %-10s %9s" % (
        "titolo", "prob.", "chiusura", "compra<=", "protez.", "obiett.", "vendi il", "tipico"))
    for n, c in enumerate(r["candidates"][:r["top"]], 1):
        pl = plan_for(c, r, style_id, hold)
        g = m["gruppi"][c["g"]]
        print(" %2d  %-6s %7s %9.2f %9.2f %s %s  %-10s %9s" % (
            n, c["symbol"].replace(".MI", ""), f_pct(m["p"][c["g"]], 0, False), c["price"], pl["limite"],
            num(pl["stop"]), num(pl["target"]), pl["uscita_giorno"], f_pct(g.get("median"))))
    print("\n  La regola conta più del titolo. Probabilità di riuscita di tutti i candidati, per regola:")
    for h in HOLDS:
        print("   %-12s %s" % (HOLD_NAMES[h], "  ".join("%s %s" % (s["nome"], f_pct(r["models"][vkey(s["id"], h)]["base"], 0, False))
                                                     for s in STYLES)))
    o = m.get("oos")
    if o:
        print("\nVERIFICA WALK-FORWARD (%s - %s, %d settimane mai viste dalla stima):" % (o["da"], o["a"], o["settimane"]))
        for b in o["calibrazione"]:
            print("  quinto %d: stimava %s -> è andata bene il %s (%d operazioni)" % (
                b["gruppo"] + 1, f_pct(b["stimata"], 0, False), f_pct(b["osservata"], 0, False), b["n"]))
        for g, lab in (("top", "i primi 10"), ("tutti", "tutti i candidati"), ("bottom", "gli ultimi 10")):
            print("  %-18s %s in guadagno, media %s" % (lab, f_pct(o[g]["p_gain"], 0, False), f_pct(o[g]["mean"], 2)))
        if o["t"] is not None:
            print("  vantaggio dei primi 10 sui candidati: t = %.2f (%s)" % (
                o["t"], "significativo" if o["t"] > 2 else "non distinguibile dal caso"))
    print("\nStime dal passato, non previsioni. Bias di sopravvivenza. Non è consulenza finanziaria.")


# ------------------------------------------------------------------ main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mercato", choices=sorted(MERCATI), default="usa", help="usa (S&P 100) o italia (FTSE MIB)")
    ap.add_argument("--tickers", help="lista separata da virgole al posto dell'universo del mercato")
    ap.add_argument("--asof", help="usa solo i dati fino a questa data (YYYY-MM-DD)")
    ap.add_argument("--top", type=int, default=TOP, help="quanti titoli (default 10)")
    ap.add_argument("--stile", choices=[s["id"] for s in STYLES], default=DEFAULT_STYLE)
    ap.add_argument("--durata", type=int, choices=HOLDS, default=DEFAULT_HOLD, help="sedute: 10, 21 o 63")
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
    print_report(r, a.stile, a.durata)
    os.makedirs(TRADER, exist_ok=True)
    name = "settimana.json" if a.mercato == "usa" else "settimana-%s.json" % a.mercato
    with open(os.path.join(TRADER, name), "w", encoding="utf-8") as fh:
        json.dump(r, fh)
    print("\n[settimana] scritto trader/%s  (per l'app: python3 app.py)" % name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
