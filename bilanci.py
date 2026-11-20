#!/usr/bin/env python3
"""I bilanci delle aziende USA dalla SEC (dati XBRL di data.sec.gov), come caratteristiche della rete del medio periodo:
i fattori "value" e "quality" degli studi (Fama e French 1992 e 2015; Novy-Marx 2013; Asness, Frazzini e Pedersen,
"Quality minus junk", 2019).

    python3 bilanci.py AAPL MSFT       # stampa le misure di oggi

Ogni numero conta solo dal giorno in cui l'azienda l'ha depositato alla SEC (la data "filed"): la rete non vede mai il
futuro. Si usano solo misure che non dipendono dai frazionamenti delle azioni:
  utili_prezzo       utile netto dell'ultimo anno / valore di borsa (il flottante dichiarato alla SEC, portato al prezzo
                     del giorno con il rapporto dei prezzi corretti di Yahoo)
  roe                utile netto / patrimonio netto
  margine            utile netto / ricavi
  crescita_ricavi    ricavi dell'ultimo anno contro l'anno prima
  debito             passività / attività
  crescita_dividendi dividendo per azione dell'ultimo anno contro l'anno prima (dallo stesso bilancio)
  ha_bilanci         1 se ci sono i numeri, 0 se no (azioni non USA, ETF, crypto)

La SEC chiede ai programmi di presentarsi: qui si usa un nome generico, senza dati personali.
Solo la libreria standard e numpy. Non è consulenza finanziaria.
"""

import bisect
import datetime
import json
import os
import re
import sys
import time
import urllib.request

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "trader", "cache", "sec")
UA = "Finanza ricerca"
NOMI_BILANCI = ("utili_prezzo", "roe", "margine", "crescita_ricavi", "debito", "crescita_dividendi", "ha_bilanci",
                "sorpresa_utili", "bilancio_fresco")
# il calendario dei conti: la sorpresa degli utili dell'ultimo trimestre (contro lo stesso trimestre dell'anno prima) e
# quanto è fresco l'ultimo bilancio depositato. Dopo i conti il prezzo continua per settimane nella direzione della
# sorpresa ("post-earnings announcement drift", Bernard e Thomas 1989). False: le due colonne restano a zero.
# Provato con la cross-validation epurata (python3 rete_lungo.py --epurata-calendario, 20 novembre 2026): a 1 settimana
# +0,30 % sulla media con il calendario contro +0,34 % senza (t 2,4 contro 3,2), a 1 e 3 mesi uguale. Non aiuta: spento.
CALENDARIO = False
RICAVI = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
          "RevenueFromContractWithCustomerIncludingAssessedTax")
CONCETTI = {"utile": ("NetIncomeLoss",), "ricavi": RICAVI, "patrimonio": ("StockholdersEquity",), "passivita": ("Liabilities",),
            "attivita": ("Assets",), "totale_passivo": ("LiabilitiesAndStockholdersEquity",), "dividendo": ("CommonStockDividendsPerShareDeclared", "CommonStockDividendsPerShareCashPaid")}
_ultima = [0.0]


def _get(url, timeout=60):
    pausa = _ultima[0] + 0.25 - time.time()                     # al più 4 richieste al secondo (la SEC ne permette 10)
    if pausa > 0:
        time.sleep(pausa)
    _ultima[0] = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _norm(nome):
    nome = nome.lower().replace("&", " and ")
    nome = re.sub(r"[^a-z0-9 ]", " ", nome)
    via = {"inc", "corp", "corporation", "co", "company", "ltd", "plc", "the", "holdings", "holding", "group", "class", "de",
           "n", "v", "nv", "sa", "ag", "se", "incorporated", "limited", "lp", "llc", "a", "b", "com"}
    return [t for t in nome.split() if t not in via]


def elenco_aziende():
    """Le aziende che depositano bilanci alla SEC (cik, nome), dagli elenchi di alcuni trimestri recenti."""
    path = os.path.join(CACHE, "aziende.json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 30 * 86400:
        with open(path, encoding="utf-8") as fh:
            return {int(k): v for k, v in json.load(fh).items()}
    aziende = {}
    anno = datetime.date.today().year
    for a in (anno, anno - 1):
        for q in ("Q1", "Q2", "Q3", "Q4"):
            for concetto in ("dei/EntityCommonStockSharesOutstanding/shares", "us-gaap/Assets/USD"):
                try:
                    d = _get("https://data.sec.gov/api/xbrl/frames/%s/CY%d%sI.json" % (concetto, a, q))
                except Exception:
                    continue
                for e in d.get("data", []):
                    aziende.setdefault(int(e["cik"]), e["entityName"])
    os.makedirs(CACHE, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(aziende, fh)
    return aziende


def cik_di(simboli_nomi, log=print):
    """Il codice SEC (CIK) di ogni ticker USA: si cercano le aziende con il nome più simile a quello di Yahoo e si
    conferma con l'elenco dei ticker della SEC per quell'azienda. {ticker: cik o None}, in cache."""
    path = os.path.join(CACHE, "cik.json")
    try:
        with open(path, encoding="utf-8") as fh:
            mappa = json.load(fh)
    except (OSError, ValueError):
        mappa = {}
    mancano = [(s, n) for s, n in simboli_nomi if s not in mappa]
    if not mancano:
        return mappa
    aziende = elenco_aziende()
    tok = {cik: set(_norm(n)) for cik, n in aziende.items()}
    for sym, nome in mancano:
        t = set(_norm(nome or ""))
        if not t:
            mappa[sym] = None
            continue
        punti = sorted(((len(t & v) / len(t | v), cik) for cik, v in tok.items() if t & v), reverse=True)[:4]
        trovato = None
        for _, cik in punti:
            try:
                sub = _get("https://data.sec.gov/submissions/CIK%010d.json" % cik)
            except Exception:
                continue
            tick = {x.upper().replace(".", "-") for x in sub.get("tickers") or []}
            if sym.upper().replace(".", "-") in tick:
                trovato = cik
                break
        mappa[sym] = trovato
        log("[bilanci] %-6s %s → %s" % (sym, nome, trovato))
    os.makedirs(CACHE, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(mappa, fh)
    return mappa


def fatti(cik, max_age=7 * 86400):
    """I numeri che servono, dal bilancio XBRL della SEC (compattati in cache): {concetto: [[filed, start, end, val, form, accn]]}
    e il flottante [[filed, data, valore in dollari]]."""
    path = os.path.join(CACHE, "fatti", "%010d.json" % cik)
    if os.path.exists(path) and (time.time() - os.path.getmtime(path) < max_age or os.environ.get("FINANZA_SENZA_RETE") == "1"):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    d = _get("https://data.sec.gov/api/xbrl/companyfacts/CIK%010d.json" % cik)
    f = d.get("facts", {})
    gaap = f.get("us-gaap", {})
    out = {}
    for chiave, nomi in CONCETTI.items():
        righe = []
        for nome in nomi:
            for unita, lista in (gaap.get(nome, {}).get("units") or {}).items():
                for x in lista:
                    if x.get("form") in ("10-K", "10-K/A", "10-Q", "10-Q/A") and "filed" in x and "end" in x:
                        righe.append([x["filed"], x.get("start"), x["end"], float(x["val"]), x["form"], x.get("accn")])
        out[chiave] = righe
    flot = []
    for unita, lista in (f.get("dei", {}).get("EntityPublicFloat", {}).get("units") or {}).items():
        for x in lista:
            if "filed" in x and "end" in x:
                flot.append([x["filed"], x["end"], float(x["val"])])
    out["flottante"] = flot
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))
    return out


def _annui(righe):
    """Le voci di un anno intero (dai 10-K, durata 330-400 giorni): [(filed, end, val, accn)] ordinate per deposito."""
    out = []
    for filed, start, end, val, form, accn in righe:
        if not start or not form.startswith("10-K"):
            continue
        giorni = (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days
        if 330 <= giorni <= 400:
            out.append((filed, end, val, accn))
    return sorted(out)


def _trimestri(righe):
    """Gli utili di un trimestre (dai 10-Q, 80-100 giorni): [(filed, end, val, accn)] ordinati per deposito."""
    out = []
    for filed, start, end, val, form, accn in righe:
        if start and form.startswith("10-Q") and 80 <= (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days <= 100:
            out.append((filed, end, val, accn))
    return sorted(out)


def sorprese(righe):
    """Per ogni deposito di un 10-Q: (data di deposito, sorpresa), con la sorpresa = utile del trimestre contro lo stesso
    trimestre dell'anno prima nello stesso bilancio, tra -1 e +1. Solo dati noti quel giorno."""
    T = _trimestri(righe)
    out = []
    for accn in sorted({x[3] for x in T}):
        q = [x for x in T if x[3] == accn]
        ultimo = max(q, key=lambda x: x[1])
        e = datetime.date.fromisoformat(ultimo[1])
        prima = [x for x in q if 330 <= (e - datetime.date.fromisoformat(x[1])).days <= 400]
        if prima and prima[0][2] != 0:
            out.append((ultimo[0], float(np.clip((ultimo[2] - prima[0][2]) / abs(prima[0][2]), -1, 1))))
    return sorted(out)


def _istanti(righe):
    return sorted((filed, end, val) for filed, start, end, val, form, accn in righe if not start)


def _crescita(annui, fino):
    """Crescita dell'ultimo anno depositato entro `fino`: si confrontano i due anni dello stesso bilancio (stessi criteri)."""
    noti = [x for x in annui if x[0] <= fino]
    if not noti:
        return None
    ultimo = max(noti, key=lambda x: (x[1], x[0]))
    stesso = [x for x in noti if x[3] == ultimo[3] and x[1] < ultimo[1]]
    prima = max(stesso, key=lambda x: x[1]) if stesso else None
    if prima is None or prima[2] == 0:
        return None
    return ultimo[2] / abs(prima[2]) - 1


def _ultimo(serie, fino, chiave=lambda x: (x[1], x[0])):
    noti = [x for x in serie if x[0] <= fino]
    return max(noti, key=chiave) if noti else None


def per_titolo(sym, giorni, prezzi):
    """Le misure di bilancio di un titolo USA per i giorni dati, o zeri se la SEC non lo ha (o senza rete e senza cache)."""
    try:
        with open(os.path.join(CACHE, "cik.json"), encoding="utf-8") as fh:
            cik = json.load(fh).get(sym)
        if not cik:
            return np.zeros((len(giorni), len(NOMI_BILANCI)), np.float32)
        if os.environ.get("FINANZA_SENZA_RETE") == "1" and not os.path.exists(os.path.join(CACHE, "fatti", "%010d.json" % cik)):
            return np.zeros((len(giorni), len(NOMI_BILANCI)), np.float32)
        return tabella(fatti(cik), giorni, prezzi)
    except Exception:
        return np.zeros((len(giorni), len(NOMI_BILANCI)), np.float32)


def tabella(sym_fatti, giorni, prezzi):
    """Le misure di bilancio per ogni giorno (ISO) con il prezzo corretto di quel giorno: array (giorni, NOMI_BILANCI).
    Si usa solo quello che era già depositato alla SEC quel giorno."""
    out = np.zeros((len(giorni), len(NOMI_BILANCI)), np.float32)
    if not sym_fatti:
        return out
    F = sym_fatti
    utile, ricavi, div = _annui(F.get("utile", [])), _annui(F.get("ricavi", [])), _annui(F.get("dividendo", []))
    patr, pas, att = _istanti(F.get("patrimonio", [])), _istanti(F.get("passivita", [])), _istanti(F.get("attivita", []))
    if not pas:                                                       # chi non dichiara le passività totali: totale meno patrimonio
        tot = {(f, e): v for f, e, v in _istanti(F.get("totale_passivo", []))}
        pas = sorted((f, e, tot[(f, e)] - v) for f, e, v in patr if (f, e) in tot)
    flot = sorted(tuple(x) for x in F.get("flottante", []))
    ordinali = [datetime.date.fromisoformat(g).toordinal() for g in giorni]
    depositi = sorted({r[0] for r in F.get("utile", [])})
    S = sorprese(F.get("utile", []))
    date_sorpresa, valori_sorpresa = [x[0] for x in S], [x[1] for x in S]
    mese, base, valore = None, np.zeros(len(NOMI_BILANCI), np.float32), None
    for i, g in enumerate(giorni):
        if g[:7] != mese:                                             # i bilanci cambiano di rado: si ricalcola una volta al mese
            mese, base, valore = g[:7], np.zeros(len(NOMI_BILANCI), np.float32), None
            u = _ultimo(utile, g)
            if u is not None:
                base[6] = 1.0
                p, r = _ultimo(patr, g), _ultimo(ricavi, g)
                if p is not None and p[2] > 0:
                    base[1] = np.clip(u[2] / p[2], -1, 1)
                if r is not None and r[2] > 0:
                    base[2] = np.clip(u[2] / r[2], -1, 1)
                cr = _crescita(ricavi, g)
                base[3] = np.clip(cr, -0.5, 1.0) if cr is not None else 0.0
                a, l = _ultimo(att, g), _ultimo(pas, g)
                if a is not None and l is not None and a[2] > 0:
                    base[4] = np.clip(l[2] / a[2], 0, 1.5)
                cd = _crescita(div, g)
                base[5] = np.clip(cd, -1, 1) if cd is not None else 0.0
                fl = _ultimo(flot, g)
                if fl is not None and fl[2] > 0:                      # il valore di borsa del giorno del flottante, e il prezzo di allora
                    k = int(np.searchsorted(ordinali, datetime.date.fromisoformat(fl[1]).toordinal(), side="right")) - 1
                    if k >= 0 and prezzi[k] > 0:
                        valore = (u[2], fl[2], prezzi[k])
        out[i] = base
        if CALENDARIO and base[6]:
            k = bisect.bisect_right(depositi, g) - 1                  # l'ultimo bilancio depositato entro oggi
            if k >= 0:
                giorni_da = ordinali[i] - datetime.date.fromisoformat(depositi[k]).toordinal()
                out[i, 8] = np.exp(-giorni_da / 30.0)                   # 1 il giorno dei conti, quasi 0 dopo tre mesi
            j = bisect.bisect_right(date_sorpresa, g) - 1
            if j >= 0:
                out[i, 7] = valori_sorpresa[j] * np.exp(-(ordinali[i] - datetime.date.fromisoformat(date_sorpresa[j]).toordinal()) / 60.0)
        if valore is not None and prezzi[i] > 0:                      # utile / valore di borsa di oggi (rapporto dei prezzi corretti)
            cap = valore[1] * prezzi[i] / valore[2]
            out[i, 0] = np.clip(valore[0] / cap, -0.5, 0.5) * 10 if cap > 0 else 0.0
    return out


def main(argv=None):
    import settimana
    simboli = (argv if argv is not None else sys.argv[1:]) or ["AAPL"]
    nomi = []
    for s in simboli:
        m = json.loads(settimana.fetch(s))["chart"]["result"][0]["meta"]
        nomi.append((s, m.get("longName") or m.get("shortName") or s))
    mappa = cik_di(nomi)
    import segnali
    for s in simboli:
        if not mappa.get(s):
            print(s, "non trovato alla SEC")
            continue
        gg, o, h, l, c = segnali.giornaliere(s, "America/New_York", (16, 5))
        T = tabella(fatti(mappa[s]), gg, c)
        print(s, {n: round(float(x), 3) for n, x in zip(NOMI_BILANCI, T[-1])})
    return 0


if __name__ == "__main__":
    sys.exit(main())
