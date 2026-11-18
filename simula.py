#!/usr/bin/env python3
"""Simula un titolo dal codice ISIN (o dal ticker): probabilità di guadagno a 1 giorno,
1 settimana, 1 mese e 1 anno con la Macchina del Tempo, e quanto ci si può fidare.

    python3 simula.py IT0003132476                 # ENI
    python3 simula.py US0378331005 IE00B4L5Y983    # Apple e un ETF MSCI World
    python3 simula.py AAPL                         # anche dal ticker

Per ogni titolo:
  1. trova il ticker dall'ISIN (ricerca di Yahoo Finance) e scarica fino a 25 anni di prezzi
     giornalieri corretti per dividendi e split;
  2. COM'È ANDATA DAVVERO: su tutte le finestre reali della storia (ogni giorno, ogni
     settimana, ogni mese, ogni anno) quante volte il prezzo è salito;
  3. MACCHINA DEL TEMPO: 10.000 futuri costruiti con pezzi veri della storia. Per 1 giorno,
     1 settimana e 1 mese rigioca finestre vere; per 1 anno incolla 12 mesi veri presi a caso,
     così ottiene 10.000 anni possibili invece dei pochi reali. La tendenza di fondo viene
     tolta e rimessa secondo tre scenari:
       nessuna crescita   0 % l'anno
       prudente           la crescita passata, ridotta in base a quanto è incerta (consigliato)
       come in passato    la crescita media degli anni scaricati
  4. AFFIDABILITÀ per ogni orizzonte: alta, media o bassa, dal numero di casi indipendenti
     nella storia e da quanto i tre scenari sono d'accordo.

Aggiunge il codice a simula_lista.json: `python3 app.py` lo rielabora con prezzi aggiornati e lo
mette nell'app.
Prezzi lordi: niente costi né tasse. Non è consulenza finanziaria.
Solo libreria standard, Python 3.8+.
"""

import argparse
import datetime
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import settimana

ROOT = os.path.dirname(os.path.abspath(__file__))
TRADER = os.path.join(ROOT, "trader")
CACHE_MAX = os.path.join(TRADER, "cache", "max")
LISTA = os.path.join(ROOT, "simula_lista.json")   # gli ISIN aggiunti all'app (versionato)
ISIN_FILE = os.path.join(ROOT, "isin.json")
UA = settimana.UA

HORIZONS = [("1 giorno", 1), ("1 settimana", 5), ("1 mese", 21), ("3 mesi", 63), ("6 mesi", 126), ("1 anno", 252)]
DURATE = ("1 mese", "3 mesi", "6 mesi", "1 anno")     # tra queste si sceglie per quanto tenere uno strumento
RISCHIO = 0.10                   # ... la più probabile tra quelle in cui 1 volta su 10 non si perde più del 10 %
BLOCK = 21                       # la Macchina del Tempo incolla pezzi di un mese
N_SIM = 10000
YEARS_MAX = 25
PRIOR_GROWTH = 0.05              # punto di partenza prudente: +5 % l'anno
PRIOR_SD = 0.04                  # quanto può variare da un titolo all'altro la vera crescita annua attesa:
                                 # pochi punti; il resto della differenza passata è soprattutto fortuna
SCENARI = [("zero", "Nessuna crescita"), ("prudente", "Prudente"), ("passato", "Come in passato")]
EXCH_IT = ("MIL",)               # Borsa Italiana
EXCH_US = ("NMS", "NYQ", "NGM", "NCM", "ASE", "PCX", "BTS")


class SimError(Exception):
    pass


# ------------------------------------------------------------------ ISIN e ricerca

def isin_ok(code):
    """Formato e cifra di controllo di un codice ISIN (ISO 6166)."""
    code = code.strip().upper()
    if len(code) != 12 or not code[:2].isalpha() or not code[2:11].isalnum() or not code[11].isdigit():
        return False
    digits = "".join(str(int(ch, 36)) for ch in code[:11])
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return (10 - total % 10) % 10 == int(code[11])


def _get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def search(query):
    """I risultati della ricerca di Yahoo Finance per un ISIN, un ticker o un nome."""
    url = ("https://query2.finance.yahoo.com/v1/finance/search?q=%s&quotesCount=8&newsCount=0"
           % urllib.parse.quote(query))
    try:
        return json.loads(_get(url)).get("quotes", [])
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise SimError("ricerca non riuscita per %s: %s" % (query, e))


def pick_quote(quotes, isin=None):
    """Sceglie il listino: per un ISIN italiano Borsa Italiana, per uno USA le borse USA; per gli
    altri (per esempio ETF irlandesi o lussemburghesi) Milano se c'è, altrimenti il primo."""
    ok = [q for q in quotes if q.get("symbol") and q.get("quoteType") in ("EQUITY", "ETF", "MUTUALFUND", "INDEX")]
    if not ok:
        return None
    country = (isin or "")[:2]
    prefer = EXCH_US if country == "US" else EXCH_IT
    for q in ok:
        if q.get("exchange") in prefer:
            return q
    return ok[0]


def load_isin_map():
    try:
        with open(ISIN_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def resolve(query):
    """ISIN o ticker -> {"symbol", "name", "exchange", "type", "isin"}."""
    q = query.strip().upper()
    known = load_isin_map()
    if isin_ok(q):
        if q in known:
            return {"symbol": known[q], "name": "", "exchange": "", "type": "", "isin": q}
        best = pick_quote(search(q), q)
        if not best:
            raise SimError("nessun titolo trovato per l'ISIN %s" % q)
        return {"symbol": best["symbol"], "name": best.get("longname") or best.get("shortname") or "",
                "exchange": best.get("exchDisp") or best.get("exchange") or "", "type": best.get("quoteType", ""),
                "isin": q}
    if len(q) == 12 and q[:2].isalpha():
        raise SimError("%s sembra un ISIN, ma la cifra di controllo non torna: ricontrolla il codice" % q)
    rev = {v: k for k, v in known.items()}
    return {"symbol": q, "name": "", "exchange": "", "type": "", "isin": rev.get(q)}


# ------------------------------------------------------------------ prezzi

def fetch_max(symbol, max_age_hours=12):
    """Fino a YEARS_MAX anni di candele giornaliere (cache di 12 ore). Con range=max Yahoo
    passa a candele mensili, quindi si chiedono date di inizio e fine esplicite."""
    path = os.path.join(CACHE_MAX, symbol.replace("/", "_") + ".v2.json")      # v2: con i dividendi
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < max_age_hours * 3600:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    last = None
    for host in ("query2", "query1"):
        now = int(time.time())
        url = ("https://%s.finance.yahoo.com/v8/finance/chart/%s?period1=%d&period2=%d&interval=1d"
               "&includeAdjustedClose=true&events=div" % (host, urllib.parse.quote(symbol), now - YEARS_MAX * 366 * 86400, now))
        try:
            text = _get(url, timeout=40)
            os.makedirs(CACHE_MAX, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            return text
        except urllib.error.HTTPError as e:
            last = "HTTP %d" % e.code
            if e.code == 404:
                break
        except (urllib.error.URLError, OSError) as e:
            last = str(getattr(e, "reason", e))
    raise SimError("non riesco a scaricare i prezzi di %s (%s)" % (symbol, last))


def series(text):
    """-> (meta, date, chiusure corrette). Scarta la candela di oggi se la seduta non è finita."""
    res = json.loads(text)["chart"]
    if not res.get("result"):
        raise SimError((res.get("error") or {}).get("description") or "nessun dato")
    res = res["result"][0]
    meta = res.get("meta", {})
    if meta.get("dataGranularity", "1d") != "1d":
        raise SimError("Yahoo ha restituito candele %s invece che giornaliere" % meta.get("dataGranularity"))
    ts = res.get("timestamp") or []
    ind = res.get("indicators", {})
    adj = (ind.get("adjclose") or [{}])[0].get("adjclose") or (ind.get("quote") or [{}])[0].get("close") or []
    off = meta.get("gmtoffset", 0)
    dates, closes = [], []
    for t, c in zip(ts, adj):
        if c is None or c <= 0:
            continue
        d = datetime.datetime.fromtimestamp(t + off, datetime.timezone.utc).strftime("%Y-%m-%d")
        if dates and dates[-1] == d:
            closes[-1] = float(c)
            continue
        dates.append(d)
        closes.append(float(c))
    end = (((meta.get("currentTradingPeriod") or {}).get("regular") or {}).get("end"))
    if dates and end and time.time() < end:
        today = datetime.datetime.fromtimestamp(time.time() + off, datetime.timezone.utc).strftime("%Y-%m-%d")
        if dates[-1] == today:
            dates.pop()
            closes.pop()
    extra = settimana.chiusura_mancante(meta, dates[-1] if dates else None)
    if extra:                                        # ultima seduta con la barra vuota: chiusura dai metadati
        dates.append(extra[0])
        closes.append(extra[1])
    return meta, dates, closes


# ------------------------------------------------------------------ simulazione

def pct(xs, q):
    return settimana.pct(xs, q)


def summary(rets):
    """rets: rendimenti semplici -> probabilità di guadagno e intervalli."""
    if not rets:
        return None
    return {"p_gain": round(sum(1 for r in rets if r > 0) / len(rets), 4), "median": round(pct(rets, .5), 4),
            "p5": round(pct(rets, .05), 4), "p10": round(pct(rets, .10), 4), "p90": round(pct(rets, .90), 4),
            "p95": round(pct(rets, .95), 4), "mean": round(sum(rets) / len(rets), 4), "n": len(rets)}


def durata_consigliata(orizzonti):
    """Per quanto tenere lo strumento: tra 1 mese, 3 mesi, 6 mesi e 1 anno, la durata con la probabilità
    di guadagno più alta (scenario prudente) tra quelle in cui 1 volta su 10 non si perde più del 10 %
    (la stessa soglia del giudizio "Sì"). A parità di probabilità la più breve. None se nessuna rispetta
    il limite: allora decide la categoria. Verificata in verifica.py (scelta_durata)."""
    ok = []
    for o in orizzonti:
        m = o["scenari"].get("prudente") if o["orizzonte"] in DURATE else None
        if not m:
            continue
        p10 = m["p10"] if m.get("p10") is not None else m["p5"]
        if round(p10, 2) >= -RISCHIO:
            ok.append((round(m["p_gain"], 2), -o["giorni"], o["giorni"]))
    return max(ok)[2] if ok else None


def reliability(n_indep, spread):
    """Affidabilità di una probabilità: quanti casi indipendenti ci sono e quanto conta l'ipotesi
    sulla crescita (distanza tra 'nessuna crescita' e 'come in passato')."""
    if n_indep >= 100 and spread <= 0.10:
        lvl = "alta"
    elif n_indep >= 20 and spread <= 0.20:
        lvl = "media"
    else:
        lvl = "bassa"
    why = []
    why.append("%s %s nella storia" % (format(n_indep, ",").replace(",", "."),
                                       "periodo indipendente" if n_indep == 1 else "periodi indipendenti"))
    if spread <= 0.05:
        why.append("gli scenari di crescita quasi non cambiano il risultato")
    elif spread <= 0.15:
        why.append("gli scenari di crescita spostano il risultato di %d punti" % round(spread * 100))
    else:
        why.append("il risultato dipende molto dalla crescita che si suppone (%d punti di differenza)"
                   % round(spread * 100))
    return {"livello": lvl, "motivo": "; ".join(why)}


CALENDARI = {
    # azioni, ETF, obbligazioni: giorni di borsa
    "borsa": {"anno": 252, "orizzonti": HORIZONS, "blocco": BLOCK, "vol": 63},
    # crypto: si scambiano tutti i giorni, weekend compresi
    "sempre": {"anno": 365, "orizzonti": [("1 giorno", 1), ("1 settimana", 7), ("1 mese", 30), ("3 mesi", 91),
                                          ("6 mesi", 182), ("1 anno", 365)], "blocco": 30, "vol": 91},
}
CRYPTO = "BTC-EUR ETH-EUR SOL-EUR XRP-EUR BNB-EUR ADA-EUR DOGE-EUR LTC-EUR DOT-EUR LINK-EUR AVAX-EUR TRX-EUR".split()


def simulate(dates, closes, n=N_SIM, seed=19, cal="borsa"):
    """Com'è andata davvero + Macchina del Tempo per 1 giorno, 1 settimana, 1 mese, 3 mesi e 1 anno.
    cal: "borsa" (252 giorni l'anno) o "sempre" (365, per le crypto)."""
    C = CALENDARI[cal]
    A, B = C["anno"], C["blocco"]
    if len(closes) > YEARS_MAX * A + 1:
        dates, closes = dates[-(YEARS_MAX * A + 1):], closes[-(YEARS_MAX * A + 1):]
    N = len(closes) - 1
    if N < 2 * B:
        raise SimError("storia troppo corta: %d giorni" % (N + 1))
    lr = [math.log(closes[i + 1] / closes[i]) for i in range(N)]
    S = [0.0]
    for x in lr:
        S.append(S[-1] + x)
    years = N / A
    mu = S[-1] / N
    sd = math.sqrt(sum((x - mu) ** 2 for x in lr) / (N - 1))
    mu_a, sd_a = mu * A, sd * math.sqrt(A)
    prior = math.log(1 + PRIOR_GROWTH)
    se = sd_a / math.sqrt(years)
    w = PRIOR_SD ** 2 / (PRIOR_SD ** 2 + se ** 2)
    mu_prud = (prior + w * (mu_a - prior)) / A
    drift = {"zero": 0.0, "prudente": mu_prud, "passato": mu}

    rnd = random.Random(seed)
    out = []
    year_paths = None
    for label, h in C["orizzonti"]:
        row = {"orizzonte": label, "giorni": h, "storico": None, "scenari": {}, "affidabilita": None}
        if N >= h + 20:
            row["storico"] = summary([math.exp(S[k + h] - S[k]) - 1 for k in range(0, N - h + 1)])
            row["storico"]["indipendenti"] = N // h
        # pezzi veri, tolta la tendenza media della storia
        if h <= B:
            draws = []
            for _ in range(n):
                k = rnd.randrange(0, N - h + 1)
                draws.append(S[k + h] - S[k] - mu * h)
        else:
            blocks = [B] * (h // B) + ([h % B] if h % B else [])
            draws, paths = [], []
            for _ in range(n):
                cum, path = 0.0, []
                for b in blocks:
                    k = rnd.randrange(0, N - b + 1)
                    cum += S[k + b] - S[k] - mu * b
                    path.append(cum)
                draws.append(cum)
                paths.append(path)
            year_paths = paths
        for sid, _ in SCENARI:
            row["scenari"][sid] = summary([math.exp(x + drift[sid] * h) - 1 for x in draws])
        spread = abs(row["scenari"]["passato"]["p_gain"] - row["scenari"]["zero"]["p_gain"])
        row["affidabilita"] = reliability(N // h, spread)
        out.append(row)

    # ventaglio di un anno, mese per mese (blocchi interi), senza tendenza: l'app aggiunge quella dello scenario
    fan = [[1.0] * 5]
    for mth in range(min(12, len(year_paths[0]))):
        col = sorted(math.exp(p[mth]) for p in year_paths)
        fan.append([round(pct(col, q), 5) for q in (.05, .25, .5, .75, .95)])

    # il calo più grande dal picco, nella storia usata
    peak, dd = closes[0], 0.0
    for c in closes:
        peak = max(peak, c)
        dd = min(dd, c / peak - 1)

    # com'è oggi: le stesse misure che usa l'algoritmo dei consigli
    last, V = len(closes) - 1, C["vol"]
    stato = {"sopra_media200": None, "vs_media200": None, "anno": None, "dal_massimo": None, "vol3m": None}
    if last >= A:
        sma = sum(closes[last - 199:last + 1]) / 200
        rv = lr[-V:]
        mv = sum(rv) / len(rv)
        stato = {"sopra_media200": closes[last] > sma, "vs_media200": round(closes[last] / sma - 1, 4),
                 "anno": round(closes[last] / closes[last - A] - 1, 4),
                 "dal_massimo": round(closes[last] / max(closes[last - A + 1:last + 1]) - 1, 4),
                 "vol3m": round(math.sqrt(sum((x - mv) ** 2 for x in rv) / (len(rv) - 1)) * math.sqrt(A), 4)}

    step = 5 if cal == "borsa" else 7
    c0 = max(0, len(closes) - 5 * A)
    tail = (len(dates) - 1 - c0) % step
    return {
        "stato": stato, "cal": cal, "blocco": B, "calo_massimo": round(dd, 4),
        "da": dates[0], "a": dates[-1], "anni": round(years, 1), "prezzo": round(closes[-1], 6),
        "volatilita": round(sd_a, 4), "crescita": {"zero": 0.0, "prudente": round(math.exp(mu_prud * A) - 1, 4),
                                                    "passato": round(math.exp(mu_a) - 1, 4)},
        "drift": {k: round(v, 8) for k, v in drift.items()},
        "orizzonti": out, "ventaglio": fan, "durata": durata_consigliata(out),
        "media10": round(closes[-1] / (sum(closes[-10:]) / len(closes[-10:])) - 1, 5),   # piccolo ribasso se < 0
        "grafico": {"dates": dates[c0::step] + ([dates[-1]] if tail else []),
                    "close": [round(x, 6) for x in closes[c0::step]] + ([round(closes[-1], 6)] if tail else [])},
    }


def instrument(query, text=None):
    """ISIN o ticker -> scheda completa con la simulazione."""
    info = resolve(query)
    text = text if text is not None else fetch_max(info["symbol"])
    meta, dates, closes = series(text)
    cal = "sempre" if (meta.get("instrumentType") == "CRYPTOCURRENCY" or info["symbol"] in CRYPTO) else "borsa"
    sim = simulate(dates, closes, cal=cal)
    sim["rendimento"] = settimana.div_yield(text)
    return {
        "isin": info.get("isin"), "symbol": info["symbol"],
        "name": info["name"] or meta.get("longName") or meta.get("shortName") or info["symbol"],
        "exchange": info["exchange"] or meta.get("fullExchangeName") or meta.get("exchangeName") or "",
        "type": info["type"] or meta.get("instrumentType") or "", "currency": meta.get("currency") or "",
        "generato": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        **sim,
    }


# ------------------------------------------------------------------ elenco per l'app

def load_list():
    try:
        with open(LISTA, encoding="utf-8") as fh:
            return [str(x) for x in json.load(fh)]
    except (OSError, ValueError):
        return []


def save_list(codes):
    with open(LISTA, "w", encoding="utf-8") as fh:
        json.dump(sorted(set(codes)), fh, indent=1)


# ------------------------------------------------------------------ stampa

def f_pct(x, d=1, sign=True):
    return settimana.f_pct(x, d, sign)


def print_sim(s):
    print("\n%s  (%s · %s%s)" % (s["name"], s["symbol"], s["exchange"], (" · ISIN " + s["isin"]) if s.get("isin") else ""))
    print("Prezzi dal %s al %s (%s anni) · ultimo %s %s · oscilla del %s l'anno" % (
        s["da"], s["a"], str(s["anni"]).replace(".", ","), s["prezzo"], s["currency"], f_pct(s["volatilita"], 0, False)))
    print("Crescita annua: come in passato %s · prudente %s · nessuna 0 %%\n" % (
        f_pct(s["crescita"]["passato"]), f_pct(s["crescita"]["prudente"])))
    print("  %-12s %-28s %-28s %-8s %s" % ("orizzonte", "Macchina del Tempo (prudente)", "com'è andata davvero", "", "affidabilità"))
    for r in s["orizzonti"]:
        m = r["scenari"]["prudente"]
        h = r["storico"]
        mt = "%s in guadagno, di solito %s" % (f_pct(m["p_gain"], 0, False), f_pct(m["median"]))
        st = ("%s su %s casi" % (f_pct(h["p_gain"], 0, False), format(h["indipendenti"], ",").replace(",", "."))) if h else "n/d"
        print("  %-12s %-28s %-28s %-8s %s (%s)" % (r["orizzonte"], mt, st, "", r["affidabilita"]["livello"].upper(),
                                                r["affidabilita"]["motivo"]))
    print("\n  Intervallo 9 casi su 10 (prudente): " + " · ".join(
        "%s da %s a %s" % (r["orizzonte"], f_pct(r["scenari"]["prudente"]["p5"], 0), f_pct(r["scenari"]["prudente"]["p95"], 0))
        for r in s["orizzonti"]))
    print("  Senza costi né tasse. Stime dal passato, non previsioni. Non è consulenza finanziaria.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("codici", nargs="+", help="codici ISIN (es. IT0003132476) o ticker (es. AAPL, ENI.MI)")
    ap.add_argument("--no-salva", action="store_true", help="non aggiungere all'app")
    a = ap.parse_args(argv)
    codes, added, rc = load_list(), [], 0
    for q in a.codici:
        try:
            s = instrument(q)
        except (SimError, settimana.FetchError) as e:
            print("[simula] %s: %s" % (q, e))
            rc = 1
            continue
        print_sim(s)
        added.append(s.get("isin") or s["symbol"])
    if not a.no_salva and added:
        save_list(codes + added)
        print("\n[simula] aggiunto a simula_lista.json: %s. Esegui python3 app.py per vederlo nell'app." % ", ".join(added))
    return rc


if __name__ == "__main__":
    sys.exit(main())
