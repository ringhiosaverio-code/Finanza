#!/usr/bin/env python3
"""La tendenza come la fanno i fondi istituzionali (i CTA), sulle crypto: si compra quello che sale da settimane e mesi,
con una posizione tanto più piccola quanto più il prezzo oscilla. Solo acquisti (vendere allo scoperto sulle crypto,
dicono gli studi, ha perso quasi sempre).

    python3 crypto_tendenza.py        # studio su tutta la storia giornaliera, scrive crypto_tendenza.json

Le fonti (verificate):
  - Hurst, Ooi e Pedersen, "A Century of Evidence on Trend-Following Investing" (AQR, Journal of Portfolio Management
    2017): la media dei segnali di momento a 1, 3 e 12 mesi, con il rischio tenuto costante;
  - Moskowitz, Ooi e Pedersen, "Time Series Momentum" (Journal of Financial Economics 2012);
  - Moreira e Muir, "Volatility-Managed Portfolios" (Journal of Finance 2017): meno esposizione quando la volatilità
    è alta;
  - Liu, Tsyvinski e Wu, "Common Risk Factors in Cryptocurrency" (Journal of Finance 2022): il momento è uno dei tre
    fattori delle crypto;
  - Han, Kang e Ryu, sul momento delle crypto con ipotesi realistiche: forte nel tempo, ma vendere allo scoperto perde.

Ogni giorno, alla chiusura (UTC), per ogni crypto: segnale = media di [rendimento di 30, 91, 365 giorni > 0]
(0, 1/3, 2/3 o 1); peso = segnale x (volatilità obiettivo / volatilità degli ultimi 30 giorni), al massimo 1/N.
Si ribilancia ogni giorno e si pagano i costi sulla parte comprata o venduta. Si confronta con: tenere tutte le crypto
in parti uguali; la tendenza senza la volatilità obiettivo; tenere solo Bitcoin. Le misure sono anche sulle due metà
del periodo, per vedere se regge. Le crypto sono quelle che esistono ancora oggi: il passato è più bello di come era.
Solo numpy e la libreria standard. Non è consulenza finanziaria.
"""

import datetime
import json
import math
import os
import sys

import numpy as np

import segnali
import simula

ROOT = os.path.dirname(os.path.abspath(__file__))
USCITA = os.path.join(ROOT, "crypto_tendenza.json")
FINESTRE = (30, 91, 365)          # i tre momenti, in giorni
VOL_GIORNI = 30                   # la volatilità per dimensionare
VOL_OBIETTIVO = 0.40              # volatilità annua obiettivo di ogni crypto (le crypto oscillano 60-100 % l'anno)
COSTO = 0.002                     # per lato, sulla parte scambiata
ANNO = 365


def carica(simboli=None):
    """Le chiusure giornaliere UTC (Yahoo, in euro) sulla stessa griglia di giorni: (giorni, simboli, chiusure con NaN)."""
    simboli = list(simboli or simula.CRYPTO)
    serie = {}
    for s in simboli:
        g, o, h, l, c = segnali.giornaliere(s, "UTC", (23, 59))
        if len(g) > 400:
            serie[s] = dict(zip(g, np.asarray(c, dtype=np.float64)))
    giorni = sorted({g for v in serie.values() for g in v})
    nomi = list(serie)
    C = np.full((len(giorni), len(nomi)), np.nan)
    for j, s in enumerate(nomi):
        for i, g in enumerate(giorni):
            C[i, j] = serie[s].get(g, np.nan)
    return giorni, nomi, C


def pesi(C, vol_obiettivo=VOL_OBIETTIVO, finestre=FINESTRE, con_vol=True):
    """I pesi decisi alla chiusura di ogni giorno (usano solo i prezzi fino a quel giorno): (giorni, crypto)."""
    T, N = C.shape
    lc = np.log(C)
    r = np.vstack([np.full((1, N), np.nan), np.diff(lc, axis=0)])
    W = np.zeros((T, N))
    for t in range(max(finestre), T):
        ok = ~np.isnan(lc[t]) & ~np.isnan(lc[t - max(finestre)])
        if not ok.any():
            continue
        segnale = np.mean([lc[t] - lc[t - f] > 0 for f in finestre], axis=0)
        vol = np.nanstd(r[t - VOL_GIORNI + 1:t + 1], axis=0) * math.sqrt(ANNO)
        n = ok.sum()
        tetto = 1.0 / n
        if con_vol:
            w = segnale * np.minimum(vol_obiettivo / np.maximum(vol, 1e-6) / n, tetto)
        else:
            w = segnale * tetto
        W[t] = np.where(ok, np.nan_to_num(w), 0.0)
    return W


def simula_pesi(C, W, costo=COSTO):
    """Il conto giorno per giorno: i pesi decisi alla chiusura di t valgono per il rendimento da t a t+1; si pagano i
    costi sulla parte scambiata. Ritorna i rendimenti giornalieri netti."""
    r = np.vstack([np.diff(C, axis=0) / C[:-1], np.zeros((1, C.shape[1]))])
    r = np.nan_to_num(r)
    giro = np.abs(np.diff(np.vstack([np.zeros((1, W.shape[1])), W]), axis=0)).sum(axis=1)
    return (W * r).sum(axis=1) - costo * giro


def misure(rd):
    """Rendimento annuo composto, volatilità annua, Sharpe (senza tasso), calo massimo, giorni."""
    rd = np.asarray(rd)
    if len(rd) < 30:
        return None
    conto = np.cumprod(1 + rd)
    anni = len(rd) / ANNO
    cagr = conto[-1] ** (1 / anni) - 1
    vol = rd.std() * math.sqrt(ANNO)
    calo = float((conto / np.maximum.accumulate(conto) - 1).min())
    return {"annuo": float(cagr), "volatilita": float(vol), "sharpe": float(rd.mean() * ANNO / vol) if vol > 0 else 0.0,
            "calo_massimo": calo, "giorni": int(len(rd)), "totale": float(conto[-1] - 1)}


def studia(log=print, salva=True):
    giorni, nomi, C = carica()
    inizio = max(FINESTRE)
    strategie = {
        "tendenza_vol": pesi(C),
        "tendenza": pesi(C, con_vol=False),
    }
    disp = ~np.isnan(C)
    n = np.maximum(disp.sum(axis=1, keepdims=True), 1)
    strategie["tutte_uguali"] = np.where(disp, 1.0 / n, 0.0)
    b = nomi.index("BTC-EUR")
    W = np.zeros_like(C)
    W[:, b] = disp[:, b]
    strategie["solo_bitcoin"] = W
    meta = inizio + (len(giorni) - inizio) // 2
    ris = {"creato": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "da": giorni[inizio], "a": giorni[-1], "meta": giorni[meta], "crypto": nomi, "costo": COSTO,
           "vol_obiettivo": VOL_OBIETTIVO, "finestre": list(FINESTRE), "strategie": {}}
    for k, W in strategie.items():
        rd = simula_pesi(C, W)[inizio:-1]
        espo = W[inizio:-1].sum(axis=1)
        ris["strategie"][k] = {"tutto": misure(rd), "prima_meta": misure(rd[:meta - inizio]), "seconda_meta": misure(rd[meta - inizio:]),
                               "esposizione_media": float(espo.mean())}
        m = ris["strategie"][k]["tutto"]
        log("[crypto_tendenza] %-13s annuo %+6.1f %% · volatilità %5.1f %% · Sharpe %.2f · calo massimo %6.1f %% · esposizione %.0f %%" % (
            k, 100 * m["annuo"], 100 * m["volatilita"], m["sharpe"], 100 * m["calo_massimo"], 100 * ris["strategie"][k]["esposizione_media"]))
    Wo = strategie["tendenza_vol"][-1]
    ris["oggi"] = {"giorno": giorni[-1], "pesi": {s: round(float(w), 4) for s, w in zip(nomi, Wo) if w > 0},
                   "in_euro": round(float(1 - Wo.sum()), 4)}
    if salva:
        with open(USCITA, "w", encoding="utf-8") as fh:
            json.dump(ris, fh, separators=(",", ":"))
        log("[crypto_tendenza] scritto %s" % os.path.basename(USCITA))
    return ris


def main(argv=None):
    studia()
    return 0


if __name__ == "__main__":
    sys.exit(main())
