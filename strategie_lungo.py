#!/usr/bin/env python3
"""Le strategie dei libri più apprezzati su tendenza e momento, provate sui mercati dell'app (10 anni di chiusure
giornaliere, con i costi), confrontate con il semplice comprare e tenere, sulle due metà del periodo.

    python3 strategie_lungo.py        # scrive strategie_lungo.json

  - Gary Antonacci, "Dual Momentum Investing" (2014): ogni fine mese, tra azioni USA (CSSPX) ed europee (SMEA) quella
    con il rendimento di 12 mesi più alto; se nemmeno quella ha battuto la liquidità (zero), obbligazioni (IEAG).
  - Mebane Faber, "A Quantitative Approach to Tactical Asset Allocation" (2007; rivisto nel 2018): ogni fine mese, ogni
    ETF in parti uguali, tenuto solo se sopra la media di 10 mesi (210 giorni), altrimenti liquidità.
  - Andreas Clenow, "Stocks on the Move" (2015): ogni settimana le azioni con la tendenza più forte e regolare
    (pendenza annua della regressione esponenziale di 90 giorni per R²), sopra la media di 100 giorni e senza salti
    oltre il 15 % negli ultimi 90; nuove entrate solo con l'indice sopra la media di 200 giorni; peso dalla volatilità
    (ATR di 20 giorni: ogni titolo muove il conto dello 0,1 % al giorno).
  - La tendenza dei fondi (Hurst, Ooi e Pedersen, AQR 2017) con la volatilità obiettivo (Moreira e Muir 2017), sugli ETF.

Attenzione: i titoli sono quelli di oggi (chi è uscito dall'indice manca), quindi il passato delle azioni è più bello
di com'era. Solo numpy e la libreria standard. Non è consulenza finanziaria.
"""

import datetime
import json
import math
import os
import sys

import numpy as np

import crypto_tendenza as CT
import segnali
import settimana

ROOT = os.path.dirname(os.path.abspath(__file__))
USCITA = os.path.join(ROOT, "strategie_lungo.json")
ANNO = 252


def carica(simboli, tz="Europe/Rome", chiusura=(17, 35)):
    """Chiusure (e massimi, minimi) giornaliere sulla stessa griglia: (giorni, nomi, C, H, L) con NaN dove mancano."""
    serie = {}
    for s in simboli:
        g, o, h, l, c = segnali.giornaliere(s, tz, chiusura)
        if len(g) > 300:
            serie[s] = {d: (float(hh), float(ll), float(cc)) for d, hh, ll, cc in zip(g, h, l, c)}
    giorni = sorted({d for v in serie.values() for d in v})
    nomi = list(serie)
    A = np.full((3, len(giorni), len(nomi)), np.nan)
    for j, s in enumerate(nomi):
        for i, d in enumerate(giorni):
            if d in serie[s]:
                A[:, i, j] = serie[s][d]
    H, L, C = A
    for X in (C, H, L):                                                         # i buchi: l'ultimo valore noto
        for j in range(X.shape[1]):
            ultimo = np.nan
            for i in range(X.shape[0]):
                if np.isnan(X[i, j]):
                    X[i, j] = ultimo
                else:
                    ultimo = X[i, j]
    return giorni, nomi, C, H, L


def fine_mese(giorni):
    return np.array([i == len(giorni) - 1 or giorni[i][:7] != giorni[i + 1][:7] for i in range(len(giorni))])


def tieni(W, quando):
    """I pesi cambiano solo nei giorni `quando`; negli altri restano quelli di prima."""
    out = np.zeros_like(W)
    ultimo = np.zeros(W.shape[1])
    for i in range(len(W)):
        if quando[i]:
            ultimo = W[i]
        out[i] = ultimo
    return out


def antonacci(giorni, nomi, C, usa="CSSPX.MI", estero="SMEA.MI", obbligazioni="IEAG.MI"):
    W = np.zeros_like(C)
    iu, ie, ib = nomi.index(usa), nomi.index(estero), nomi.index(obbligazioni)
    for i in range(ANNO, len(giorni)):
        r = {k: C[i, k] / C[i - ANNO, k] - 1 for k in (iu, ie)}
        k = max(r, key=r.get)
        W[i, k if r[k] > 0 else ib] = 1.0
    return tieni(W, fine_mese(giorni))


def faber(giorni, nomi, C):
    W = np.zeros_like(C)
    for i in range(210, len(giorni)):
        media = np.nanmean(C[i - 209:i + 1], axis=0)
        ok = ~np.isnan(C[i]) & ~np.isnan(C[i - 209])
        W[i] = np.where(ok & (C[i] > media), 1.0 / max(ok.sum(), 1), 0.0)
    return tieni(W, fine_mese(giorni))


def pendenza_r2(lc):
    """Pendenza annua (in proporzione) della regressione esponenziale e R², su una finestra di log-prezzi."""
    x = np.arange(len(lc), dtype=np.float64)
    b, a = np.polyfit(x, lc, 1)
    pred = a + b * x
    ss = ((lc - lc.mean()) ** 2).sum()
    r2 = 1 - ((lc - pred) ** 2).sum() / ss if ss > 0 else 0.0
    return (math.exp(b * ANNO) - 1) * r2


def clenow(giorni, nomi, C, H, L, indice, n_max=20, rischio=0.001):
    """Stocks on the Move: ogni mercoledì si rifà la classifica; si vende chi non è più nel 20 % migliore o non passa i
    filtri; si compra solo con l'indice sopra la media di 200 giorni."""
    T, N = C.shape
    W = np.zeros_like(C)
    tenuti = {}
    lc = np.log(C)
    tr = np.maximum(H[1:] - L[1:], np.maximum(np.abs(H[1:] - C[:-1]), np.abs(L[1:] - C[:-1])))
    tr = np.vstack([np.full((1, N), np.nan), tr])
    for i in range(200, T):
        if datetime.date.fromisoformat(giorni[i]).weekday() != 2:              # il mercoledì
            W[i] = W[i - 1]
            continue
        punti = np.full(N, -np.inf)
        for j in range(N):
            f = lc[i - 89:i + 1, j]
            if np.isnan(f).any():
                continue
            sopra = C[i, j] > np.nanmean(C[i - 99:i + 1, j])
            salto = np.nanmax(np.abs(np.diff(C[i - 90:i + 1, j]) / C[i - 90:i, j])) > 0.15
            if sopra and not salto:
                punti[j] = pendenza_r2(f)
        ordine = [j for j in np.argsort(-punti) if np.isfinite(punti[j])]
        migliori = set(ordine[:max(1, int(round(N * 0.2)))])
        tenuti = {j: w for j, w in tenuti.items() if j in migliori}             # si vende chi è uscito
        indice_ok = indice[i] > np.nanmean(indice[i - 199:i + 1])
        if indice_ok:
            for j in ordine:
                if len(tenuti) >= n_max or sum(tenuti.values()) >= 1:
                    break
                if j in tenuti:
                    continue
                atr = np.nanmean(tr[i - 19:i + 1, j])
                w = min(rischio * C[i, j] / max(atr, 1e-9), 1 - sum(tenuti.values()), 0.2)
                if w > 0.005:
                    tenuti[j] = w
        W[i] = 0.0
        for j, w in tenuti.items():
            W[i, j] = w
    return W


def misure(rd):
    m = CT.misure(rd)
    if m:                                                                       # su 252 giorni di borsa
        rd = np.asarray(rd)
        anni = len(rd) / ANNO
        m["annuo"] = float(np.prod(1 + rd) ** (1 / anni) - 1)
        m["volatilita"] = float(rd.std() * math.sqrt(ANNO))
        m["sharpe"] = float(rd.mean() * ANNO / (rd.std() * math.sqrt(ANNO))) if rd.std() > 0 else 0.0
    return m


def prova(nome, giorni, C, W, inizio, costo, log):
    rd = CT.simula_pesi(C, W, costo)[inizio:-1]
    meta = (len(rd)) // 2
    out = {"tutto": misure(rd), "prima_meta": misure(rd[:meta]), "seconda_meta": misure(rd[meta:]),
           "esposizione_media": float(W[inizio:-1].sum(axis=1).mean()), "meta": giorni[inizio + meta]}
    m = out["tutto"]
    log("   %-28s annuo %+6.1f %% · Sharpe %.2f · calo massimo %6.1f %% · seconda metà %+5.1f %% (Sharpe %.2f, calo %5.1f %%)" % (
        nome, 100 * m["annuo"], m["sharpe"], 100 * m["calo_massimo"], 100 * out["seconda_meta"]["annuo"], out["seconda_meta"]["sharpe"],
        100 * out["seconda_meta"]["calo_massimo"]))
    return out


def studia(log=print, salva=True):
    ris = {"creato": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "mercati": {}}
    # ETF a Milano
    etf = settimana.MERCATI["etf"]["universo"] + ["IEAG.MI", "SGLD.MI"]
    g, nomi, C, H, L = carica(etf)
    inizio = 260
    uguali = np.where(~np.isnan(C), 1.0 / C.shape[1], 0.0)
    log("[strategie_lungo] ETF (%d), dal %s al %s" % (len(nomi), g[inizio], g[-1]))
    M = {"da": g[inizio], "a": g[-1], "titoli": nomi, "strategie": {}}
    Wa, Wf = antonacci(g, nomi, C), faber(g, nomi, C)
    M["strategie"]["antonacci"] = prova("Antonacci, momento doppio", g, C, Wa, inizio, 0.001, log)
    M["strategie"]["faber"] = prova("Faber, media di 10 mesi", g, C, Wf, inizio, 0.001, log)
    fm = [i for i, x in enumerate(fine_mese(g)) if x and i < len(g) - 1] or [len(g) - 1]
    ultimo = fm[-1]                                                             # l'ultima fine mese chiusa: i pesi di questo mese
    M["oggi"] = {k: {"giorno": g[ultimo], "pesi": {s: round(float(w), 4) for s, w in zip(nomi, W[ultimo]) if w > 0}}
                 for k, W in (("faber", Wf), ("antonacci", Wa))}
    Wt = CT.pesi(C, vol_obiettivo=0.10, finestre=(21, 63, 252))
    M["strategie"]["tendenza_vol"] = prova("Tendenza dei fondi, vol. 10 %", g, C, Wt, inizio, 0.001, log)
    sw = np.zeros_like(C)
    sw[:, nomi.index("SWDA.MI")] = 1
    M["strategie"]["mondo"] = prova("Comprare e tenere SWDA", g, C, sw, inizio, 0.001, log)
    M["strategie"]["uguali"] = prova("Tutti gli ETF in parti uguali", g, C, tieni(uguali, fine_mese(g)), inizio, 0.001, log)
    ris["mercati"]["etf"] = M
    # azioni USA e italiane, con il filtro dell'indice
    for mer, idx, costo, n_max in (("usa", "SPY", 0.0005, 20), ("italia", "FTSEMIB.MI", 0.001, 8)):
        tz = settimana.MERCATI[mer]["fuso"]
        ch = settimana.MERCATI[mer]["chiusura"]
        g, nomi, C, H, L = carica(settimana.MERCATI[mer]["universo"], tz, (ch[0], ch[1] + 5))
        gi, _, CI, _, _ = carica([idx], tz, (ch[0], ch[1] + 5))
        mappa = dict(zip(gi, CI[:, 0]))
        indice = np.array([mappa.get(d, np.nan) for d in g])
        for i in range(1, len(indice)):
            if np.isnan(indice[i]):
                indice[i] = indice[i - 1]
        inizio = 260
        log("[strategie_lungo] azioni %s (%d), dal %s al %s" % (mer, len(nomi), g[inizio], g[-1]))
        M = {"da": g[inizio], "a": g[-1], "titoli": len(nomi), "strategie": {}}
        M["strategie"]["clenow"] = prova("Clenow, Stocks on the Move", g, C, clenow(g, nomi, C, H, L, indice, n_max), inizio, costo, log)
        Wi = np.zeros((len(g), 1))
        Wi[:] = 1
        M["strategie"]["indice"] = prova("Comprare e tenere l'indice", g, indice[:, None], Wi, inizio, costo, log)
        uguali = np.where(~np.isnan(C), 1.0 / C.shape[1], 0.0)
        M["strategie"]["uguali"] = prova("Tutte in parti uguali", g, C, tieni(uguali, fine_mese(g)), inizio, costo, log)
        ris["mercati"][mer] = M
    if salva:
        with open(USCITA, "w", encoding="utf-8") as fh:
            json.dump(ris, fh, separators=(",", ":"))
        log("[strategie_lungo] scritto %s" % os.path.basename(USCITA))
    return ris


def main(argv=None):
    studia()
    return 0


if __name__ == "__main__":
    sys.exit(main())
