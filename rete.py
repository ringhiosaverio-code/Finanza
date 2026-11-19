#!/usr/bin/env python3
"""Una rete neurale che impara a fare operazioni sulle crypto, con orizzonti da un minuto a due giorni.

    python3 rete_dati.py                     # prima: gli scambi di Kraken, 400 giorni (circa 75 minuti)
    python3 rete.py --studia                 # addestra e verifica la rete a finestre mobili, per più costi (circa 30 minuti)
    python3 rete.py --sovradattamento        # aggiunge: quello che impara nel passato dura nel futuro? (qualche minuto)
    python3 rete.py --ordini-limite          # gli ordini orari di intraday.py, rigiocati minuto per minuto sugli scambi veri
    python3 rete_live.py                     # la rete dal vivo, in un conto finto

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
si misura sul mese dopo, mai visto. Nessun numero della verifica serve a scegliere qualcosa. Per comprare, nel mese di
scelta il guadagno deve essere credibile (almeno 1,5 errori standard sopra zero su 20 operazioni): se no la rete resta fuori.

Risultato (rete_modello.json, riassunto nell'app e nel README): con i costi dell'app la rete non guadagna fuori campione.

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

import segnali
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
                   "mercato_1h", "mercato_24h", "relativo_24h"]
                # i segnali della ricerca (vedi segnali.py): dentro la giornata...
                + ["vwap_24h", "stagione_1h", "btc_5", "btc_60", "dal_giorno", "prima_mezzora", "williams",
                   "rottura_su_ieri", "rottura_giu_ieri"]
                # ...anno, mese, settimana, giorno dalle chiusure giornaliere, sentimento e notizie
                + ["g_" + n for n in segnali.NOMI_GIORNALIERI] + list(segnali.NOMI_SENTIMENTO) + list(segnali.NOMI_NOTIZIE)
                # i segnali della skill trader-scanner (in fondo: i modelli di prima usano solo i loro)
                + list(segnali.NOMI_SCANNER)
                # perché le crypto salgono o scendono: i mercati che le muovono (futures di Wall Street, VIX, tassi,
                # petrolio, oro, cambio), dalle barre orarie di Yahoo (in fondo: i modelli di prima usano solo i loro)
                + list(segnali.NOMI_MOTORI))
N_FEATURE = len(NOMI_FEATURE)
N_BASE = NOMI_FEATURE.index("vwap_24h")                             # le prime N_BASE: quelle di prima
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
        self.vc = cumula(M.v * M.c)                                     # per il VWAP
        self.simboli = list(getattr(M, "simboli", []))
        # i giorni UTC: indice del giorno di ogni minuto, prezzo a mezzanotte (chiusura del minuto prima), massimo e
        # minimo di ogni giorno intero
        g0 = int(M.t0 // 86400)
        self.giorno = ((M.t0 + 60.0 * np.arange(M.n)) // 86400).astype(np.int64) - g0
        ng = int(self.giorno[-1]) + 1
        self.inizio = np.searchsorted(self.giorno, np.arange(ng))       # primo minuto di ogni giorno
        C = M.c.shape[0]
        self.alto, self.basso = np.zeros((C, ng)), np.zeros((C, ng))
        for d in range(ng):
            a, b = self.inizio[d], (self.inizio[d + 1] if d + 1 < ng else M.n)
            self.alto[:, d], self.basso[:, d] = M.h[:, a:b].max(axis=1), M.l[:, a:b].min(axis=1)
        self.giorni_iso = [datetime.date.fromordinal(datetime.date(1970, 1, 1).toordinal() + g0 + d).isoformat() for d in range(ng)]
        self.esterni = esterni_crypto(self.simboli, self.giorni_iso)    # (C, giorni, n): giornalieri, sentimento, notizie


def esterni_crypto(simboli, giorni_iso):
    """I segnali che non vengono dagli scambi, per giorno UTC e crypto: anno, mese, settimana, giorno e gli altri dalle
    chiusure giornaliere di Yahoo, il Fear & Greed e le notizie (sempre del giorno prima, già chiuso). Zeri dove mancano."""
    n = len(segnali.NOMI_GIORNALIERI) + len(segnali.NOMI_SENTIMENTO) + len(segnali.NOMI_NOTIZIE) + len(segnali.NOMI_SCANNER)
    out = np.zeros((len(simboli), len(giorni_iso), n), np.float32)
    if not simboli or not giorni_iso:
        return out
    sent = segnali.sentimento_per_giorno(giorni_iso)
    notizie = segnali.notizie_per_giorno(segnali.notizie("crypto", "bitcoin OR cryptocurrency OR crypto", log=lambda m: None), giorni_iso)
    ng = len(segnali.NOMI_GIORNALIERI)
    for c, sym in enumerate(simboli):
        giorni, o, h, l, cl = segnali.giornaliere(sym, "UTC", (23, 59))
        if len(giorni) < 60 and sym in rete_dati.COPPIE_ROBOT:                 # Yahoo non la ha: le giornaliere di Kraken
            giorni, o, h, l, cl = segnali.giornaliere_kraken(rete_dati.COPPIE_ROBOT[sym])
        out[c, :, :ng] = segnali.per_giorno(giorni, segnali.tabella_giornaliera(o, h, l, cl, anno=365, mese=30, settimana=7), giorni_iso)
        out[c, :, ng:ng + 2] = sent
        out[c, :, ng + 2:ng + 4] = notizie
        out[c, :, ng + 4:] = segnali.per_giorno(giorni, segnali.tabella_scanner(cl), giorni_iso)
    return out


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
    cols += segnali_crypto(P, K, sig, z)
    X = np.stack(cols, axis=-1).astype(np.float32)
    assert X.shape[-1] == N_FEATURE, X.shape
    return np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)


def segnali_crypto(P, K, sig, z):
    """I segnali della ricerca, per ogni crypto e istante K (solo il passato: barre fino a K-1, giorni già chiusi)."""
    C, ult = P.lr.shape[0], K - 1
    cK, lrK = P.c[:, ult], P.lr[:, ult]
    out = []
    # VWAP delle ultime 24 ore (Aziz): sopra o sotto il prezzo medio pagato
    vol24 = P.v[:, K] - P.v[:, K - 1440]
    vwap = (P.vc[:, K] - P.vc[:, K - 1440]) / np.maximum(vol24, 1e-12)
    out.append(np.where(vol24 > 0, np.clip(np.log(cK / np.maximum(vwap, 1e-12)) / (sig * math.sqrt(24.0)), -8, 8), 0.0))
    # stagionalità (Heston, Korajczyk e Sadka; Eross e altri): l'ora che comincia adesso, nei 7 giorni prima
    st = np.zeros((C, len(K)))
    for d in range(1, 8):
        a = K - d * 1440
        st += P.lr[:, a + 59] - P.lr[:, a - 1]
    out.append(np.clip(st / 7.0 / sig, -8, 8))
    # Bitcoin guida le altre (5 minuti e un'ora)
    b = P.simboli.index("BTC-EUR") if "BTC-EUR" in P.simboli else None
    for L in (5, 60):
        riga = z[L][b] if b is not None else z[L].mean(axis=0)
        out.append(np.broadcast_to(riga, (C, len(K))))
    # dentro il giorno UTC: dall'inizio del giorno, prima mezz'ora (Gao e altri; Wen e altri), rottura di volatilità di
    # Williams (apertura + metà dell'escursione di ieri) e rotture del massimo e del minimo di ieri
    d = P.giorno[K]
    s0 = P.inizio[d]
    apertura = P.lr[:, np.maximum(s0 - 1, 0)]                          # il prezzo a mezzanotte: chiusura del minuto prima
    minuti = np.maximum(K - s0, 1)
    out.append(np.clip((lrK - apertura) / (sig * np.sqrt(minuti / 60.0)), -8, 8))
    pm = np.where(K - s0 >= 30, P.lr[:, np.minimum(s0 + 29, P.n - 1)] - apertura, 0.0)
    out.append(np.clip(pm / (sig * math.sqrt(0.5)), -8, 8))
    ieri = np.maximum(d - 1, 0)
    hi, lo = P.alto[:, ieri], P.basso[:, ieri]
    rng = np.maximum(hi - lo, 1e-12)
    c0 = np.exp(apertura)
    ok = d >= 1
    out.append(np.where(ok, np.clip((cK - (c0 + 0.5 * rng)) / rng, -5, 5), 0.0))
    out.append(np.where(ok, np.clip(np.log(cK / hi) / (sig * math.sqrt(24.0)), -8, 8), 0.0))
    out.append(np.where(ok, np.clip(np.log(cK / lo) / (sig * math.sqrt(24.0)), -8, 8), 0.0))
    # anno, mese, settimana, giorno, sentimento e notizie: del giorno prima
    E = P.esterni[:, d, :]
    out += [E[:, :, j] for j in range(E.shape[-1])]
    # i mercati che muovono le crypto, barre orarie chiuse prima dell'istante di decisione
    Mo = segnali.tabella_motori(P.t0 + 60.0 * K, "1h")
    out += [np.broadcast_to(Mo[:, j], (C, len(K))) for j in range(Mo.shape[1])]
    return out


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


# ---------------------------------------------------------------- ordini limite appresi: gli esiti di ogni ordine

PROFONDITA = (1.0, 1.75, 2.5)          # quanto sotto il prezzo si mette l'ordine di acquisto, in volatilità orarie
TENUTA_LIMITE = 1440                   # minuti al massimo in posizione dopo l'esecuzione


def etichette_limite(M, K, sig, profondita=PROFONDITA, costo=COSTO, slip=SLIP_STOP, stop_sig=3.0, validita=60,
                     tenuta=TENUTA_LIMITE):
    """Per ogni crypto, istante K e profondità d: com'è andato un ordine di acquisto fermo a L = prezzo - d x sigma,
    valido `validita` minuti da K. Si esegue solo se uno scambio a mercato di VENDITA avviene sotto L; poi obiettivo
    il prezzo di partenza (solo se uno scambio a mercato di ACQUISTO avviene sopra, da un minuto dopo l'entrata),
    protezione stop_sig x sigma sotto l'entrata (conta già nel minuto dell'entrata, eseguita un po' peggio) e uscita
    a mercato dopo `tenuta` minuti. Ritorna: guadagno netto (0 se non si esegue), minuti fino a essere liberi (se non
    si esegue, la validità), se si è eseguito, e dove c'è il futuro per saperlo."""
    K = np.asarray(K)
    C, N, D = M.o.shape[0], len(K), len(profondita)
    Y = np.zeros((C, N, D), np.float32)
    LK = np.full((C, N, D), float(validita), np.float32)
    FILL = np.zeros((C, N, D), bool)
    OK = np.zeros((C, N, D), bool)
    for c in range(C):
        ls, hb, low, o, cl = M.ls[c], M.hb[c], M.l[c], M.o[c], M.c[c]
        okk = K + validita + tenuta + 1 <= M.n - 1
        Wls = sliding_window_view(ls, validita)
        for d, prof in enumerate(profondita):
            OK[c, :, d] = okk
            p0 = cl[K - 1]
            L = p0 * (1.0 - prof * sig[c])
            for i in np.flatnonzero(okk):
                k = K[i]
                tocca = Wls[k] < L[i]
                if not tocca.any():
                    continue
                mf = k + int(tocca.argmax())
                S = L[i] * (1.0 - stop_sig * sig[c, i])
                fine = mf + tenuta
                fermo = low[mf:fine + 1] <= S
                preso = hb[mf + 1:fine + 1] > p0[i]
                ts = int(fermo.argmax()) if fermo.any() else 10 ** 9
                tt = int(preso.argmax()) + 1 if preso.any() else 10 ** 9
                if ts <= tt and ts < 10 ** 9:
                    uscita, durata = min(S, o[mf + ts]) * (1.0 - slip), ts + 1
                elif tt < 10 ** 9:
                    uscita, durata = p0[i], tt + 1
                else:
                    uscita, durata = o[fine], fine - mf + 1
                Y[c, i, d] = (1.0 - costo) ** 2 * uscita / L[i] - 1.0
                LK[c, i, d] = (mf - k) + durata
                FILL[c, i, d] = True
    return Y, LK, FILL, OK


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

    def copy(self):
        return self.copia()

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

def _oriz(D):
    return tuple(getattr(D, "orizzonti", ORIZZONTI))


def _passo(D):
    return getattr(D, "passo", PASSO)


def _avvio(D):
    return getattr(D, "avvio", AVVIO)


def politica(Q, margine=0.0, ritmo=0.0, orizzonti=None):
    """Q: (..., 1 + orizzonti), in frazioni (0,01 = 1 %). Compra se la mossa migliore supera l'attesa di `margine`.
    `ritmo` toglie un costo per ora di capitale bloccato (serve alla previsione diretta: nell'apprendimento per
    rinforzo il valore dell'attesa contiene già quel costo). Ritorna per ogni istante 0 (aspetta) o l'indice
    dell'orizzonte + 1."""
    ore = np.array(orizzonti or ORIZZONTI, dtype=np.float32)[:Q.shape[-1] - 1] / 60.0
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


def statistiche(T, n_crypto, n_istanti, passo=PASSO, n_orizzonti=None):
    """Riassunto di un insieme di operazioni (l'output di simula) su n_istanti decisioni per crypto."""
    if len(T) == 0:
        return {"n": 0, "media": 0.0, "dev": 0.0, "vinte": 0.0, "mediana": 0.0, "p10": 0.0, "somma": 0.0, "minuti": 0.0,
                "esposizione": 0.0, "al_giorno": 0.0, "protezione": 0.0, "orizzonti": [0] * (n_orizzonti or len(ORIZZONTI))}
    r = T[:, 3]
    giorni = n_istanti * passo / 1440.0
    hist = np.bincount(T[:, 2].astype(int), minlength=n_orizzonti or len(ORIZZONTI)).tolist()
    return {"n": int(len(T)), "media": float(r.mean()), "dev": float(r.std()), "vinte": float((r > 0).mean()), "mediana": float(np.median(r)),
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

    def con_costo(self, costo):
        """Gli stessi dati con un altro costo per lato: l'esito è (1-c)^2 x (rapporto dei prezzi) - 1, quindi si rifà
        senza ripassare i prezzi."""
        d = object.__new__(Dati)
        d.__dict__.update(self.__dict__)
        d.costo = costo
        d.R = np.where(self.OK, ((1.0 + self.R) / (1.0 - self.costo) ** 2) * (1.0 - costo) ** 2 - 1.0, 0.0).astype(np.float32)
        return d

    def indice(self, giorno):
        """Il primo istante di decisione dal giorno (con decimali) contato dall'inizio dei dati."""
        return int(np.searchsorted(self.K, giorno * 1440.0))

    def norm(self, X, media, dev):
        return np.clip((X - media) / dev, -6.0, 6.0).astype(np.float32)

    def statistiche_norm(self, i0, i1):
        x = self.X[:, i0:i1].reshape(-1, self.X.shape[-1])
        return x.mean(axis=0).astype(np.float32), np.maximum(x.std(axis=0), 1e-3).astype(np.float32)


def finestre(D, giorni_test=30, giorni_val=30, embargo=2, min_addestramento=100, max_finestre=6, margine_fine=2.0):
    """Le finestre mobili: per ognuna un periodo di addestramento, uno di scelta (il mese prima del test) e uno di
    test. Tra l'uno e l'altro c'è un intervallo di `embargo` giorni (l'esito di un'operazione guarda avanti fino a
    2 giorni: senza intervallo l'addestramento vedrebbe un pezzo del futuro del test)."""
    fine = D.giorni - margine_fine                                  # gli esiti lunghi dell'ultimo tratto mancano
    out = []
    for k in range(max_finestre):
        te1 = fine - k * giorni_test
        te0 = te1 - giorni_test
        va1 = te0 - embargo
        va0 = va1 - giorni_val
        tr1 = va0 - embargo
        if tr1 < min_addestramento + _avvio(D) / 1440.0:
            break
        out.append({"addestramento": (D.indice(_avvio(D) / 1440.0), D.indice(tr1)), "scelta": (D.indice(va0), D.indice(va1)),
                    "test": (D.indice(te0), D.indice(te1)), "giorni": (round(te0, 1), round(te1, 1))})
    return out[::-1]


# ---------------------------------------------------------------- come impara

def _bersagli_previsione(D, i0, i1):
    """Previsione diretta: l'uscita di ogni orizzonte è il guadagno netto; aspettare vale zero."""
    R, OK = D.R[:, i0:i1], D.OK[:, i0:i1]
    n = R.shape[0] * R.shape[1]
    Y = np.zeros((n, 1 + R.shape[-1]), np.float32)
    M = np.ones_like(Y)
    Y[:, 1:] = (R / ESCALA).reshape(n, -1)
    M[:, 1:] = OK.reshape(n, -1)
    return Y, M


def _bersagli_q(D, i0, i1, V, gamma=GAMMA, passo=None):
    """Apprendimento per rinforzo: il valore di una mossa è il guadagno netto dell'operazione più il valore,
    scontato, dello stato in cui si torna liberi (V, calcolato dalla rete dell'iterazione prima).
    Aspettare vale il valore scontato del quarto d'ora dopo. V ha forma (crypto, istanti)."""
    C, Ns, passo = D.C, i1 - i0, passo or _passo(D)
    R, LK, OK = D.R[:, i0:i1], D.LK[:, i0:i1], D.OK[:, i0:i1]
    Y = np.zeros((C, Ns, 1 + R.shape[-1]), np.float32)
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
    X = D.norm(D.X[:, i0:i1], media, dev).reshape(-1, D.X.shape[-1])
    Q = (rete.avanti(X) * ESCALA).reshape(D.C, i1 - i0, -1)
    out = {}
    for m in margini:
        for r in ritmi:
            T = simula(politica(Q, m, r, _oriz(D)), D.R[:, i0:i1], D.LK[:, i0:i1], D.FE[:, i0:i1], D.OK[:, i0:i1], _passo(D))
            out[(m, r)] = (T, statistiche(T, D.C, i1 - i0, _passo(D), len(_oriz(D))))
    return Q, out


MARGINI = (0.0, 0.0005, 0.001, 0.002, 0.004)
T_MINIMA = 1.5          # per comprare, nel periodo di scelta il guadagno medio deve valere almeno 1,5 errori standard sopra zero
N_MINIMO = 20           # e basarsi su almeno 20 operazioni


def credibile(s):
    """Il risultato di un periodo di scelta: abbastanza operazioni e un guadagno netto medio positivo e non dovuto al caso."""
    return s["n"] >= N_MINIMO and s["media"] > 0 and s["media"] / (s["dev"] / math.sqrt(s["n"]) + 1e-12) >= T_MINIMA


def apprendi_q(D, tr, va, iterazioni=14, epoche=3, nascosti=(96, 48), seed=0, lr=1e-3, wd=1e-4, gamma=GAMMA,
               log=None, valuta=True):
    """Q-learning a iterazioni: a ogni giro la rete riconta il valore di ogni mossa con la rete del giro prima
    (la "memoria" è la storia intera del periodo di addestramento) e la rifà imparare. Dopo ogni iterazione si
    guarda come va la sua politica sul periodo di scelta: è la curva di apprendimento. Ritorna la rete scelta
    (l'iterazione con il risultato migliore nel periodo di scelta, margine medio), le normalizzazioni e le curve."""
    i0, i1 = tr
    media, dev = D.statistiche_norm(i0, i1)
    nf, no = D.X.shape[-1], 1 + len(_oriz(D))
    Xt = D.norm(D.X[:, i0:i1], media, dev).reshape(-1, nf)
    rete = Rete([nf, *nascosti, no], seed)
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
                riga["m%g" % m] = {"n": s["n"], "media": s["media"], "dev": s["dev"], "somma": s["somma"],
                                   "orizzonti": s["orizzonti"], "minuti": s["minuti"]}
        curve.append(riga)
        if log:
            s = riga.get("m0.001", {})
            log("   Q iter %2d: errore %.4f · V medio %+.4f · scelta (margine 0,1 %%): %d operazioni, media %+.3f %%" % (
                it + 1, perdite[-1], riga["valore_medio"], s.get("n", 0), 100 * s.get("media", 0.0)))
        if valuta:                                                      # il migliore (iterazione, margine) del periodo di scelta, se credibile
            for m in MARGINI:
                c = riga["m%g" % m]
                if credibile(c) and (migliore is None or c["somma"] > migliore[0]):
                    migliore = (c["somma"], it + 1, rete.copia(), m)
    if migliore is None:                                                # niente di credibile: la rete resta fuori
        return {"rete": rete.copia(), "media": media, "dev": dev, "curve": curve, "iterazione": iterazioni,
                "margine": float("inf"), "tipo": "q", "fuori": True}
    _, it_best, rete_best, margine = migliore
    return {"rete": rete_best, "media": media, "dev": dev, "curve": curve, "iterazione": it_best, "margine": margine,
            "tipo": "q", "fuori": False}


def apprendi_previsione(D, tr, va, epoche=14, nascosti=(96, 48), seed=0, lr=1e-3, wd=1e-4, log=None):
    """Previsione diretta: la rete prevede il guadagno netto di ogni orizzonte (regressione). Si tiene l'epoca
    con l'errore più basso nel periodo di scelta; margine e costo del tempo si scelgono sullo stesso periodo."""
    i0, i1 = tr
    media, dev = D.statistiche_norm(i0, i1)
    nf, no = D.X.shape[-1], 1 + len(_oriz(D))
    Xt = D.norm(D.X[:, i0:i1], media, dev).reshape(-1, nf)
    Yt, Mt = _bersagli_previsione(D, i0, i1)
    Xv = D.norm(D.X[:, va[0]:va[1]], media, dev).reshape(-1, nf)
    Yv, Mv = _bersagli_previsione(D, *va)
    rete = Rete([nf, *nascosti, no], seed)
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
    cand = [(s["somma"], m, r) for (m, r), (T, s) in ris.items() if credibile(s)]
    if not cand:
        return {"rete": rete_best, "media": media, "dev": dev, "curve": curve, "iterazione": e_best,
                "margine": float("inf"), "ritmo": 0.0, "tipo": "previsione", "fuori": True}
    scelta = max(cand)
    return {"rete": rete_best, "media": media, "dev": dev, "curve": curve, "iterazione": e_best, "margine": scelta[1],
            "ritmo": scelta[2], "tipo": "previsione", "fuori": False}


def su_misura(X, modello):
    """Le caratteristiche che il modello conosce: uno addestrato prima dei segnali nuovi usa solo le prime (quelle di
    allora), perché i segnali nuovi sono aggiunti in fondo."""
    return X[..., :len(modello["media"])]


def decisioni(modello, D, i0, i1):
    """Le azioni (0 aspetta, altrimenti orizzonte + 1) di un modello su [i0, i1), per ogni crypto."""
    X = D.norm(su_misura(D.X[:, i0:i1], modello), modello["media"], modello["dev"]).reshape(D.C * (i1 - i0), -1)
    Q = (modello["rete"].avanti(X) * ESCALA).reshape(D.C, i1 - i0, -1)
    return politica(Q, modello["margine"], modello.get("ritmo", 0.0), _oriz(D)), Q


# ---------------------------------------------------------------- la probabilità di guadagno: scegliere le operazioni che chiudono in guadagno

QUOTE = (0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2)     # le soglie che si provano: il meglio x % delle occasioni del periodo di scelta
FASCE = (0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 1.0)            # fasce di probabilità stimata, per vedere se la stima è giusta


def sigmoide(z):
    return (1.0 / (1.0 + np.exp(-np.clip(z, -30.0, 30.0)))).astype(np.float32)


def _entropia(p, y, m):
    return -(y * np.log(p + 1e-7) + (1.0 - y) * np.log(1.0 - p + 1e-7)) * m


def addestra_probabilita(rete, X, Y, Mk, epoche, lr=1e-3, wd=1e-4, batch=2048, rng=None):
    """Entropia incrociata sui soli esiti validi (Mk = 1): l'uscita j della rete è il logit della probabilità che
    comprando adesso e tenendo l'orizzonte j si chiuda in guadagno dopo i costi. Ritorna l'errore di ogni epoca."""
    rng = rng or np.random.default_rng(0)
    ott = Adam(rete, lr, wd)
    n, perdite = len(X), []
    for e in range(epoche):
        ordine = rng.permutation(n)
        tot, peso = 0.0, 0.0
        for a in range(0, n, batch):
            idx = ordine[a:a + batch]
            z, att = rete.avanti(X[idx], tieni=True)
            p, y, m = sigmoide(z), Y[idx], Mk[idx]
            s = max(float(m.sum()), 1.0)
            tot += float(_entropia(p, y, m).sum())
            peso += s
            gW, gb = rete.indietro(att, ((p - y) * m / s).astype(np.float32))
            ott.passo(gW, gb)
        perdite.append(tot / max(peso, 1.0))
    return perdite


def _bersagli_probabilita(D, i0, i1):
    """1 se l'operazione (comprare all'istante, tenere l'orizzonte) chiude in guadagno dopo i costi, 0 se no."""
    R, OK = D.R[:, i0:i1], D.OK[:, i0:i1]
    n = R.shape[0] * R.shape[1]
    return (R > 0).reshape(n, -1).astype(np.float32), OK.reshape(n, -1).astype(np.float32)


def probabilita(modello, D, i0, i1):
    """Le probabilità di chiudere in guadagno, per crypto (o titolo), istante e orizzonte: array (C, istanti, orizzonti)."""
    X = D.norm(su_misura(D.X[:, i0:i1], modello), modello["media"], modello["dev"]).reshape(D.C * (i1 - i0), -1)
    return sigmoide(modello["rete"].avanti(X)).reshape(D.C, i1 - i0, -1)


def politica_probabilita(P, soglia):
    """Compra dove l'orizzonte con la probabilità più alta arriva alla soglia, e tiene quell'orizzonte."""
    return np.where(P.max(axis=-1) >= soglia, P.argmax(axis=-1) + 1, 0)


MEMORIE = (None, 90.0, 30.0)                  # mezza vita dei pesi per recenza, in giorni (None: tutto il passato conta uguale)


def pesi_recenza(D, i0, i1, mezza_vita):
    """Un peso per ogni campione (crypto x istante) di [i0, i1): 1 per il più recente, la metà ogni `mezza_vita` giorni
    più indietro (López de Prado, "Advances in Financial Machine Learning", cap. 4). None: tutti 1."""
    n = D.C * (i1 - i0)
    if mezza_vita is None:
        return np.ones(n, np.float32)
    eta = (D.K[i1 - 1] - D.K[i0:i1]) / 1440.0
    w = (0.5 ** (eta / mezza_vita)).astype(np.float32)
    return np.broadcast_to(w, (D.C, i1 - i0)).reshape(n)


def apprendi_probabilita(D, tr, va, epoche=8, nascosti=(64, 32), seed=0, lr=1e-3, wd=1e-4, log=None, memorie=None):
    """La rete impara, da tutte le operazioni possibili del periodo di addestramento e dal loro esito, quali chiudono in
    guadagno. Si tiene l'epoca che stima meglio le operazioni del periodo di scelta (mai viste); poi, sullo stesso periodo,
    si sceglie quante delle occasioni migliori prendere (le soglie di QUOTE): quella con la media per operazione più alta,
    su almeno N_MINIMO operazioni. Il cancello (credibile) dice se quella scelta era un guadagno credibile; il robot la
    usa comunque, la verifica a finestre la misura sul periodo dopo."""
    i0, i1 = tr
    media, dev = D.statistiche_norm(i0, i1)
    nf, H = D.X.shape[-1], len(_oriz(D))
    Xt = D.norm(D.X[:, i0:i1], media, dev).reshape(-1, nf)
    Yt, Mt = _bersagli_probabilita(D, i0, i1)
    Xv = D.norm(D.X[:, va[0]:va[1]], media, dev).reshape(-1, nf)
    Yv, Mv = _bersagli_probabilita(D, *va)
    base = np.clip((Yt * Mt).sum(axis=0) / np.maximum(Mt.sum(axis=0), 1.0), 1e-4, 1 - 1e-4)
    curve, migliore = [], None
    giorni_tr = (D.K[i1 - 1] - D.K[i0]) / 1440.0
    memorie = MEMORIE if memorie is None else memorie
    for mv in memorie:                                       # quanto contano i dati recenti: lo sceglie il periodo di scelta
        if mv is not None and mv * 2 > giorni_tr:
            continue
        rete = Rete([nf, *nascosti, H], seed)
        rete.b[-1][:] = np.log(base / (1.0 - base)).astype(np.float32)      # si parte dalla frequenza di ogni orizzonte
        rng = np.random.default_rng(seed)
        Mw = Mt * pesi_recenza(D, i0, i1, mv)[:, None]
        for e in range(epoche):
            perdite = addestra_probabilita(rete, Xt, Yt, Mw, 1, lr=lr * (0.8 ** (e // 3)), wd=wd, rng=rng)
            errore_v = float(_entropia(sigmoide(rete.avanti(Xv)), Yv, Mv).sum() / max(float(Mv.sum()), 1.0))
            curve.append({"memoria": mv, "epoca": e + 1, "errore": perdite[-1], "errore_scelta": errore_v})
            if log:
                log("   probabilità (memoria %s) epoca %2d: errore %.4f · scelta %.4f" % (mv, e + 1, perdite[-1], errore_v))
            if migliore is None or errore_v < migliore[0]:
                migliore = (errore_v, e + 1, rete.copia(), mv)
    _, e_best, rete_best, memoria = migliore
    m = {"rete": rete_best, "media": media, "dev": dev, "curve": curve, "iterazione": e_best, "tipo": "probabilita",
         "base": base.tolist(), "memoria": memoria}
    P = probabilita(m, D, *va)
    pm = P.max(axis=-1)
    prove = []
    for q in QUOTE:
        soglia = float(np.quantile(pm, 1.0 - q))
        s = statistiche(esegui(D, politica_probabilita(P, soglia), *va), D.C, va[1] - va[0], _passo(D), H)
        prove.append({"quota": q, "soglia": soglia, "n": s["n"], "media": s["media"], "dev": s["dev"], "vinte": s["vinte"],
                      "somma": s["somma"]})
    scelta = max([p for p in prove if p["n"] >= N_MINIMO] or prove, key=lambda p: p["media"])
    m.update({"soglia": scelta["soglia"], "quota": scelta["quota"], "prove": prove, "fuori": not credibile(scelta),
              "scelta": {k: scelta[k] for k in ("n", "media", "vinte", "somma")}})
    return m


# ---------------------------------------------------------------- quali segnali sono legati a quello che succede dopo

def _ranghi(x):
    o = np.argsort(x, kind="stable")
    r = np.empty(len(x), np.float64)
    r[o] = np.arange(len(x))
    return r


def _corr(a, b):
    a, b = a - a.mean(), b - b.mean()
    d = math.sqrt(float((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / d) if d > 0 else 0.0


def studio_segnali(D, nomi, periodi, costo, separa, fonti=None, n_max=400_000, seme=0):
    """Per ogni segnale (colonna di D.X): la correlazione di rango con l'esito netto di ogni orizzonte in ogni periodo
    (periodi: [(nome, primo istante)], per esempio l'ultimo anno, mese, settimana, giorno), l'orizzonte e il verso in cui
    conta di più (scelti sui dati prima di `separa`) e una prova fuori campione: comprando dopo `separa` solo quando il
    segnale è nel decimo migliore per quel verso (soglia presa dai dati prima), una posizione alla volta, cosa sarebbe
    successo. Ritorna una lista ordinata per forza del legame nel periodo più lungo."""
    Dc = D.con_costo(costo)
    H = len(_oriz(D))
    rng = np.random.default_rng(seme)
    out = []
    for f, nome in enumerate(nomi):
        riga = {"nome": nome, "fonte": (fonti or {}).get(nome), "ic": {}}
        for pn, i0 in periodi:
            x = Dc.X[:, i0:, f].reshape(-1)
            if x.std() == 0:
                riga["ic"][pn] = [0.0] * H
                continue
            vals = []
            for h in range(H):
                ok = Dc.OK[:, i0:, h].reshape(-1)
                xa, ra = x[ok], Dc.R[:, i0:, h].reshape(-1)[ok]
                if len(xa) > n_max:
                    sel = rng.choice(len(xa), n_max, replace=False)
                    xa, ra = xa[sel], ra[sel]
                vals.append(_corr(_ranghi(xa), _ranghi(ra)) if len(xa) > 30 else 0.0)
            riga["ic"][pn] = vals
        # orizzonte e verso dai dati prima di `separa` (il periodo più lungo, senza la parte finale)
        i0 = periodi[0][1]
        x_prima = Dc.X[:, i0:separa, f]
        if x_prima.std() == 0 or separa <= i0:
            riga.update({"orizzonte": None, "verso": 0, "prova": None})
            out.append(riga)
            continue
        ic_prima = []
        for h in range(H):
            ok = Dc.OK[:, i0:separa, h].reshape(-1)
            xa, ra = x_prima.reshape(-1)[ok], Dc.R[:, i0:separa, h].reshape(-1)[ok]
            if len(xa) > n_max:
                sel = rng.choice(len(xa), n_max, replace=False)
                xa, ra = xa[sel], ra[sel]
            ic_prima.append(_corr(_ranghi(xa), _ranghi(ra)) if len(xa) > 30 else 0.0)
        h_best = int(np.argmax(np.abs(ic_prima)))
        verso = 1 if ic_prima[h_best] >= 0 else -1
        soglia = float(np.quantile(x_prima, 0.9 if verso > 0 else 0.1))
        xd = Dc.X[:, separa:, f]
        az = np.where((xd >= soglia) if verso > 0 else (xd <= soglia), h_best + 1, 0)
        st = statistiche(esegui(Dc, az, separa, Dc.N), D.C, Dc.N - separa, _passo(D), H)
        riga.update({"orizzonte": _oriz(D)[h_best], "verso": verso, "ic_prima": ic_prima[h_best],
                     "prova": {"n": st["n"], "vinte": st["vinte"], "media": st["media"]}})
        out.append(riga)
    forza = lambda r: max((abs(v) for v in r["ic"][periodi[0][0]]), default=0.0)
    return sorted(out, key=forza, reverse=True)


def calibrazione(pp, rr, fasce=FASCE):
    """Per fasce di probabilità stimata: quante occasioni, la stima media, quante hanno chiuso in guadagno davvero e il
    guadagno medio. Se la rete sa scegliere, nelle fasce alte si vince di più."""
    pp, rr = np.asarray(pp, dtype=np.float64), np.asarray(rr, dtype=np.float64)
    out = []
    for lo, hi in zip(fasce[:-1], fasce[1:]):
        m = (pp >= lo) & ((pp < hi) if hi < 1.0 else (pp <= hi))
        n = int(m.sum())
        out.append({"da": lo, "a": hi, "n": n, "stimata": float(pp[m].mean()) if n else None,
                    "vinte": float((rr[m] > 0).mean()) if n else None, "media": float(rr[m].mean()) if n else None})
    return out


def valuta_probabilita(D, wins, costo, log=None, seme=0):
    """Fuori campione, finestra per finestra: la rete della probabilità di guadagno con la soglia scelta sul periodo di
    scelta (come la usa il robot), le stesse quote provate sul test, e la calibrazione delle stime su tutte le occasioni."""
    Dc = D.con_costo(costo)
    out = {"finestre": [], "strategie": {"probabilita": []}, "scelte": []}
    per_quota = {q: [] for q in QUOTE}
    pp, rr = [], []
    for k, w in enumerate(wins):
        i0, i1 = w["test"]
        m = apprendi_probabilita(Dc, w["addestramento"], w["scelta"], seed=seme + k)
        P = probabilita(m, Dc, i0, i1)
        T = esegui(Dc, politica_probabilita(P, m["soglia"]), i0, i1)
        out["strategie"]["probabilita"].append(T)
        out["finestre"].append({"giorni": w["giorni"], "test": (i0, i1)})
        out["scelte"].append({"fuori": m["fuori"], "epoca": m["iterazione"], "soglia": m["soglia"], "quota": m["quota"],
                              "scelta": m["scelta"]})
        for prova in m["prove"]:
            per_quota[prova["quota"]].append(esegui(Dc, politica_probabilita(P, prova["soglia"]), i0, i1))
        j = P.argmax(axis=-1)[..., None]
        ok = np.take_along_axis(Dc.OK[:, i0:i1], j, axis=-1)[..., 0]
        pp.append(P.max(axis=-1)[ok])
        rr.append(np.take_along_axis(Dc.R[:, i0:i1], j, axis=-1)[..., 0][ok])
        if log:
            s = statistiche(T, D.C, i1 - i0, _passo(D), len(_oriz(D)))
            log("   probabilità: soglia %.3f (il meglio %.1f %%)%s · %d operazioni, in guadagno %.0f %%, media %+.3f %%" % (
                m["soglia"], 100 * m["quota"], "" if not m["fuori"] else " senza via libera", s["n"], 100 * s["vinte"], 100 * s["media"]))
    for q in QUOTE:
        out["strategie"]["quota_%g" % q] = per_quota[q]
    pp, rr = np.concatenate(pp), np.concatenate(rr)
    out["calibrazione"] = calibrazione(pp, rr)
    out["tutte"] = {"n": int(len(rr)), "vinte": float((rr > 0).mean()), "media": float(rr.mean()), "stimata": float(pp.mean())}
    return out


def blocco_probabilita(D, ris):
    """Il riassunto per il JSON (e l'app) di valuta_probabilita."""
    b = {"probabilita": riassumi(D, ris, "probabilita"), "scelte_probabilita": ris["scelte"],
         "calibrazione": ris["calibrazione"], "tutte": ris["tutte"], "per_quota": []}
    for q in QUOTE:
        st = riassumi(D, ris, "quota_%g" % q)
        b["per_quota"].append({"quota": q, "n": st["n"], "media": st["media"], "vinte": st["vinte"], "totale": st["totale"]})
    return b


def modello_probabilita(D, costo, seme=0, log=None, giorni_val=30, embargo=2, margine_fine=2.0):
    """La rete della probabilità che usa il robot: addestrata su tutti i dati tranne l'ultimo periodo, che serve a
    scegliere l'epoca e la soglia."""
    fine = D.giorni - margine_fine
    tr = (D.indice(_avvio(D) / 1440.0), D.indice(fine - giorni_val - 2 * embargo))
    va = (D.indice(fine - giorni_val - embargo), D.indice(fine - embargo))
    return apprendi_probabilita(D.con_costo(costo), tr, va, seed=seme, log=log)


def json_probabilita(m, data=None):
    """Il modello della probabilità per il JSON (pesi compresi: li usa il robot)."""
    return {"tipo": "probabilita", "fuori": m["fuori"], "iterazione": m["iterazione"], "soglia": m["soglia"], "quota": m["quota"],
            "scelta": m["scelta"], "prove": m["prove"], "base": m["base"], "addestrato": data, "memoria": m.get("memoria"),
            "media": m["media"].tolist(), "dev": m["dev"].tolist(), "rete": m["rete"].a_dizionario(5)}


def esperienza(storia, m, data, n_dati):
    """Una riga in più nel diario degli addestramenti (gli ultimi 60): cosa ha scelto la rete ogni volta che ha imparato."""
    riga = {"data": data, "dati": n_dati, "soglia": round(m["soglia"], 4), "quota": m["quota"], "fuori": m["fuori"],
            "memoria": m.get("memoria"),
            "n": m["scelta"]["n"], "vinte": round(m["scelta"]["vinte"], 4), "media": round(m["scelta"]["media"], 6)}
    storia = [r for r in (storia or []) if r.get("data") != data] + [riga]
    return storia[-60:]


# ---------------------------------------------------------------- riferimenti e verifica a finestre mobili

# da dove viene ogni segnale (per l'app): studi, libri, trader
FONTI_SEGNALI = {
    "rend_5": "rendimenti a più scale: momento e inversione (Jegadeesh 1990; Liu e Tsyvinski 2021)",
    "flusso_15": "squilibrio acquisti/vendite (Cont, Kukanov e Stoikov 2014)", "flusso_60": "squilibrio acquisti/vendite (Cont, Kukanov e Stoikov 2014)",
    "flusso_240": "squilibrio acquisti/vendite (Cont, Kukanov e Stoikov 2014)", "flusso_1440": "squilibrio acquisti/vendite (Cont, Kukanov e Stoikov 2014)",
    "log_sigma_ora": "volatilità (Corsi 2009)", "vol_1h_su_24h": "volatilità a più scale (Corsi 2009)", "vol_24h_su_7g": "volatilità a più scale (Corsi 2009)",
    "ora_sin": "ora del giorno (Eross e altri 2019)", "ora_cos": "ora del giorno (Eross e altri 2019)",
    "vwap_24h": "VWAP (Aziz, How to Day Trade for a Living)", "stagione_1h": "stagionalità oraria (Heston, Korajczyk e Sadka 2010)",
    "btc_5": "Bitcoin guida le altre crypto", "btc_60": "Bitcoin guida le altre crypto",
    "dal_giorno": "momento dentro la giornata (Gao e altri 2018)", "prima_mezzora": "prima mezz'ora (Gao e altri 2018; Wen e altri 2022)",
    "williams": "rottura di volatilità (Larry Williams)", "rottura_su_ieri": "massimo di ieri (Crabel)", "rottura_giu_ieri": "minimo di ieri (Crabel)",
    "g_anno": "momento di un anno (Moskowitz, Ooi e Pedersen 2012)", "g_mese": "momento di un mese (Liu e Tsyvinski 2021)",
    "g_settimana": "momento di una settimana (Liu e Tsyvinski 2021)", "g_giorno": "ritorno del giorno prima (Jegadeesh 1990)",
    "g_media200": "media di 200 giorni (Detzel e altri 2021)", "g_max52": "massimo di 52 settimane (George e Hwang 2004)",
    "g_rsi2": "RSI a 2 giorni (Connors e Raschke)", "g_nr7": "giornata stretta NR7 (Crabel)", "g_range_atr": "escursione di ieri sull'ATR (Crabel)",
    "g_vol_mese": "volatilità del mese (Corsi 2009)", "paura_avidita": "Fear & Greed (alternative.me)", "paura_avidita_7g": "Fear & Greed, variazione in 7 giorni",
    "notizie_volume": "quantità di notizie (GDELT; Tetlock 2007)", "notizie_tono": "tono delle notizie (GDELT; Tetlock 2007)",
    **segnali.FONTI_MOTORI,
}


def periodi_crypto(D, margine_fine=2.0):
    """Ultimo anno, mese, settimana e giorno con gli esiti già noti (gli orizzonti lunghi guardano avanti 2 giorni)."""
    fine = D.giorni - margine_fine
    return [(n, D.indice(max(fine - g, _avvio(D) / 1440.0))) for n, g in (("anno", 365), ("mese", 30), ("settimana", 7), ("giorno", 1))]


REGOLE_CRYPTO = ("ribasso", "momento", "sempre_1g", "williams", "prima_mezzora", "flusso", "btc_guida", "paura")


def az_regola(D, i0, i1, nome):
    """Regole fissate prima di guardare i risultati, per confronto. Tre semplici: un ribasso a 4 ore (rendimento a 4 ore
    sotto -2 volatilità: compra e tieni 4 ore), un rialzo a 1 giorno (sopra +1,5: tieni un giorno), comprare sempre e
    tenere un giorno. Cinque dai libri e dagli studi: la rottura di volatilità di Larry Williams (sopra l'apertura del
    giorno più metà dell'escursione di ieri, appena rotta: tieni 8 ore); il momento dentro la giornata (Gao e altri; Wen e
    altri: alle 23 UTC, se la prima mezz'ora del giorno è salita, tieni l'ultima ora); il flusso degli ordini (Cont e
    altri: acquisti a mercato insistenti e prezzo in salita nell'ultima ora, tieni un'ora); Bitcoin che guida (è salito
    nell'ultima ora, l'altra crypto non ancora: tieni un'ora); la paura estrema (Fear & Greed sotto 15 dopo un giorno
    di ribasso: tieni un giorno)."""
    X = D.X[:, i0:i1]
    F = NOMI_FEATURE.index
    az = np.zeros(X.shape[:2], dtype=int)
    if nome == "ribasso":
        az[X[:, :, F("rend_240")] < -2.0] = 1 + ORIZZONTI.index(240)
    elif nome == "momento":
        az[X[:, :, F("rend_1440")] > 1.5] = 1 + ORIZZONTI.index(1440)
    elif nome == "sempre_1g":
        az[:] = 1 + ORIZZONTI.index(1440)
    elif nome == "williams":
        w = X[:, :, F("williams")]
        az[(w > 0.0) & (w <= 0.25)] = 1 + ORIZZONTI.index(480)
    elif nome == "prima_mezzora":
        ora = ((D.M.t0 + 60.0 * D.K[i0:i1]) % 86400) / 3600.0
        sel = np.isclose(ora, 23.0)
        az[:, sel] = np.where(X[:, sel, F("prima_mezzora")] > 0.5, 1 + ORIZZONTI.index(60), 0)
    elif nome == "flusso":
        az[(X[:, :, F("flusso_60")] > 0.3) & (X[:, :, F("rend_60")] > 1.0)] = 1 + ORIZZONTI.index(60)
    elif nome == "btc_guida":
        az[(X[:, :, F("btc_60")] > 1.5) & (X[:, :, F("rend_60")] < 0.5)] = 1 + ORIZZONTI.index(60)
    elif nome == "paura":
        az[(X[:, :, F("paura_avidita")] < -1.4) & (X[:, :, F("rend_1440")] < -1.0)] = 1 + ORIZZONTI.index(1440)
    else:
        raise ValueError(nome)
    return az


def esegui(D, az, i0, i1):
    return simula(az, D.R[:, i0:i1], D.LK[:, i0:i1], D.FE[:, i0:i1], D.OK[:, i0:i1], _passo(D))


def _giorni(D, i0, i1):
    """I giorni (interi, dall'inizio dei dati) coperti da [i0, i1)."""
    return int(D.K[i0] // 1440), int(D.K[i1 - 1] // 1440) + 1


def regole_crypto(nomi=REGOLE_CRYPTO):
    return {n: (lambda D, i0, i1, n=n: az_regola(D, i0, i1, n)) for n in nomi}


def valuta_costo(D, wins, costo, iterazioni=14, epoche=3, log=None, seme=0, regole=None):
    """Tutte le finestre mobili per un costo: addestra le due reti, le prova sul test, mette a confronto le regole
    (di serie quelle delle crypto: {nome: funzione(D, i0, i1) -> azioni}). Ritorna per ogni strategia le operazioni
    di test di ogni finestra e le curve di apprendimento."""
    regole = regole_crypto() if regole is None else regole
    Dc = D.con_costo(costo)
    out = {"finestre": [], "strategie": {k: [] for k in ("q", "previsione", *regole)},
           "curve_q": [], "curve_previsione": [], "scelte": []}
    for k, w in enumerate(wins):
        i0, i1 = w["test"]
        if log:
            log(" finestra %d/%d: test giorni %s, addestramento %d giorni" % (k + 1, len(wins), w["giorni"], (D.K[w["addestramento"][1] - 1] - D.K[w["addestramento"][0]]) // 1440))
        mq = apprendi_q(Dc, w["addestramento"], w["scelta"], iterazioni=iterazioni, epoche=epoche, seed=seme + k)
        mp = apprendi_previsione(Dc, w["addestramento"], w["scelta"], seed=seme + k)
        az_q, _ = decisioni(mq, Dc, i0, i1)
        az_p, _ = decisioni(mp, Dc, i0, i1)
        T = {"q": esegui(Dc, az_q, i0, i1), "previsione": esegui(Dc, az_p, i0, i1)}
        for nome, f in regole.items():
            T[nome] = esegui(Dc, f(Dc, i0, i1), i0, i1)
        for nome, t in T.items():
            out["strategie"][nome].append(t)
        out["finestre"].append({"giorni": w["giorni"], "test": (i0, i1)})
        out["curve_q"].append(mq["curve"])
        out["curve_previsione"].append(mp["curve"])
        out["scelte"].append({"q": {"fuori": mq["fuori"], "iterazione": mq["iterazione"], "margine": mq["margine"]},
                              "previsione": {"fuori": mp["fuori"], "epoca": mp["iterazione"], "margine": mp["margine"]}})
        if log:
            st = {nome: statistiche(t, D.C, i1 - i0, _passo(D), len(_oriz(D))) for nome, t in T.items()}
            log("   Q: %s · %d operazioni, media %+.3f %% | previsione: %s · %d op., media %+.3f %% | %s" % (
                "FUORI" if mq["fuori"] else "dentro it.%d marg.%g" % (mq["iterazione"], mq["margine"]), st["q"]["n"], 100 * st["q"]["media"],
                "FUORI" if mp["fuori"] else "dentro", st["previsione"]["n"], 100 * st["previsione"]["media"],
                " · ".join("%s %+.3f %% (%d)" % (nome, 100 * st[nome]["media"], st[nome]["n"]) for nome in regole)))
    return out


def riassumi(D, ris, strategia):
    """Le operazioni di test di tutte le finestre messe insieme: statistiche, serie giornaliera, curva del conto."""
    tutte, giornaliera, per_finestra = [], [], []
    for T, w in zip(ris["strategie"][strategia], ris["finestre"]):
        i0, i1 = w["test"]
        g0, g1 = _giorni(D, i0, i1)
        serie = serie_giornaliera(T, D.K[i0:i1], D.M.t0, D.C, g0 + int(D.M.t0 // 86400), g1 + int(D.M.t0 // 86400))
        giornaliera.append(serie)
        per_finestra.append(statistiche(T, D.C, i1 - i0, _passo(D), len(_oriz(D))))
        if len(T):
            tutte.append(T)
    T = np.concatenate(tutte) if tutte else np.zeros((0, 6))
    g = np.concatenate(giornaliera) if giornaliera else np.zeros(0)
    n_istanti = sum(w["test"][1] - w["test"][0] for w in ris["finestre"])
    st = statistiche(T, D.C, n_istanti, _passo(D), len(_oriz(D)))
    st.update({"giorni": int(len(g)), "totale": float(g.sum()), "sharpe": float(g.mean() / g.std() * math.sqrt(365)) if g.std() > 0 else 0.0,
               "ic90": bootstrap_blocchi(g), "conto": np.round(np.cumsum(g), 5).tolist(), "per_finestra": per_finestra})
    return st


def ic_per_orizzonte(D, wins, costo=COSTO, seme=0):
    """Fuori campione: la correlazione di rango tra la previsione diretta e l'esito, per ogni orizzonte e finestra,
    e l'esito medio per quinti della previsione (messi insieme tutte le finestre)."""
    Dc = D.con_costo(costo)
    H = len(_oriz(D))
    ic, acc = [], [([], []) for _ in range(H)]
    rango = lambda x: np.argsort(np.argsort(x)) / max(len(x) - 1, 1)
    for k, w in enumerate(wins):
        mp = apprendi_previsione(Dc, w["addestramento"], w["scelta"], epoche=3, seed=seme + k)
        i0, i1 = w["test"]
        X = Dc.norm(Dc.X[:, i0:i1], mp["media"], mp["dev"]).reshape(-1, Dc.X.shape[-1])
        Q = mp["rete"].avanti(X) * ESCALA
        Rt, Ok = Dc.R[:, i0:i1].reshape(-1, H), Dc.OK[:, i0:i1].reshape(-1, H)
        riga = []
        for j in range(H):
            m = Ok[:, j]
            riga.append(float(np.corrcoef(rango(Q[m, 1 + j]), rango(Rt[m, j]))[0, 1]))
            acc[j][0].append(Q[m, 1 + j])
            acc[j][1].append(Rt[m, j])
        ic.append(riga)
    quinti = []
    for q, r in acc:
        q, r = np.concatenate(q), np.concatenate(r)
        o, n = np.argsort(q), len(q)
        quinti.append([float(r[o[a * n // 5:(a + 1) * n // 5]].mean()) for a in range(5)] + [float(r[o[int(n * 0.98):]].mean())])
    return {"orizzonti": list(_oriz(D)), "per_finestra": ic, "medio": np.mean(ic, axis=0).tolist(), "quinti": quinti}


def sovradattamento(D, wins, costo=COSTO, iterazioni=14, margine=0.001, seme=0, log=None):
    """Quello che la rete ha imparato dura? Per ogni finestra: la stessa rete (dopo tutte le iterazioni, margine fisso)
    sul periodo in cui ha imparato e su quello mai visto. Se impara il passato ma non il futuro, nel primo guadagna e nel
    secondo no: è sovradattamento. Ritorna, per ogni finestra, le statistiche di addestramento e di test."""
    Dc = D.con_costo(costo)
    out = []
    for k, w in enumerate(wins):
        m = apprendi_q(Dc, w["addestramento"], w["scelta"], iterazioni=iterazioni, seed=seme + k, valuta=False)
        riga = {}
        for nome, (i0, i1) in (("addestramento", w["addestramento"]), ("test", w["test"])):
            X = Dc.norm(Dc.X[:, i0:i1], m["media"], m["dev"]).reshape(-1, Dc.X.shape[-1])
            Q = (m["rete"].avanti(X) * ESCALA).reshape(Dc.C, i1 - i0, -1)
            T = esegui(Dc, politica(Q, margine, 0.0, _oriz(Dc)), i0, i1)
            riga[nome] = statistiche(T, Dc.C, i1 - i0, _passo(Dc), len(_oriz(Dc)))
        out.append(riga)
        if log:
            log("   finestra %d: addestramento %d operazioni, media %+.3f %% · test %d operazioni, media %+.3f %%" % (
                k + 1, riga["addestramento"]["n"], 100 * riga["addestramento"]["media"], riga["test"]["n"], 100 * riga["test"]["media"]))
    return out


def incondizionato(D, costo=COSTO):
    """Comprando a ogni quarto d'ora e tenendo h minuti: esito netto medio e quante volte si guadagna, per orizzonte."""
    Dc = D.con_costo(costo)
    out = []
    for j, h in enumerate(_oriz(D)):
        m = Dc.OK[:, :, j]
        r = Dc.R[:, :, j][m]
        out.append({"orizzonte": h, "media": float(r.mean()), "vinte": float((r > 0).mean()), "dev": float(r.std()),
                    "protezione": float(Dc.FE[:, :, j][m].mean())})
    return out


# ---------------------------------------------------------------- il muro dei costi, per orizzonte, dagli scambi

ORIZZONTI_SECONDI = (1, 5, 15, 60, 300, 900, 3600, 14400, 86400, 172800)


def studio_orizzonti(simboli=("BTC-EUR", "ETH-EUR", "SOL-EUR", "XRP-EUR", "DOGE-EUR", "DOT-EUR"), giorni=60, costo=COSTO):
    """Quanto si muove il prezzo in euro, dagli scambi veri di Kraken, a ogni orizzonte da 1 secondo a 2 giorni, e
    quante volte la mossa batte i costi di un'operazione completa (2 x costo): per ogni crypto, la mossa tipica
    (mediana del valore assoluto), la quota di mosse più grandi dei costi (in un verso o nell'altro) e la quota di
    rialzi più grandi dei costi (quelle in cui un acquisto avrebbe guadagnato). Include la quota di secondi in cui c'è
    stato almeno uno scambio: dove il prezzo non cambia, non c'è niente da fare."""
    muro = 2 * costo
    out = {"orizzonti": list(ORIZZONTI_SECONDI), "costo_per_lato": costo, "crypto": {}}
    for sym in simboli:
        g = giorni_continui(sym)[-giorni:]
        t, p, v, sd = carica_scambi(sym, g)
        durata = t[-1] - t[0]
        secondi = np.unique(np.floor(t).astype(np.int64))
        righe = []
        for h in ORIZZONTI_SECONDI:
            passo = max(5.0, h / 4.0)
            x = np.arange(t[0], t[-1] - h, passo)
            if len(x) > 1_500_000:
                x = x[:: int(math.ceil(len(x) / 1_500_000))]
            p0 = p[np.searchsorted(t, x, side="right") - 1]
            p1 = p[np.searchsorted(t, x + h, side="right") - 1]
            r = np.log(p1 / p0)
            righe.append({"mediana": float(np.median(np.abs(r))), "oltre": float((np.abs(r) > muro).mean()),
                          "rialzo_oltre": float((r > muro).mean()), "n": int(len(r))})
        out["crypto"][sym] = {"scambi_ora": float(len(t) / durata * 3600), "secondi_con_scambi": float(len(secondi) / durata),
                              "giorni": len(g), "per_orizzonte": righe}
    return out


# ---------------------------------------------------------------- tutto insieme: studia

def _pulisci(x):
    """Per il JSON: numpy -> numeri, infinito -> None."""
    if isinstance(x, dict):
        return {str(k): _pulisci(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_pulisci(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if (math.isinf(x) or math.isnan(x)) else float(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.ndarray):
        return _pulisci(x.tolist())
    return x


def modello_finale(D, costo, iterazioni=14, seme=0, log=None, giorni_val=30, embargo=2, margine_fine=2.0):
    """La rete che si usa davvero: addestrata su tutti i dati tranne l'ultimo mese, che serve a scegliere (iterazione e
    margine) con lo stesso cancello della verifica. Se nell'ultimo mese non c'è un guadagno credibile resta fuori."""
    fine = D.giorni - margine_fine
    tr = (D.indice(_avvio(D) / 1440.0), D.indice(fine - giorni_val - 2 * embargo))
    va = (D.indice(fine - giorni_val - embargo), D.indice(fine - embargo))
    m = apprendi_q(D.con_costo(costo), tr, va, iterazioni=iterazioni, seed=seme, log=log)
    return m


def studia(giorni=None, costi=(COSTO, 0.001, 0.0005, 0.0002), iterazioni=14, log=print, salva=True):
    t0 = time.time()
    try:                                                     # il diario degli addestramenti continua da quello di prima
        with open(MODELLO, encoding="utf-8") as fh:
            diario = json.load(fh).get("esperienza")
    except (OSError, ValueError):
        diario = None
    M = carica_mondo(max_giorni=giorni)
    D = Dati(M)
    wins = finestre(D)
    inizio = datetime.datetime.fromtimestamp(M.t0, datetime.timezone.utc).date()
    data = lambda g: (inizio + datetime.timedelta(days=int(g))).isoformat()
    ris = {"creato": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "dati": {"da": data(0), "a": data(M.n / 1440 - 1), "giorni": int(M.n / 1440), "crypto": M.simboli,
                    "scambi": "Kraken, in euro", "campioni": int(D.C * D.N)},
           "config": {"orizzonti": list(ORIZZONTI), "passo_minuti": PASSO, "costo_per_lato": COSTO, "k_stop": K_STOP,
                      "slip_protezione": SLIP_STOP, "gamma": GAMMA, "iterazioni": iterazioni, "nascosti": [96, 48],
                      "caratteristiche": NOMI_FEATURE, "t_minima": T_MINIMA, "n_minimo": N_MINIMO},
           "finestre": [{"test_da": data(w["giorni"][0]), "test_a": data(w["giorni"][1]), "giorni": list(w["giorni"])} for w in wins],
           "incondizionato": incondizionato(D), "costi": {}, "modelli": {}, "probabilita": {}}
    fine_dati = data(M.n / 1440 - 1)
    log("[rete] dati pronti: %d giorni, %d campioni, %d finestre (%.0f s)" % (ris["dati"]["giorni"], ris["dati"]["campioni"], len(wins), time.time() - t0))
    log("[rete] il muro dei costi, dagli scambi")
    ris["orizzonti_scambi"] = studio_orizzonti()
    log("[rete] informazione fuori campione della previsione, per orizzonte")
    ris["informazione"] = ic_per_orizzonte(D, wins)
    log("[rete] quali segnali sono legati a quello che succede dopo: ultimo anno, mese, settimana, giorno")
    ris["segnali"] = studio_segnali(D, NOMI_FEATURE, periodi_crypto(D), costi[0], D.indice(D.giorni - 2.0 - 30), FONTI_SEGNALI)
    log("[rete] sovradattamento: periodo di addestramento contro periodo mai visto")
    ris["sovradattamento"] = sovradattamento(D, wins, costi[0], iterazioni, log=log)
    for c in costi:
        log("[rete] costo %.2f %% per lato" % (100 * c))
        r = valuta_costo(D, wins, c, iterazioni=iterazioni, log=log)
        blocco = {nome: riassumi(D, r, nome) for nome in r["strategie"]}
        blocco["scelte"] = r["scelte"]
        if c == costi[0]:                                      # le curve di apprendimento: una per finestra, a costo pieno
            blocco["curve_q"] = [[{k: v for k, v in riga.items() if k in ("iterazione", "errore", "valore_medio", "m0.001", "m0")} for riga in cur]
                                 for cur in r["curve_q"]]
            blocco["curve_previsione"] = r["curve_previsione"]
        blocco.update(blocco_probabilita(D, valuta_probabilita(D, wins, c, log=log)))     # scegliere le operazioni vincenti
        ris["costi"]["%g" % c] = blocco
        mp = modello_probabilita(D, c)
        ris["probabilita"]["%g" % c] = json_probabilita(mp, fine_dati)
        if c == costi[0]:
            ris["esperienza"] = esperienza(diario, mp, fine_dati, int(M.n / 1440))
        m = modello_finale(D, c, iterazioni=iterazioni)
        ris["modelli"]["%g" % c] = {"tipo": "q", "fuori": m["fuori"], "iterazione": m["iterazione"], "margine": m["margine"],
                                    "media": m["media"].tolist(), "dev": m["dev"].tolist(), "rete": m["rete"].a_dizionario(5)}
        log("[rete] modello finale a %.2f %%: %s" % (100 * c, "resta fuori" if m["fuori"] else "iterazione %d, margine %g" % (m["iterazione"], m["margine"])))
        ris["durata_minuti"] = round((time.time() - t0) / 60, 1)
        if salva:                                              # dopo ogni costo: un errore più avanti non butta via il lavoro fatto
            with open(MODELLO, "w", encoding="utf-8") as fh:
                json.dump(_pulisci(ris), fh, separators=(",", ":"))
            log("[rete] scritto %s (%d KB, %.0f minuti)" % (os.path.basename(MODELLO), os.path.getsize(MODELLO) // 1024, (time.time() - t0) / 60))
    return ris


def aggiungi_probabilita(costi=(COSTO, 0.0005), giorni=None, log=print, solo_modello=False, percorso=None):
    """Aggiorna rete_modello.json senza rifare tutto lo studio: per ogni costo la verifica a finestre della scelta per
    probabilità di guadagno (salvo solo_modello) e il modello che usa il robot, addestrato con i dati di oggi; più una
    riga nel diario degli addestramenti. Con solo_modello=True è il riaddestramento di ogni sera (qualche minuto)."""
    percorso = percorso or MODELLO
    t0 = time.time()
    with open(percorso, encoding="utf-8") as fh:
        ris = json.load(fh)
    M = carica_mondo(max_giorni=giorni)
    D = Dati(M)
    fine_dati = datetime.datetime.fromtimestamp(M.t0 + 60.0 * (M.n - 1), datetime.timezone.utc).date().isoformat()
    log("[rete] probabilità di guadagno: %d giorni di scambi fino al %s (%.0f s)" % (int(M.n / 1440), fine_dati, time.time() - t0))
    ris.setdefault("probabilita", {})
    wins = None if solo_modello else finestre(D)
    if not solo_modello:                                                       # quali segnali contano, con quelli nuovi
        log("[rete] quali segnali sono legati a quello che succede dopo: anno, mese, settimana, giorno")
        ris["segnali"] = _pulisci(studio_segnali(D, NOMI_FEATURE, periodi_crypto(D), costi[0], D.indice(D.giorni - 2.0 - 30), FONTI_SEGNALI))
    for c in costi:
        chiave = "%g" % c
        if wins is not None and chiave in ris.get("costi", {}):
            log("[rete] verifica a finestre, costo %.2f %% per lato" % (100 * c))
            ris["costi"][chiave].update(_pulisci(blocco_probabilita(D, valuta_probabilita(D, wins, c, log=log))))
        m = modello_probabilita(D, c)
        ris["probabilita"][chiave] = _pulisci(json_probabilita(m, fine_dati))
        if c == costi[0]:
            ris["esperienza"] = _pulisci(esperienza(ris.get("esperienza"), m, fine_dati, int(M.n / 1440)))
        log("[rete] modello del robot a %.2f %%: compra dal %.1f %% stimato (il meglio %.1f %% delle occasioni)%s" % (
            100 * c, 100 * m["soglia"], 100 * m["quota"], "" if not m["fuori"] else ", senza via libera"))
        with open(percorso + ".tmp", "w", encoding="utf-8") as fh:            # dopo ogni costo, senza mai lasciare il file a metà
            json.dump(_pulisci(ris), fh, separators=(",", ":"))
        os.replace(percorso + ".tmp", percorso)
    log("[rete] scritto %s (%.0f minuti)" % (os.path.basename(percorso), (time.time() - t0) / 60))
    return ris


# ---------------------------------------------------------------- il modello finale, per chi lo usa dal vivo

def da_json(m):
    """Un modello scritto da studia(): la rete, le normalizzazioni, il margine (None = resta fuori = infinito); per il
    modello della probabilità anche la soglia e la quota."""
    out = {"rete": Rete.da_dizionario(m["rete"]), "media": np.array(m["media"], dtype=np.float32),
           "dev": np.array(m["dev"], dtype=np.float32), "margine": float("inf") if m.get("margine") is None else float(m["margine"]),
           "fuori": bool(m.get("fuori")), "iterazione": m.get("iterazione"), "tipo": m.get("tipo", "q"), "ritmo": 0.0}
    if out["tipo"] == "probabilita":
        out.update({"soglia": float(m["soglia"]), "quota": m.get("quota"), "addestrato": m.get("addestrato")})
    return out


def carica_probabilita(costo=None, percorso=MODELLO):
    """Il modello della probabilità di guadagno per quel costo per lato (il più alto se None), o None se non c'è.
    Ritorna (modello, costo)."""
    try:
        with open(percorso, encoding="utf-8") as fh:
            r = json.load(fh)
    except (OSError, ValueError):
        return None
    tutti = r.get("probabilita") or {}
    chiavi = sorted(tutti, key=float, reverse=True)
    k = (chiavi[0] if chiavi else None) if costo is None else next((x for x in chiavi if abs(float(x) - costo) < 1e-12), None)
    return (da_json(tutti[k]), float(k)) if k is not None else None


def carica_modello(costo=None, percorso=MODELLO):
    """Il modello finale di rete_modello.json per quel costo per lato (il più alto se None). Ritorna (modello, costo)."""
    with open(percorso, encoding="utf-8") as fh:
        r = json.load(fh)
    chiavi = sorted((k for k in r.get("modelli", {})), key=float, reverse=True)
    if not chiavi:
        raise ValueError("rete_modello.json non ha modelli: python3 rete.py --studia")
    k = chiavi[0] if costo is None else next((x for x in chiavi if abs(float(x) - costo) < 1e-12), None)
    if k is None:
        raise ValueError("nessun modello per il costo %g: ci sono %s" % (costo, ", ".join(chiavi)))
    return da_json(r["modelli"][k]), float(k)


def valori_a(modello, M, k):
    """I valori che il modello dà a ogni mossa adesso, per ogni crypto: array (crypto, 1 + orizzonti), in frazioni.
    k è il minuto (indice) in cui si decide: contano solo le barre prima di k."""
    P = Pronto(M)
    X = su_misura(caratteristiche(P, np.array([k]))[:, 0, :], modello)
    Xn = np.clip((X - modello["media"]) / modello["dev"], -6.0, 6.0).astype(np.float32)
    return modello["rete"].avanti(Xn) * ESCALA, sigma_ora(P, np.array([k]))[:, 0]


# ---------------------------------------------------------------- le operazioni della rete, minuto per minuto (per il robot)

_VOCE = {"probabilita": "probabilita", "q": "vantaggio", "previsione": "vantaggio", None: "vantaggio"}   # come si chiama il punteggio


def scelte_modello(modello, X, margine=None, orizzonti_ok=None):
    """Le decisioni di un modello su caratteristiche X (C, istanti, n): (azioni, punteggio). Per il Q-learning il punteggio
    è il vantaggio di comprare sull'attesa e si compra oltre il margine; per il modello della probabilità è la probabilità
    di chiudere in guadagno dell'orizzonte migliore e si compra dalla soglia (margine, se dato, la sostituisce)."""
    C, N = X.shape[:2]
    X = su_misura(X, modello)
    Xn = np.clip((X - modello["media"]) / modello["dev"], -6.0, 6.0).astype(np.float32).reshape(-1, X.shape[-1])
    out = modello["rete"].avanti(Xn).reshape(C, N, -1)
    if modello.get("tipo") == "probabilita":
        Pr = sigmoide(out)
        if orizzonti_ok is not None:                                           # solo le durate permesse
            Pr = np.where(np.asarray(orizzonti_ok)[None, None, :], Pr, 0.0).astype(np.float32)
        return politica_probabilita(Pr, modello["soglia"] if margine is None else margine), Pr.max(axis=-1)
    Q = out * ESCALA
    return politica(Q, modello["margine"] if margine is None else margine), Q[..., 1:].max(axis=-1) - Q[..., 0]


def rigioca(modello, M, k_da, k_a, margine=None, costo=COSTO, slip=SLIP_STOP, ogni=1, quota_minima=None, quota_ora=None,
            orizzonte_max=None):
    """Le operazioni che il modello fa decidendo ogni `ogni` minuti in [k_da, k_a), una posizione alla volta per crypto,
    come nell'addestramento: la decisione al minuto k usa solo le barre prima di k e si entra all'apertura di k; la
    protezione scatta sui minimi dei minuti (eseguita un po' peggio); si esce all'apertura del minuto in cui finisce
    l'orizzonte scelto. Le posizioni che a fine dati non sono ancora chiuse tornano tra le 'aperte', con protezione e
    scadenza, perché chi le segue dal vivo possa chiuderle. margine=None: quello del modello.
    Ritorna (operazioni chiuse, aperte, vantaggio dell'ultimo minuto per crypto)."""
    P = Pronto(M)
    K = np.arange(max(k_da, AVVIO), k_a, ogni)
    if len(K) == 0:
        return [], [], {}
    X = caratteristiche(P, K)
    sig = sigma_ora(P, K)
    ok = None if not orizzonte_max or modello.get("tipo") != "probabilita" else np.array([h <= orizzonte_max for h in ORIZZONTI])
    az, vantaggio = scelte_modello(modello, X, margine, ok)
    if quota_minima and modello.get("tipo") == "probabilita" and margine is None:
        # la soglia imparata può essere così alta che il robot non compra mai: allora prende almeno il meglio
        # `quota_minima` delle occasioni di questi giorni (sempre le più probabili secondo la rete)
        # e in ogni ora di ogni giorno il meglio `quota_ora` delle occasioni di quell'ora, così compra a tutte le ore
        ora = (M.t0 // 60 + K) // 60                                          # l'ora (dall'epoca) di ogni decisione
        S = np.full(len(K), min(modello["soglia"], float(np.quantile(vantaggio, 1.0 - quota_minima))))
        if quota_ora:
            for h in np.unique(ora):
                m = ora == h
                S[m] = np.minimum(S[m], float(np.quantile(vantaggio[:, m], 1.0 - quota_ora)))
        tutte, _ = scelte_modello(modello, X, 0.0, ok)
        az = np.where(vantaggio >= S[None, :], tutte, 0)
    iso = lambda k: datetime.datetime.fromtimestamp(M.t0 + 60.0 * k, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    chiuse, aperte = [], []
    for c, sym in enumerate(M.simboli):
        libero = 0
        for i in np.flatnonzero(az[c] > 0):
            k = int(K[i])
            if k < libero:
                continue
            h = ORIZZONTI[int(az[c, i]) - 1]
            entrata = float(M.o[c, k])
            stop = entrata * (1.0 - min(K_STOP * float(sig[c, i]) * math.sqrt(h / 60.0), 0.9))
            fine = k + h
            tocca = np.flatnonzero(M.l[c, k:min(fine, M.n)] <= stop)
            op = {"sym": sym, "t": iso(k), "prezzo": round(entrata, 8), "minuti": int(h), "protezione": round(stop, 8),
                  "scade": iso(fine), _VOCE[modello.get("tipo")]: round(float(vantaggio[c, i]), 6)}
            if len(tocca):
                kk = k + int(tocca[0])
                uscita, t_usc, motivo = min(stop, float(M.o[c, kk])) * (1.0 - slip), kk + 1, "protezione"
            elif fine <= M.n - 1:
                uscita, t_usc, motivo = float(M.o[c, fine]), fine, "scadenza"
            else:
                aperte.append(op)
                break                                          # aperta: finché non si chiude, niente altro su questa crypto
            op.update({"t_uscita": iso(t_usc), "prezzo_uscita": round(uscita, 8), "motivo": motivo,
                       "r": round((1.0 - costo) ** 2 * uscita / entrata - 1.0, 6)})
            chiuse.append(op)
            libero = t_usc
    chiuse.sort(key=lambda o: o["t"])
    return chiuse, aperte, {sym: round(float(vantaggio[c, -1]), 6) for c, sym in enumerate(M.simboli)}


# ---------------------------------------------------------------- a riga di comando

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ordini-limite", action="store_true",
                    help="gli ordini orari di intraday.py rigiocati sugli scambi veri (servono i dati di rete_dati.py)")
    ap.add_argument("--studia", action="store_true",
                    help="addestra e verifica la rete a finestre mobili, per più costi; scrive rete_modello.json")
    ap.add_argument("--sovradattamento", action="store_true",
                    help="aggiunge a rete_modello.json il confronto tra periodo di addestramento e periodo mai visto (qualche minuto)")
    ap.add_argument("--probabilita", action="store_true",
                    help="aggiunge a rete_modello.json la scelta delle operazioni per probabilità di guadagno: verifica a finestre e modello del robot")
    ap.add_argument("--robot", action="store_true",
                    help="riaddestra solo il modello della probabilità che usa il robot, con gli scambi fino a ieri (ogni sera, qualche minuto)")
    ap.add_argument("--costi", default=None, help="costi per lato da provare (di serie 0.002,0.001,0.0005,0.0002 con --studia, 0.002,0.0005 con --probabilita)")
    ap.add_argument("--iterazioni", type=int, default=14)
    ap.add_argument("--giorni", type=int, default=None, help="solo gli ultimi n giorni di dati")
    a = ap.parse_args(argv)
    costi = tuple(float(x) for x in a.costi.split(",")) if a.costi else None
    if a.studia:
        studia(a.giorni, costi or (COSTO, 0.001, 0.0005, 0.0002), a.iterazioni)
        return 0
    if a.probabilita or a.robot:
        aggiungi_probabilita(costi or ((COSTO,) if a.robot else (COSTO, 0.0005)), a.giorni, solo_modello=a.robot)
        return 0
    if a.sovradattamento:
        with open(MODELLO, encoding="utf-8") as fh:
            ris = json.load(fh)
        D = Dati(carica_mondo(max_giorni=a.giorni))
        ris["sovradattamento"] = _pulisci(sovradattamento(D, finestre(D), max(float(k) for k in ris["costi"]), a.iterazioni, log=print))
        with open(MODELLO, "w", encoding="utf-8") as fh:
            json.dump(ris, fh, separators=(",", ":"))
        print("[rete] aggiunto il sovradattamento a %s" % os.path.basename(MODELLO))
        return 0
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
