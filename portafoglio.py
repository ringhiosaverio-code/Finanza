#!/usr/bin/env python3
"""Un portafoglio unico con le strategie che hanno funzionato, e la rete neurale come parte del portafoglio: si misura
quanto rendono e quanto rischiano insieme, settimana per settimana, con i costi, sugli anni che la rete non aveva visto.

    python3 portafoglio.py        # scrive portafoglio.json

I pezzi (rendimenti settimanali):
  mondo        SWDA, l'ETF sul mondo intero, tenuto
  faber        gli ETF solo se sopra la media di 10 mesi (strategie_lungo.py)
  obbligazioni IEAG, le obbligazioni in euro, tenute
  crypto       la tendenza come i fondi sulle crypto (crypto_tendenza.py)
  rete_etf     ogni settimana i 3 ETF (o oro) che la rete del medio periodo stima più probabili in guadagno, con la rete
               addestrata solo sugli anni prima (rete_lungo.py, la stessa verifica anno per anno)
Le combinazioni si ribilanciano ogni settimana ai pesi fissati; si confrontano con il solo SWDA e con il classico 80/20.
In più la "volatilità obiettivo" sul portafoglio intero (Moreira e Muir 2017): meno esposizione quando oscilla di più.
Non è consulenza finanziaria.
"""

import datetime
import json
import math
import os
import sys

import numpy as np

import crypto_tendenza as CT
import rete_lungo as RL
import strategie_lungo as SL

ROOT = os.path.dirname(os.path.abspath(__file__))
USCITA = os.path.join(ROOT, "portafoglio.json")
SETTIMANE = 52


def settimanali(giorni, rd):
    """Da rendimenti giornalieri (giorni ISO) a rendimenti per settimana (indice = ordinale // 7)."""
    out = {}
    for g, r in zip(giorni, rd):
        w = datetime.date.fromisoformat(g).toordinal() // 7
        out[w] = out.get(w, 1.0) * (1 + r)
    return {w: v - 1 for w, v in out.items()}


def pezzo_semplice(sym):
    g, nomi, C, H, L = SL.carica([sym])
    rd = np.r_[0.0, np.diff(C[:, 0]) / C[:-1, 0]]
    return settimanali(g, np.nan_to_num(rd))


def pezzo_faber():
    etf = SL.settimana.MERCATI["etf"]["universo"] + ["IEAG.MI", "SGLD.MI"]
    g, nomi, C, H, L = SL.carica(etf)
    W = SL.faber(g, nomi, C)
    rd = CT.simula_pesi(C, W, 0.001)                    # il peso deciso alla chiusura di t vale da t a t+1
    return settimanali(g[1:], rd[:-1])


def pezzo_crypto():
    g, nomi, C = CT.carica()
    rd = CT.simula_pesi(C, CT.pesi(C))
    return settimanali(g[1:], rd[:-1])


def pezzo_rete_etf(scelte=3, log=print):
    """Le scelte settimanali della rete sugli ETF, fuori campione: per ogni anno la rete impara solo dagli esiti chiusi
    prima, come in rete_lungo.verifica. Rendimento della settimana = media dei 3 scelti (a 7 giorni, dopo i costi)."""
    C = RL.Campioni(lambda m: None)
    ultimo = datetime.date.fromordinal(int(C.g.max())).year
    P = np.full(len(C.X), np.nan, np.float32)
    for anno in range(ultimo - RL.ANNI_VERIFICA, ultimo + 1):
        a0, a1 = datetime.date(anno, 1, 1).toordinal(), datetime.date(anno + 1, 1, 1).toordinal()
        fine = C.g + max(RL.ORIZZONTI)
        tr = np.flatnonzero(fine < a0 - 365)
        va = np.flatnonzero((C.g >= a0 - 365) & (fine < a0))
        te = np.flatnonzero((C.g >= a0) & (C.g < a1))
        if len(tr) < RL.MIN_ADDESTRAMENTO or not len(te):
            continue
        log("[portafoglio] rete: anno %d" % anno)
        P[te] = RL.stima(RL.addestra(C, tr, va), C.X[te])[:, 0]
    ok = ~np.isnan(P) & np.isin(C.cat, ("etf", "oro")) & C.OK[:, 0]
    out = {}
    for w in np.unique(C.settimana[ok]):
        k = np.flatnonzero(ok & (C.settimana == w))
        if len(k) >= 5:
            out[int(w)] = float(C.R[k[np.argsort(-P[k])[:scelte]], 0].mean())
    return out


def combina(pezzi, pesi, settimane, vol_obiettivo=None):
    """Il portafoglio ribilanciato ogni settimana ai pesi; con vol_obiettivo l'esposizione si riduce quando la
    volatilità delle ultime 26 settimane supera l'obiettivo (il resto in liquidità a zero)."""
    r = np.array([sum(p * pezzi[k].get(w, 0.0) for k, p in pesi.items()) for w in settimane])
    if vol_obiettivo:
        esp = np.ones(len(r))
        for i in range(26, len(r)):
            v = r[i - 26:i].std() * math.sqrt(SETTIMANE)
            esp[i] = min(1.0, vol_obiettivo / max(v, 1e-9))
        r = r * esp
    return r


def misure(r):
    r = np.asarray(r)
    if len(r) < 20:
        return None
    conto = np.cumprod(1 + r)
    anni = len(r) / SETTIMANE
    vol = r.std() * math.sqrt(SETTIMANE)
    return {"annuo": float(conto[-1] ** (1 / anni) - 1), "volatilita": float(vol),
            "sharpe": float(r.mean() * SETTIMANE / vol) if vol > 0 else 0.0,
            "calo_massimo": float((conto / np.maximum.accumulate(conto) - 1).min()), "settimane": int(len(r))}


COMBINAZIONI = {
    "solo_mondo": ({"mondo": 1.0}, None, "Solo SWDA, il mondo intero"),
    "classico_80_20": ({"mondo": 0.8, "obbligazioni": 0.2}, None, "Il classico: 80 % SWDA, 20 % obbligazioni"),
    "piano": ({"mondo": 0.6, "faber": 0.2, "obbligazioni": 0.1, "crypto": 0.1}, None, "Il piano: 60 % SWDA, 20 % Faber, 10 % obbligazioni, 10 % crypto in tendenza"),
    "piano_rete": ({"mondo": 0.5, "rete_etf": 0.2, "faber": 0.1, "obbligazioni": 0.1, "crypto": 0.1}, None, "Il piano con la rete: 50 % SWDA, 20 % scelte della rete sugli ETF, 10 % Faber, 10 % obbligazioni, 10 % crypto"),
    "piano_rete_vol": ({"mondo": 0.5, "rete_etf": 0.2, "faber": 0.1, "obbligazioni": 0.1, "crypto": 0.1}, 0.12, "Il piano con la rete e la volatilità obiettivo del 12 %"),
    "rete_sola": ({"rete_etf": 1.0}, None, "Solo le scelte settimanali della rete sugli ETF"),
}


def studia(log=print, salva=True):
    log("[portafoglio] carico i pezzi")
    pezzi = {"mondo": pezzo_semplice("SWDA.MI"), "obbligazioni": pezzo_semplice("IEAG.MI"), "faber": pezzo_faber(),
             "crypto": pezzo_crypto(), "rete_etf": pezzo_rete_etf(log=log)}
    comuni = sorted(set.intersection(*[set(p) for p in pezzi.values()]))[1:-1]      # le settimane che hanno tutti i pezzi
    da = datetime.date.fromordinal(comuni[0] * 7).isoformat()
    a = datetime.date.fromordinal(comuni[-1] * 7).isoformat()
    meta = len(comuni) // 2
    ris = {"creato": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "da": da, "a": a,
           "meta": datetime.date.fromordinal(comuni[meta] * 7).isoformat(), "combinazioni": {}}
    log("[portafoglio] %d settimane comuni, dal %s al %s" % (len(comuni), da, a))
    for k, (pesi, vol, nome) in COMBINAZIONI.items():
        r = combina(pezzi, pesi, comuni, vol)
        ris["combinazioni"][k] = {"nome": nome, "pesi": pesi, "vol_obiettivo": vol, "tutto": misure(r),
                                  "prima_meta": misure(r[:meta]), "seconda_meta": misure(r[meta:])}
        if k in ("piano_rete", "solo_mondo", "classico_80_20"):                 # per il simulatore del futuro nell'app
            ris["combinazioni"][k]["settimane"] = [round(float(x), 5) for x in r]
        m, s2 = ris["combinazioni"][k]["tutto"], ris["combinazioni"][k]["seconda_meta"]
        log("   %-16s annuo %+6.1f %% · volatilità %5.1f %% · Sharpe %.2f · calo %6.1f %% · seconda metà %+5.1f %% (Sharpe %.2f, calo %5.1f %%)" % (
            k, 100 * m["annuo"], 100 * m["volatilita"], m["sharpe"], 100 * m["calo_massimo"], 100 * s2["annuo"], s2["sharpe"], 100 * s2["calo_massimo"]))
    if salva:
        with open(USCITA, "w", encoding="utf-8") as fh:
            json.dump(ris, fh, separators=(",", ":"))
        log("[portafoglio] scritto %s" % os.path.basename(USCITA))
    return ris


def main(argv=None):
    studia()
    return 0


if __name__ == "__main__":
    sys.exit(main())
