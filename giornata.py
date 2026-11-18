#!/usr/bin/env python3
"""In giornata: comprare e vendere nella stessa seduta.

    python3 giornata.py      # stampa il piano per la prossima seduta; app.py lo mette nella sezione "In giornata"

Le regole sono quelle dei libri e degli studi (vedi REGOLE), verificate da libri.py su 25 anni di
candele giornaliere: nessuna resta in guadagno dopo i costi in entrambi i periodi. Il piano serve a
esercitarsi con una regola precisa e con i numeri veri davanti, non perché guadagni.

Due piani. Il primo usa la regola "Oops!" di Larry Williams (Long-Term Secrets to Short-Term Trading, 1999):
se la seduta apre sotto il minimo della seduta prima, si compra quando il prezzo risale a quel
minimo (ordine "stop") e si vende in chiusura. È la regola andata più vicina al pareggio, uguale nei
due periodi. Per ogni titolo: il livello, quante volte è successo nella sua storia e com'è andata.
Il secondo è l'unica regola di breve periodo che regge, ma non è in giornata: il "momento notturno"
(Lou, Polk, Skouras 2019), i 10 titoli USA con le notti migliori delle ultime 21, comprati in
chiusura e venduti all'apertura dopo. Regge solo con costi molto bassi (fino a 0,02 % tra entrata
e uscita, ordini sulle aste di chiusura e apertura): libri.py lo verifica su 25 anni.
Solo libreria standard.
"""

import datetime
import json
import sys

import settimana
import simula

# le regole per la stessa seduta, fissate prima di guardare i risultati (libri.py le verifica)
REGOLE = [
    {"id": "ogni", "nome": "Ogni giorno: compra all'apertura, vendi in chiusura", "fonte": "riferimento",
     "desc": "Il movimento medio di una seduta, senza nessuna regola."},
    {"id": "oops", "nome": "Oops! di Williams", "fonte": "Williams 1999",
     "desc": "Se apre sotto il minimo di ieri, compra quando risale a quel minimo; vendi in chiusura."},
    {"id": "gapgiu", "nome": "Gap giù all'apertura", "fonte": "Akbas, Boehmer, Jiang, Koch 2022",
     "desc": "Se apre sotto la chiusura di ieri di almeno un'escursione media (ATR 14), compra all'apertura; vendi in chiusura."},
    {"id": "gapgiu200", "nome": "Gap giù, titolo in salita", "fonte": "Akbas e altri 2022",
     "desc": "Lo stesso, solo se ieri chiudeva sopra la media a 200 giorni."},
    {"id": "gapsu", "nome": "Gap su all'apertura", "fonte": "controllo",
     "desc": "Se apre sopra la chiusura di ieri di almeno un'escursione media, compra all'apertura; vendi in chiusura."},
    {"id": "dopocalo", "nome": "Il giorno dopo un forte ribasso", "fonte": "controllo",
     "desc": "Se ieri ha perso più di due escursioni medie, compra all'apertura; vendi in chiusura."},
    {"id": "primo", "nome": "Primo giorno del mese", "fonte": "Ariel 1987",
     "desc": "Compra all'apertura del primo giorno di borsa del mese; vendi in chiusura."},
]
CHIUSURA = {"usa": "21:55 ora italiana (la borsa chiude alle 22)", "italia": "17:25 (la borsa chiude alle 17:30)"}
APERTURA = {"usa": "15:30 ora italiana", "italia": "9:00"}
PER_MERCATO = {"usa": 8, "italia": 6}           # i titoli più scambiati per cui fare il piano


def giornaliere(sym):
    """Candele giornaliere corrette per dividendi e split: (date, O, H, L, C, volumi in valuta).
    Se Yahoo lascia vuota l'ultima seduta, la prende dai metadati (prezzo, massimo, minimo)."""
    text = simula.fetch_max(sym)
    _, dts, _ = simula.series(text)
    ok = set(dts)
    res = json.loads(text)["chart"]["result"][0]
    meta = res.get("meta", {})
    q, off = res["indicators"]["quote"][0], meta.get("gmtoffset", 0)
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q["close"]
    vol = q.get("volume") or [None] * len(res["timestamp"])
    rows = {}
    for t, o, h, l, c, a, v in zip(res["timestamp"], q["open"], q["high"], q["low"], q["close"], adj, vol):
        if None in (o, h, l, c, a) or min(o, h, l, c, a) <= 0:
            continue
        d = datetime.datetime.fromtimestamp(t + off, datetime.timezone.utc).strftime("%Y-%m-%d")
        if d in ok:
            f = a / c
            rows[d] = (o * f, max(h, o, c) * f, min(l, o, c) * f, a, (v or 0) * c)
    extra = settimana.chiusura_mancante(meta, max(rows) if rows else None)
    if extra and extra[0] in ok:
        d, c, h, lo = extra
        rows[d] = (c, h, lo, c, 0.0)
    d = sorted(rows)
    return d, [rows[k][0] for k in d], [rows[k][1] for k in d], [rows[k][2] for k in d], [rows[k][3] for k in d], [rows[k][4] for k in d]


def media_mobile(x, n):
    out, s = [None] * len(x), 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def atr(H, L, C, n=14):
    tr = [H[0] - L[0]] + [max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1])) for i in range(1, len(C))]
    return media_mobile(tr, n)


def operazioni(d, O, H, L, C, regola):
    """Le operazioni aperte e chiuse nella stessa seduta: lista di (data, rendimento lordo)."""
    n, out = len(C), []
    a14, m200 = atr(H, L, C), media_mobile(C, 200)
    buona = lambda i: H[i] > L[i] and L[i] <= O[i] <= H[i]
    for t in range(201, n):
        if not buona(t) or not buona(t - 1) or not a14[t - 1]:
            continue
        gap, ap = O[t] / C[t - 1] - 1, a14[t - 1] / C[t - 1]
        if regola == "ogni":
            out.append((d[t], C[t] / O[t] - 1))
        elif regola == "oops":
            if O[t] < L[t - 1] <= H[t]:
                out.append((d[t], C[t] / L[t - 1] - 1))
        elif regola == "gapgiu" and gap <= -ap:
            out.append((d[t], C[t] / O[t] - 1))
        elif regola == "gapgiu200" and gap <= -ap and m200[t - 1] and C[t - 1] > m200[t - 1]:
            out.append((d[t], C[t] / O[t] - 1))
        elif regola == "gapsu" and gap >= ap:
            out.append((d[t], C[t] / O[t] - 1))
        elif regola == "dopocalo" and C[t - 1] / C[t - 2] - 1 <= -2 * ap:
            out.append((d[t], C[t] / O[t] - 1))
        elif regola == "primo" and d[t][:7] != d[t - 1][:7]:
            out.append((d[t], C[t] / O[t] - 1))
    return out


def storia(d, O, H, L, C, costo):
    """Com'è andata la regola Oops! su questo titolo: quante volte, in guadagno, media dopo i costi."""
    ops = operazioni(d, O, H, L, C, "oops")
    giorni = max(1, len(C) - 201)
    if not ops:
        return {"n": 0, "giorni": giorni}
    nette = sorted(r - costo for _, r in ops)
    return {"n": len(ops), "giorni": giorni, "frequenza": round(len(ops) / giorni, 4),
            "p_gain": round(sum(1 for x in nette if x > 0) / len(nette), 4), "media": round(sum(nette) / len(nette), 5),
            "p10": round(nette[len(nette) // 10], 4), "da": ops[0][0]}


def piani(log=print):
    """Il piano Oops! per la prossima seduta dei titoli più scambiati di ogni mercato."""
    out = []
    for m, quanti in PER_MERCATO.items():
        cfg = settimana.MERCATI[m]
        righe = []
        for sym in cfg["universo"]:
            try:
                d, O, H, L, C, V = giornaliere(sym)
            except (simula.SimError, ValueError, KeyError, OSError) as e:
                log("[giornata] %s saltato: %s" % (sym, e))
                continue
            if len(C) < 300:
                continue
            scambi = sum(V[-63:]) / 63
            righe.append((scambi, sym, d, O, H, L, C))
        righe.sort(reverse=True)
        for scambi, sym, d, O, H, L, C in righe[:quanti]:
            a14 = atr(H, L, C)[-1]
            out.append({"mercato": m, "symbol": sym, "valuta": cfg["valuta"], "data": d[-1], "chiusura": round(C[-1], 4),
                        "minimo": round(L[-1], 4), "massimo": round(H[-1], 4), "atr": round(a14, 4),
                        "distanza": round(L[-1] / C[-1] - 1, 4), "apertura": APERTURA[m], "vendi_entro": CHIUSURA[m],
                        "scambi": round(scambi), "storia": storia(d, O, H, L, C, cfg["costo"] / 100)})
    try:
        notte = piano_notte(log)
    except Exception as e:                                       # rete o dati: il resto del piano resta
        log("[giornata] piano della notte saltato: %s" % e)
        notte = None
    return {"regola": "oops", "regole": REGOLE, "piani": out, "costi": {m: settimana.MERCATI[m]["costo"] / 100 for m in PER_MERCATO},
            "notte": notte}


NOTTI = 21            # notti su cui si misura il "momento notturno"
TOP_NOTTE = 10        # quanti titoli si comprano
SOGLIA_COSTI = 0.0002 # regge (in entrambe le metà, t >= 2) con costi fino a 0,02 % tra entrata e uscita (libri.py)


def serie_notte_testo(text):
    """Dalla risposta del grafico di Yahoo: [(data, apertura, chiusura o None se la seduta è in corso)],
    corrette per dividendi e split come le chiusure."""
    res = json.loads(text)["chart"]["result"][0]
    meta, q = res.get("meta", {}), res["indicators"]["quote"][0]
    off = meta.get("gmtoffset", 0)
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q["close"]
    righe = {}
    for t, o, c, a in zip(res.get("timestamp") or [], q["open"], q["close"], adj):
        if o is None or o <= 0:
            continue
        d = datetime.datetime.fromtimestamp(t + off, datetime.timezone.utc).strftime("%Y-%m-%d")
        f = (a / c) if (a and c) else 1.0
        righe[d] = (o * f, a if (a and c) else None)                    # apertura corretta, chiusura (None se in corso)
    return [(d, righe[d][0], righe[d][1]) for d in sorted(righe)]


def notti(sym):
    """I rendimenti notturni (logaritmo di apertura / chiusura del giorno prima) di un titolo, compresa
    l'apertura di oggi se la seduta è già iniziata. -> (date, rendimenti, ultima chiusura, data della chiusura)."""
    import math
    S = serie_notte_testo(simula.fetch_max(sym))
    date, rend = [], []
    for (g0, _, c0), (g1, o1, _) in zip(S, S[1:]):
        if c0 and o1:
            date.append(g1)
            rend.append(math.log(o1 / c0))
    chiuse = [(g, c) for g, _, c in S if c]
    return date, rend, (chiuse[-1][1] if chiuse else None), (chiuse[-1][0] if chiuse else None)


def prezzi_notte(log=print, quante=45):
    """Aperture e chiusure ufficiali delle ultime `quante` sedute dei titoli USA: il robot dell'app ci
    rifà la lista di ogni giorno e chiude ogni notte con i prezzi veri. {simbolo: [[data, apertura, chiusura]]}"""
    out = {}
    for sym in settimana.MERCATI["usa"]["universo"]:
        try:
            S = serie_notte_testo(simula.fetch_max(sym))
        except (simula.SimError, ValueError, KeyError, OSError) as e:
            log("[giornata] %s saltato: %s" % (sym, e))
            continue
        out[sym] = [[d, round(o, 4), round(c, 4) if c else None] for d, o, c in S[-quante:]]
    return out


def piano_notte(log=print, adesso=None):
    """Il momento notturno (Lou, Polk, Skouras 2019): i TOP_NOTTE titoli USA con la media più alta dei
    rendimenti delle ultime NOTTI notti; si comprano in chiusura e si vendono all'apertura dopo."""
    righe = []
    for sym in settimana.MERCATI["usa"]["universo"]:
        try:
            date, rend, chiusura, giorno = notti(sym)
        except (simula.SimError, ValueError, KeyError, OSError) as e:
            log("[giornata] %s saltato: %s" % (sym, e))
            continue
        if len(rend) > NOTTI and chiusura:
            m = sum(rend[-NOTTI:]) / NOTTI
            righe.append({"symbol": sym, "media_notte": round(m, 6), "ultima_notte": date[-1], "chiusura": round(chiusura, 4),
                          "data_chiusura": giorno, "notti_su": round(sum(1 for x in rend[-NOTTI:] if x > 0) / NOTTI, 3)})
    righe.sort(key=lambda r: -r["media_notte"])
    ny = adesso or settimana.now_in("America/New_York")
    oggi = ny.strftime("%Y-%m-%d")
    aperta_oggi = oggi in settimana.trading_days_after((ny - datetime.timedelta(days=7)).strftime("%Y-%m-%d"), 10, "usa")
    compra = oggi if aperta_oggi and (ny.hour, ny.minute) < (15, 50) else settimana.trading_days_after(oggi, 1, "usa")[0]
    vendi = settimana.trading_days_after(compra, 1, "usa")[0]
    return {"titoli": righe[:TOP_NOTTE], "notti": NOTTI, "compra": compra, "vendi": vendi, "candidati": len(righe),
            "prezzi": prezzi_notte(log),
            "ordini": {"compra": "al prezzo di chiusura (MOC), entro le 21:50 ora italiana",
                       "vendi": "al prezzo di apertura (MOO), entro le 15:28 ora italiana"},
            "soglia_costi": SOGLIA_COSTI}


def main():
    r = piani()
    print("PIANO PER LA PROSSIMA SEDUTA (Oops! di Williams: se apre sotto il minimo, compra quando risale lì; vendi in chiusura)")
    for p in r["piani"]:
        s = p["storia"]
        print("  %-8s %-6s chiusura %10.3f  livello %10.3f (%+.1f%%)  storia: %d volte, %.0f%% in guadagno, media %+.2f%% dopo i costi" % (
            p["symbol"], p["mercato"], p["chiusura"], p["minimo"], 100 * p["distanza"], s.get("n", 0),
            100 * s.get("p_gain", 0), 100 * s.get("media", 0)))
    n = r.get("notte")
    if n:
        print("\nMOMENTO NOTTURNO: compra alla chiusura del %s, vendi all'apertura del %s (solo con costi fino a %.2f %%)" % (
            n["compra"], n["vendi"], 100 * n["soglia_costi"]))
        for t in n["titoli"]:
            print("  %-6s media delle ultime %d notti %+.3f %% · in salita %2.0f %% delle notti · chiusura %s" % (
                t["symbol"], n["notti"], 100 * t["media_notte"], 100 * t["notti_su"], t["chiusura"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
