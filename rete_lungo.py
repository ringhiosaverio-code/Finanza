#!/usr/bin/env python3
"""La rete neurale per il medio e lungo periodo: 1 settimana, 1 mese e 3 mesi, su azioni USA e italiane, ETF azionari e
obbligazionari, oro e crypto.

    python3 rete_lungo.py          # scarica le chiusure giornaliere (10 anni), studia, verifica: rete_lungo.json

Ogni settimana, per ogni titolo, la rete vede numeri che usano solo il passato:
  - del titolo: momento di un anno, un mese, una settimana, un giorno, distanza dalla media di 200 giorni e dal massimo
    di 52 settimane, RSI a 2 giorni, giornata stretta, escursione, volatilità (segnali.py), e la sua categoria;
  - del mondo, cioè perché i mercati salgono o scendono (del giorno prima, già chiuso): S&P 500 nell'ultimo mese e
    rispetto alla sua media di 200 giorni, FTSE MIB, VIX (la paura) e la sua variazione, tasso USA a 10 anni e curva dei
    tassi (10 anni meno 3 mesi), dollaro, petrolio, oro, credito (obbligazioni ad alto rendimento contro quelle sicure),
    euro/dollaro, Fear & Greed delle crypto;
e stima la probabilità che comprare alla chiusura e vendere dopo 7, 30 o 91 giorni chiuda in guadagno dopo i costi.

Verifica onesta, anno per anno: per ogni anno degli ultimi cinque la rete impara solo dagli esiti già chiusi prima
dell'inizio dell'anno, poi sceglie ogni settimana il meglio 10 % dei titoli; si confronta con tutti i titoli e con la
regola semplice del momento (il meglio 10 % per forza dell'ultimo anno). Lo studio dei segnali dice quali dati sono
legati a quello che succede dopo. Solo numpy e la libreria standard. Non è consulenza finanziaria.
"""

import argparse
import datetime
import json
import math
import os
import sys
import time

import numpy as np

import rete
import bilanci
import segnali
import settimana
import simula

ROOT = os.path.dirname(os.path.abspath(__file__))
USCITA = os.path.join(ROOT, "rete_lungo.json")
# le reti per categoria: ETF azionari con l'oro, e obbligazioni; ognuna con il suo file, la sua verifica e il suo conto
SEZIONI = {"etf": {"categorie": ("etf", "oro"), "file": "rete_lungo_etf.json", "quota": 0.25, "scelte": 3},
           "obbligazioni": {"categorie": ("bond",), "file": "rete_lungo_obbligazioni.json", "quota": 0.25, "scelte": 4}}
MIN_ADDESTRAMENTO = 5000                               # campioni minimi per una finestra della verifica (meno per categoria)
ORIZZONTI = (7, 30, 91)                                # giorni di calendario
NOMI_ORIZZONTI = ("1 settimana", "1 mese", "3 mesi")
CATEGORIE = ("usa", "italia", "etf", "bond", "oro", "crypto", "europa")
COSTO = {"usa": 0.001, "italia": 0.002, "etf": 0.001, "bond": 0.001, "oro": 0.001, "crypto": 0.004,
         "europa": 0.003}                              # andata e ritorno (Europa: le tasse sulle transazioni di Francia e Regno Unito)
UNIVERSO_ESTESO = True                                 # più esempi: Nasdaq 100, grandi azioni europee, ETF di settore e di fattore
STORIA = 260                                           # righe di storia prima del primo campione
QUOTA = 0.10                                           # ogni settimana, il meglio 10 % dei titoli
ANNI_VERIFICA = 5

# i mercati che muovono gli altri, dalle chiusure giornaliere (Yahoo): nome, simbolo, fuso, chiusura
MONDO = [("sp500", "^GSPC", "America/New_York", (16, 0)), ("vix", "^VIX", "America/New_York", (16, 15)),
         ("tnx", "^TNX", "America/New_York", (16, 0)), ("irx", "^IRX", "America/New_York", (16, 0)),
         ("dollaro", "DX-Y.NYB", "America/New_York", (17, 0)), ("petrolio", "CL=F", "America/New_York", (17, 0)),
         ("oro", "GC=F", "America/New_York", (17, 0)), ("hyg", "HYG", "America/New_York", (16, 0)),
         ("lqd", "LQD", "America/New_York", (16, 0)), ("ftsemib", "FTSEMIB.MI", "Europe/Rome", (17, 35)),
         ("eurusd", "EURUSD=X", "Europe/London", (23, 0))]
NOMI_MONDO = ["sp500_mese", "sp500_media200", "ftsemib_mese", "vix_livello", "vix_mese", "tassi_mese", "curva_tassi",
              "dollaro_mese", "petrolio_mese", "oro_mese", "credito_mese", "eurusd_mese"]
BILANCI = True                                         # i bilanci delle aziende USA dalla SEC (bilanci.py)
NOMI_FEATURE = (["g_" + n for n in segnali.NOMI_GIORNALIERI] + ["trimestre"] + ["cat_" + c for c in CATEGORIE]
                + NOMI_MONDO + list(segnali.NOMI_SENTIMENTO) + ["b_" + n for n in bilanci.NOMI_BILANCI])
FONTI = {
    "b_utili_prezzo": "bilancio: utili sul valore di borsa, il fattore value (Fama e French 1992)", "b_roe": "bilancio: redditività del patrimonio, il fattore quality (Novy-Marx 2013)",
    "b_margine": "bilancio: margine di utile (Asness, Frazzini e Pedersen, Quality minus junk)", "b_crescita_ricavi": "bilancio: crescita dei ricavi in un anno",
    "b_debito": "bilancio: passività sulle attività (Asness, Frazzini e Pedersen)", "b_crescita_dividendi": "bilancio: crescita del dividendo in un anno",
    "b_ha_bilanci": "bilancio: azienda USA con i conti alla SEC",
    "b_sorpresa_utili": "calendario dei conti: sorpresa degli utili del trimestre, che sfuma in due mesi (Bernard e Thomas 1989)",
    "b_bilancio_fresco": "calendario dei conti: quanto è recente l'ultimo bilancio depositato",
    "g_anno": "momento di un anno (Jegadeesh e Titman 1993; Moskowitz, Ooi e Pedersen 2012)", "g_mese": "inversione di un mese (Jegadeesh 1990)",
    "g_settimana": "inversione di una settimana (Lehmann 1990)", "g_media200": "sopra o sotto la media di 200 giorni (Faber 2007)",
    "g_max52": "vicinanza al massimo di 52 settimane (George e Hwang 2004)", "g_vol_mese": "volatilità bassa (Ang e altri 2006)",
    "trimestre": "momento di tre mesi", "sp500_mese": "S&P 500 nell'ultimo mese", "sp500_media200": "S&P 500 sopra la media di 200 giorni (Faber 2007)",
    "ftsemib_mese": "FTSE MIB nell'ultimo mese", "vix_livello": "VIX, la paura: alto rispetto all'ultimo anno (Whaley 2000)",
    "vix_mese": "VIX nell'ultimo mese", "tassi_mese": "tasso USA a 10 anni nell'ultimo mese", "curva_tassi": "curva dei tassi, 10 anni meno 3 mesi (Estrella e Mishkin 1998)",
    "dollaro_mese": "dollaro nell'ultimo mese", "petrolio_mese": "petrolio nell'ultimo mese (Driesprong, Jacobsen e Maat 2008)",
    "oro_mese": "oro nell'ultimo mese", "credito_mese": "credito: alto rendimento contro sicuri (Gilchrist e Zakrajšek 2012)",
    "eurusd_mese": "euro/dollaro nell'ultimo mese", "paura_avidita": "Fear & Greed delle crypto", "paura_avidita_7g": "Fear & Greed, variazione in una settimana",
}


# ---------------------------------------------------------------- dati

def titoli():
    out = []
    for m in ("usa", "italia", "etf", "bond", "oro"):
        M = settimana.MERCATI[m]
        out += [(s, m, M["fuso"], (M["chiusura"][0], M["chiusura"][1] + 5)) for s in M["universo"]]
    out += [(s, "crypto", "UTC", (23, 59)) for s in simula.CRYPTO]
    if UNIVERSO_ESTESO:
        import universo_esteso as U
        gia = {x[0] for x in out}
        out += [(s, "usa", "America/New_York", (16, 5)) for s in U.NASDAQ if s not in gia]
        out += [(s, "europa", "Europe/Rome", (17, 35)) for s in U.EUROPA if s not in gia]
        out += [(s, "etf", "Europe/Rome", (17, 35)) for s in U.ETF if s not in gia]
    return out


def tabella_mondo(log=print):
    """I segnali del mondo per ogni giorno di calendario dal primo dato: ([giorni ISO], array (giorni, NOMI_MONDO))."""
    serie = {}
    for nome, sym, tz, ch in MONDO:
        gg, o, h, l, c = segnali.giornaliere(sym, tz, ch)
        if len(gg) < 300:
            log("[rete_lungo] %s non disponibile" % sym)
        serie[nome] = (gg, np.asarray(c, dtype=np.float64))
    tutti = sorted({g for gg, _ in serie.values() for g in gg})
    if not tutti:
        return [], np.zeros((0, len(NOMI_MONDO)), np.float32)
    d0, d1 = datetime.date.fromisoformat(tutti[0]), datetime.date.fromisoformat(tutti[-1])
    giorni = [(d0 + datetime.timedelta(days=k)).isoformat() for k in range((d1 - d0).days + 1)]

    def su_giorni(nome, f):
        """f(c) -> valori per ogni chiusura del mercato; portati su ogni giorno di calendario (l'ultimo valore noto)."""
        gg, c = serie[nome]
        if len(gg) < 300:
            return np.zeros(len(giorni), np.float32)
        v = np.nan_to_num(np.asarray(f(c), dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)
        return segnali.per_giorno(gg, v[:, None].astype(np.float32), giorni, ritardo=0)[:, 0]

    def rend(c, n=21):
        lc = np.log(np.maximum(c, 1e-9))
        r = np.zeros(len(c))
        r[n:] = lc[n:] - lc[:-n]
        return r

    def z_mese(c):                                    # rendimento di un mese diviso per la volatilità di un anno
        r1 = np.r_[0.0, np.diff(np.log(np.maximum(c, 1e-9)))]
        vol = np.array([r1[max(0, i - 251):i + 1].std() if i > 20 else 0.01 for i in range(len(c))])
        return np.clip(rend(c) / np.maximum(vol * math.sqrt(21), 1e-6), -6, 6)

    def media200(c):
        m = np.array([c[max(0, i - 199):i + 1].mean() for i in range(len(c))])
        return np.clip(np.log(c / m) * 5, -5, 5)

    def livello(c):                                    # log del livello contro la mediana dell'ultimo anno
        return np.clip(np.array([math.log(max(c[i], 1e-9) / max(np.median(c[max(0, i - 251):i + 1]), 1e-9)) for i in range(len(c))]) * 2, -5, 5)

    def diff_mese(c):                                  # variazione in punti (tassi: 0,1 = 10 punti base)
        d = np.zeros(len(c))
        d[21:] = c[21:] - c[:-21]
        return np.clip(d, -5, 5)

    cols = [su_giorni("sp500", z_mese), su_giorni("sp500", media200), su_giorni("ftsemib", z_mese),
            su_giorni("vix", livello), su_giorni("vix", lambda c: np.clip(rend(c) * 3, -5, 5)),
            su_giorni("tnx", diff_mese), np.zeros(len(giorni), np.float32),
            su_giorni("dollaro", z_mese), su_giorni("petrolio", z_mese), su_giorni("oro", z_mese),
            np.zeros(len(giorni), np.float32), su_giorni("eurusd", z_mese)]
    tnx = su_giorni("tnx", lambda c: c)
    irx = su_giorni("irx", lambda c: c)
    cols[6] = np.where((tnx != 0) & (irx != 0), np.clip(tnx - irx, -5, 5), 0.0)
    gh, ch = serie["hyg"]
    gl, cl = serie["lqd"]
    if len(gh) > 300 and len(gl) > 300:
        comuni = sorted(set(gh) & set(gl))
        ih, il = {g: k for k, g in enumerate(gh)}, {g: k for k, g in enumerate(gl)}
        rap = np.array([ch[ih[g]] / cl[il[g]] for g in comuni])
        cols[10] = segnali.per_giorno(comuni, z_mese(rap)[:, None].astype(np.float32), giorni, ritardo=0)[:, 0]
    return giorni, np.stack(cols, axis=1).astype(np.float32)


class Campioni:
    """Un campione per titolo e settimana: caratteristiche (solo passato), rendimenti netti a 7, 30 e 91 giorni."""

    def __init__(self, log=print, categorie=None):
        gm, TM = tabella_mondo(log)
        fg = segnali.fear_greed(log=log)
        X, R, OK, giorni, sym, cat = [], [], [], [], [], []
        self.ultimi = []                                                       # per titolo: la riga di oggi
        for s, m, tz, ch in titoli():
            if categorie and m not in categorie:
                continue
            gg, o, h, l, c = segnali.giornaliere(s, tz, ch)
            n = len(gg)
            if n < STORIA + 30:
                continue
            o, h, l, c = (np.asarray(x, dtype=np.float64) for x in (o, h, l, c))
            cr = m == "crypto"
            T = segnali.tabella_giornaliera(o, h, l, c, *((365, 30, 7) if cr else (252, 21, 5)))
            lc = np.log(c)
            r1 = np.r_[0.0, np.diff(lc)]
            q = 91 if cr else 63
            vol = np.array([r1[max(1, i - 20):i + 1].std() if i > 5 else 0.02 for i in range(n)])
            tri = np.zeros(n)
            tri[q:] = (lc[q:] - lc[:-q]) / np.maximum(vol[q:] * math.sqrt(q), 1e-6)
            passo = 7 if cr else 5
            righe = list(range(STORIA, n, passo))
            if righe[-1] != n - 1:
                righe.append(n - 1)                                            # l'ultima chiusura: per le scelte di oggi
            date = [datetime.date.fromisoformat(g) for g in gg]
            ordin = np.array([d.toordinal() for d in date])
            mondo = segnali.per_giorno(gm, TM, [gg[i] for i in righe], ritardo=1) if len(gm) else np.zeros((len(righe), len(NOMI_MONDO)), np.float32)
            sent = segnali.sentimento_per_giorno([gg[i] for i in righe], fg)
            onehot = np.zeros(len(CATEGORIE), np.float32)
            onehot[CATEGORIE.index(m)] = 1.0
            B = bilanci.per_titolo(s, gg, c) if (BILANCI and m == "usa") else np.zeros((n, len(bilanci.NOMI_BILANCI)), np.float32)
            for k, i in enumerate(righe):
                x = np.concatenate([T[i], [np.clip(tri[i], -8, 8)], onehot, mondo[k], sent[k], B[i]]).astype(np.float32)
                rr, ok = np.zeros(len(ORIZZONTI)), np.zeros(len(ORIZZONTI), bool)
                for j, H in enumerate(ORIZZONTI):
                    e = int(np.searchsorted(ordin, ordin[i] + H))
                    if e < n:
                        rr[j], ok[j] = c[e] / c[i] * (1.0 - COSTO[m]) - 1.0, True
                if i == n - 1:
                    self.ultimi.append((s, m, gg[i], float(c[i]), x))
                if i < n - 1 or ok.any():
                    X.append(x), R.append(rr), OK.append(ok), giorni.append(ordin[i]), sym.append(s), cat.append(m)
        self.X = np.nan_to_num(np.array(X, np.float32), nan=0.0, posinf=0.0, neginf=0.0)
        self.R, self.OK = np.array(R, np.float32), np.array(OK, bool)
        self.g, self.sym, self.cat = np.array(giorni), np.array(sym), np.array(cat)
        self.settimana = self.g // 7                                           # la settimana del campione
        log("[rete_lungo] %d campioni, %d titoli, dal %s al %s" % (len(self.X), len(set(sym)),
            datetime.date.fromordinal(int(self.g.min())), datetime.date.fromordinal(int(self.g.max()))))


# ---------------------------------------------------------------- la rete

# cosa impara la rete. "assoluto": chiudere in guadagno dopo i costi. "relativo": fare meglio della metà degli altri titoli
# nella stessa settimana (Gu, Kelly e Xiu, "Empirical Asset Pricing via Machine Learning", Review of Financial Studies
# 2020: le reti sanno ordinare i titoli tra loro molto meglio che indovinare dove va tutto il mercato)
OBIETTIVO = "assoluto"                                  # il confronto (rete_lungo.py --confronta) non ha trovato di meglio
INSIEME = 5                                            # 5 reti nella media: con una sola il risultato dipende molto dal caso (+0,45 % o +0,66 % a settimana con due partenze diverse)


def bersagli(C, obiettivo=None):
    """1 dove il campione ha fatto quello che la rete deve imparare, 0 se no (per ogni orizzonte)."""
    obiettivo = obiettivo or OBIETTIVO
    if obiettivo == "assoluto":
        return (C.R > 0).astype(np.float32)
    chiave = ("_bers", obiettivo)
    if getattr(C, "_bers", None) is not None and C._bers[0] == chiave:
        return C._bers[1]
    Y = np.zeros(C.R.shape, np.float32)
    for j in range(C.R.shape[1]):
        for w in np.unique(C.settimana):
            k = np.flatnonzero((C.settimana == w) & C.OK[:, j])
            if len(k) >= 4:
                Y[k, j] = (C.R[k, j] > np.median(C.R[k, j])).astype(np.float32)
    C._bers = (chiave, Y)
    return Y


def addestra(C, tr, va, epoche=20, seed=0, log=None, insieme=None, obiettivo=None):
    """Una rete [n, 32, 16, 3] (o la media di `insieme` reti con semi diversi): la probabilità, a 7, 30 e 91 giorni, di
    chiudere in guadagno ("assoluto") o di fare meglio degli altri titoli ("relativo"). Per ogni rete si tiene l'epoca
    che stima meglio il periodo di scelta (mai visto)."""
    insieme = insieme or INSIEME
    media, dev = C.X[tr].mean(axis=0), C.X[tr].std(axis=0) + 1e-6
    norm = lambda X: np.clip((X - media) / dev, -6, 6).astype(np.float32)
    Y = bersagli(C, obiettivo)
    Xt, Yt, Mt = norm(C.X[tr]), Y[tr], C.OK[tr].astype(np.float32)
    Xv, Yv, Mv = norm(C.X[va]), Y[va], C.OK[va].astype(np.float32)
    base = np.clip((Yt * Mt).sum(axis=0) / np.maximum(Mt.sum(axis=0), 1), 1e-3, 1 - 1e-3)
    membri, epoche_scelte = [], []
    for k in range(insieme):
        r = rete.Rete([C.X.shape[1], 32, 16, len(ORIZZONTI)], seed + 101 * k)
        r.b[-1][:] = np.log(base / (1 - base))
        rng = np.random.default_rng(seed + 101 * k)
        migliore = None
        for e in range(epoche):
            rete.addestra_probabilita(r, Xt, Yt, Mt, 1, lr=1e-3 * 0.9 ** e, wd=3e-4, batch=256, rng=rng)
            err = float(rete._entropia(rete.sigmoide(r.avanti(Xv)), Yv, Mv).sum() / max(float(Mv.sum()), 1.0)) if len(Xv) else 0.0
            if log:
                log("   rete %d, epoca %2d: errore sul periodo di scelta %.4f" % (k + 1, e + 1, err))
            if migliore is None or err < migliore[0]:
                migliore = (err, e + 1, r.copia())
        membri.append(migliore[2])
        epoche_scelte.append(migliore[1])
    modello = membri[0] if len(membri) == 1 else rete.Insieme(membri)
    return {"rete": modello, "media": media, "dev": dev, "epoca": int(np.median(epoche_scelte)), "norm": norm}


def stima(m, X):
    return rete.sigmoide(m["rete"].avanti(m["norm"](X)))


def auc(p, y):
    """Area sotto la curva ROC: 0,5 = come tirare a sorte."""
    if y.min() == y.max():
        return None
    o = np.argsort(p)
    rk = np.empty(len(p))
    rk[o] = np.arange(1, len(p) + 1)
    n1 = y.sum()
    return float((rk[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * (len(y) - n1)))


def scelte_settimanali(C, idx, punteggio, j, quota=QUOTA):
    """Ogni settimana il meglio `quota` dei titoli per punteggio: (rendimenti delle scelte, di tutti, scarto per settimana)."""
    scelte, tutti, scarti, prese = [], [], [], []
    ok = idx[C.OK[idx, j]]
    for w in np.unique(C.settimana[ok]):
        k = ok[C.settimana[ok] == w]
        if len(k) < 10:
            continue
        n = max(1, int(round(len(k) * quota)))
        top = k[np.argsort(-punteggio[k])[:n]]
        scelte += C.R[top, j].tolist()
        prese += top.tolist()
        tutti += C.R[k, j].tolist()
        scarti.append(float(C.R[top, j].mean() - C.R[k, j].mean()))
    scelte_settimanali.prese = np.array(prese, dtype=np.int64)                 # quali campioni ha scelto (l'ultima chiamata)
    return np.array(scelte), np.array(tutti), np.array(scarti)


def riassunto(r):
    return {"n": int(len(r)), "media": float(r.mean()) if len(r) else 0.0, "vinte": float((r > 0).mean()) if len(r) else 0.0}


def verifica(C, log=print, quota=QUOTA, minimo=None, insieme=None, obiettivo=None):
    """Anno per anno: si impara dagli esiti chiusi prima dell'anno, si sceglie durante l'anno."""
    ultimo = datetime.date.fromordinal(int(C.g.max())).year
    P = np.full((len(C.X), len(ORIZZONTI)), np.nan, np.float32)
    anni = []
    for anno in range(ultimo - ANNI_VERIFICA, ultimo + 1):
        a0 = datetime.date(anno, 1, 1).toordinal()
        a1 = datetime.date(anno + 1, 1, 1).toordinal()
        fine_esito = C.g + max(ORIZZONTI)
        tr = np.flatnonzero(fine_esito < a0 - 365)                          # addestramento: esiti chiusi un anno prima
        va = np.flatnonzero((C.g >= a0 - 365) & (fine_esito < a0))          # scelta dell'epoca: l'anno prima, esiti chiusi
        te = np.flatnonzero((C.g >= a0) & (C.g < a1))
        if len(tr) < (minimo or MIN_ADDESTRAMENTO) or len(te) == 0:
            continue
        log("[rete_lungo] verifica %d: impara da %d campioni, sceglie su %d, prova su %d" % (anno, len(tr), len(va), len(te)))
        m = addestra(C, tr, va, insieme=insieme, obiettivo=obiettivo)
        P[te] = stima(m, C.X[te])
        anni.append(anno)
    te = np.flatnonzero(~np.isnan(P[:, 0]))
    out = {"anni": anni, "orizzonti": {}}
    F = NOMI_FEATURE.index
    for j, H in enumerate(ORIZZONTI):
        k = te[C.OK[te, j]]
        y = (C.R[k, j] > 0).astype(int)
        p = P[k, j]
        cal = []
        for a, b in zip(np.quantile(p, np.linspace(0, 1, 6))[:-1], np.quantile(p, np.linspace(0, 1, 6))[1:]):
            s = k[(p >= a) & (p <= b)]
            if len(s):
                cal.append({"stimata": float(P[s, j].mean()), "vera": float((C.R[s, j] > 0).mean()), "n": int(len(s))})
        sc, tu, scarti = scelte_settimanali(C, te, P[:, j], j, quota)
        prese = scelte_settimanali.prese
        composizione = {c: float((C.cat[prese] == c).mean()) for c in CATEGORIE} if len(prese) else {}
        mo, _, scarti_mo = scelte_settimanali(C, te, C.X[:, F("g_anno")], j, quota)
        sovrapp = max(H / 7.0, 1.0)                                         # le settimane si sovrappongono: t più prudente
        t = float(scarti.mean() / (scarti.std(ddof=1) / math.sqrt(len(scarti) / sovrapp))) if len(scarti) > 3 else 0.0
        per_anno = []
        for anno in anni:
            ka = te[(C.g[te] >= datetime.date(anno, 1, 1).toordinal()) & (C.g[te] < datetime.date(anno + 1, 1, 1).toordinal())]
            s1, t1, _ = scelte_settimanali(C, ka, P[:, j], j, quota)
            per_anno.append({"anno": anno, "scelte": riassunto(s1), "tutti": riassunto(t1)})
        out["orizzonti"][str(H)] = {"auc": auc(p, y), "calibrazione": cal, "scelte": riassunto(sc), "tutti": riassunto(tu),
                                    "momento": riassunto(mo), "scarto": float(scarti.mean()) if len(scarti) else 0.0, "t": t,
                                    "per_anno": per_anno, "composizione": composizione,
                                    "tutti_composizione": {c: float((C.cat[k] == c).mean()) for c in CATEGORIE},
                                    "per_categoria": {c: riassunto(C.R[k[(C.cat[k] == c)], j]) for c in CATEGORIE}}
        o = out["orizzonti"][str(H)]
        # la rete generale usata per scegliere solo dentro una sezione (ETF con l'oro, obbligazioni): il meglio 25 % di ogni settimana
        o["sezioni"] = {}
        for nome_s, S in SEZIONI.items():
            ks = te[np.isin(C.cat[te], S["categorie"])]
            n_sez = len(set(C.sym[np.isin(C.cat, S["categorie"])].tolist()))
            if len(ks):                                                     # come il robot: le migliori `scelte` della settimana
                s1, t1, sc1 = scelte_settimanali(C, ks, P[:, j], j, S["scelte"] / max(n_sez, 1))
                o["sezioni"][nome_s] = {"scelte": riassunto(s1), "tutti": riassunto(t1),
                                        "t": float(sc1.mean() / (sc1.std(ddof=1) / math.sqrt(len(sc1) / max(H / 7.0, 1.0)))) if len(sc1) > 3 and sc1.std() > 0 else 0.0}
        # il confronto giusto: titoli a caso con la stessa miscela di categorie delle scelte (le crypto salgono di più)
        o["stesso_mix"] = float(sum(composizione.get(c, 0.0) * o["per_categoria"][c]["media"] for c in CATEGORIE))
        log("[rete_lungo] %s: AUC %.3f · scelte %d, media %+.2f %% (in guadagno %.0f %%) · tutti %+.2f %% · momento %+.2f %% · scarto t %.1f" % (
            NOMI_ORIZZONTI[j], o["auc"] or 0, o["scelte"]["n"], 100 * o["scelte"]["media"], 100 * o["scelte"]["vinte"],
            100 * o["tutti"]["media"], 100 * o["momento"]["media"], t))
    return out


def studio_segnali(C):
    """Quanto ogni dato è legato al rendimento dopo (correlazione per ranghi), su tutto, sugli ultimi 3 anni e sull'ultimo
    anno, per ogni orizzonte. Per i dati del titolo si guarda anche dentro la settimana (chi sale di più tra i titoli)."""
    fine = C.g.max()
    periodi = [("tutte", C.g.min()), ("3 anni", fine - 3 * 365 - 91), ("anno", fine - 365 - 91)]
    rango = lambda v: np.argsort(np.argsort(v)).astype(np.float64)
    out = []
    for f, nome in enumerate(NOMI_FEATURE):
        if nome.startswith("cat_"):
            continue
        ic = {}
        for per, da in periodi:
            ic[per] = []
            for j in range(len(ORIZZONTI)):
                k = np.flatnonzero((C.g >= da) & C.OK[:, j])
                x, y = C.X[k, f], C.R[k, j]
                ic[per].append(float(np.corrcoef(rango(x), rango(y))[0, 1]) if len(k) > 100 and x.std() > 0 else 0.0)
        out.append({"nome": nome, "fonte": FONTI.get(nome, ""), "ic": ic, "mondo": nome in NOMI_MONDO or nome in segnali.NOMI_SENTIMENTO})
    out.sort(key=lambda s: -abs(s["ic"]["tutte"][1]))
    return out


def oggi(C, m):
    """Le scelte di oggi: per ogni orizzonte i titoli con la probabilità stimata più alta."""
    if not C.ultimi:
        return {}
    X = np.array([u[4] for u in C.ultimi], np.float32)
    P = stima(m, X)
    out = {}
    for j, H in enumerate(ORIZZONTI):
        o = np.argsort(-P[:, j])
        out[str(H)] = [{"sym": C.ultimi[i][0], "categoria": C.ultimi[i][1], "data": C.ultimi[i][2], "prezzo": round(C.ultimi[i][3], 6),
                        "probabilita": round(float(P[i, j]), 4)} for i in o]
        out[str(H) + "_media"] = float(P[:, j].mean())
    return out


def pesi_con_isteresi(o, scelte, giorno, categorie, precedenti, margine, orizzonte="7"):
    """Come pesi_robot, ma si tengono gli ETF della settimana prima finché la loro probabilità non scende sotto quella
    dell'ultimo dei migliori meno `margine` (portafoglio.studio_costi_tasse: con le tasse italiane conviene cambiare meno)."""
    lista = [x for x in (o.get(orizzonte) or []) if not categorie or x["categoria"] in categorie]
    if not lista:
        return {"giorno": giorno, "pesi": {}, "margine": margine}
    prob = {x["sym"]: x["probabilita"] for x in lista}
    soglia = lista[min(scelte, len(lista)) - 1]["probabilita"] - margine
    tenuti = [s for s in (precedenti or []) if s in prob and prob[s] >= soglia][:scelte]
    nuovi = [x["sym"] for x in lista if x["sym"] not in tenuti][:scelte - len(tenuti)]
    d = datetime.date.fromisoformat(giorno)
    lunedi = (d - datetime.timedelta(days=d.weekday())).isoformat()
    tutti = tenuti + nuovi
    return {"giorno": lunedi, "pesi": {s: round(1.0 / len(tutti), 4) for s in tutti}, "tenuti": tenuti, "margine": margine}


def _margine_e_precedenti():
    """Il margine imparato da portafoglio.py e le scelte della settimana prima (dal diario della rete dal vivo)."""
    margine, precedenti = 0.02, []
    try:
        with open(os.path.join(ROOT, "portafoglio.json"), encoding="utf-8") as fh:
            margine = float(json.load(fh).get("costi_tasse", {}).get("margine_oggi", margine))
    except (OSError, ValueError):
        pass
    try:
        with open(DIARIO, encoding="utf-8") as fh:
            voci = json.load(fh).get("voci") or []
        if voci:
            precedenti = voci[-1].get("scelte") or []
    except (OSError, ValueError):
        pass
    return margine, precedenti


def pesi_robot(o, scelte, giorno, categorie=None, orizzonte="7"):
    """I pesi per un conto del robot: le `scelte` (delle `categorie`) con la probabilità più alta di chiudere in guadagno
    all'orizzonte (di serie una settimana, dove la verifica regge), in parti uguali, rifatti ogni settimana (dal lunedì)."""
    lista = [x for x in (o.get(orizzonte) or []) if not categorie or x["categoria"] in categorie]
    d = datetime.date.fromisoformat(giorno)
    lunedi = (d - datetime.timedelta(days=d.weekday())).isoformat()
    return {"giorno": lunedi, "pesi": {x["sym"]: round(1.0 / scelte, 4) for x in lista[:scelte]}}


DIARIO = os.path.join(ROOT, "diario_rete.json")


PESO_RETE = 0.20                                       # il peso della rete nel piano finché il diario non dice altro


def controllo_peso(voci, ultime=26, minimo=8):
    """Il controllo dal vivo, con una regola fissata prima di vedere i risultati: sulle ultime settimane chiuse del diario
    (al più 26) lo scarto medio tra le scelte della rete e la media degli ETF, e il suo t. Meno di 8 settimane: peso di
    partenza. t <= -2: fuori dal piano; <= -1: 10 %; >= 1: 25 %; >= 2: 30 %; altrimenti 20 %. Il resto va su SWDA."""
    fatte = [v for v in voci if v.get("esito") is not None and v.get("tutti") is not None][-ultime:]
    n = len(fatte)
    if n < minimo:
        return {"n": n, "peso": PESO_RETE, "t": None, "scarto": None, "stato": "in prova",
                "messaggio": "Il diario ha %d settimane chiuse: ne servono almeno %d per giudicare la rete dal vivo." % (n, minimo)}
    d = np.array([v["esito"] - v["tutti"] for v in fatte])
    sd = d.std(ddof=1)
    t = float(d.mean() / (sd / math.sqrt(n))) if sd > 0 else 0.0
    if t <= -2:
        peso, stato = 0.0, "tolta dal piano"
    elif t <= -1:
        peso, stato = 0.10, "ridotta"
    elif t >= 2:
        peso, stato = 0.30, "aumentata"
    elif t >= 1:
        peso, stato = 0.25, "aumentata un po'"
    else:
        peso, stato = PESO_RETE, "normale"
    return {"n": n, "peso": peso, "t": t, "scarto": float(d.mean()), "stato": stato,
            "messaggio": "Nelle ultime %d settimane le scelte della rete hanno fatto in media %+.2f %% a settimana rispetto alla media degli ETF (t %.1f): peso nel piano %d %%." % (
                n, 100 * d.mean(), t, round(100 * peso))}


def aggiorna_diario(scelta, C, percorso=None):
    """Il diario della rete dal vivo: le scelte sugli ETF di ogni lunedì con i prezzi di entrata, e una settimana dopo
    il risultato vero (media delle scelte) contro la media di tutti gli ETF e dell'oro. Solo dati arrivati dopo la scelta."""
    percorso = percorso or DIARIO
    try:
        with open(percorso, encoding="utf-8") as fh:
            G = json.load(fh)
    except (OSError, ValueError):
        G = {"voci": []}
    prezzi = {u[0]: u[3] for u in C.ultimi if u[1] in ("etf", "oro")}
    oggi = datetime.date.fromisoformat(max(u[2] for u in C.ultimi if u[1] in ("etf", "oro"))) if C.ultimi else datetime.date.today()
    ultima = max((datetime.date.fromisoformat(v["giorno"]) for v in G["voci"]), default=None)
    if ultima is None or (oggi - ultima).days >= 7:                             # una voce a settimana, con i prezzi del giorno della scelta
        G["voci"].append({"giorno": oggi.isoformat(), "scelte": list(scelta["pesi"]), "prezzi": prezzi, "esito": None, "tutti": None})
    for v in G["voci"]:
        if v["esito"] is not None or (oggi - datetime.date.fromisoformat(v["giorno"])).days < 7:
            continue
        fine = (datetime.date.fromisoformat(v["giorno"]) + datetime.timedelta(days=7)).isoformat()
        r = {}
        for s, p0 in v["prezzi"].items():
            if not p0:
                continue
            gg, o, h, l, c = segnali.giornaliere(s, "Europe/Rome", (17, 35))
            k = next((i for i, g in enumerate(gg) if g >= fine), None)
            if k is not None:
                r[s] = float(c[k]) / p0 * (1 - COSTO["etf"]) - 1
        sc = [r[s] for s in v["scelte"] if s in r]
        if sc and len(r) >= 5:
            v["esito"], v["tutti"] = float(np.mean(sc)), float(np.mean(list(r.values())))
    G["voci"] = G["voci"][-104:]
    G["controllo"] = controllo_peso(G["voci"])                            # il peso della rete nel piano, deciso dal vivo
    with open(percorso, "w", encoding="utf-8") as fh:
        json.dump(G, fh, separators=(",", ":"))
    return G


def studia(log=print, salva=True, sezione=None):
    t0 = time.time()
    S = SEZIONI.get(sezione) or {}
    uscita = os.path.join(ROOT, S["file"]) if S else USCITA
    quota = S.get("quota", QUOTA)
    C = Campioni(log, S.get("categorie"))
    ris = {"creato": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "orizzonti": list(ORIZZONTI),
           "nomi_orizzonti": list(NOMI_ORIZZONTI), "caratteristiche": list(NOMI_FEATURE), "quota": quota, "costi": COSTO,
           "sezione": sezione,
           "dati": {"campioni": int(len(C.X)), "titoli": int(len(set(C.sym.tolist()))),
                    "da": datetime.date.fromordinal(int(C.g.min())).isoformat(), "a": datetime.date.fromordinal(int(C.g.max())).isoformat(),
                    "per_categoria": {c: int(len(set(C.sym[C.cat == c].tolist()))) for c in CATEGORIE}}}
    log("[rete_lungo] quali dati sono legati a quello che succede dopo")
    ris["segnali"] = studio_segnali(C)
    ris["verifica"] = verifica(C, log, quota, 800 if S else None)
    fine_esito = C.g + max(ORIZZONTI)
    tr = np.flatnonzero(fine_esito < C.g.max() - 365)
    va = np.flatnonzero((C.g >= C.g.max() - 365 - max(ORIZZONTI)) & C.OK[:, 0])
    m = addestra(C, tr if len(tr) > (800 if S else MIN_ADDESTRAMENTO) else np.flatnonzero(C.OK[:, 0]), va)
    ris["oggi"] = oggi(C, m)
    ris["prezzi"] = {u[0]: round(float(u[3]), 6) for u in C.ultimi}          # gli ultimi prezzi: il robot li usa per i titoli fuori dall'app
    ris["nomi_categorie"] = {"europa": "Azioni europee"}
    if S:
        ris["robot"] = pesi_robot(ris["oggi"], S["scelte"], ris["dati"]["a"])
    else:                                                                       # la rete generale sceglie anche dentro ETF e obbligazioni
        ris["robot_sezioni"] = {k: pesi_robot(ris["oggi"], v["scelte"], ris["dati"]["a"], v["categorie"]) for k, v in SEZIONI.items()}
        margine, precedenti = _margine_e_precedenti()                     # gli ETF: si cambia solo quando conviene (costi e tasse)
        ris["robot_sezioni"]["etf"] = pesi_con_isteresi(ris["oggi"], SEZIONI["etf"]["scelte"], ris["dati"]["a"], SEZIONI["etf"]["categorie"],
                                                        precedenti, margine)
        if salva:
            aggiorna_diario(ris["robot_sezioni"]["etf"], C)
    ris["durata_minuti"] = round((time.time() - t0) / 60, 1)
    if salva:
        with open(uscita, "w", encoding="utf-8") as fh:
            json.dump(rete._pulisci(ris), fh, separators=(",", ":"))
        log("[rete_lungo] scritto %s (%.1f minuti)" % (os.path.basename(uscita), ris["durata_minuti"]))
    return ris


def verifica_epurata(C, blocchi=10, embargo=14, log=print, seme=0):
    """La cross-validation epurata con embargo (López de Prado, "Advances in Financial Machine Learning", cap. 7): il
    tempo si divide in `blocchi` pezzi; ogni pezzo fa da prova per una rete addestrata su tutti gli altri, togliendo i
    campioni il cui esito (fino a 91 giorni) si sovrappone al pezzo di prova e quelli dei `embargo` giorni dopo. Così
    ogni settimana dal primo all'ultimo anno ha una stima fatta senza conoscerla: più settimane, un t più affidabile.
    Ritorna le misure per orizzonte (tutti i titoli, ETF con le 3 scelte) e per blocco."""
    ordine = np.argsort(C.g, kind="stable")
    pezzi = np.array_split(ordine, blocchi)
    P = np.full((len(C.X), len(ORIZZONTI)), np.nan, np.float32)
    rng = np.random.default_rng(seme)
    fine_esito = C.g + max(ORIZZONTI)
    for b, te in enumerate(pezzi):
        g0, g1 = C.g[te].min(), C.g[te].max()
        fuori = (fine_esito >= g0) & (C.g <= g1 + embargo)                # epurati: l'esito tocca la prova, o sono subito dopo
        idx = np.flatnonzero(~fuori)
        va = rng.choice(idx, size=max(1, len(idx) // 7), replace=False)  # per scegliere l'epoca: un settimo, a caso
        tr = np.setdiff1d(idx, va)
        log("[rete_lungo] epurata: blocco %d/%d (%s … %s), impara da %d campioni" % (
            b + 1, blocchi, datetime.date.fromordinal(int(g0)), datetime.date.fromordinal(int(g1)), len(tr)))
        P[te] = stima(addestra(C, tr, va), C.X[te])
    te = np.flatnonzero(~np.isnan(P[:, 0]))
    out = {"blocchi": blocchi, "embargo": embargo, "orizzonti": {}}
    n_etf = len(set(C.sym[np.isin(C.cat, ("etf", "oro"))].tolist()))
    for j, H in enumerate(ORIZZONTI):
        sovr = max(H / 7.0, 1.0)
        def misura(idx, quota):
            sc, tu, scarti = scelte_settimanali(C, idx, P[:, j], j, quota)
            t = float(scarti.mean() / (scarti.std(ddof=1) / math.sqrt(len(scarti) / sovr))) if len(scarti) > 3 else 0.0
            return {"scelte": riassunto(sc), "tutti": riassunto(tu), "t": t, "settimane": int(len(scarti))}
        o = {"tutti": misura(te, QUOTA), "etf": misura(te[np.isin(C.cat[te], ("etf", "oro"))], 3.0 / max(n_etf, 1))}
        o["per_blocco"] = []
        for p in pezzi:                                                  # quanti blocchi su 10 la rete batte la media
            sc, tu, _ = scelte_settimanali(C, p, P[:, j], j, QUOTA)
            if len(sc):
                o["per_blocco"].append({"da": datetime.date.fromordinal(int(C.g[p].min())).isoformat(), "scelte": float(sc.mean()), "tutti": float(tu.mean())})
        out["orizzonti"][str(H)] = o
        log("[rete_lungo] epurata %s: tutti %+.2f %% contro %+.2f %% (t %.1f, %d settimane) · ETF %+.2f %% contro %+.2f %% (t %.1f) · meglio in %d blocchi su %d" % (
            NOMI_ORIZZONTI[j], 100 * o["tutti"]["scelte"]["media"], 100 * o["tutti"]["tutti"]["media"], o["tutti"]["t"], o["tutti"]["settimane"],
            100 * o["etf"]["scelte"]["media"], 100 * o["etf"]["tutti"]["media"], o["etf"]["t"],
            sum(1 for x in o["per_blocco"] if x["scelte"] > x["tutti"]), len(o["per_blocco"])))
    return out


def confronta(log=print, uscita=None):
    """La stessa verifica anno per anno con quattro modi di addestrare: cosa impara (guadagno o meglio degli altri) e
    quante reti nella media. Scrive il confronto in rete_lungo_confronto.json."""
    C = Campioni(lambda m: None)
    out = {}
    for obiettivo in ("assoluto", "relativo"):
        for n in (1, 5):
            log("[rete_lungo] confronto: obiettivo %s, %d reti" % (obiettivo, n))
            v = verifica(C, lambda m: None, insieme=n, obiettivo=obiettivo)
            out["%s_%d" % (obiettivo, n)] = {h: {"scelte": x["scelte"], "tutti": x["tutti"], "t": x["t"], "auc": x["auc"],
                                                  "etf": x["sezioni"].get("etf")} for h, x in v["orizzonti"].items()}
            for h, x in v["orizzonti"].items():
                log("   %3s giorni: scelte %+.2f %% contro %+.2f %% di tutti (t %.1f, AUC %.3f) · ETF %+.2f %% contro %+.2f %% (t %.1f)" % (
                    h, 100 * x["scelte"]["media"], 100 * x["tutti"]["media"], x["t"], x["auc"] or 0,
                    100 * x["sezioni"]["etf"]["scelte"]["media"], 100 * x["sezioni"]["etf"]["tutti"]["media"], x["sezioni"]["etf"]["t"]))
    with open(uscita or os.path.join(ROOT, "rete_lungo_confronto.json"), "w", encoding="utf-8") as fh:
        json.dump(rete._pulisci(out), fh, separators=(",", ":"))
    return out


def per_app(sezione=None):
    try:
        with open(os.path.join(ROOT, SEZIONI[sezione]["file"]) if sezione else USCITA, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sezione", choices=sorted(SEZIONI), help="solo una categoria: etf (con l'oro) o obbligazioni")
    ap.add_argument("--tutte", action="store_true", help="la rete generale e quelle di ETF e obbligazioni")
    ap.add_argument("--confronta", action="store_true", help="confronta obiettivo assoluto/relativo e 1/5 reti sulla stessa verifica")
    ap.add_argument("--epurata-calendario", action="store_true", help="la cross-validation epurata con e senza il calendario dei conti (sorpresa degli utili)")
    ap.add_argument("--epurata", action="store_true", help="la cross-validation epurata (10 blocchi, embargo 14 giorni), con e senza bilanci: rete_lungo_epurata.json")
    a = ap.parse_args(argv)
    if a.epurata_calendario:                                # il calendario dei conti aiuta? stessi blocchi, con e senza
        try:
            with open(os.path.join(ROOT, "rete_lungo_epurata.json"), encoding="utf-8") as fh:
                ris = json.load(fh)
        except (OSError, ValueError):
            ris = {}
        for nome, c in (("senza_calendario", False), ("con_calendario", True)):
            bilanci.CALENDARIO = c
            print("[rete_lungo] cross-validation epurata, %s" % nome.replace("_", " "))
            ris[nome] = verifica_epurata(Campioni(lambda m: None))
        ris["creato_calendario"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        with open(os.path.join(ROOT, "rete_lungo_epurata.json"), "w", encoding="utf-8") as fh:
            json.dump(rete._pulisci(ris), fh, separators=(",", ":"))
        return 0
    if a.epurata:
        global BILANCI
        ris = {"creato": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
        for nome, b in (("senza_bilanci", False), ("con_bilanci", True)):
            BILANCI = b
            print("[rete_lungo] cross-validation epurata, %s" % nome.replace("_", " "))
            ris[nome] = verifica_epurata(Campioni(lambda m: None))
        with open(os.path.join(ROOT, "rete_lungo_epurata.json"), "w", encoding="utf-8") as fh:
            json.dump(rete._pulisci(ris), fh, separators=(",", ":"))
        return 0
    if a.confronta:
        confronta()
        return 0
    if a.tutte:
        for sez in (None, *SEZIONI):
            studia(sezione=sez)
    else:
        studia(sezione=a.sezione)
    return 0


if __name__ == "__main__":
    sys.exit(main())
