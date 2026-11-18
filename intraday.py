#!/usr/bin/env python3
"""Crypto intraday: entrate e uscite per le prossime 24 ore, con la verifica delle stesse regole
sugli ultimi 2 anni di candele orarie (Yahoo Finance).

    python3 intraday.py              # stampa i piani di oggi e la verifica; app.py li mette nella sezione Crypto
    python3 intraday.py --varianti   # prova 9 varianti delle regole, primo anno contro secondo

Due regole, fissate prima di guardare i risultati, più il confronto "compra e vendi dopo 24 ore":
  Ribasso  ordine limite sotto il prezzo attuale (ultima chiusura oraria - 3 ATR orari);
           protezione 3 ATR sotto l'entrata, obiettivo il prezzo di partenza.
  Rottura  ordine che scatta se il prezzo supera il massimo delle ultime 24 ore;
           protezione 1,5 ATR sotto, obiettivo il doppio del rischio sopra.
  Il piano vale 24 ore: se l'ordine non scatta, niente operazione; se scatta, si chiude al più
  tardi 24 ore dopo l'inizio del piano. Costi 0,2 % per lato. ATR = escursione media di una
  candela oraria nelle ultime 24 ore.
La verifica rifà il piano alle 17 e alle 21 UTC (quando si aggiorna l'app) di ogni giorno degli
ultimi 2 anni, per tutte e 12 le crypto, e separa il primo anno dal secondo.
Solo libreria standard. Non è consulenza finanziaria.
"""

import datetime
import json
import os
import sys
import time
import urllib.request

import simula

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "trader", "cache", "intraday")
UA = "Mozilla/5.0 (compatible; finanza/1.0)"
COSTO = 0.002                      # per lato
ORE = 24
STORIA_ORE = 7 * 24                # i piani degli ultimi 7 giorni, con com'è andata: il robot dell'app li usa
REGOLE = [
    {"id": "ribasso", "nome": "Compra il ribasso",
     "desc": "Ordine limite 3 escursioni orarie sotto il prezzo; protezione 3 escursioni sotto l'entrata; obiettivo il prezzo di partenza."},
    {"id": "rottura", "nome": "Compra la rottura",
     "desc": "Ordine che scatta sopra il massimo delle ultime 24 ore; protezione 1,5 escursioni sotto; obiettivo il doppio del rischio."},
    {"id": "tempo", "nome": "Compra ora, vendi tra 24 ore", "desc": "Il confronto: nessun livello, solo il tempo."},
]


def candele(sym, max_age=3600):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, sym + ".json")
    adesso = time.time()
    # da riscaricare se vecchio, o se da allora si è chiusa un'altra candela oraria
    if (not os.path.exists(path) or adesso - os.path.getmtime(path) > max_age
            or int(adesso // 3600) > int(os.path.getmtime(path) // 3600)):
        url = "https://query2.finance.yahoo.com/v8/finance/chart/%s?range=730d&interval=1h" % sym
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=40) as r:
            text = r.read().decode("utf-8", "replace")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    letto = os.path.getmtime(path)
    with open(path, encoding="utf-8") as fh:
        res = json.load(fh)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    # solo candele orarie già chiuse quando sono state scaricate: Yahoo aggiunge la candela in corso
    # e, in fondo, un punto con l'ora dell'ultimo scambio
    return [(t, o, h, l, c) for t, o, h, l, c in zip(res["timestamp"], q["open"], q["high"], q["low"], q["close"])
            if None not in (o, h, l, c) and t % 3600 == 0 and t + 3600 <= letto]


def atr(B, i, n=24):
    return sum(max(B[k][2] - B[k][3], abs(B[k][2] - B[k - 1][4]), abs(B[k][3] - B[k - 1][4]))
               for k in range(i - n + 1, i + 1)) / n


PARAMETRI = {"ribasso": {"tipo": "ribasso", "e": 3, "s": 3, "ore": ORE},
             "rottura": {"tipo": "rottura", "s": 1.5, "t": 2, "ore": ORE},
             "tempo": {"tipo": "tempo", "ore": ORE}}
# le regole dell'app e 9 varianti, fissate prima di guardare i risultati: python3 intraday.py --varianti
VARIANTI = [
    ("Compra il ribasso", PARAMETRI["ribasso"]),
    ("Compra la rottura", PARAMETRI["rottura"]),
    ("Compra ora, vendi tra 24 ore", PARAMETRI["tempo"]),
    ("Ribasso, solo con la tendenza a favore", dict(PARAMETRI["ribasso"], filtro="tendenza")),
    ("Rottura, solo con la tendenza a favore", dict(PARAMETRI["rottura"], filtro="tendenza")),
    ("24 ore, solo con la tendenza a favore", dict(PARAMETRI["tempo"], filtro="tendenza")),
    ("Ribasso più profondo (5 escursioni)", dict(PARAMETRI["ribasso"], e=5)),
    ("Ribasso, piano valido 72 ore", dict(PARAMETRI["ribasso"], ore=72)),
    ("Rottura, piano valido 72 ore", dict(PARAMETRI["rottura"], ore=72)),
    ("Compra ora, vendi tra 7 giorni", dict(PARAMETRI["tempo"], ore=168)),
    ("7 giorni, solo con la tendenza a favore", dict(PARAMETRI["tempo"], ore=168, filtro="tendenza")),
    ("7 giorni, solo se è salita nell'ultima settimana", dict(PARAMETRI["tempo"], ore=168, filtro="settimana")),
]


def livelli(B, i, regola, v=None):
    """Entrata, protezione e obiettivo del piano fatto alla chiusura della candela i."""
    v = v or PARAMETRI[regola]
    c, a = B[i][4], atr(B, i)
    if v["tipo"] == "ribasso":
        e = c - v["e"] * a
        return {"entrata": e, "tipo": "limite", "protezione": e - v["s"] * a, "obiettivo": c}
    if v["tipo"] == "rottura":
        e = max(b[2] for b in B[i - 23:i + 1])
        return {"entrata": e, "tipo": "sopra", "protezione": e - v["s"] * a, "obiettivo": e + v["t"] * v["s"] * a}
    return {"entrata": c, "tipo": "subito", "protezione": None, "obiettivo": None}


def filtro(B, i, f):
    """tendenza: prezzo sopra la media delle ultime 20 giornate (480 ore); settimana: sopra di 7 giorni fa."""
    if not f:
        return True
    if f == "tendenza":
        return B[i][4] > sum(b[4] for b in B[i - 479:i + 1]) / 480
    return B[i][4] > B[i - 168][4]


def esito(B, i, regola, v=None):
    """Rendimento netto del piano fatto alla candela i, 'no' se l'ordine non scatta (o il filtro dice
    di non entrare), None senza dati."""
    v = v or PARAMETRI[regola]
    win = B[i + 1:i + 1 + v["ore"]]
    if len(win) < v["ore"]:
        return None
    if not filtro(B, i, v.get("filtro")):
        return "no"
    if v["tipo"] == "tempo":
        return win[-1][4] / B[i][4] - 1 - 2 * COSTO
    lv = livelli(B, i, regola, v)
    e, stop, tgt = lv["entrata"], lv["protezione"], lv["obiettivo"]
    trig = None
    for k, b in enumerate(win):
        if (v["tipo"] == "ribasso" and b[3] <= e) or (v["tipo"] == "rottura" and b[2] >= e):
            trig = k
            fill = min(e, b[1]) if v["tipo"] == "ribasso" else max(e, b[1])
            break
    if trig is None:
        return "no"
    for k in range(trig, len(win)):
        b = win[k]
        if k > trig and b[1] <= stop:
            return b[1] / fill - 1 - 2 * COSTO
        if k > trig and b[1] >= tgt:
            return b[1] / fill - 1 - 2 * COSTO
        if b[3] <= stop:
            return stop / fill - 1 - 2 * COSTO
        if b[2] >= tgt:
            return tgt / fill - 1 - 2 * COSTO
    return win[-1][4] / fill - 1 - 2 * COSTO


def ora_piano(B, i):
    """Il piano nasce alla chiusura della candela i (che si apre a B[i][0])."""
    return datetime.datetime.fromtimestamp(B[i][0] + 3600, datetime.timezone.utc)


def utc(d):
    return d.strftime("%Y-%m-%d %H:%M UTC")


def piani_recenti(B, ore=(17, 21)):
    """Le candele chiuse alle 17 o alle 21 UTC delle ultime 24 ore, dalla più recente: i piani nascono
    lì, come nella verifica, e ognuno vale 24 ore."""
    out = [i for i in range(len(B) - 1, max(24, len(B) - 1 - ORE), -1) if ora_piano(B, i).hour in ore]
    return out or [len(B) - 1]


def fase(B, i, regola):
    """A che punto è il piano nato alla candela i, rigiocando le candele orarie chiuse dopo:
    attesa (l'entrata non è ancora scattata), dentro, obiettivo, protezione (chiuso),
    scaduto (24 ore senza entrare), scaduto_dentro (24 ore passate: si vende)."""
    win = B[i + 1:i + 1 + ORE]
    if regola == "tempo":
        if len(win) < ORE:
            return {"fase": "dentro", "prezzo_entrata": B[i][4], "quando": utc(ora_piano(B, i))}
        return {"fase": "scaduto_dentro", "prezzo_entrata": B[i][4], "quando": utc(ora_piano(B, i)),
                "rendimento": win[-1][4] / B[i][4] - 1 - 2 * COSTO}
    lv = livelli(B, i, regola)
    e, stop, tgt = lv["entrata"], lv["protezione"], lv["obiettivo"]
    fill, t_in = None, None
    for b in win:
        quando = utc(datetime.datetime.fromtimestamp(b[0], datetime.timezone.utc))
        if fill is None:
            if not ((regola == "ribasso" and b[3] <= e) or (regola == "rottura" and b[2] >= e)):
                continue
            fill, t_in = (min(e, b[1]) if regola == "ribasso" else max(e, b[1])), quando
        for nome, tocca, px in (("protezione", b[3] <= stop, stop), ("obiettivo", b[2] >= tgt, tgt)):
            if tocca:
                return {"fase": nome, "prezzo_entrata": fill, "quando": t_in, "chiusura": quando,
                        "rendimento": px / fill - 1 - 2 * COSTO}
    if len(win) >= ORE:
        if fill is None:
            return {"fase": "scaduto"}
        return {"fase": "scaduto_dentro", "prezzo_entrata": fill, "quando": t_in,
                "rendimento": win[-1][4] / fill - 1 - 2 * COSTO}
    return {"fase": "dentro", "prezzo_entrata": fill, "quando": t_in} if fill is not None else {"fase": "attesa"}


def piano(B, i, regola):
    rnd = lambda d: {k: (round(v, 6) if isinstance(v, float) else v) for k, v in d.items()}
    return dict(rnd(livelli(B, i, regola)), **rnd(fase(B, i, regola)))


def stat(xs):
    done = sorted(x for x in xs if x != "no")
    if not done:
        return {"n": 0, "eseguite": 0}
    return {"n": len(done), "eseguite": round(len(done) / len(xs), 4),
            "p_gain": round(sum(1 for x in done if x > 0) / len(done), 4),
            "media": round(sum(done) / len(done), 5), "tipico": round(done[len(done) // 2], 5),
            "p10": round(done[len(done) // 10], 5), "p90": round(done[9 * len(done) // 10], 5)}


def analizza(log=print, max_age=3600):
    per, tutti = {}, {r["id"]: {"anno1": [], "anno2": []} for r in REGOLE}
    for sym in simula.CRYPTO:
        try:
            B = candele(sym, max_age)
        except Exception as e:                               # rete, dati mancanti
            log("[intraday] %s saltato: %s" % (sym, e))
            continue
        storia = {r["id"]: [] for r in REGOLE}
        for i in range(200, len(B) - ORE - 1):
            h = datetime.datetime.fromtimestamp(B[i][0] + 3600, datetime.timezone.utc).hour
            if h not in (17, 21):
                continue
            meta = "anno1" if B[i][0] < B[0][0] + 365 * 86400 else "anno2"
            for r in REGOLE:
                x = esito(B, i, r["id"])
                if x is not None:
                    storia[r["id"]].append(x)
                    tutti[r["id"]][meta].append(x)
        rec = piani_recenti(B)
        i, ora = rec[0], ora_piano(B, rec[0])
        precedenti = [dict(piano(B, j, r), regola=r, ora=utc(ora_piano(B, j)),     # ancora nelle 24 ore:
                           fino=utc(ora_piano(B, j) + datetime.timedelta(hours=ORE)))  # se sei dentro, vale ancora
                      for j in rec[1:] for r in ("ribasso", "rottura")]
        piani_7g = [dict(piano(B, j, r), regola=r, ora=utc(ora_piano(B, j)), fino=utc(ora_piano(B, j) + datetime.timedelta(hours=ORE)))
                  for j in range(max(25, len(B) - 1 - STORIA_ORE), len(B)) if ora_piano(B, j).hour in (17, 21)
                  for r in ("ribasso", "rottura")]
        per[sym] = {"prezzo": round(B[-1][4], 6), "prezzo_ora": utc(ora_piano(B, len(B) - 1)), "storia_piani": piani_7g,
                    "ora": utc(ora), "fino": utc(ora + datetime.timedelta(hours=ORE)),
                    "piani": {r["id"]: piano(B, i, r["id"]) for r in REGOLE}, "precedenti": precedenti,
                    "storia": {k: stat(v) for k, v in storia.items()}}
    verifica = {k: {"anno1": stat(v["anno1"]), "anno2": stat(v["anno2"]), "tutto": stat(v["anno1"] + v["anno2"])}
                for k, v in tutti.items()}
    return {"regole": REGOLE, "costo_per_lato": COSTO, "ore": ORE, "crypto": per, "verifica": verifica}


def varianti(log=print):
    """Tutte le VARIANTI sugli stessi piani della verifica (17 e 21 UTC, 2 anni, 12 crypto), primo anno
    e secondo anno separati: si sceglie sul primo, si controlla sul secondo."""
    res = [{"anno1": [], "anno2": []} for _ in VARIANTI]
    for sym in simula.CRYPTO:
        try:
            B = candele(sym)
        except Exception as e:                               # rete, dati mancanti
            log("[intraday] %s saltato: %s" % (sym, e))
            continue
        for i in range(500, len(B) - 1):
            if ora_piano(B, i).hour not in (17, 21):
                continue
            meta = "anno1" if B[i][0] < B[0][0] + 365 * 86400 else "anno2"
            for (nome, v), r in zip(VARIANTI, res):
                x = esito(B, i, v["tipo"], v)
                if x is not None:
                    r[meta].append(x)
    out = [{"nome": nome, "ore": v["ore"], "anno1": stat(r["anno1"]), "anno2": stat(r["anno2"])}
           for (nome, v), r in zip(VARIANTI, res)]
    migliore = max(out, key=lambda x: x["anno1"].get("media", -1))
    return {"generato": datetime.date.today().isoformat(), "costo_per_lato": COSTO, "varianti": out,
            "scelta_sul_primo_anno": migliore["nome"]}


def main():
    if "--varianti" in sys.argv:
        v = varianti()
        for x in v["varianti"]:
            print("  %-50s anno 1: media %+.2f%%, in guadagno %2.0f%% · anno 2: media %+.2f%%, in guadagno %2.0f%%" % (
                x["nome"], 100 * x["anno1"]["media"], 100 * x["anno1"]["p_gain"], 100 * x["anno2"]["media"], 100 * x["anno2"]["p_gain"]))
        print("[intraday] la migliore sul primo anno: %s (app.py le mette nella sezione Crypto)" % v["scelta_sul_primo_anno"])
        return 0
    r = analizza()
    f = lambda s: ("%3.0f%% eseguite, %3.0f%% in guadagno, media %+.2f%%, 1 su 10 sotto %+.1f%%" % (
        100 * s["eseguite"], 100 * s["p_gain"], 100 * s["media"], 100 * s["p10"])) if s.get("n") else "nessuna"
    print("VERIFICA (2 anni, 12 crypto, piani alle 17 e alle 21 UTC, costi 0,2 % per lato)")
    for reg in REGOLE:
        v = r["verifica"][reg["id"]]
        print("  %-30s anno 1: %s\n  %-30s anno 2: %s" % (reg["nome"], f(v["anno1"]), "", f(v["anno2"])))
    print("\nPIANI PER LE PROSSIME 24 ORE")
    for sym, x in r["crypto"].items():
        p = x["piani"]["ribasso"]
        print("  %-9s %12s · ribasso: compra a %s, protezione %s, obiettivo %s · fino a %s" % (
            sym, x["prezzo"], round(p["entrata"], 6), round(p["protezione"], 6), round(p["obiettivo"], 6), x["fino"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
