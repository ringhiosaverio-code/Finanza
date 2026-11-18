#!/usr/bin/env python3
"""Crypto a medio e lungo termine: cosa dicono i dati veri, con regole fissate prima di guardare.

    python3 crypto_lungo.py        # stampa i risultati

Sulle chiusure giornaliere in euro delle crypto dell'app (Yahoo Finance, tutta la storia disponibile):

  compra e tieni     dal primo anno di storia di ogni crypto (il primo anno, quello del lancio, si salta)
  tendenza 200 / 50  dentro quando la chiusura di ieri è sopra la media dei suoi ultimi 200 (o 50) giorni,
                     altrimenti in euro; 0,2 % di costi a ogni cambio. Media calcolata su tutta la storia.
  paniere            pesi uguali tra le crypto con almeno un anno di storia, ribilanciato il primo di ogni
                     mese (0,2 % sul denaro spostato); dal giorno in cui ce ne sono almeno 3
  durata             quante volte tenere 1 mese, 1, 2 o 4 anni ha chiuso in guadagno (tutte le partenze)
  a rate o subito    12 rate mensili contro tutto subito, su tutte le finestre di 12 mesi
  oggi               la crypto è sopra o sotto le medie di 200 e 50 giorni?

Ogni misura sulle due metà del periodo, per vedere se regge. Le crypto sono quelle che esistono ancora
oggi (molte altre sono sparite): i risultati del passato sono migliori di quelli che si potevano avere
scegliendo allora. Solo libreria standard. Non è consulenza finanziaria.
"""

import datetime
import math
import statistics
import sys

import simula

COSTO = 0.002                 # per lato, a ogni cambio (exchange in euro, come nel resto dell'app)
ANNO = 365                    # le crypto si scambiano tutti i giorni
DURATE = (("1 mese", 30), ("1 anno", 365), ("2 anni", 730), ("4 anni", 1460))
REGOLE = (("compra e tieni", None), ("tendenza 200", 200), ("tendenza 50", 50))
PRINCIPALI = ("BTC-EUR", "ETH-EUR")


def carica(log=print):
    dati = {}
    for s in simula.CRYPTO:
        try:
            _, d, c = simula.series(simula.fetch_max(s))
        except (simula.SimError, ValueError, KeyError, OSError) as e:
            log("[crypto_lungo] %s saltato: %s" % (s, e))
            continue
        if len(c) > ANNO + 30:
            dati[s] = (list(d), [float(x) for x in c])
    return dati


def medie(c, n):
    """Media mobile semplice di n giorni (None finché non ci sono n chiusure)."""
    out, somma = [], 0.0
    for i, x in enumerate(c):
        somma += x
        if i >= n:
            somma -= c[i - n]
        out.append(somma / n if i >= n - 1 else None)
    return out


def rendimenti(c, n=None, da=0, costo=COSTO):
    """Rendimenti giornalieri da `da` in poi: compra e tieni (n None) o tendenza a n giorni (dentro se la
    chiusura di ieri è sopra la sua media). -> (rendimenti, quota di giorni dentro, cambi)."""
    r = [c[i + 1] / c[i] - 1 for i in range(da, len(c) - 1)]
    if n is None:
        return r, 1.0, 0
    ma = medie(c, n)
    out, prima, cambi, dentro_tot = [], False, 0, 0
    for k, i in enumerate(range(da, len(c) - 1)):
        dentro = ma[i] is not None and c[i] > ma[i]
        x = r[k] if dentro else 0.0
        if dentro != prima:
            x -= costo
            cambi += 1
        prima = dentro
        dentro_tot += dentro
        out.append(x)
    return out, dentro_tot / max(1, len(out)), cambi


def misure(r):
    """-> crescita l'anno, calo massimo, oscillazione annua."""
    eq, picco, calo = 1.0, 1.0, 0.0
    for x in r:
        eq *= 1 + x
        picco = max(picco, eq)
        calo = min(calo, eq / picco - 1)
    anni = len(r) / ANNO
    return {"anno": round(eq ** (1 / anni) - 1, 4) if anni > 0 and eq > 0 else None, "calo": round(calo, 4),
            "oscillazione": round(statistics.pstdev(r) * math.sqrt(ANNO), 4) if len(r) > 1 else None}


def per_crypto(dati):
    out = []
    for s, (d, c) in dati.items():
        if len(c) < 3 * ANNO:
            continue
        riga = {"symbol": s, "dal": d[ANNO], "al": d[-1], "anni": round((len(c) - 1 - ANNO) / ANNO, 1), "regole": {}}
        meta = ANNO + (len(c) - 1 - ANNO) // 2
        for nome, n in REGOLE:
            r, dentro, cambi = rendimenti(c, n, da=ANNO)
            m = misure(r)
            m.update({"dentro": round(dentro, 3), "cambi": cambi,
                      "prima": misure(rendimenti(c[:meta + 1], n, da=ANNO)[0]),
                      "dopo": misure(rendimenti(c, n, da=meta)[0])})
            riga["regole"][nome] = m
        riga["meta"] = d[meta]
        out.append(riga)
    return out


def paniere(dati):
    """Pesi uguali tra le crypto con almeno un anno di storia, ribilanciati il primo giorno di ogni mese."""
    date = sorted({x for d, _ in dati.values() for x in d})
    idx = {s: {x: i for i, x in enumerate(d)} for s, (d, _) in dati.items()}
    ma200 = {s: medie(c, 200) for s, (_, c) in dati.items()}
    risultati = {}
    for nome, n in (("compra e tieni", None), ("tendenza 200", 200)):
        quote, dentro, valori, inizio, mese = {}, {}, [], None, None
        for k in range(1, len(date)):
            ieri, oggi = date[k - 1], date[k]
            ok = [s for s in dati if idx[s].get(ieri) is not None and idx[s].get(oggi) is not None and idx[s][ieri] >= ANNO]
            if inizio is None:
                if len(ok) < 3:
                    continue
                inizio, valori = ieri, [1.0]
            v = valori[-1]
            if oggi[:7] != mese:                                     # ribilancia: pesi uguali
                mese = oggi[:7]
                nuove = {s: v / len(ok) for s in ok}
                spostato = sum(abs(nuove.get(s, 0) - quote.get(s, 0)) for s in set(nuove) | set(quote))
                v -= spostato * COSTO
                quote = {s: v / len(ok) for s in ok}
            for s in list(quote):
                if s not in ok:                                      # dati mancanti quel giorno: resta fermo
                    continue
                c, i, j = dati[s][1], idx[s][oggi], idx[s][ieri]
                su = n is None or (ma200[s][j] is not None and c[j] > ma200[s][j])
                if n is not None and su != dentro.get(s, False):
                    quote[s] *= 1 - COSTO
                    dentro[s] = su
                if su:
                    quote[s] *= c[i] / c[j]
            valori.append(sum(quote.values()))
        r = [valori[i + 1] / valori[i] - 1 for i in range(len(valori) - 1)]
        meta = len(r) // 2
        risultati[nome] = dict(misure(r), prima=misure(r[:meta]), dopo=misure(r[meta:]))
        risultati["dal"] = inizio
    risultati["crypto"] = len(dati)
    return risultati


def durate(dati):
    out = {}
    for s in PRINCIPALI:
        if s not in dati:
            continue
        d, c = dati[s]
        out[s] = []
        for nome, h in DURATE:
            if len(c) <= h + 30:
                continue
            r = sorted(c[i + h] / c[i] - 1 for i in range(len(c) - h))
            out[s].append({"durata": nome, "giorni": h, "p_gain": round(sum(x > 0 for x in r) / len(r), 3),
                           "tipico": round(statistics.median(r), 4), "dieci": round(r[len(r) // 10], 4),
                           "peggiore": round(r[0], 4), "indipendenti": len(c) // h})
    return out


def rate(dati, mesi=12, passo=30):
    """12 rate mensili (una ogni 30 giorni) contro tutto subito, valutati alla fine dei 12 mesi."""
    out = {}
    fine = mesi * passo + 5
    for s in PRINCIPALI:
        if s not in dati:
            continue
        _, c = dati[s]
        subito, a_rate = [], []
        for i in range(len(c) - fine):
            f = c[i + fine]
            subito.append(f / c[i] - 1)
            a_rate.append(sum(f / c[i + k * passo] for k in range(mesi)) / mesi - 1)
        if not subito:
            continue
        vince = sum(a > b for a, b in zip(subito, a_rate)) / len(subito)
        q = lambda x, p: sorted(x)[int(p * (len(x) - 1))]
        out[s] = {"finestre": len(subito), "subito_vince": round(vince, 3),
                  "subito": {"tipico": round(statistics.median(subito), 4), "dieci": round(q(subito, .1), 4), "peggiore": round(min(subito), 4)},
                  "rate": {"tipico": round(statistics.median(a_rate), 4), "dieci": round(q(a_rate, .1), 4), "peggiore": round(min(a_rate), 4)}}
    return out


def oggi(dati):
    out = []
    for s, (d, c) in dati.items():
        m200, m50 = medie(c, 200)[-1], medie(c, 50)[-1]
        if m200 is None:
            continue
        sopra = c[-1] > m200
        giorni = 0                                                   # da quanti giorni è da quella parte
        ma = medie(c, 200)
        for i in range(len(c) - 1, 0, -1):
            if ma[i] is None or (c[i] > ma[i]) != sopra:
                break
            giorni += 1
        out.append({"symbol": s, "data": d[-1], "prezzo": round(c[-1], 6), "media200": round(m200, 6), "media50": round(m50, 6),
                    "sopra200": sopra, "sopra50": c[-1] > m50, "dist200": round(c[-1] / m200 - 1, 4), "giorni": giorni})
    return out


def analisi(log=print):
    dati = carica(log)
    if not dati:
        raise ValueError("nessun dato delle crypto")
    return {"generato": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "costo": COSTO,
            "per_crypto": per_crypto(dati), "paniere": paniere(dati), "durate": durate(dati), "rate": rate(dati), "oggi": oggi(dati)}


def main():
    A = analisi()
    p = lambda x: "  n/d" if x is None else "%+5.0f%%" % (100 * x)
    print("PER CRYPTO (dal primo anno di storia): crescita l'anno, calo massimo; prima metà | seconda metà")
    for r in A["per_crypto"]:
        print("%-9s %s→%s" % (r["symbol"], r["dal"], r["al"]))
        for nome, m in r["regole"].items():
            print("   %-15s %s calo %s | prima %s (calo %s) · dopo %s (calo %s) · dentro %3.0f%%, %d cambi" % (
                nome, p(m["anno"]), p(m["calo"]), p(m["prima"]["anno"]), p(m["prima"]["calo"]), p(m["dopo"]["anno"]), p(m["dopo"]["calo"]),
                100 * m["dentro"], m["cambi"]))
    P = A["paniere"]
    print("\nPANIERE a pesi uguali dal %s:" % P["dal"])
    for nome in ("compra e tieni", "tendenza 200"):
        m = P[nome]
        print("   %-15s %s calo %s | prima %s · dopo %s" % (nome, p(m["anno"]), p(m["calo"]), p(m["prima"]["anno"]), p(m["dopo"]["anno"])))
    print("\nTENERE: quante volte in guadagno")
    for s, rr in A["durate"].items():
        for x in rr:
            print("   %-8s %-7s %3.0f%% · tipico %s · 1 su 10 sotto %s · peggiore %s · periodi separati %d" % (
                s, x["durata"], 100 * x["p_gain"], p(x["tipico"]), p(x["dieci"]), p(x["peggiore"]), x["indipendenti"]))
    print("\nA RATE (12 mesi) O TUTTO SUBITO")
    for s, x in A["rate"].items():
        print("   %-8s subito meglio nel %3.0f%% delle finestre · tipico: subito %s, a rate %s · peggiore: subito %s, a rate %s" % (
            s, 100 * x["subito_vince"], p(x["subito"]["tipico"]), p(x["rate"]["tipico"]), p(x["subito"]["peggiore"]), p(x["rate"]["peggiore"])))
    print("\nOGGI")
    for x in A["oggi"]:
        print("   %-9s %s la media a 200 giorni (%s) da %d giorni · %s quella a 50" % (
            x["symbol"], "sopra" if x["sopra200"] else "sotto", p(x["dist200"]), x["giorni"], "sopra" if x["sopra50"] else "sotto"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
