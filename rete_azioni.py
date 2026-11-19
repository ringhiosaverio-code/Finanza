#!/usr/bin/env python3
"""La rete neurale per le azioni italiane in giornata: compra durante la seduta e chiude al più tardi in chiusura.

    python3 rete_azioni.py --studia      # barre da 5 minuti (Yahoo, ultimi 60 giorni), addestra, verifica: rete_azioni_modello.json
    python3 rete_azioni.py --oggi        # le operazioni che la rete fa nelle ultime sedute (quelle che il robot rigioca)

Lo stesso ragionamento della rete delle crypto (rete.py), sui titoli del FTSE MIB: ogni 5 minuti, per ogni titolo, la rete
vede numeri che usano solo il passato (rendimenti da 5 minuti a 5 sedute, volatilità, apertura e salto dalla chiusura di
ieri, posizione nel minimo-massimo di oggi, volumi, ora del giorno, mercato intero) e dà un valore a ogni mossa: aspettare,
oppure comprare all'apertura della barra successiva e tenere 5, 15, 30 minuti, 1, 2, 4 ore o fino alla chiusura. Tutto
si chiude entro la seduta (09:00-17:30): niente posizioni di notte. Protezione sotto l'entrata, costi per lato (commissione
e spread: per chi compra e vende nello stesso giorno la Tobin tax non si paga, conta il saldo di fine giornata).

Impara con il Q-learning di rete.py e si verifica a finestre mobili come le crypto, con i dati che Yahoo dà gratis: 5
minuti per gli ultimi 60 giorni (circa 60 sedute). Sono pochi: la verifica dice quanto poco. Le quotazioni di Milano
gratuite arrivano con 15 minuti di ritardo. Solo numpy e la libreria standard. Non è consulenza finanziaria.
"""

import argparse
import datetime
import json
import math
import os
import sys
import time
import types
import urllib.request
from zoneinfo import ZoneInfo

import numpy as np

import rete
import segnali
import settimana

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "trader", "cache", "rete_azioni")
MODELLO = os.path.join(ROOT, "rete_azioni_modello.json")
UA = "Mozilla/5.0 (finanza-rete-azioni)"
ROMA = ZoneInfo("Europe/Rome")
BARRA = 5                                       # minuti per barra
BARRE = 102                                     # barre in una seduta: 09:00-17:30
APRE = 9 * 60                                   # minuti dalla mezzanotte, ora italiana
PRIMA = 2                                       # si decide dalla terza barra (09:10): servono due barre di oggi
SEDUTE_STORIA = 5                               # sedute di storia per le caratteristiche
ORIZZONTI = (5, 15, 30, 60, 120, 240, 510)      # minuti; 510 = fino alla chiusura
COSTO = 0.001                                   # per lato: commissione e spread
SLIP = 0.0005                                   # la protezione si esegue un po' peggio del livello
SIGMA_MIN = 0.0005
RITARDI = (1, 3, 6, 12, 24, 48, 102, 204, 510)  # in barre: da 5 minuti a 5 sedute
NOMI_FEATURE = (["rend_%d" % L for L in RITARDI] + ["log_sigma_ora", "vol_2h_su_5g", "oggi", "salto", "pos_oggi",
                 "da_ieri", "minuti", "minuti_sin", "minuti_cos", "sett_sin", "sett_cos", "volume_1h", "mercato_1h",
                 "mercato_seduta", "relativo_seduta"]
                # i segnali della ricerca e dei libri (vedi segnali.py): opening range (Crabel; Zarattini e Aziz), volume
                # relativo ("stocks in play"), VWAP (Aziz), prima mezz'ora (Gao e altri), stagionalità della stessa
                # mezz'ora (Heston, Korajczyk e Sadka)...
                + ["sopra_or", "sotto_or", "ampiezza_or", "volume_relativo", "vwap_oggi", "prima_mezzora", "stagione_30m"]
                # ...anno, mese, settimana, giorno e gli altri dalle chiusure giornaliere, salto della notte sull'ATR
                # (Chan, buy-on-gap; Lou, Polk e Skouras) e le notizie sulla Borsa di Milano
                + ["g_" + n for n in segnali.NOMI_GIORNALIERI] + ["salto_atr"] + list(segnali.NOMI_NOTIZIE)
                # i segnali della skill trader-scanner (in fondo: i modelli di prima usano solo i loro)
                + list(segnali.NOMI_SCANNER))
N_FEATURE = len(NOMI_FEATURE)
N_BASE = NOMI_FEATURE.index("sopra_or")
BARRE_OR = 3                                    # opening range: i primi 15 minuti
SEDUTE_STAGIONE = 10                            # stagionalità e volume relativo: le ultime 10 sedute


# ---------------------------------------------------------------- dati: barre da 5 minuti di Yahoo

def scarica(sym, max_age=600, intervallo="5m", periodo="60d"):
    """Le barre di Yahoo (aperture in secondi UTC, apertura, massimo, minimo, chiusura, volume), dalla cache se recente."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, "%s-%s.json" % (sym, intervallo))
    if not os.path.exists(path) or time.time() - os.path.getmtime(path) > max_age:
        url = "https://query2.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=%s" % (sym, periodo, intervallo)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=40) as r:
            testo = r.read().decode("utf-8", "replace")
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            fh.write(testo)
        os.replace(path + ".tmp", path)
    with open(path, encoding="utf-8") as fh:
        res = json.load(fh)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    righe = [(t, o, h, l, c, v or 0) for t, o, h, l, c, v in zip(res["timestamp"], q["open"], q["high"], q["low"], q["close"], q["volume"])
             if None not in (o, h, l, c)]
    return archivia(sym, righe) if intervallo == "5m" else righe


def archivia(sym, righe, cartella=None):
    """Yahoo dà le barre da 5 minuti solo degli ultimi 60 giorni: qui si tengono tutte quelle già viste, così ogni giorno
    la rete ha una seduta in più da cui imparare. Le barre nuove vincono su quelle vecchie (l'ultima della seduta in
    corso cambia finché non è chiusa). Ritorna tutte le barre, in ordine."""
    cartella = cartella or os.path.join(CACHE, "archivio")
    os.makedirs(cartella, exist_ok=True)
    path = os.path.join(cartella, "%s.npz" % sym)
    unite = {}
    if os.path.exists(path):
        try:
            with np.load(path) as z:
                unite = {int(t): (int(t), float(o), float(h), float(l), float(c), float(v))
                         for t, o, h, l, c, v in zip(z["t"], z["o"], z["h"], z["l"], z["c"], z["v"])}
        except (OSError, ValueError, KeyError):                                  # archivio rovinato: si riparte
            unite = {}
    unite.update({int(r[0]): (int(r[0]), *map(float, r[1:])) for r in righe})
    out = [unite[t] for t in sorted(unite)]
    if out:
        a = np.array(out, dtype=np.float64)
        np.savez_compressed(path + ".tmp.npz", t=a[:, 0], o=a[:, 1], h=a[:, 2], l=a[:, 3], c=a[:, 4], v=a[:, 5])
        os.replace(path + ".tmp.npz", path)
    return out


class Barre:
    """Le barre di tutti i titoli sulla stessa griglia: sedute x 102 barre (09:00-17:25), in ora italiana. Dove un titolo
    non ha scambi la barra resta al prezzo di prima con volume zero. `vera` dice quali barre ci sono davvero (l'ultima
    seduta può essere a metà)."""

    def __init__(self, simboli, righe_per_simbolo):
        giorni = sorted({datetime.datetime.fromtimestamp(t, ROMA).date() for righe in righe_per_simbolo for t, *_ in righe})
        self.simboli, self.giorni = list(simboli), giorni
        S, C = len(giorni), len(simboli)
        pos = {g: k for k, g in enumerate(giorni)}
        inizio = [datetime.datetime(g.year, g.month, g.day, 9, 0, tzinfo=ROMA).timestamp() for g in giorni]
        self.T = (np.array(inizio)[:, None] + 60.0 * BARRA * np.arange(BARRE)[None, :]).reshape(-1)   # inizio di ogni barra, UTC
        self.t0 = float(datetime.datetime(giorni[0].year, giorni[0].month, giorni[0].day, tzinfo=datetime.timezone.utc).timestamp())
        self.K = (self.T - self.t0) / 60.0                                           # minuti dalla mezzanotte UTC del primo giorno
        A = {k: np.full((C, S * BARRE), np.nan) for k in "ohlc"}
        V = np.zeros((C, S * BARRE))
        for c, righe in enumerate(righe_per_simbolo):
            for t, o, h, l, cl, v in righe:
                d = datetime.datetime.fromtimestamp(t, ROMA)
                j = (d.hour * 60 + d.minute - APRE) // BARRA
                if 0 <= j < BARRE and d.date() in pos:
                    g = pos[d.date()] * BARRE + j
                    A["o"][c, g], A["h"][c, g], A["l"][c, g], A["c"][c, g], V[c, g] = o, h, l, cl, v
        self.vera = ~np.isnan(A["c"])
        for c in range(C):                                                           # dove manca, il prezzo di prima
            ultimo = np.maximum.accumulate(np.where(self.vera[c], np.arange(S * BARRE), -1))
            primo = int(np.argmax(self.vera[c])) if self.vera[c].any() else 0
            ultimo[ultimo < 0] = primo
            chiusura = A["c"][c][ultimo]
            chiusura[:primo] = A["o"][c][primo]
            for k in "ohlc":
                A[k][c] = np.where(self.vera[c], A[k][c], chiusura)
        self.o, self.h, self.l, self.c, self.v = A["o"], A["h"], A["l"], A["c"], V
        self.S, self.C, self.n = S, C, S * BARRE
        # l'ultima barra vera di ogni titolo e in tutto (le sedute di oggi possono essere a metà)
        self.ultima = int(max(np.flatnonzero(self.vera.any(axis=0)))) if self.vera.any() else -1


def carica(simboli=None, max_age=600, log=print):
    simboli = list(simboli or settimana.MERCATI["italia"]["universo"])
    ok, righe = [], []
    for s in simboli:
        try:
            r = scarica(s, max_age)
        except Exception as e:                                                       # rete o titolo senza barre: si salta
            log("[rete_azioni] %s saltato: %s" % (s, str(e)[:80]))
            continue
        if len(r) > 500:
            ok.append(s)
            righe.append(r)
    if not ok:
        raise ValueError("nessun titolo con barre da 5 minuti")
    return Barre(ok, righe)


# ---------------------------------------------------------------- caratteristiche ed esiti

def esterni_azioni(B):
    """Per titolo e seduta (del giorno prima, già chiuso): i segnali giornalieri di segnali.py, l'ATR a 14 giorni e le
    notizie sulla Borsa di Milano. Si calcolano una volta per insieme di barre."""
    if getattr(B, "_esterni", None) is not None:
        return B._esterni
    giorni = [g.isoformat() for g in B.giorni]
    ng = len(segnali.NOMI_GIORNALIERI)
    tab = np.zeros((B.C, B.S, ng), np.float32)
    sc = np.zeros((B.C, B.S, len(segnali.NOMI_SCANNER)), np.float32)
    atr = np.zeros((B.C, B.S), np.float32)
    for c, sym in enumerate(B.simboli):
        gg, o, h, l, cl = segnali.giornaliere(sym, "Europe/Rome", (17, 35))
        if len(gg):
            tab[c] = segnali.per_giorno(gg, segnali.tabella_giornaliera(o, h, l, cl), giorni)
            atr[c] = segnali.per_giorno(gg, segnali.atr_giornaliero(o, h, l, cl)[:, None], giorni)[:, 0]
            sc[c] = segnali.per_giorno(gg, segnali.tabella_scanner(cl), giorni)
    notizie = segnali.notizie_per_giorno(segnali.notizie(
        "borsa_milano", '("Piazza Affari" OR "Borsa di Milano" OR "FTSE MIB") sourcelang:italian', log=lambda m: None), giorni)
    B._esterni = (tab, atr, notizie, sc)
    return B._esterni


def segnali_azioni(B, G, sig, lc, s0, hi, lo, vc):
    """I segnali della ricerca per ogni titolo e barra di decisione G: solo barre prima di G e giorni già chiusi."""
    C, N = B.C, len(G)
    ult = G - 1
    j = G - s0                                                                   # barre di oggi già chiuse
    cK = B.c[:, ult]
    s15 = sig * math.sqrt(BARRE_OR * BARRA / 60.0)
    out = []
    # opening range dei primi 15 minuti (o di quelli già passati): sopra il massimo, sotto il minimo, quanto è largo
    fine_or = s0 + np.minimum(j, BARRE_OR) - 1
    hor, lor = hi[:, fine_or], lo[:, fine_or]
    out.append(np.clip(np.log(cK / hor) / s15, -8, 8))
    out.append(np.clip(np.log(cK / lor) / s15, -8, 8))
    out.append(np.clip(np.log(np.maximum(hor / lor, 1.0 + 1e-9)) / s15, 0, 10))
    # volume relativo: il volume di oggi fin qui contro quello delle ultime sedute alla stessa ora (stocks in play)
    oggi = vc[:, G] - vc[:, s0]
    somma, quante = np.zeros((C, N)), np.zeros(N)
    for d in range(1, SEDUTE_STAGIONE + 1):
        a = s0 - d * BARRE
        ok = a >= 0
        aa = np.where(ok, a, 0)
        somma += np.where(ok, vc[:, aa + j] - vc[:, aa], 0.0)
        quante += ok
    out.append(np.where(quante > 0, np.clip(np.log((oggi + 1.0) / (somma / np.maximum(quante, 1) + 1.0)), -5, 5), 0.0))
    # VWAP di oggi (Aziz): il prezzo contro il prezzo medio pagato oggi
    pv = _cum(B.v * B.c)
    vol_oggi = vc[:, G] - vc[:, s0]
    vwap = (pv[:, G] - pv[:, s0]) / np.maximum(vol_oggi, 1e-9)
    minuti = np.maximum(j * BARRA, BARRA)
    out.append(np.where(vol_oggi > 0, np.clip(np.log(cK / np.maximum(vwap, 1e-12)) / (sig * np.sqrt(minuti / 60.0)), -8, 8), 0.0))
    # prima mezz'ora (Gao, Han, Li e Zhou): dalle 9:30 in poi, il rendimento delle 9:00-9:30
    pm = np.where(j >= 6, lc[:, np.minimum(s0 + 5, B.n - 1)] - np.log(B.o[:, s0]), 0.0)
    out.append(np.clip(pm / (sig * math.sqrt(0.5)), -8, 8))
    # stagionalità (Heston, Korajczyk e Sadka): la mezz'ora che comincia adesso, nelle ultime sedute
    somma, quante = np.zeros((C, N)), np.zeros(N)
    fine = np.minimum(j + 5, BARRE - 1)
    for d in range(1, SEDUTE_STAGIONE + 1):
        a = s0 - d * BARRE
        ok = a >= 0
        aa = np.where(ok, a, 0)
        somma += np.where(ok, lc[:, aa + fine] - lc[:, aa + j - 1], 0.0)
        quante += ok
    out.append(np.clip(somma / np.maximum(quante, 1) / (sig * math.sqrt(0.5)), -8, 8))
    # giornalieri (anno, mese, settimana, giorno...), salto della notte sull'ATR, notizie: della seduta prima
    tab, atr, notizie, sc = esterni_azioni(B)
    s = G // BARRE
    T = tab[:, s, :]
    out += [T[:, :, k] for k in range(T.shape[-1])]
    salto = B.o[:, s0] - B.c[:, s0 - 1]
    a = atr[:, s]
    out.append(np.where(a > 0, np.clip(salto / np.maximum(a, 1e-12), -6, 6), 0.0))
    out += [np.broadcast_to(notizie[s, k], (C, N)) for k in range(notizie.shape[-1])]
    out += [sc[:, s, k] for k in range(sc.shape[-1])]                              # trader-scanner, della seduta prima
    return out


def _cum(x):
    return np.concatenate([np.zeros(x.shape[:-1] + (1,)), np.cumsum(x, axis=-1)], axis=-1)


def decisioni_possibili(B, solo_complete=True):
    """Gli indici delle barre in cui si può decidere: dalla terza barra della seduta, dopo SEDUTE_STORIA sedute di storia.
    solo_complete: senza la seduta in corso (serve per imparare, perché il suo esito non c'è ancora)."""
    g = np.arange(B.n)
    j, s = g % BARRE, g // BARRE
    ok = (j >= PRIMA) & (s >= SEDUTE_STORIA) & (g <= B.ultima)
    if solo_complete:
        ultima_seduta = B.ultima // BARRE
        if B.ultima % BARRE != BARRE - 1:
            ok &= s < ultima_seduta
    return g[ok]


def caratteristiche(B, G):
    """Le N_FEATURE caratteristiche per ogni titolo e ogni barra di decisione G (si usa solo quello che c'è prima di G)."""
    G = np.asarray(G)
    lc = np.log(B.c)
    r1 = np.zeros_like(lc)
    r1[:, 1:] = np.diff(lc, axis=1)
    primo_di_seduta = (np.arange(B.n) % BARRE) == 0
    r1_seduta = np.where(primo_di_seduta[None, :], 0.0, r1)                      # la volatilità senza i salti della notte
    r2 = _cum(r1_seduta ** 2)
    ult = G - 1
    sig = np.maximum(np.sqrt(np.maximum((r2[:, G] - r2[:, G - 510]) / 510.0 * 12.0, 0.0)), SIGMA_MIN)
    s2h = np.sqrt(np.maximum((r2[:, G] - r2[:, G - 24]) / 24.0 * 12.0, 0.0))
    cols, z = [], {}
    for L in RITARDI:
        z[L] = np.clip((lc[:, ult] - lc[:, ult - L]) / (sig * math.sqrt(L * BARRA / 60.0)), -8, 8)
        cols.append(z[L])
    cols += [np.log(sig), np.log((s2h + 1e-5) / sig)]
    s0 = (G // BARRE) * BARRE                                                     # prima barra di oggi
    minuti = (G - s0) * BARRA
    apertura = np.log(B.o[:, s0])
    ieri = lc[:, s0 - 1]
    cols.append(np.clip((lc[:, ult] - apertura) / (sig * np.sqrt(np.maximum(minuti, BARRA) / 60.0)), -8, 8))
    cols.append(np.clip((apertura - ieri) / (sig * math.sqrt(8.5)), -8, 8))
    hs, ls = B.h.reshape(B.C, B.S, BARRE), B.l.reshape(B.C, B.S, BARRE)
    hi = np.maximum.accumulate(hs, axis=2).reshape(B.C, -1)
    lo = np.minimum.accumulate(ls, axis=2).reshape(B.C, -1)
    cols.append((B.c[:, ult] - lo[:, ult]) / np.maximum(hi[:, ult] - lo[:, ult], 1e-12))
    cols.append(np.clip((lc[:, ult] - ieri) / (sig * math.sqrt(8.5)), -8, 8))
    fase = minuti / (BARRE * BARRA)
    giorno = np.array([B.giorni[int(s)].weekday() for s in G // BARRE]) / 7.0 * 2 * np.pi
    for f in (fase, np.sin(2 * np.pi * fase), np.cos(2 * np.pi * fase), np.sin(giorno), np.cos(giorno)):
        cols.append(np.broadcast_to(f, (B.C, len(G))))
    vc = _cum(B.v)
    v12 = vc[:, G] - vc[:, G - 12]
    v510 = (vc[:, G] - vc[:, G - 510]) / 510.0 * 12.0
    cols.append(np.log((v12 + 1.0) / (v510 + 1.0)))
    m12, m102 = z[12].mean(axis=0), z[102].mean(axis=0)
    cols += [np.broadcast_to(m12, (B.C, len(G))), np.broadcast_to(m102, (B.C, len(G))), z[102] - m102]
    cols += segnali_azioni(B, G, sig, lc, s0, hi, lo, vc)
    X = np.stack(cols, axis=-1).astype(np.float32)
    assert X.shape[-1] == N_FEATURE, X.shape
    return np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0), sig


def esiti(B, G, sig, costo=COSTO, orizzonti=ORIZZONTI):
    """Per ogni titolo, barra di decisione G e orizzonte: compro all'apertura di G e vendo all'apertura della barra dopo
    `h` minuti, o alla chiusura della seduta se viene prima; protezione a K_STOP x sigma x radice(ore) sotto l'entrata.
    Ritorna guadagno netto, minuti fino a essere liberi, protezione scattata, e se l'esito c'è (barre vere fino all'uscita)."""
    G = np.asarray(G)
    C, N, H = B.C, len(G), len(orizzonti)
    R = np.zeros((C, N, H), np.float32)
    LK = np.zeros((C, N, H), np.float32)
    FE = np.zeros((C, N, H), bool)
    OK = np.zeros((C, N, H), bool)
    fine_seduta = (G // BARRE) * BARRE + BARRE                                    # la barra dopo l'ultima di oggi
    for jh, h in enumerate(orizzonti):
        e = np.minimum(G + h // BARRA, fine_seduta)
        alla_chiusura = e >= fine_seduta
        OK[:, :, jh] = (e - 1 <= B.ultima)[None, :]
        for i, g in enumerate(G):
            if not OK[0, i, jh]:
                continue
            ee = int(e[i])
            entrata = B.o[:, g]
            stop = entrata * (1.0 - np.minimum(rete.K_STOP * sig[:, i] * math.sqrt(h / 60.0), 0.9))
            finestra = B.l[:, g:ee]
            tocca = finestra <= stop[:, None]
            fermato = tocca.any(axis=1)
            primo = tocca.argmax(axis=1)
            uscita = B.c[:, ee - 1] if alla_chiusura[i] else B.o[:, min(ee, B.n - 1)]
            uscita = np.where(fermato, np.minimum(stop, B.o[np.arange(C), g + primo]) * (1.0 - SLIP), uscita)
            R[:, i, jh] = (1.0 - costo) ** 2 * uscita / entrata - 1.0
            LK[:, i, jh] = np.where(fermato, (primo + 1) * BARRA, (ee - g) * BARRA)
            FE[:, i, jh] = fermato
    return R, LK, FE, OK


class DatiAzioni(rete.Dati):
    """Le stesse cose di rete.Dati (caratteristiche, esiti, tempi), per le azioni: così l'addestramento e la verifica
    di rete.py valgono uguali."""

    def __init__(self, B, costo=COSTO, solo_complete=True):
        self.B, self.costo = B, costo
        self.M = types.SimpleNamespace(t0=B.t0)
        self.G = decisioni_possibili(B, solo_complete)
        self.K = B.K[self.G]
        self.X, self.sig = caratteristiche(B, self.G)
        self.R, self.LK, self.FE, self.OK = esiti(B, self.G, self.sig, costo)
        self.C, self.N = self.X.shape[:2]
        self.giorni = float(self.K[-1] // 1440 + 1)
        self.orizzonti, self.passo, self.avvio = ORIZZONTI, BARRA, float(self.K[0])


def regole(D):
    """Tre regole semplici fissate prima di guardare, per confronto: compra all'apertura (09:10) e vendi in chiusura;
    compra dopo un'ora in ribasso (sotto -2 volatilità) e tieni un'ora; compra dopo un'ora in rialzo (sopra +2) e tieni un'ora."""
    ih, ic = ORIZZONTI.index(60), ORIZZONTI.index(510)
    z = NOMI_FEATURE.index("rend_12")

    def apertura(D, i0, i1):
        az = np.zeros((D.C, i1 - i0), dtype=int)
        az[:, (D.G[i0:i1] % BARRE) == PRIMA] = 1 + ic
        return az

    def ribasso(D, i0, i1):
        az = np.zeros((D.C, i1 - i0), dtype=int)
        az[D.X[:, i0:i1, z] < -2.0] = 1 + ih
        return az

    def rialzo(D, i0, i1):
        az = np.zeros((D.C, i1 - i0), dtype=int)
        az[D.X[:, i0:i1, z] > 2.0] = 1 + ih
        return az
    F = NOMI_FEATURE.index
    ic, i30, i60 = ORIZZONTI.index(510), ORIZZONTI.index(30), ORIZZONTI.index(60)

    def quando(D, i0, i1, condizione, h):
        az = np.zeros((D.C, i1 - i0), dtype=int)
        az[condizione] = 1 + h
        return az

    def barra(D, i0, i1):
        return np.broadcast_to(D.G[i0:i1] % BARRE, (D.C, i1 - i0))

    def orb(D, i0, i1):                    # Zarattini e Aziz; Crabel: rottura del range dei primi 15 minuti, titolo "in play"
        X, j = D.X[:, i0:i1], barra(D, i0, i1)
        return quando(D, i0, i1, (j >= BARRE_OR) & (j <= 6) & (X[..., F("volume_relativo")] > 1.0) & (X[..., F("sopra_or")] > 0), ic)

    def momento_intraday(D, i0, i1):       # Gao, Han, Li e Zhou: alle 17:00, se la prima mezz'ora è salita, tieni fino alla chiusura
        X, j = D.X[:, i0:i1], barra(D, i0, i1)
        return quando(D, i0, i1, (j == 96) & (X[..., F("prima_mezzora")] > 0.5), ic)

    def buy_on_gap(D, i0, i1):             # Chan: aperto più di un ATR sotto la chiusura di ieri, compra alle 9:10 e vendi in chiusura
        X, j = D.X[:, i0:i1], barra(D, i0, i1)
        return quando(D, i0, i1, (j == PRIMA) & (X[..., F("salto_atr")] < -1.0), ic)

    def vwap_ritorno(D, i0, i1):           # Aziz: molto sotto il VWAP di oggi, tieni un'ora
        X, j = D.X[:, i0:i1], barra(D, i0, i1)
        return quando(D, i0, i1, (X[..., F("vwap_oggi")] < -2.0) & (j < 90), i60)

    def stagione(D, i0, i1):               # Heston, Korajczyk e Sadka: la stessa mezz'ora è salita nelle ultime sedute
        X = D.X[:, i0:i1]
        return quando(D, i0, i1, X[..., F("stagione_30m")] > 1.0, i30)

    return {"apertura_chiusura": apertura, "ribasso_1h": ribasso, "rialzo_1h": rialzo, "orb_in_play": orb,
            "momento_intraday": momento_intraday, "buy_on_gap": buy_on_gap, "vwap_ritorno": vwap_ritorno, "stagione": stagione}


# ---------------------------------------------------------------- studia

FONTI_SEGNALI = dict(rete.FONTI_SEGNALI, **{
    "sopra_or": "opening range (Crabel; Zarattini e Aziz 2023)", "sotto_or": "opening range (Crabel; Zarattini e Aziz 2023)",
    "ampiezza_or": "ampiezza dell'opening range (Crabel)", "volume_relativo": "volume relativo, stocks in play (Zarattini, Barbon e Aziz 2024)",
    "vwap_oggi": "VWAP di oggi (Aziz)", "prima_mezzora": "prima mezz'ora (Gao, Han, Li e Zhou 2018)",
    "stagione_30m": "stessa mezz'ora nelle sedute prima (Heston, Korajczyk e Sadka 2010)",
    "salto_atr": "salto della notte sull'ATR (Chan; Lou, Polk e Skouras 2019)", "salto": "salto della notte (Lou, Polk e Skouras 2019)",
    "g_anno": "momento di un anno (Moskowitz, Ooi e Pedersen 2012)", "g_mese": "momento di un mese (Jegadeesh e Titman)",
    "g_settimana": "inversione di una settimana (Lehmann 1990)", "g_giorno": "ritorno del giorno prima (Jegadeesh 1990)",
    "notizie_volume": "quantità di notizie su Piazza Affari (GDELT; Tetlock 2007)", "notizie_tono": "tono delle notizie su Piazza Affari (GDELT; Tetlock 2007)",
    "minuti": "ora della seduta", "oggi": "dall'apertura di oggi", "da_ieri": "dalla chiusura di ieri", "pos_oggi": "posizione nel minimo-massimo di oggi",
})


def periodi_sedute(D):
    """Tutte le sedute, l'ultimo mese (21), l'ultima settimana (5) e l'ultima seduta, come primo istante di ognuno."""
    seduta = D.G // BARRE
    ultima = int(seduta[-1])
    inizio = lambda n: int(np.searchsorted(seduta, ultima - n + 1))
    return [("tutte", 0), ("mese", inizio(21)), ("settimana", inizio(5)), ("giorno", inizio(1))]


FINESTRE = dict(giorni_test=14, giorni_val=14, embargo=1, min_addestramento=14, max_finestre=8, margine_fine=1.0)


def _precedente():
    try:
        with open(MODELLO, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def studia(costi=(COSTO, 0.0005), iterazioni=10, log=print, salva=True):
    t0 = time.time()
    prima = _precedente()
    B = carica(max_age=6 * 3600, log=log)
    D = DatiAzioni(B)
    wins = rete.finestre(D, **FINESTRE)
    log("[rete_azioni] %d titoli, %d sedute (%s … %s), %d campioni, %d finestre" % (
        B.C, B.S, B.giorni[0], B.giorni[-1], D.C * D.N, len(wins)))
    inizio = datetime.datetime.fromtimestamp(B.t0, datetime.timezone.utc).date()
    data = lambda g: (inizio + datetime.timedelta(days=int(g))).isoformat()
    ris = {"creato": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "dati": {"da": B.giorni[0].isoformat(), "a": B.giorni[-1].isoformat(), "sedute": B.S, "titoli": B.simboli,
                    "barre": "Yahoo Finance, 5 minuti", "campioni": int(D.C * D.N)},
           "config": {"orizzonti": list(ORIZZONTI), "passo_minuti": BARRA, "costo_per_lato": COSTO, "k_stop": rete.K_STOP,
                      "caratteristiche": list(NOMI_FEATURE), "iterazioni": iterazioni, "t_minima": rete.T_MINIMA, "n_minimo": rete.N_MINIMO},
           "finestre": [{"test_da": data(w["giorni"][0]), "test_a": data(w["giorni"][1]), "giorni": list(w["giorni"])} for w in wins],
           "incondizionato": rete.incondizionato(D, costi[0]), "costi": {}, "modelli": {}, "probabilita": {}}
    if wins:
        ris["informazione"] = rete.ic_per_orizzonte(D, wins, costo=costi[0])
    log("[rete_azioni] quali segnali sono legati a quello che succede dopo: tutte le sedute, ultimo mese, settimana, giorno")
    per = periodi_sedute(D)
    ris["segnali"] = rete.studio_segnali(D, NOMI_FEATURE, per, costi[0], per[1][1], FONTI_SEGNALI)
    for c in costi:
        log("[rete_azioni] costo %.2f %% per lato" % (100 * c))
        if wins:
            r = rete.valuta_costo(D, wins, c, iterazioni=iterazioni, log=log, regole=regole(D))
            blocco = {nome: rete.riassumi(D, r, nome) for nome in r["strategie"]}
            sedute_test = len({int(D.G[i] // BARRE) for w in wins for i in range(*w["test"])})
            for nome in r["strategie"]:
                blocco[nome]["per_seduta"] = blocco[nome]["n"] / max(sedute_test, 1)
                blocco[nome]["sedute"] = sedute_test
            blocco["scelte"] = r["scelte"]
            if c == costi[0]:
                blocco["curve_q"] = [[{k: v for k, v in riga.items() if k in ("iterazione", "errore", "valore_medio", "m0.001", "m0")} for riga in cur]
                                     for cur in r["curve_q"]]
            rp = rete.valuta_probabilita(D, wins, c, log=log)                  # scegliere le operazioni che chiudono in guadagno
            blocco.update(rete.blocco_probabilita(D, rp))
            blocco["probabilita"]["per_seduta"] = blocco["probabilita"]["n"] / max(sedute_test, 1)
            blocco["probabilita"]["sedute"] = sedute_test
            ris["costi"]["%g" % c] = blocco
        m = rete.modello_finale(D, c, iterazioni=iterazioni, giorni_val=FINESTRE["giorni_val"], embargo=FINESTRE["embargo"],
                                margine_fine=FINESTRE["margine_fine"])
        ris["modelli"]["%g" % c] = {"tipo": "q", "fuori": m["fuori"], "iterazione": m["iterazione"], "margine": m["margine"],
                                    "media": m["media"].tolist(), "dev": m["dev"].tolist(), "rete": m["rete"].a_dizionario(5)}
        log("[rete_azioni] modello finale a %.2f %%: %s" % (100 * c, "resta fuori" if m["fuori"] else "margine %g" % m["margine"]))
        mp = rete.modello_probabilita(D, c, giorni_val=FINESTRE["giorni_val"], embargo=FINESTRE["embargo"], margine_fine=FINESTRE["margine_fine"])
        ris["probabilita"]["%g" % c] = rete.json_probabilita(mp, B.giorni[-1].isoformat())
        log("[rete_azioni] probabilità a %.2f %%: compra dal %.1f %% stimato (il meglio %.1f %% delle occasioni)%s" % (
            100 * c, 100 * mp["soglia"], 100 * mp["quota"], "" if not mp["fuori"] else ", senza via libera"))
        if c == costi[0]:
            ris["esperienza"] = rete.esperienza(prima.get("esperienza"), mp, B.giorni[-1].isoformat(), B.S)
    ris["durata_minuti"] = round((time.time() - t0) / 60, 1)
    if salva:
        with open(MODELLO, "w", encoding="utf-8") as fh:
            json.dump(rete._pulisci(ris), fh, separators=(",", ":"))
        log("[rete_azioni] scritto %s (%d KB)" % (os.path.basename(MODELLO), os.path.getsize(MODELLO) // 1024))
    return ris


def per_app():
    """I risultati per l'app (senza i pesi), o None."""
    try:
        with open(MODELLO, encoding="utf-8") as fh:
            r = json.load(fh)
    except (OSError, ValueError):
        return None
    for m in list((r.get("modelli") or {}).values()) + list((r.get("probabilita") or {}).values()):
        for k in ("rete", "media", "dev"):
            m.pop(k, None)
    return r


# ---------------------------------------------------------------- le operazioni delle ultime sedute, per il robot

MARGINE_ROBOT = 0.001
SEDUTE_ROBOT = 3


def rigioca(modello, B, margine=None, sedute=SEDUTE_ROBOT, costo=COSTO):
    """Le operazioni che la rete fa nelle ultime `sedute` sedute (anche quella in corso), una posizione alla volta per
    titolo, tutte chiuse entro la seduta. Le posizioni della seduta in corso non ancora chiuse sono 'aperte'. Con il
    modello della probabilità compra dalla sua soglia, con il Q-learning dal margine (margine=None: quelli del modello)."""
    G_tutte = decisioni_possibili(B, solo_complete=False)
    ultima_seduta = B.ultima // BARRE
    G = G_tutte[(G_tutte // BARRE) > ultima_seduta - sedute]
    if len(G) == 0:
        return [], [], {}
    X, sig = caratteristiche(B, G)
    az, vantaggio = rete.scelte_modello(modello, X, margine)
    voce = "probabilita" if modello.get("tipo") == "probabilita" else "vantaggio"
    iso = lambda t: datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    chiuse, aperte = [], []
    for c, sym in enumerate(B.simboli):
        libero = 0
        for i in np.flatnonzero(az[c] > 0):
            g = int(G[i])
            if g < libero or not B.vera[c, g]:
                continue
            h = ORIZZONTI[int(az[c, i]) - 1]
            fine_seduta = (g // BARRE) * BARRE + BARRE
            e = min(g + h // BARRA, fine_seduta)
            entrata = float(B.o[c, g])
            stop = entrata * (1.0 - min(rete.K_STOP * float(sig[c, i]) * math.sqrt(h / 60.0), 0.9))
            chiusura = B.T[fine_seduta - 1] + 60.0 * BARRA
            scade = B.T[e] if e < fine_seduta else chiusura
            op = {"sym": sym, "t": iso(B.T[g]), "prezzo": round(entrata, 6), "minuti": int(min(h, (e - g) * BARRA)),
                  "protezione": round(stop, 6), "scade": iso(scade), voce: round(float(vantaggio[c, i]), 6)}
            ultima_vera = B.ultima
            tocca = np.flatnonzero(B.l[c, g:min(e, ultima_vera + 1)] <= stop)
            if len(tocca):
                kk = g + int(tocca[0])
                uscita, t_usc, motivo = min(stop, float(B.o[c, kk])) * (1.0 - SLIP), B.T[kk] + 60.0 * BARRA, "protezione"
            elif e - 1 <= ultima_vera:
                if e >= fine_seduta:
                    uscita, t_usc, motivo = float(B.c[c, e - 1]), chiusura, "chiusura"
                else:
                    uscita, t_usc, motivo = float(B.o[c, e]), B.T[e], "scadenza"
            else:
                aperte.append(op)
                break
            op.update({"t_uscita": iso(t_usc), "prezzo_uscita": round(uscita, 6), "motivo": motivo,
                       "r": round((1.0 - costo) ** 2 * uscita / entrata - 1.0, 6)})
            chiuse.append(op)
            libero = e if motivo != "protezione" else kk + 1
    chiuse.sort(key=lambda o: o["t"])
    return chiuse, aperte, {sym: round(float(vantaggio[c, -1]), 6) for c, sym in enumerate(B.simboli)}


def robot(margine=MARGINE_ROBOT, sedute=SEDUTE_ROBOT, log=print):
    """Per il robot dell'app: le operazioni della rete nelle ultime sedute. Se c'è, la rete della probabilità di guadagno
    sceglie le operazioni (compra dove la probabilità stimata arriva alla soglia imparata, anche senza il via libera della
    verifica); se no il Q-learning con il margine imposto (compra quando la mossa migliore batte l'attesa di quel margine)."""
    with open(MODELLO, encoding="utf-8") as fh:
        r = json.load(fh)
    sel = r.get("probabilita") or {}
    if sel:
        chiave = max(sel, key=float)
        modello, margine = rete.da_json(sel[chiave]), None
    else:
        chiave = max(r["modelli"], key=float)
        modello = rete.da_json(r["modelli"][chiave])
    costo = float(chiave)
    B = carica(max_age=300, log=lambda m: None)
    chiuse, aperte, vantaggio = rigioca(modello, B, margine, sedute, costo)
    log("[rete_azioni] per il robot: %d operazioni chiuse, %d aperte nelle ultime %d sedute" % (len(chiuse), len(aperte), sedute))
    prob = modello.get("tipo") == "probabilita"
    return {"generato": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "costo": costo,
            "tipo": modello.get("tipo"), "margine": None if prob else margine, "soglia": modello.get("soglia") if prob else None,
            "quota": modello.get("quota") if prob else None, "sedute": sedute, "orizzonti": list(ORIZZONTI),
            "ultima_barra": datetime.datetime.fromtimestamp(B.T[B.ultima], datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if B.ultima >= 0 else None,
            "modello": {"fuori": modello["fuori"], "iterazione": modello.get("iterazione"), "addestrato": modello.get("addestrato")},
            "operazioni": chiuse, "aperte": aperte, "vantaggio": vantaggio,
            "prezzi": {sym: round(float(B.c[c, B.ultima]), 6) for c, sym in enumerate(B.simboli)} if B.ultima >= 0 else {}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--studia", action="store_true")
    ap.add_argument("--oggi", action="store_true")
    ap.add_argument("--iterazioni", type=int, default=10)
    a = ap.parse_args(argv)
    if a.studia:
        studia(iterazioni=a.iterazioni)
        return 0
    if a.oggi:
        r = robot()
        print("[rete_azioni] %s" % ("compra dal %.1f %% di probabilità stimata di chiudere in guadagno" % (100 * r["soglia"]) if r["soglia"] is not None
                                     else "compra quando batte l'attesa di %.2f %%" % (100 * r["margine"])))
        for o in r["operazioni"][-15:] + r["aperte"]:
            print("  %s %-9s compra a %.4f per %3d minuti → %s" % (o["t"], o["sym"], o["prezzo"], o["minuti"],
                  ("%s a %.4f: %+.2f %%" % (o["motivo"], o["prezzo_uscita"], 100 * o["r"])) if "r" in o else "ancora aperta"))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
