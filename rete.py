#!/usr/bin/env python3
"""Una rete neurale che impara a fare operazioni sulle crypto, con orizzonti da un minuto a due giorni.

    python3 rete.py --ordini-limite          # gli ordini orari di intraday.py, rigiocati minuto per minuto sugli scambi veri
    (in sviluppo: --studia, --costi, --oggi)  # addestra e verifica la rete, costi per orizzonte, cosa farebbe adesso

Dati: ogni scambio delle 12 crypto su Kraken, in euro (rete_dati.py), ricostruito in barre da un minuto.
La rete vede, a ogni quarto d'ora e per ogni crypto, 36 numeri che usano solo il passato (rendimenti su 12
scale, volatilità, posizione nel minimo-massimo, flusso di acquisti e vendite, ora e giorno) ed esce con un
valore per ogni mossa possibile: aspettare, oppure comprare e tenere 1, 5, 15, 30 minuti, 1, 2, 4, 8, 12 ore,
1 o 2 giorni. Ogni acquisto ha una protezione che scatta se il prezzo scende troppo; i costi sono quelli
dell'app (0,2 % per lato). Si può essere dentro una sola volta per crypto: un'operazione blocca il capitale
di quella crypto finché non è chiusa, quindi la rete deve scegliere anche QUANDO aspettare.

Come impara, in due modi che si confrontano:
  - apprendimento per rinforzo (Q-learning su decisioni a durata variabile, "fitted Q"): il valore di una mossa
    è il guadagno netto dell'operazione più il valore, scontato, dello stato in cui ci si ritrova quando si
    torna liberi. Il prezzo non dipende dalle nostre operazioni, quindi per ogni istante si sa cosa sarebbe
    successo con ogni mossa: l'"esperienza" è la storia riletta a ripetizione, un giro per iterazione;
  - previsione diretta: la rete prevede il guadagno netto di ogni orizzonte e si compra dove supera una soglia.
Si verifica a finestre mobili (cammina nel tempo): si addestra sul passato, si sceglie con il mese successivo,
si misura sul mese dopo, mai visto. Nessun numero della verifica serve a scegliere qualcosa.

Solo numpy (la rete e il suo addestramento sono scritti qui, niente framework). Non è consulenza finanziaria.
"""

import argparse
import datetime
import json
import math
import os
import sys
import time

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

import rete_dati

ROOT = os.path.dirname(os.path.abspath(__file__))
MODELLO = os.path.join(ROOT, "rete_modello.json")
ORIZZONTI = (1, 5, 15, 30, 60, 120, 240, 480, 720, 1440, 2880)      # minuti: quanto si tiene dopo l'acquisto
PASSO = 15                                                          # minuti tra una decisione e la successiva
COSTO = 0.002                                                       # per lato, come nell'app (commissione e spread)
K_STOP = 2.5                                                        # protezione: K_STOP x volatilità oraria x radice(ore)
SLIP_STOP = 0.001                                                   # una protezione si esegue un po' peggio del livello
SIGMA_MIN = 0.0005                                                  # volatilità oraria minima (0,05 %)
RITARDI = (5, 15, 30, 60, 120, 240, 480, 720, 1440, 2880, 4320, 10080)
ESTREMI = (60, 240, 1440, 10080)
FLUSSO = (15, 60, 240, 1440)
AVVIO = 10080 + 60                                                  # minuti di storia che servono prima di decidere
GAMMA = 0.995                                                       # sconto per passo di 15 minuti (mezza vita ~ 35 ore)
ESCALA = 0.01                                                       # le uscite della rete sono in unità dell'1 %
NOMI_FEATURE = (["rend_%d" % L for L in RITARDI] + ["log_sigma_ora", "vol_1h_su_24h", "vol_24h_su_7g"]
                + ["pos_%d" % W for W in ESTREMI] + ["dist_max_24h", "dist_min_24h"]
                + ["flusso_%d" % W for W in FLUSSO]
                + ["intensita_1h", "liquidita", "volume_1h", "spread", "ora_sin", "ora_cos", "sett_sin", "sett_cos",
                   "mercato_1h", "mercato_24h", "relativo_24h"])
N_FEATURE = len(NOMI_FEATURE)
ARCO = ("aspetta",) + tuple(ORIZZONTI)


# ---------------------------------------------------------------- dati: scambi -> barre da un minuto

def carica_scambi(sym, giorni):
    """Gli scambi di quei giorni (stringhe AAAA-MM-GG), in ordine di tempo: t, p, v, s (+1 acquisto, -1 vendita)."""
    parti = []
    for g in giorni:
        z = np.load(rete_dati.percorso(sym, g))
        parti.append((z["t"], z["p"], z["v"], z["s"]))
    if not parti:
        raise ValueError("nessun dato per %s" % sym)
    return tuple(np.concatenate([x[k] for x in parti]) for k in range(4))


def barre(scambi, t0, n):
    """n barre da un minuto a partire da t0 (secondi UTC, multiplo di 60). Dove non ci sono scambi il prezzo
    resta quello di prima e il volume è zero. Ritorna un dizionario di array lunghi n."""
    t, p, v, s = scambi
    mi = np.floor((t - t0) / 60.0).astype(np.int64)
    dentro = (mi >= 0) & (mi < n)
    t, p, v, s, mi = t[dentro], p[dentro], v[dentro], s[dentro], mi[dentro]
    if len(p) == 0:
        raise ValueError("nessuno scambio nel periodo")
    inizi = np.concatenate(([0], np.flatnonzero(np.diff(mi) != 0) + 1))
    fini = np.concatenate((inizi[1:], [len(p)]))
    minuti = mi[inizi]
    passo = np.zeros(len(p))
    passo[1:] = np.abs(np.diff(p)) / p[:-1]                     # mossa tra uno scambio e il successivo: stima lo spread
    quota = lambda x: np.add.reduceat(x, inizi)
    B = {k: np.zeros(n) for k in ("o", "h", "l", "c", "v", "n", "vb", "vs", "st", "hb")}
    B["ls"] = np.full(n, np.inf)
    ha = np.zeros(n, dtype=bool)
    ha[minuti] = True
    B["o"][minuti], B["c"][minuti] = p[inizi], p[fini - 1]
    B["h"][minuti], B["l"][minuti] = np.maximum.reduceat(p, inizi), np.minimum.reduceat(p, inizi)
    B["v"][minuti], B["n"][minuti] = quota(v), fini - inizi
    B["vb"][minuti], B["vs"][minuti] = quota(np.where(s > 0, v, 0.0)), quota(np.where(s < 0, v, 0.0))
    B["st"][minuti] = quota(passo)
    # chi compra a mercato "prende" le vendite in attesa e viceversa: un ordine di acquisto fermo a L si esegue
    # di certo se uno scambio a mercato di vendita avviene sotto L, e uno di vendita fermo a H se uno di acquisto avviene sopra H
    B["ls"][minuti] = np.minimum.reduceat(np.where(s < 0, p, np.inf), inizi)    # il prezzo più basso a cui si è venduto a mercato
    B["hb"][minuti] = np.maximum.reduceat(np.where(s > 0, p, 0.0), inizi)       # il più alto a cui si è comprato a mercato
    primo = int(minuti[0])
    ultimo = np.maximum.accumulate(np.where(ha, np.arange(n), primo))   # l'ultima barra con scambi fino a qui
    chiuso = B["c"][ultimo]
    chiuso[:primo] = p[inizi[0]]                                        # prima del primo scambio: il primo prezzo
    for k in ("o", "h", "l", "c"):
        B[k] = np.where(ha, B[k], chiuso)
    return B


class Mondo:
    """Le barre da un minuto di tutte le crypto, sulla stessa griglia di tempo."""

    def __init__(self, simboli, t0, B):
        self.simboli, self.t0 = list(simboli), float(t0)
        self.n = len(B[0]["c"])
        for k in ("o", "h", "l", "c", "v", "n", "vb", "vs", "st", "ls", "hb"):
            setattr(self, "nt" if k == "n" else k, np.stack([b[k] for b in B]))   # nt: numero di scambi per minuto

    def tempo(self, k):
        return self.t0 + 60.0 * np.asarray(k)


def giorni_continui(sym):
    """I giorni in cache senza buchi, fino al più recente."""
    d = os.path.join(rete_dati.CACHE, sym)
    tutti = sorted(f[:-4] for f in os.listdir(d) if f.endswith(".npz") and ".tmp" not in f) if os.path.isdir(d) else []
    out = []
    for g in reversed(tutti):
        if out and (datetime.date.fromisoformat(out[0]) - datetime.date.fromisoformat(g)).days != 1:
            break
        out.insert(0, g)
    return out


def carica_mondo(simboli=None, max_giorni=None, ultimo=None):
    """Carica le serie dei giorni che tutte le crypto hanno in comune, contigui. max_giorni: solo gli ultimi."""
    simboli = list(simboli or rete_dati.COPPIE)
    per = {s: giorni_continui(s) for s in simboli}
    mancanti = [s for s in simboli if not per[s]]
    if mancanti:
        raise ValueError("nessun dato in cache per %s: python3 rete_dati.py" % ", ".join(mancanti))
    fine = min(per[s][-1] for s in simboli) if ultimo is None else ultimo
    inizio = max(per[s][0] for s in simboli)
    g0, g1 = datetime.date.fromisoformat(inizio), datetime.date.fromisoformat(fine)
    if max_giorni:
        g0 = max(g0, g1 - datetime.timedelta(days=max_giorni - 1))
    giorni = [(g0 + datetime.timedelta(days=k)).isoformat() for k in range((g1 - g0).days + 1)]
    t0 = datetime.datetime(g0.year, g0.month, g0.day, tzinfo=datetime.timezone.utc).timestamp()
    n = len(giorni) * 1440
    B = [barre(carica_scambi(s, giorni), t0, n) for s in simboli]
    return Mondo(simboli, t0, B)


# ---------------------------------------------------------------- finestre mobili e somme cumulate

def finestra_max(x, W):
    """Il massimo mobile degli ultimi W valori (con la finestra parziale all'inizio), in tempo lineare."""
    n = x.shape[-1]
    if W <= 1:
        return x.copy()
    resto = (-n) % W
    xp = np.concatenate([x, np.full(x.shape[:-1] + (resto,), -np.inf)], axis=-1) if resto else x
    b = xp.reshape(x.shape[:-1] + (xp.shape[-1] // W, W))
    pre = np.maximum.accumulate(b, axis=-1).reshape(xp.shape)
    suf = np.maximum.accumulate(b[..., ::-1], axis=-1)[..., ::-1].reshape(xp.shape)
    out = np.empty(x.shape, dtype=x.dtype)
    if n >= W:
        out[..., W - 1:] = np.maximum(suf[..., :n - W + 1], pre[..., W - 1:n])
    out[..., :min(W - 1, n)] = np.maximum.accumulate(x[..., :min(W - 1, n)], axis=-1)
    return out


def finestra_min(x, W):
    return -finestra_max(-x, W)


def cumula(x):
    return np.concatenate([np.zeros(x.shape[:-1] + (1,)), np.cumsum(x, axis=-1)], axis=-1)


class Pronto:
    """Quello che serve per calcolare le caratteristiche in un istante qualunque: somme cumulate e finestre mobili."""

    def __init__(self, M):
        self.lr = np.log(M.c)
        r1 = np.zeros_like(self.lr)
        r1[:, 1:] = np.diff(self.lr, axis=1)
        self.r2 = cumula(r1 ** 2)
        self.nn, self.v, self.vb, self.vs, self.st = (cumula(getattr(M, k)) for k in ("nt", "v", "vb", "vs", "st"))
        self.hi = {W: finestra_max(M.h, W) for W in ESTREMI}
        self.lo = {W: finestra_min(M.l, W) for W in ESTREMI}
        self.c, self.t0, self.n = M.c, M.t0, M.n


def griglia(n, passo=PASSO, avvio=AVVIO):
    """Gli istanti di decisione (indici di minuto): quarti d'ora, dopo la storia che serve."""
    primo = int(math.ceil(avvio / passo) * passo)
    return np.arange(primo, n - 1, passo)


def sigma_ora(P, K):
    """Volatilità per ora, dai rendimenti a un minuto delle ultime 24 ore (solo passato)."""
    var = (P.r2[:, K] - P.r2[:, K - 1440]) / 1440.0 * 60.0
    return np.maximum(np.sqrt(np.maximum(var, 0.0)), SIGMA_MIN)


def caratteristiche(P, K):
    """Le N_FEATURE caratteristiche per ogni crypto e ogni istante K: array (crypto, len(K), N_FEATURE).
    Usano solo le barre prima di K (l'ultima chiusa è K-1): niente futuro."""
    C = P.lr.shape[0]
    K = np.asarray(K)
    ult = K - 1
    sig = sigma_ora(P, K)
    z, cols = {}, []
    lrK = P.lr[:, ult]
    for L in RITARDI:
        z[L] = np.clip((lrK - P.lr[:, ult - L]) / (sig * math.sqrt(L / 60.0)), -8, 8)
        cols.append(z[L])
    s60 = np.sqrt(np.maximum(P.r2[:, K] - P.r2[:, K - 60], 0.0))                      # per ora, dall'ultima ora
    s7g = np.sqrt(np.maximum((P.r2[:, K] - P.r2[:, K - 10080]) / 10080.0 * 60.0, 0.0))
    cols += [np.log(sig), np.log((s60 + 1e-5) / sig), np.log(sig / (s7g + 1e-5))]
    cK = P.c[:, ult]
    for W in ESTREMI:
        hi, lo = P.hi[W][:, ult], P.lo[W][:, ult]
        cols.append((cK - lo) / np.maximum(hi - lo, 1e-12))
    cols.append(np.log(P.hi[1440][:, ult] / cK) / sig)
    cols.append(np.log(cK / P.lo[1440][:, ult]) / sig)
    for W in FLUSSO:
        b, s = P.vb[:, K] - P.vb[:, K - W], P.vs[:, K] - P.vs[:, K - W]
        cols.append((b - s) / (b + s + 1e-12))
    n60 = P.nn[:, K] - P.nn[:, K - 60]
    n7 = P.nn[:, K] - P.nn[:, K - 10080]
    v60, v7 = P.v[:, K] - P.v[:, K - 60], P.v[:, K] - P.v[:, K - 10080]
    cols.append(np.log((n60 + 1.0) / (n7 * 60.0 / 10080.0 + 1.0)))
    cols.append(np.log(1.0 + n7 / 168.0))
    cols.append(np.log((v60 + 1e-9) / (v7 * 60.0 / 10080.0 + 1e-9)))
    steps = P.st[:, K] - P.st[:, K - 1440]
    cols.append(np.log(steps / np.maximum(P.nn[:, K] - P.nn[:, K - 1440], 1.0) + 1e-6))
    T = P.t0 + 60.0 * K
    ora, giorno = (T % 86400) / 86400.0 * 2 * np.pi, ((T // 86400 + 3) % 7) / 7.0 * 2 * np.pi
    for f in (np.sin(ora), np.cos(ora), np.sin(giorno), np.cos(giorno)):
        cols.append(np.broadcast_to(f, (C, len(K))))
    m60, m24 = z[60].mean(axis=0), z[1440].mean(axis=0)
    cols += [np.broadcast_to(m60, (C, len(K))), np.broadcast_to(m24, (C, len(K))), z[1440] - m24]
    X = np.stack(cols, axis=-1).astype(np.float32)
    assert X.shape[-1] == N_FEATURE, X.shape
    return np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)


# ---------------------------------------------------------------- etichette: cosa sarebbe successo

def etichette(M, K, sig, costo=COSTO, orizzonti=ORIZZONTI):
    """Per ogni crypto, istante K e orizzonte h: il guadagno netto di "compro all'apertura della barra K e vendo
    h minuti dopo", con la protezione a K_STOP x sigma x radice(h/60) sotto l'entrata (eseguita un po' peggio),
    e dopo quanti minuti si è di nuovo liberi. Ritorna R (crypto, istanti, orizzonti) float32, i minuti fino a
    essere liberi, se è scattata la protezione e una maschera che dice se il futuro c'è (le ultime ore non hanno
    l'esito degli orizzonti lunghi)."""
    K = np.asarray(K)
    C, N, H = M.o.shape[0], len(K), len(orizzonti)
    regolare = N > 1 and bool(np.all(np.diff(K) == K[1] - K[0]))
    R = np.zeros((C, N, H), dtype=np.float32)
    LK = np.zeros((C, N, H), dtype=np.float32)
    FE = np.zeros((C, N, H), dtype=bool)
    OK = np.zeros((C, N, H), dtype=bool)
    for c in range(C):
        o, low = M.o[c], M.l[c]
        for j, h in enumerate(orizzonti):
            ok = K + h <= M.n - 1
            OK[c, :, j] = ok
            k = K[ok]
            if len(k) == 0:
                continue
            entrata = o[k]
            stop = entrata * (1.0 - np.minimum(K_STOP * sig[c, ok] * math.sqrt(h / 60.0), 0.9))
            uscita = o[k + h].copy()
            minuti = np.full(len(k), float(h))
            fermato = np.zeros(len(k), dtype=bool)
            W = sliding_window_view(low, h)
            vista = W[k[0]:k[-1] + 1:K[1] - K[0]] if regolare else None   # finestre senza copiarle
            for a in range(0, len(k), 4000):                          # a pezzi: la matrice finestre x ore è grande
                sl = slice(a, a + 4000)
                w = vista[sl] if vista is not None else W[k[sl]]
                tocca = w <= stop[sl, None]
                f = tocca.any(axis=1)
                if f.any():
                    quando = tocca.argmax(axis=1)
                    kk = k[sl][f] + quando[f]
                    livello = np.minimum(stop[sl][f], o[kk])          # se apre già sotto, si esce all'apertura
                    uscita[sl][f] = livello * (1.0 - SLIP_STOP)
                    minuti[sl][f] = quando[f] + 1.0
                    fermato[sl] = f
            R[c, ok, j] = ((1.0 - costo) ** 2 * (uscita / entrata) - 1.0).astype(np.float32)
            LK[c, ok, j] = minuti
            FE[c, ok, j] = fermato
    return R, LK, FE, OK


# ---------------------------------------------------------------- gli ordini limite orari, sugli scambi veri

def prova_ordini_limite(M, livelli=(1.5, 2.0, 3.0), costo=COSTO, slip=SLIP_STOP, stop_atr=3.0, tenuta=1440,
                        realistico=True, giorni_periodo=60):
    """Gli ordini orari di intraday.py (ribasso a `livelli` escursioni orarie sotto il prezzo, valido un'ora, protezione
    3 escursioni sotto l'entrata, obiettivo il prezzo di partenza, fuori al più tardi dopo 24 ore, uno alla volta per
    crypto) rigiocati minuto per minuto sugli scambi veri, per vedere se i risultati delle candele orarie reggono.
    realistico=True: un ordine di acquisto fermo a L si esegue solo se uno scambio a mercato di VENDITA avviene sotto L
    (se qualcuno vende sotto L, tutti gli acquisti in attesa a L sono stati eseguiti prima), e l'obiettivo, una vendita
    ferma a H, solo se uno scambio a mercato di ACQUISTO avviene sopra H, da un minuto dopo l'entrata. Con False basta
    che il minimo/massimo del minuto tocchino il livello. La protezione conta già nel minuto dell'entrata.
    Ritorna {livello: statistiche, "periodi": medie ogni giorni_periodo giorni}."""
    C, n = M.o.shape
    nh = n // 60
    h_h = M.h[:, :nh * 60].reshape(C, nh, 60).max(axis=2)
    l_h = M.l[:, :nh * 60].reshape(C, nh, 60).min(axis=2)
    c_h = M.c[:, :nh * 60].reshape(C, nh, 60)[:, :, -1]
    tr = np.zeros((C, nh))
    tr[:, 1:] = np.maximum.reduce([h_h[:, 1:] - l_h[:, 1:], np.abs(h_h[:, 1:] - c_h[:, :-1]), np.abs(l_h[:, 1:] - c_h[:, :-1])])
    out = {}
    for e in livelli:
        esiti = []                                                       # (ora d'inizio, guadagno netto, come è finita)
        for c in range(C):
            j = 25
            while j < nh - 26:
                atr = tr[c, j - 24:j].mean()
                p0 = c_h[c, j - 1]
                if atr <= 0 or p0 <= 0:
                    j += 1
                    continue
                L, m0 = p0 - e * atr, 60 * j
                tocca = (M.ls[c, m0:m0 + 60] < L) if realistico else (M.l[c, m0:m0 + 60] <= L)
                if not tocca.any():
                    j += 1
                    continue
                mf = m0 + int(tocca.argmax())
                S, fine = L - stop_atr * atr, min(mf + tenuta, n - 2)
                fermo = M.l[c, mf:fine + 1] <= S
                preso = (M.hb[c, mf + 1:fine + 1] > p0) if realistico else (M.h[c, mf + 1:fine + 1] >= p0)
                ts = int(fermo.argmax()) if fermo.any() else 10 ** 9
                tt = int(preso.argmax()) + 1 if preso.any() else 10 ** 9
                if ts <= tt and ts < 10 ** 9:
                    uscita, durata, come = min(S, M.o[c, mf + ts]) * (1 - slip), ts + 1, "protezione"
                elif tt < 10 ** 9:
                    uscita, durata, come = p0, tt + 1, "obiettivo"
                else:
                    uscita, durata, come = M.o[c, fine], fine - mf + 1, "tempo"
                esiti.append((j, (1 - costo) ** 2 * uscita / L - 1, come))
                j = max(25, int(math.ceil((mf + durata) / 60.0)))
        r = np.array([x[1] for x in esiti])
        ore = np.array([x[0] for x in esiti])
        out[e] = {"n": int(len(r)), "media": float(r.mean()) if len(r) else 0.0, "vinte": float((r > 0).mean()) if len(r) else 0.0,
                  "al_giorno": float(len(r) / (n / 1440.0)),
                  **{k: float(np.mean([x[2] == k for x in esiti])) if esiti else 0.0 for k in ("obiettivo", "protezione", "tempo")},
                  "periodi": [(float(r[(ore >= a * 24) & (ore < (a + giorni_periodo) * 24)].mean()) if ((ore >= a * 24) & (ore < (a + giorni_periodo) * 24)).sum() >= 5 else None)
                              for a in range(0, int(n / 1440), giorni_periodo)]}
    return out


# ---------------------------------------------------------------- la rete (un perceptron a tre strati, in numpy)

class Rete:
    """Ingresso -> 2 strati nascosti -> una uscita per mossa (aspettare, poi un orizzonte per volta). Attivazione
    ReLU con una piccola pendenza sotto zero; addestramento con Adam (scritto qui, senza framework)."""

    def __init__(self, dims, seed=0):
        self.dims = list(dims)
        rng = np.random.default_rng(seed)
        self.W = [(rng.standard_normal((a, b)) * math.sqrt(2.0 / a)).astype(np.float32) for a, b in zip(dims[:-1], dims[1:])]
        self.W[-1] *= 0.1
        self.b = [np.zeros(b, np.float32) for b in dims[1:]]

    def avanti(self, X, tieni=False):
        a, att = X, [X]
        for i in range(len(self.W)):
            z = a @ self.W[i] + self.b[i]
            a = z if i == len(self.W) - 1 else np.where(z > 0, z, np.float32(0.02) * z)
            att.append(a)
        return (a, att) if tieni else a

    def indietro(self, att, d):
        L = len(self.W)
        gW, gb = [None] * L, [None] * L
        for i in reversed(range(L)):
            if i < L - 1:
                d = d * np.where(att[i + 1] > 0, np.float32(1.0), np.float32(0.02))
            gW[i], gb[i] = att[i].T @ d, d.sum(axis=0)
            if i > 0:
                d = d @ self.W[i].T
        return gW, gb

    def copia(self):
        r = Rete(self.dims)
        r.W, r.b = [w.copy() for w in self.W], [b.copy() for b in self.b]
        return r

    def a_dizionario(self, cifre=7):
        return {"dims": self.dims, "W": [np.round(w, cifre).tolist() for w in self.W],
                "b": [np.round(b, cifre).tolist() for b in self.b]}

    @staticmethod
    def da_dizionario(d):
        r = Rete(d["dims"])
        r.W = [np.array(w, dtype=np.float32) for w in d["W"]]
        r.b = [np.array(b, dtype=np.float32) for b in d["b"]]
        return r


class Adam:
    def __init__(self, rete, lr=1e-3, wd=1e-4, b1=0.9, b2=0.999):
        self.r, self.lr, self.wd, self.b1, self.b2, self.t = rete, lr, wd, b1, b2, 0
        self.m = [np.zeros_like(p) for p in rete.W + rete.b]
        self.v = [np.zeros_like(p) for p in rete.W + rete.b]

    def passo(self, gW, gb):
        self.t += 1
        par = self.r.W + self.r.b
        for k, (p, g) in enumerate(zip(par, gW + gb)):
            self.m[k] = self.b1 * self.m[k] + (1 - self.b1) * g
            self.v[k] = self.b2 * self.v[k] + (1 - self.b2) * g * g
            mh = self.m[k] / (1 - self.b1 ** self.t)
            vh = self.v[k] / (1 - self.b2 ** self.t)
            if k < len(self.r.W):
                p *= np.float32(1.0 - self.lr * self.wd)                  # decadimento dei pesi (non dei bias)
            p -= (self.lr * mh / (np.sqrt(vh) + 1e-8)).astype(np.float32)


def addestra(rete, X, Y, Mk, epoche, lr=1e-3, wd=1e-4, batch=2048, rng=None, dopo_epoca=None):
    """Errore quadratico medio sui soli bersagli validi (Mk = 1). Ritorna l'errore medio di ogni epoca."""
    rng = rng or np.random.default_rng(0)
    ott = Adam(rete, lr, wd)
    n, perdite = len(X), []
    for e in range(epoche):
        ordine = rng.permutation(n)
        tot, peso = 0.0, 0.0
        for a in range(0, n, batch):
            idx = ordine[a:a + batch]
            out, att = rete.avanti(X[idx], tieni=True)
            m = Mk[idx]
            err = (out - Y[idx]) * m
            s = max(float(m.sum()), 1.0)
            tot += float((err * err).sum())
            peso += s
            gW, gb = rete.indietro(att, (2.0 / s) * err)
            ott.passo(gW, gb)
        perdite.append(tot / max(peso, 1.0))
        if dopo_epoca is not None:
            dopo_epoca(e, perdite[-1])
    return perdite


# ---------------------------------------------------------------- politica, simulazione, statistiche

def politica(Q, margine=0.0, ritmo=0.0):
    """Q: (..., 1 + orizzonti), in frazioni (0,01 = 1 %). Compra se la mossa migliore supera l'attesa di `margine`.
    `ritmo` toglie un costo per ora di capitale bloccato (serve alla previsione diretta: nell'apprendimento per
    rinforzo il valore dell'attesa contiene già quel costo). Ritorna per ogni istante 0 (aspetta) o l'indice
    dell'orizzonte + 1."""
    ore = np.array(ORIZZONTI, dtype=np.float32) / 60.0
    punti = Q[..., 1:] - ritmo * ore
    miglior = punti.max(axis=-1)
    az = punti.argmax(axis=-1) + 1
    return np.where(miglior - Q[..., 0] > margine, az, 0)


def simula(az, R, LK, FE, OK, passo=PASSO):
    """Segue le decisioni nel tempo, una crypto per volta e una posizione alla volta: se si è dentro, le decisioni
    nuove si saltano fino a quando l'operazione si chiude. Ritorna un array (operazioni, 6): crypto, istante,
    orizzonte, guadagno netto, minuti in posizione, protezione scattata (0/1)."""
    righe = []
    for c in range(az.shape[0]):
        libero = 0
        for i in np.flatnonzero(az[c] > 0):
            if i < libero:
                continue
            j = int(az[c, i]) - 1
            if not OK[c, i, j]:
                continue
            lock = float(LK[c, i, j])
            righe.append((c, i, j, float(R[c, i, j]), lock, float(FE[c, i, j])))
            libero = i + max(1, int(math.ceil(lock / passo)))
    return np.array(righe, dtype=np.float64).reshape(-1, 6)


def statistiche(T, n_crypto, n_istanti, passo=PASSO):
    """Riassunto di un insieme di operazioni (l'output di simula) su n_istanti decisioni per crypto."""
    if len(T) == 0:
        return {"n": 0, "media": 0.0, "vinte": 0.0, "mediana": 0.0, "p10": 0.0, "somma": 0.0, "minuti": 0.0,
                "esposizione": 0.0, "al_giorno": 0.0, "protezione": 0.0, "orizzonti": [0] * len(ORIZZONTI)}
    r = T[:, 3]
    giorni = n_istanti * passo / 1440.0
    hist = np.bincount(T[:, 2].astype(int), minlength=len(ORIZZONTI)).tolist()
    return {"n": int(len(T)), "media": float(r.mean()), "vinte": float((r > 0).mean()), "mediana": float(np.median(r)),
            "p10": float(np.percentile(r, 10)), "somma": float(r.sum()), "minuti": float(T[:, 4].mean()),
            "esposizione": float(T[:, 4].sum() / (n_crypto * n_istanti * passo)), "al_giorno": float(len(T) / giorni),
            "protezione": float(T[:, 5].mean()), "orizzonti": hist}


def serie_giornaliera(T, K, t0, n_crypto, giorni_da, giorni_a):
    """Il rendimento giornaliero del conto: ogni crypto ha 1/n_crypto del capitale e ogni operazione vale il suo
    guadagno netto nel giorno in cui si chiude. Ritorna un array con un valore per giorno in [giorni_da, giorni_a)."""
    out = np.zeros(giorni_a - giorni_da)
    for c, i, j, r, lock, f in T:
        giorno = int((t0 + 60.0 * K[int(i)] + 60.0 * lock) // 86400) - giorni_da
        if 0 <= giorno < len(out):
            out[giorno] += r / n_crypto
    return out


def bootstrap_blocchi(x, blocco=7, n=2000, seed=1):
    """Intervallo al 90 % della media di una serie giornaliera, con blocchi di giorni (le giornate vicine si somigliano)."""
    x = np.asarray(x, dtype=np.float64)
    if len(x) < 2 * blocco:
        return [float("nan"), float("nan")]
    rng = np.random.default_rng(seed)
    nb = int(math.ceil(len(x) / blocco))
    medie = np.empty(n)
    for k in range(n):
        inizi = rng.integers(0, len(x) - blocco + 1, nb)
        medie[k] = np.concatenate([x[a:a + blocco] for a in inizi])[:len(x)].mean()
    return [float(np.percentile(medie, 5)), float(np.percentile(medie, 95))]


# ---------------------------------------------------------------- insiemi di dati e finestre mobili

class Dati:
    """Caratteristiche, esiti e tempi per crypto x istante di decisione."""

    def __init__(self, M, costo=COSTO):
        self.M, self.costo = M, costo
        self.P = Pronto(M)
        self.K = griglia(M.n)
        self.sig = sigma_ora(self.P, self.K)
        self.X = caratteristiche(self.P, self.K)
        self.R, self.LK, self.FE, self.OK = etichette(M, self.K, self.sig, costo)
        self.C, self.N = self.X.shape[:2]
        self.giorni = M.n / 1440.0

    def indice(self, giorno):
        """Il primo istante di decisione dal giorno (con decimali) contato dall'inizio dei dati."""
        return int(np.searchsorted(self.K, giorno * 1440.0))

    def norm(self, X, media, dev):
        return np.clip((X - media) / dev, -6.0, 6.0).astype(np.float32)

    def statistiche_norm(self, i0, i1):
        x = self.X[:, i0:i1].reshape(-1, N_FEATURE)
        return x.mean(axis=0).astype(np.float32), np.maximum(x.std(axis=0), 1e-3).astype(np.float32)


def finestre(D, giorni_test=30, giorni_val=30, embargo=2, min_addestramento=100, max_finestre=6):
    """Le finestre mobili: per ognuna un periodo di addestramento, uno di scelta (il mese prima del test) e uno di
    test. Tra l'uno e l'altro c'è un intervallo di `embargo` giorni (l'esito di un'operazione guarda avanti fino a
    2 giorni: senza intervallo l'addestramento vedrebbe un pezzo del futuro del test)."""
    fine = D.giorni - 2.0                                           # gli esiti lunghi dell'ultimo tratto mancano
    out = []
    for k in range(max_finestre):
        te1 = fine - k * giorni_test
        te0 = te1 - giorni_test
        va1 = te0 - embargo
        va0 = va1 - giorni_val
        tr1 = va0 - embargo
        if tr1 < min_addestramento + AVVIO / 1440.0:
            break
        out.append({"addestramento": (D.indice(AVVIO / 1440.0), D.indice(tr1)), "scelta": (D.indice(va0), D.indice(va1)),
                    "test": (D.indice(te0), D.indice(te1)), "giorni": (round(te0, 1), round(te1, 1))})
    return out[::-1]


# ---------------------------------------------------------------- come impara

def _bersagli_previsione(D, i0, i1):
    """Previsione diretta: l'uscita di ogni orizzonte è il guadagno netto; aspettare vale zero."""
    R, OK = D.R[:, i0:i1], D.OK[:, i0:i1]
    n = R.shape[0] * R.shape[1]
    Y = np.zeros((n, 1 + len(ORIZZONTI)), np.float32)
    M = np.ones_like(Y)
    Y[:, 1:] = (R / ESCALA).reshape(n, -1)
    M[:, 1:] = OK.reshape(n, -1)
    return Y, M


def _bersagli_q(D, i0, i1, V, gamma=GAMMA, passo=PASSO):
    """Apprendimento per rinforzo: il valore di una mossa è il guadagno netto dell'operazione più il valore,
    scontato, dello stato in cui si torna liberi (V, calcolato dalla rete dell'iterazione prima).
    Aspettare vale il valore scontato del quarto d'ora dopo. V ha forma (crypto, istanti)."""
    C, Ns = D.C, i1 - i0
    R, LK, OK = D.R[:, i0:i1], D.LK[:, i0:i1], D.OK[:, i0:i1]
    Y = np.zeros((C, Ns, 1 + len(ORIZZONTI)), np.float32)
    M = np.zeros_like(Y)
    Y[:, :-1, 0] = gamma * V[:, 1:]
    M[:, :-1, 0] = 1.0
    passi = np.maximum(1, np.ceil(LK / passo)).astype(np.int64)         # quarti d'ora fino a essere liberi
    idx = np.arange(Ns)[None, :, None] + passi
    dentro = OK & (idx < Ns)
    futuro = np.take_along_axis(np.broadcast_to(V[:, :, None], R.shape), np.where(dentro, idx, 0), axis=1)
    Y[:, :, 1:] = np.where(dentro, R + (gamma ** passi) * futuro, 0.0)
    M[:, :, 1:] = dentro
    return (Y / ESCALA).reshape(C * Ns, -1), M.reshape(C * Ns, -1)


def _valuta(D, rete, media, dev, i0, i1, margini, ritmi=(0.0,)):
    """La politica della rete sul periodo [i0, i1): per ogni margine e ritmo, le statistiche delle operazioni."""
    X = D.norm(D.X[:, i0:i1], media, dev).reshape(-1, N_FEATURE)
    Q = (rete.avanti(X) * ESCALA).reshape(D.C, i1 - i0, -1)
    out = {}
    for m in margini:
        for r in ritmi:
            T = simula(politica(Q, m, r), D.R[:, i0:i1], D.LK[:, i0:i1], D.FE[:, i0:i1], D.OK[:, i0:i1])
            out[(m, r)] = (T, statistiche(T, D.C, i1 - i0))
    return Q, out


MARGINI = (0.0, 0.0005, 0.001, 0.002, 0.004)


def apprendi_q(D, tr, va, iterazioni=14, epoche=3, nascosti=(96, 48), seed=0, lr=1e-3, wd=1e-4, gamma=GAMMA,
               log=None, valuta=True):
    """Q-learning a iterazioni: a ogni giro la rete riconta il valore di ogni mossa con la rete del giro prima
    (la "memoria" è la storia intera del periodo di addestramento) e la rifà imparare. Dopo ogni iterazione si
    guarda come va la sua politica sul periodo di scelta: è la curva di apprendimento. Ritorna la rete scelta
    (l'iterazione con il risultato migliore nel periodo di scelta, margine medio), le normalizzazioni e le curve."""
    i0, i1 = tr
    media, dev = D.statistiche_norm(i0, i1)
    Xt = D.norm(D.X[:, i0:i1], media, dev).reshape(-1, N_FEATURE)
    rete = Rete([N_FEATURE, *nascosti, 1 + len(ORIZZONTI)], seed)
    rng = np.random.default_rng(seed)
    V = np.zeros((D.C, i1 - i0), np.float32)
    curve, migliore = [], None
    for it in range(iterazioni):
        Y, Mk = _bersagli_q(D, i0, i1, V, gamma)
        perdite = addestra(rete, Xt, Y, Mk, epoche, lr=lr * (0.7 ** (it // 4)), wd=wd, rng=rng)
        V = (rete.avanti(Xt) * ESCALA).max(axis=1).reshape(D.C, i1 - i0)
        riga = {"iterazione": it + 1, "errore": perdite[-1], "valore_medio": float(V.mean())}
        if valuta:
            _, ris = _valuta(D, rete, media, dev, *va, margini=MARGINI)
            for m in MARGINI:
                s = ris[(m, 0.0)][1]
                riga["m%g" % m] = {"n": s["n"], "media": s["media"], "somma": s["somma"], "orizzonti": s["orizzonti"],
                                   "minuti": s["minuti"]}
        curve.append(riga)
        if log:
            s = riga.get("m0.001", {})
            log("   Q iter %2d: errore %.4f · V medio %+.4f · scelta (margine 0,1 %%): %d operazioni, media %+.3f %%" % (
                it + 1, perdite[-1], riga["valore_medio"], s.get("n", 0), 100 * s.get("media", 0.0)))
        if valuta and riga["m0.001"]["n"] >= 10 and (migliore is None or riga["m0.001"]["somma"] > migliore[0]):
            migliore = (riga["m0.001"]["somma"], it + 1, rete.copia())
    if migliore is None:
        migliore = (0.0, iterazioni, rete.copia())
    _, it_best, rete_best = migliore
    margine, punti = 0.001, -1e9
    if valuta:
        for m in MARGINI:                                              # il margine, scelto nel periodo di scelta
            s = curve[it_best - 1]["m%g" % m]
            if s["n"] >= 10 and s["somma"] > punti:
                margine, punti = m, s["somma"]
    return {"rete": rete_best, "media": media, "dev": dev, "curve": curve, "iterazione": it_best, "margine": margine,
            "tipo": "q"}


def apprendi_previsione(D, tr, va, epoche=14, nascosti=(96, 48), seed=0, lr=1e-3, wd=1e-4, log=None):
    """Previsione diretta: la rete prevede il guadagno netto di ogni orizzonte (regressione). Si tiene l'epoca
    con l'errore più basso nel periodo di scelta; margine e costo del tempo si scelgono sullo stesso periodo."""
    i0, i1 = tr
    media, dev = D.statistiche_norm(i0, i1)
    Xt = D.norm(D.X[:, i0:i1], media, dev).reshape(-1, N_FEATURE)
    Yt, Mt = _bersagli_previsione(D, i0, i1)
    Xv = D.norm(D.X[:, va[0]:va[1]], media, dev).reshape(-1, N_FEATURE)
    Yv, Mv = _bersagli_previsione(D, *va)
    rete = Rete([N_FEATURE, *nascosti, 1 + len(ORIZZONTI)], seed)
    rng = np.random.default_rng(seed)
    curve, migliore = [], None
    for e in range(epoche):
        perdite = addestra(rete, Xt, Yt, Mt, 1, lr=lr * (0.8 ** (e // 3)), wd=wd, rng=rng)
        out = rete.avanti(Xv)
        errore_v = float((((out - Yv) * Mv) ** 2).sum() / max(float(Mv.sum()), 1.0))
        curve.append({"epoca": e + 1, "errore": perdite[-1], "errore_scelta": errore_v})
        if log:
            log("   previsione epoca %2d: errore %.4f · scelta %.4f" % (e + 1, perdite[-1], errore_v))
        if migliore is None or errore_v < migliore[0]:
            migliore = (errore_v, e + 1, rete.copia())
    _, e_best, rete_best = migliore
    margini, ritmi = (0.0, 0.001, 0.002, 0.004), (0.0, 0.0003, 0.0006, 0.001)
    _, ris = _valuta(D, rete_best, media, dev, *va, margini=margini, ritmi=ritmi)
    scelta = max(((s["somma"], m, r) for (m, r), (T, s) in ris.items() if s["n"] >= 10), default=(0, 0.002, 0.0))
    return {"rete": rete_best, "media": media, "dev": dev, "curve": curve, "iterazione": e_best, "margine": scelta[1],
            "ritmo": scelta[2], "tipo": "previsione"}


def decisioni(modello, D, i0, i1):
    """Le azioni (0 aspetta, altrimenti orizzonte + 1) di un modello su [i0, i1), per ogni crypto."""
    X = D.norm(D.X[:, i0:i1], modello["media"], modello["dev"]).reshape(-1, N_FEATURE)
    Q = (modello["rete"].avanti(X) * ESCALA).reshape(D.C, i1 - i0, -1)
    return politica(Q, modello["margine"], modello.get("ritmo", 0.0)), Q


# ---------------------------------------------------------------- a riga di comando

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ordini-limite", action="store_true",
                    help="gli ordini orari di intraday.py rigiocati sugli scambi veri (servono i dati di rete_dati.py)")
    ap.add_argument("--giorni", type=int, default=None, help="solo gli ultimi n giorni di dati")
    a = ap.parse_args(argv)
    if a.ordini_limite:
        M = carica_mondo(max_giorni=a.giorni)
        print("ORDINI LIMITE ORARI SUGLI SCAMBI VERI: %d giorni, %d crypto, costi %.1f %% per lato" % (M.n / 1440, len(M.simboli), 100 * COSTO))
        for realistico, nome in ((True, "esecuzione realistica (scambio a mercato oltre il livello)"),
                                 (False, "esecuzione da candela (basta che il minimo del minuto tocchi il livello)")):
            print("\n" + nome)
            for e, r in prova_ordini_limite(M, realistico=realistico).items():
                print("  %.1f escursioni: %5d operazioni (%.1f al giorno) · media %+.3f %% · in guadagno %.0f %% · obiettivo %.0f %%, protezione %.0f %%, 24 ore %.0f %%" % (
                    e, r["n"], r["al_giorno"], 100 * r["media"], 100 * r["vinte"], 100 * r["obiettivo"], 100 * r["protezione"], 100 * r["tempo"]))
                print("      ogni 60 giorni: " + " ".join(("%+.2f %%" % (100 * x)) if x is not None else "n/d" for x in r["periodi"]))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
