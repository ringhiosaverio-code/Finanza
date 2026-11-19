#!/usr/bin/env python3
"""I segnali che la ricerca, i libri e i trader indicano per l'intraday di crypto e azioni, per le reti neurali.

    python3 segnali.py              # aggiorna le fonti (giornaliere, Fear & Greed, notizie) e stampa lo stato

Le reti (rete.py per le crypto, rete_azioni.py per le azioni italiane) non vedono più solo rendimenti e volatilità: vedono
anche i segnali documentati negli studi e nei libri, alle scale che contano (anno, mese, settimana, giorno, ora):

- momento e inversione su più scale (Moskowitz, Ooi e Pedersen 2012; Jegadeesh 1990; Liu e Tsyvinski 2021 sulle crypto);
- distanza dal massimo di 52 settimane (George e Hwang 2004) e dalla media di 200 giorni (Detzel e altri 2021);
- RSI a 2 giorni (Connors e Raschke, "Street Smarts") e giornata stretta NR7 (Crabel, "Day Trading with Short Term
  Price Patterns and Opening Range Breakout");
- salto della notte rispetto all'escursione media (Chan, "Algorithmic Trading": buy-on-gap; Lou, Polk e Skouras 2019);
- il sentimento del mercato crypto (indice Fear & Greed di alternative.me) e il tono e la quantità delle notizie (GDELT)
  per l'idea di Tetlock (2007): le notizie spostano i prezzi, poi in parte si torna indietro.

Qui ci sono le fonti (con cache, così l'aggiornamento di ogni ora non scarica niente) e le tabelle giornaliere allineate
agli istanti di decisione: per una decisione nel giorno D si usa solo il giorno prima, già chiuso. I segnali di dentro la
giornata (opening range, VWAP, volume relativo, prima mezz'ora, stagionalità oraria) si calcolano in rete.py e
rete_azioni.py dalle barre. Con FINANZA_SENZA_RETE=1 non si scarica niente (si usa solo quello che c'è in cache).
"""

import datetime
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "trader", "cache", "segnali")
UA = "Mozilla/5.0 (finanza-segnali)"
GIORNO = 86400

# i segnali giornalieri, uguali per crypto e azioni (le finestre in giorni di scambio)
NOMI_GIORNALIERI = ("anno", "mese", "settimana", "giorno", "media200", "max52", "rsi2", "nr7", "range_atr", "vol_mese")
NOMI_SENTIMENTO = ("paura_avidita", "paura_avidita_7g")
NOMI_NOTIZIE = ("notizie_volume", "notizie_tono")


def senza_rete():
    return os.environ.get("FINANZA_SENZA_RETE") == "1"


def _leggi(path, max_age):
    if os.path.exists(path) and (senza_rete() or time.time() - os.path.getmtime(path) < max_age):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def _scrivi(path, dati):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(dati, fh)
    os.replace(path + ".tmp", path)


def _get(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


# ---------------------------------------------------------------- i mercati che muovono gli altri

# perché la borsa (e le crypto) salgono o scendono: Wall Street guida anche Milano e le crypto (futures), la paura (VIX),
# i tassi USA, il petrolio, l'oro e il cambio (Fama e French; Rapach, Strauss e Zhou sul ruolo guida degli USA; Whaley sul VIX)
MOTORI = [("es", "ES=F", "futures S&P 500"), ("nq", "NQ=F", "futures Nasdaq"), ("vix", "^VIX", "VIX, la paura"),
          ("tassi", "^TNX", "tasso USA a 10 anni"), ("petrolio", "CL=F", "petrolio"), ("oro", "GC=F", "oro"),
          ("eurusd", "EURUSD=X", "euro/dollaro")]
NOMI_MOTORI = ["%s_%s" % (n, p) for n, _, _ in MOTORI for p in ("1h", "giorno")]
FONTI_MOTORI = {"%s_%s" % (n, p): "%s, %s (perché il mercato si muove)" % (nome, "ultima ora" if p == "1h" else "ultimo giorno")
                for n, _, nome in MOTORI for p in ("1h", "giorno")}


def serie_mercato(sym, intervallo="1h", max_age=1800):
    """Le barre di un mercato guida da Yahoo (1h: ultimi 2 anni; 5m: ultimi 60 giorni), tenute in un archivio che cresce:
    (tempi di chiusura in secondi UTC, log della chiusura), o None."""
    import numpy as np
    chiave = (sym, intervallo, CACHE)
    if chiave in _MEMO and time.time() - _MEMO[chiave][0] < min(max_age, 600):
        return _MEMO[chiave][1]
    _MEMO[chiave] = (time.time(), _serie_mercato(sym, intervallo, max_age))
    return _MEMO[chiave][1]


_MEMO = {}


def _serie_mercato(sym, intervallo, max_age):
    import numpy as np
    cartella = os.path.join(CACHE, "mercati")
    os.makedirs(cartella, exist_ok=True)
    path = os.path.join(cartella, "%s-%s.npz" % (sym.replace("^", "_").replace("=", "_"), intervallo))
    unite = {}
    if os.path.exists(path):
        try:
            with np.load(path) as z:
                unite = dict(zip(z["t"].tolist(), z["c"].tolist()))
        except (OSError, ValueError, KeyError):
            unite = {}
    vecchio = not os.path.exists(path) or time.time() - os.path.getmtime(path) > max_age
    if vecchio and not senza_rete():
        try:
            periodo = "60d" if intervallo == "5m" else "730d"
            res = json.loads(_get("https://query2.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=%s" % (
                urllib.parse.quote(sym), periodo, intervallo)))["chart"]["result"][0]
            passo = 300 if intervallo == "5m" else 3600
            for t, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]):
                if c and c > 0:
                    unite[float(t + passo)] = float(c)
            if unite:
                tt = sorted(unite)
                np.savez_compressed(path + ".tmp.npz", t=np.array(tt), c=np.array([unite[x] for x in tt]))
                os.replace(path + ".tmp.npz", path)
        except Exception:                                                      # Yahoo non risponde: si usa l'archivio
            pass
    if len(unite) < 100:
        return None
    tt = np.array(sorted(unite))
    return tt, np.log(np.array([unite[x] for x in tt]))


def movimenti(T, serie, barra=300):
    """Per ogni istante T (secondi UTC): il movimento della serie nell'ultima ora e nelle ultime 24 ore, diviso per quanto
    si muove di solito (volatilità delle ultime ~50 ore di barre); solo barre già chiuse prima di T, zero se mancano o
    sono vecchie di più di un giorno. Ritorna (len(T), 2)."""
    import numpy as np
    T = np.asarray(T, dtype=np.float64)
    out = np.zeros((len(T), 2), np.float32)
    if serie is None:
        return out
    tc, lc = serie
    finestra = max(int(round(50 * 3600 / barra)), 10)
    r = np.diff(lc, prepend=lc[0])
    r = np.where(np.diff(tc, prepend=tc[0]) > 3600 * 4, 0.0, r)                # i salti di notte e del fine settimana non contano
    r2 = np.concatenate([[0.0], np.cumsum(r ** 2)])
    i = np.searchsorted(tc, T, side="right") - 1                                # l'ultima barra chiusa prima di T
    ok = (i >= finestra) & (T - tc[np.maximum(i, 0)] < 86400)
    ii = np.clip(i, finestra, len(tc) - 1)
    sig = np.sqrt(np.maximum((r2[ii + 1] - r2[ii + 1 - finestra]) / finestra, 1e-12))
    for j, secondi in enumerate((3600.0, 86400.0)):
        jj = np.clip(np.searchsorted(tc, tc[ii] - secondi, side="right") - 1, 0, None)
        z = (lc[ii] - lc[jj]) / (sig * math.sqrt(secondi / barra))
        out[:, j] = np.where(ok, np.clip(z, -8, 8), 0.0)
    return out


def tabella_motori(T, intervallo="1h", serie=None):
    """Tutti i mercati guida per gli istanti T: (len(T), len(NOMI_MOTORI)). serie: {nome: (tc, lc) o None} già caricate."""
    import numpy as np
    barra = 300 if intervallo == "5m" else 3600
    serie = serie if serie is not None else {n: serie_mercato(sym, intervallo) for n, sym, _ in MOTORI}
    return np.concatenate([movimenti(T, serie.get(n), barra) for n, _, _ in MOTORI], axis=1)


# ---------------------------------------------------------------- Fear & Greed (alternative.me), dal 2018

def fear_greed(max_age=6 * 3600, log=print):
    """L'indice Fear & Greed delle crypto, un valore al giorno da 0 (paura estrema) a 100 (avidità estrema): unisce
    volatilità, momento e volumi, social, sondaggi, dominanza di Bitcoin e ricerche Google. Ritorna {giorno ISO: valore},
    o {} se non si può avere. Il valore del giorno D esce a mezzanotte UTC di D."""
    path = os.path.join(CACHE, "fear_greed.json")
    d = _leggi(path, max_age)
    if d is None and not senza_rete():
        try:
            dati = json.loads(_get("https://api.alternative.me/fng/?limit=0&format=json"))["data"]
            d = {datetime.datetime.fromtimestamp(int(x["timestamp"]), datetime.timezone.utc).date().isoformat(): int(x["value"])
                 for x in dati}
            _scrivi(path, d)
        except (OSError, ValueError, KeyError) as e:
            log("[segnali] Fear & Greed non disponibile: %s" % str(e)[:80])
            d = _leggi(path, float("inf")) if os.path.exists(path) else None
    return d or {}


# ---------------------------------------------------------------- notizie (GDELT): quante e con che tono

GDELT = "https://api.gdeltproject.org/api/v2/doc/doc?"
_ultima_gdelt = [0.0]


def _gdelt(query, mode, timespan="3months", log=print, attese=(6, 20)):
    """Una serie di GDELT (una richiesta ogni 5 secondi al più, come chiede il servizio; se risponde che è troppo
    presto, si aspetta di più). Ritorna la lista di punti {date, value} o None."""
    for attesa in attese:
        pausa = _ultima_gdelt[0] + attesa - time.time()
        if pausa > 0:
            time.sleep(pausa)
        _ultima_gdelt[0] = time.time()
        url = GDELT + urllib.parse.urlencode({"query": query, "mode": mode, "format": "json", "timespan": timespan})
        try:
            testo = _get(url, timeout=60)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                continue
            log("[segnali] GDELT %s: HTTP %d" % (query, e.code))
            return None
        except OSError as e:
            log("[segnali] GDELT %s: %s" % (query, str(e)[:80]))
            return None
        if not testo.lstrip().startswith("{"):
            continue                                                   # "please limit requests": si riprova più tardi
        try:
            tl = json.loads(testo).get("timeline") or []
            return tl[0]["data"] if tl else []
        except (ValueError, KeyError, IndexError):
            return None
    log("[segnali] GDELT %s: troppe richieste, per oggi niente" % query)
    return None


def _giorno_gdelt(s):
    return datetime.datetime.strptime(s[:8], "%Y%m%d").date().isoformat()


def notizie(nome, query, max_age=20 * 3600, log=print):
    """Le notizie degli ultimi 3 mesi su un argomento, per giorno: {giorno ISO: [articoli, tono medio]}. Gli articoli
    sono il conteggio grezzo di GDELT (tutte le lingue o quella della query), il tono va da circa -10 (molto negativo)
    a +10. Le serie già scaricate si tengono: si aggiungono i giorni nuovi, così la storia cresce."""
    path = os.path.join(CACHE, "notizie", "%s.json" % nome)
    fallito = path + ".fallito"
    vecchio = _leggi(path, float("inf")) or {}
    if os.path.exists(path) and (senza_rete() or time.time() - os.path.getmtime(path) < max_age):
        return vecchio
    if senza_rete() or (os.path.exists(fallito) and time.time() - os.path.getmtime(fallito) < 6 * 3600):
        return vecchio                                                 # GDELT ha detto di no da poco: si riprova più tardi
    vol = _gdelt(query, "timelinevolraw", log=log)
    tono = _gdelt(query, "timelinetone", log=log) if vol is not None else None
    if vol is None or tono is None:
        os.makedirs(os.path.dirname(fallito), exist_ok=True)
        with open(fallito, "w") as fh:
            fh.write(str(time.time()))
        return vecchio
    per = {}
    for p in vol:
        g = _giorno_gdelt(p["date"])
        per.setdefault(g, [0.0, 0.0, 0.0])[0] += float(p.get("value", 0))
    for p in tono:
        g = _giorno_gdelt(p["date"])
        per.setdefault(g, [0.0, 0.0, 0.0])
        per[g][1] += float(p.get("value", 0))
        per[g][2] += 1
    nuovo = {g: [v[0], v[1] / v[2] if v[2] else 0.0] for g, v in per.items()}
    oggi = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    nuovo.pop(oggi, None)                                              # il giorno in corso è a metà
    unito = dict(vecchio)
    unito.update(nuovo)
    _scrivi(path, unito)
    return unito


# ---------------------------------------------------------------- dati giornalieri e segnali di anno, mese, settimana, giorno

def giornaliere(sym, tz, chiusura, max_age_ore=12):
    """Le barre giornaliere (10 anni, Yahoo, corrette per i dividendi): ([giorni ISO], o, h, l, c) in ordine. Vuote se
    non ci sono."""
    import settimana
    try:
        if senza_rete():
            path = os.path.join(settimana.CACHE, sym + ".v2.json")
            if not os.path.exists(path):
                return [], np.zeros(0), np.zeros(0), np.zeros(0), np.zeros(0)
            with open(path, encoding="utf-8") as fh:
                testo = fh.read()
        else:
            testo = settimana.fetch(sym, max_age_ore)
        _, _, ohlc = settimana.parse(testo, None, tz, chiusura)
    except Exception:                                                  # rete o ticker: niente dati giornalieri
        return [], np.zeros(0), np.zeros(0), np.zeros(0), np.zeros(0)
    giorni = sorted(ohlc)
    a = np.array([ohlc[g] for g in giorni], dtype=np.float64).reshape(-1, 4)
    return giorni, a[:, 0], a[:, 1], a[:, 2], a[:, 3]


def tabella_giornaliera(o, h, l, c, anno=252, mese=21, settimana=5):
    """I segnali alla chiusura di ogni giorno (usano quel giorno e i precedenti): array (giorni, NOMI_GIORNALIERI).
    I rendimenti sono divisi per la volatilità giornaliera di un mese per la radice dei giorni (unità comparabili)."""
    n = len(c)
    out = np.zeros((n, len(NOMI_GIORNALIERI)), np.float32)
    if n < 3:
        return out
    lc = np.log(c)
    r = np.zeros(n)
    r[1:] = np.diff(lc)
    vol = np.full(n, 0.02)                                              # all'inizio, senza storia: un valore fisso
    for i in range(2, n):
        a = max(1, i - mese + 1)
        v = r[a:i + 1].std()                                            # solo il passato fino al giorno i compreso
        if v > 0:
            vol[i] = v
    vol = np.maximum(vol, 1e-4)

    def rend(L):
        x = np.zeros(n)
        x[L:] = lc[L:] - lc[:-L]
        x[:L] = lc[:L] - lc[0]
        return np.clip(x / (vol * math.sqrt(L)), -8, 8)

    ma = np.array([c[max(0, i - 199):i + 1].mean() for i in range(n)])
    mx = np.array([h[max(0, i - anno + 1):i + 1].max() for i in range(n)])
    su = np.where(r > 0, r, 0.0)
    giu = np.where(r < 0, -r, 0.0)
    rsi = np.full(n, 50.0)
    for i in range(2, n):                                               # RSI a 2 giorni (media semplice degli ultimi 2)
        s, g = su[i - 1:i + 1].sum(), giu[i - 1:i + 1].sum()
        rsi[i] = 100.0 * s / (s + g) if s + g > 0 else 50.0
    rng = h - l
    tr = np.maximum.reduce([rng, np.abs(h - np.concatenate(([c[0]], c[:-1]))), np.abs(l - np.concatenate(([c[0]], c[:-1])))])
    atr = np.array([tr[max(0, i - 13):i + 1].mean() for i in range(n)])
    nr7 = np.array([1.0 if i >= 6 and rng[i] <= rng[i - 6:i + 1].min() else 0.0 for i in range(n)])
    out[:, 0], out[:, 1], out[:, 2], out[:, 3] = rend(anno), rend(mese), rend(settimana), rend(1)
    out[:, 4] = np.clip(np.log(c / ma) / (vol * math.sqrt(mese)), -8, 8)
    out[:, 5] = np.clip(np.log(c / mx) / (vol * math.sqrt(mese)), -8, 0)
    out[:, 6] = (rsi - 50.0) / 50.0
    out[:, 7] = nr7
    out[:, 8] = np.clip(np.log(np.maximum(rng, 1e-12) / np.maximum(atr, 1e-12)), -3, 3)
    out[:, 9] = np.log(vol)
    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


NOMI_SCANNER = ("sc_breakout_20g", "sc_bandiera", "sc_sopra_media20", "sc_ipervenduto", "sc_rimbalzo")


def tabella_scanner(c):
    """I cinque segnali della skill trader-scanner, alla chiusura di ogni giorno (0 o 1): chiusura sopra tutte le 20
    chiusure prima; bandiera rialzista (oltre +10 % nelle 10 sedute prima delle ultime 5, poi le ultime 5 chiusure in un
    intervallo del 5 %); ritorno sopra la media di 20 giorni (ieri sotto, oggi sopra); ipervenduto (RSI 14 di Wilder
    sotto 30); rimbalzo dall'ipervenduto (ieri RSI sotto 30, oggi in rialzo)."""
    c = np.asarray(c, dtype=np.float64)
    n = len(c)
    out = np.zeros((n, len(NOMI_SCANNER)), np.float32)
    if n < 22:
        return out
    d = np.diff(c, prepend=c[0])
    su, giu = np.where(d > 0, d, 0.0), np.where(d < 0, -d, 0.0)
    rsi = np.full(n, 50.0)
    ms, mg = su[1:15].mean(), giu[1:15].mean()
    for i in range(15, n):                                             # media di Wilder
        ms, mg = (ms * 13 + su[i]) / 14, (mg * 13 + giu[i]) / 14
        rsi[i] = 100.0 if mg == 0 else 100.0 - 100.0 / (1.0 + ms / mg)
    ma20 = np.array([c[max(0, i - 19):i + 1].mean() for i in range(n)])
    for i in range(21, n):
        out[i, 0] = float(c[i] > c[i - 20:i].max())
        if i >= 15:
            prima, ultime = c[i - 15:i - 4], c[i - 4:i + 1]
            out[i, 1] = float(prima[-1] / prima[0] - 1 > 0.10 and ultime.max() / ultime.min() - 1 < 0.05)
        out[i, 2] = float(c[i - 1] < ma20[i - 1] and c[i] > ma20[i])
        out[i, 3] = float(rsi[i] < 30)
        out[i, 4] = float(rsi[i - 1] < 30 and c[i] > c[i - 1])
    return out


def atr_giornaliero(o, h, l, c, n=14):
    """L'escursione media (ATR) a n giorni, alla chiusura di ogni giorno."""
    if len(c) == 0:
        return np.zeros(0)
    prev = np.concatenate(([c[0]], c[:-1]))
    tr = np.maximum.reduce([h - l, np.abs(h - prev), np.abs(l - prev)])
    return np.array([tr[max(0, i - n + 1):i + 1].mean() for i in range(len(c))])


def per_giorno(giorni_dati, valori, giorni_voluti, ritardo=1):
    """Per ogni giorno voluto (ISO), la riga di `valori` dell'ultimo giorno di dati almeno `ritardo` giorni di calendario
    prima (ritardo=1: il giorno prima, già chiuso: niente futuro). Zeri dove non c'è niente."""
    out = np.zeros((len(giorni_voluti),) + valori.shape[1:], np.float32)
    if not len(giorni_dati):
        return out
    idx = np.array([datetime.date.fromisoformat(g).toordinal() for g in giorni_dati])
    for k, g in enumerate(giorni_voluti):
        j = int(np.searchsorted(idx, datetime.date.fromisoformat(g).toordinal() - ritardo + 1)) - 1
        if j >= 0:
            out[k] = valori[j]
    return out


def sentimento_per_giorno(giorni_voluti, fg=None):
    """Fear & Greed del giorno prima (livello) e la sua variazione in 7 giorni, in unità di 25 punti."""
    fg = fear_greed() if fg is None else fg
    if not fg:
        return np.zeros((len(giorni_voluti), len(NOMI_SENTIMENTO)), np.float32)
    giorni = sorted(fg)
    v = np.array([fg[g] for g in giorni], dtype=np.float64)
    prima = np.concatenate((np.full(7, v[0]), v[:-7])) if len(v) > 7 else np.full(len(v), v[0])
    tab = np.stack([(v - 50.0) / 25.0, (v - prima) / 25.0], axis=1)
    return per_giorno(giorni, tab, giorni_voluti, ritardo=1)


def notizie_per_giorno(serie, giorni_voluti):
    """Notizie del giorno prima: quantità rispetto alla media dei 30 giorni prima (logaritmo) e tono rispetto al tono medio
    dei 30 giorni prima. Zeri dove non ci sono (prima dei 3 mesi di GDELT)."""
    if not serie:
        return np.zeros((len(giorni_voluti), len(NOMI_NOTIZIE)), np.float32)
    giorni = sorted(serie)
    n = np.array([serie[g][0] for g in giorni], dtype=np.float64)
    t = np.array([serie[g][1] for g in giorni], dtype=np.float64)
    tab = np.zeros((len(giorni), 2))
    for i in range(len(giorni)):
        a = max(0, i - 30)
        if i - a >= 5:
            tab[i, 0] = np.log((n[i] + 1.0) / (n[a:i].mean() + 1.0))
            tab[i, 1] = np.clip((t[i] - t[a:i].mean()) / (t[a:i].std() + 0.1), -5, 5)
    return per_giorno(giorni, tab, giorni_voluti, ritardo=1)


# ---------------------------------------------------------------- la lista delle fonti (per l'app e il README)

FONTI = [
    ("Moskowitz, Ooi e Pedersen (2012), Time series momentum, Journal of Financial Economics 104(2)",
     "il rendimento di un anno, un mese, una settimana prevede quello dopo, su molti mercati: i segnali anno, mese, settimana"),
    ("Liu e Tsyvinski (2021), Risks and Returns of Cryptocurrency, Review of Financial Studies 34(6)",
     "sulle crypto il momento di 1-4 settimane e l'attenzione degli investitori prevedono i rendimenti"),
    ("Detzel, Liu, Strauss, Zhou e Zhu (2021), Financial Management 50(1)",
     "le medie mobili prevedono i rendimenti di Bitcoin: il segnale media200"),
    ("George e Hwang (2004), The 52-week high and momentum investing, Journal of Finance 59(5)",
     "la distanza dal massimo di 52 settimane: il segnale max52"),
    ("Gao, Han, Li e Zhou (2018), Market intraday momentum, Journal of Financial Economics 129(2)",
     "il rendimento della prima mezz'ora prevede quello dell'ultima: il segnale prima_mezzora"),
    ("Wen, Bouri, Xu e Zhao (2022), North American Journal of Economics and Finance 62",
     "lo stesso momento dentro la giornata su Bitcoin, con inversioni in certi momenti"),
    ("Heston, Korajczyk e Sadka (2010), Intraday patterns in the cross-section of stock returns, Journal of Finance 65(4)",
     "un titolo tende a ripetere il rendimento della stessa mezz'ora dei giorni prima: i segnali di stagionalità"),
    ("Eross, McGroarty, Urquhart e Wolfe (2019), The intraday dynamics of bitcoin, Research in International Business and Finance 49",
     "volumi, volatilità e rendimenti di Bitcoin cambiano con l'ora del giorno"),
    ("Lou, Polk e Skouras (2019), A tug of war: overnight versus intraday expected returns, Journal of Financial Economics 134(1)",
     "quello che sale di notte tende a scendere di giorno: il salto della notte"),
    ("Cont, Kukanov e Stoikov (2014), The price impact of order book events, Journal of Financial Econometrics 12(1)",
     "lo squilibrio tra acquisti e vendite spiega le mosse del prezzo nel breve: i segnali di flusso"),
    ("Corsi (2009), A simple approximate long-memory model of realized volatility, Journal of Financial Econometrics 7(2)",
     "la volatilità di giorno, settimana e mese insieme prevede quella dopo"),
    ("Tetlock (2007), Giving content to investor sentiment, Journal of Finance 62(3)",
     "il tono delle notizie sposta i prezzi, poi in parte si torna indietro: i segnali delle notizie"),
    ("Zarattini e Aziz (2023), Can day trading really be profitable? (SSRN); Zarattini, Barbon e Aziz (2024), A profitable day trading strategy for the U.S. equity market (SSRN)",
     "la rottura del range dei primi 5 minuti sui titoli con volume insolito (stocks in play): i segnali opening range e volume relativo"),
    ("Toby Crabel (1990), Day Trading with Short Term Price Patterns and Opening Range Breakout",
     "opening range e giornate strette (NR7) prima delle rotture"),
    ("Larry Williams (1999), Long-Term Secrets to Short-Term Trading",
     "rottura di volatilità: apertura più metà dell'escursione di ieri"),
    ("Laurence Connors e Linda Raschke (1995), Street Smarts", "RSI a 2 giorni e ritorni dopo gli eccessi"),
    ("Ernest Chan (2013), Algorithmic Trading: Winning Strategies and Their Rationale",
     "buy-on-gap: comprare i titoli aperti molto sotto la chiusura di ieri e vendere in chiusura"),
    ("Andrew Aziz (2016), How to Day Trade for a Living", "VWAP, volume relativo e opening range per il day trading"),
    ("Claudio Sperti, Silloge di metodi operativi per il trading azionario intraday (tesi, Università di Bologna, 2010)",
     "Opening Gap, Opening Gap di Altucher, 80-20 di Connors e Oops di Williams sul FTSE MIB: provati in regole_libri.py"),
    ("Corey Rosenbloom (2011), Guida completa al trading (The Complete Trading Course)",
     "trend con le medie esponenziali a 20 e 50, oscillatore MACD 3/10, impulse buy e bullish cradle: provati in regole_libri.py"),
    ("Marcos López de Prado (2018), Advances in Financial Machine Learning",
     "pesi che danno più importanza ai dati recenti, verifica con intervalli tra addestramento e test"),
]


def main():
    fg = fear_greed()
    print("[segnali] Fear & Greed: %d giorni%s" % (len(fg), (", ultimo %s = %d" % (max(fg), fg[max(fg)])) if fg else ""))
    for nome, q in (("crypto", "bitcoin OR cryptocurrency OR crypto"),):
        s = notizie(nome, q)
        print("[segnali] notizie %s: %d giorni" % (nome, len(s)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
