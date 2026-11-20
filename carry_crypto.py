#!/usr/bin/env python3
"""Il carry delle crypto: comprare la crypto e vendere nello stesso tempo il suo contratto perpetuo (futures senza
scadenza) per la stessa cifra. I movimenti del prezzo si annullano; si incassa il "funding" che chi compra i futures
paga a chi li vende quando sono più cari del prezzo a pronti (quando è negativo, si paga). È la strategia "cash and
carry" studiata dalla Banca dei Regolamenti Internazionali (Schmeling, Schrimpf e Todorov, "Crypto carry", BIS working
paper 1087): il carry è spesso alto, ma precede i crolli e può girarsi in fretta.

    python3 carry_crypto.py        # un anno di funding orario dei futures di Kraken: carry_crypto.json

Si confrontano: stare sempre dentro; entrare solo quando il funding medio degli ultimi 7 giorni copre i costi (0,5 % tra
entrata e uscita sulle due gambe) e uscire quando la media scende sotto zero. Non si contano i piccoli scarti tra i due
prezzi, il rischio della piattaforma e le tasse. Non è consulenza finanziaria.
"""

import datetime
import json
import math
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
USCITA = os.path.join(ROOT, "carry_crypto.json")
CONTRATTI = {"BTC": "PF_XBTUSD", "ETH": "PF_ETHUSD", "SOL": "PF_SOLUSD", "XRP": "PF_XRPUSD", "DOGE": "PF_DOGEUSD", "ADA": "PF_ADAUSD",
             "LTC": "PF_LTCUSD", "LINK": "PF_LINKUSD", "AVAX": "PF_AVAXUSD", "DOT": "PF_DOTUSD"}
COSTO = 0.0025                     # entrare o uscire: due gambe (pronti 0,2 %, futures 0,05 %)
ORE_MEDIA = 7 * 24


def funding(contratto):
    url = "https://futures.kraken.com/derivatives/api/v4/historicalfundingrates?symbol=" + contratto
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "finanza"}), timeout=40) as r:
        dati = json.load(r).get("rates") or []
    return [(x["timestamp"], float(x["relativeFundingRate"])) for x in dati]


def prova(r, soglia_entrata, soglia_uscita=0.0):
    """Rendimento del carry ora per ora con la regola: dentro quando la media delle ultime 7 giorni supera la soglia."""
    dentro, conto, massimo, calo, ore_dentro, cambi = False, 1.0, 1.0, 0.0, 0, 0
    for i in range(len(r)):
        if i >= ORE_MEDIA:
            m = sum(r[i - ORE_MEDIA:i]) / ORE_MEDIA
            if soglia_entrata is None:
                voglio = True
            else:
                voglio = m > soglia_entrata if not dentro else m > soglia_uscita
            if voglio != dentro:
                conto *= 1 - COSTO
                dentro, cambi = voglio, cambi + 1
        if dentro:
            conto *= 1 + r[i]
            ore_dentro += 1
        massimo = max(massimo, conto)
        calo = min(calo, conto / massimo - 1)
    anni = max(len(r) - ORE_MEDIA, 1) / (24 * 365)
    return {"annuo": conto ** (1 / anni) - 1, "calo_massimo": calo, "dentro": ore_dentro / max(len(r) - ORE_MEDIA, 1), "cambi": cambi}


def studia(log=print, salva=True):
    ris = {"creato": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "costo": COSTO, "crypto": {}}
    soglia = COSTO * 2 / (30 * 24)                                     # coprire i costi in circa un mese
    for nome, c in CONTRATTI.items():
        try:
            dati = funding(c)
        except Exception as e:
            log("[carry] %s saltato: %s" % (nome, str(e)[:80]))
            continue
        if len(dati) < 24 * 60:
            continue
        r = [x[1] for x in dati]
        media7 = sum(r[-ORE_MEDIA:]) / ORE_MEDIA
        ris["crypto"][nome] = {"da": dati[0][0][:10], "a": dati[-1][0][:10], "sempre": prova(r, None), "regola": prova(r, soglia),
                               "oggi_annuo": media7 * 24 * 365, "oggi_dentro": media7 > soglia}
        x = ris["crypto"][nome]
        log("[carry] %-5s sempre dentro %+6.1f %% l'anno (calo %5.1f %%) · con la regola %+6.1f %% (dentro %3.0f %% del tempo, %d cambi) · oggi %+5.1f %% l'anno%s" % (
            nome, 100 * x["sempre"]["annuo"], 100 * x["sempre"]["calo_massimo"], 100 * x["regola"]["annuo"], 100 * x["regola"]["dentro"],
            x["regola"]["cambi"], 100 * x["oggi_annuo"], " (dentro)" if x["oggi_dentro"] else ""))
    if salva:
        with open(USCITA, "w", encoding="utf-8") as fh:
            json.dump(ris, fh, separators=(",", ":"))
        log("[carry] scritto %s" % os.path.basename(USCITA))
    return ris


def main(argv=None):
    studia()
    return 0


if __name__ == "__main__":
    sys.exit(main())
