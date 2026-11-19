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
import segnali
import settimana
import simula

ROOT = os.path.dirname(os.path.abspath(__file__))
USCITA = os.path.join(ROOT, "rete_lungo.json")
ORIZZONTI = (7, 30, 91)                                # giorni di calendario
NOMI_ORIZZONTI = ("1 settimana", "1 mese", "3 mesi")
CATEGORIE = ("usa", "italia", "etf", "bond", "oro", "crypto")
COSTO = {"usa": 0.001, "italia": 0.002, "etf": 0.001, "bond": 0.001, "oro": 0.001, "crypto": 0.004}   # andata e ritorno
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
NOMI_FEATURE = (["g_" + n for n in segnali.NOMI_GIORNALIERI] + ["trimestre"] + ["cat_" + c for c in CATEGORIE]
                + NOMI_MONDO + list(segnali.NOMI_SENTIMENTO))
FONTI = {
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

    def __init__(self, log=print):
        gm, TM = tabella_mondo(log)
        fg = segnali.fear_greed(log=log)
        X, R, OK, giorni, sym, cat = [], [], [], [], [], []
        self.ultimi = []                                                       # per titolo: la riga di oggi
        for s, m, tz, ch in titoli():
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
            for k, i in enumerate(righe):
                x = np.concatenate([T[i], [np.clip(tri[i], -8, 8)], onehot, mondo[k], sent[k]]).astype(np.float32)
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

def addestra(C, tr, va, epoche=20, seed=0, log=None):
    """Una rete [n, 32, 16, 3]: la probabilità di chiudere in guadagno a 7, 30 e 91 giorni. Si tiene l'epoca che stima
    meglio il periodo di scelta (mai visto)."""
    media, dev = C.X[tr].mean(axis=0), C.X[tr].std(axis=0) + 1e-6
    norm = lambda X: np.clip((X - media) / dev, -6, 6).astype(np.float32)
    Xt, Yt, Mt = norm(C.X[tr]), (C.R[tr] > 0).astype(np.float32), C.OK[tr].astype(np.float32)
    Xv, Yv, Mv = norm(C.X[va]), (C.R[va] > 0).astype(np.float32), C.OK[va].astype(np.float32)
    base = np.clip((Yt * Mt).sum(axis=0) / np.maximum(Mt.sum(axis=0), 1), 1e-3, 1 - 1e-3)
    r = rete.Rete([C.X.shape[1], 32, 16, len(ORIZZONTI)], seed)
    r.b[-1][:] = np.log(base / (1 - base))
    rng = np.random.default_rng(seed)
    migliore = None
    for e in range(epoche):
        rete.addestra_probabilita(r, Xt, Yt, Mt, 1, lr=1e-3 * 0.9 ** e, wd=3e-4, batch=256, rng=rng)
        err = float(rete._entropia(rete.sigmoide(r.avanti(Xv)), Yv, Mv).sum() / max(float(Mv.sum()), 1.0)) if len(Xv) else 0.0
        if log:
            log("   epoca %2d: errore sul periodo di scelta %.4f" % (e + 1, err))
        if migliore is None or err < migliore[0]:
            migliore = (err, e + 1, r.copia())
    return {"rete": migliore[2], "media": media, "dev": dev, "epoca": migliore[1], "norm": norm}


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


def verifica(C, log=print):
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
        if len(tr) < 5000 or len(te) == 0:
            continue
        log("[rete_lungo] verifica %d: impara da %d campioni, sceglie su %d, prova su %d" % (anno, len(tr), len(va), len(te)))
        m = addestra(C, tr, va)
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
        sc, tu, scarti = scelte_settimanali(C, te, P[:, j], j)
        prese = scelte_settimanali.prese
        composizione = {c: float((C.cat[prese] == c).mean()) for c in CATEGORIE} if len(prese) else {}
        mo, _, scarti_mo = scelte_settimanali(C, te, C.X[:, F("g_anno")], j)
        sovrapp = max(H / 7.0, 1.0)                                         # le settimane si sovrappongono: t più prudente
        t = float(scarti.mean() / (scarti.std(ddof=1) / math.sqrt(len(scarti) / sovrapp))) if len(scarti) > 3 else 0.0
        per_anno = []
        for anno in anni:
            ka = te[(C.g[te] >= datetime.date(anno, 1, 1).toordinal()) & (C.g[te] < datetime.date(anno + 1, 1, 1).toordinal())]
            s1, t1, _ = scelte_settimanali(C, ka, P[:, j], j)
            per_anno.append({"anno": anno, "scelte": riassunto(s1), "tutti": riassunto(t1)})
        out["orizzonti"][str(H)] = {"auc": auc(p, y), "calibrazione": cal, "scelte": riassunto(sc), "tutti": riassunto(tu),
                                    "momento": riassunto(mo), "scarto": float(scarti.mean()) if len(scarti) else 0.0, "t": t,
                                    "per_anno": per_anno, "composizione": composizione,
                                    "tutti_composizione": {c: float((C.cat[k] == c).mean()) for c in CATEGORIE},
                                    "per_categoria": {c: riassunto(C.R[k[(C.cat[k] == c)], j]) for c in CATEGORIE}}
        o = out["orizzonti"][str(H)]
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


def studia(log=print, salva=True):
    t0 = time.time()
    C = Campioni(log)
    ris = {"creato": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "orizzonti": list(ORIZZONTI),
           "nomi_orizzonti": list(NOMI_ORIZZONTI), "caratteristiche": list(NOMI_FEATURE), "quota": QUOTA, "costi": COSTO,
           "dati": {"campioni": int(len(C.X)), "titoli": int(len(set(C.sym.tolist()))),
                    "da": datetime.date.fromordinal(int(C.g.min())).isoformat(), "a": datetime.date.fromordinal(int(C.g.max())).isoformat(),
                    "per_categoria": {c: int(len(set(C.sym[C.cat == c].tolist()))) for c in CATEGORIE}}}
    log("[rete_lungo] quali dati sono legati a quello che succede dopo")
    ris["segnali"] = studio_segnali(C)
    ris["verifica"] = verifica(C, log)
    fine_esito = C.g + max(ORIZZONTI)
    tr = np.flatnonzero(fine_esito < C.g.max() - 365)
    va = np.flatnonzero((C.g >= C.g.max() - 365 - max(ORIZZONTI)) & C.OK[:, 0])
    m = addestra(C, tr if len(tr) > 5000 else np.flatnonzero(C.OK[:, 0]), va)
    ris["oggi"] = oggi(C, m)
    ris["durata_minuti"] = round((time.time() - t0) / 60, 1)
    if salva:
        with open(USCITA, "w", encoding="utf-8") as fh:
            json.dump(rete._pulisci(ris), fh, separators=(",", ":"))
        log("[rete_lungo] scritto %s (%.1f minuti)" % (os.path.basename(USCITA), ris["durata_minuti"]))
    return ris


def per_app():
    try:
        with open(USCITA, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.parse_args(argv)
    studia()
    return 0


if __name__ == "__main__":
    sys.exit(main())
