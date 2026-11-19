#!/usr/bin/env python3
"""Crypto intraday: entrate e uscite per le prossime 24 ore, con la verifica delle stesse regole
sugli ultimi 2 anni di candele orarie (Yahoo Finance).

    python3 intraday.py              # stampa i piani di oggi e la verifica; app.py li mette nella sezione Crypto
    python3 intraday.py --varianti   # prova 9 varianti delle regole, primo anno contro secondo
    python3 intraday.py --ore        # ordini rinnovati ogni ora: verifica su 2 anni e controllo su Kraken

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
Il 18 novembre 2026 l'app ha provato ordini rinnovati ogni ora (analizza_ore, più sotto): tre ribassi da 1,5 / 2 / 3
escursioni, validi un'ora, uno alla volta per moneta e profondità. La prima verifica li dava in guadagno, ma contava
l'obiettivo anche nella candela in cui scatta l'ordine (il massimo può essere venuto prima del minimo): corretto il
19 novembre, e rifatto minuto per minuto sugli scambi veri di Kraken (rete.py), perdono lo 0,4-0,6 % per operazione.
Il robot non li usa più. I due piani al giorno (17 e 21 UTC) restano qui come confronto.
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


# ---------------------------------------------------------------------------------------------------------
# Ordini rinnovati ogni ora: tre ribassi (1,5 / 2 / 3 escursioni), uno alla volta per moneta e profondità.
# Ogni ora piena, dalla candela oraria appena chiusa, si fa un ordine limite sotto il prezzo, valido per quella
# sola ora. Se scatta, protezione 3 escursioni sotto l'entrata, obiettivo il prezzo di partenza, al più tardi
# fuori dopo 24 ore. Finché c'è una posizione non si fanno nuovi ordini di quella profondità. La candela oraria
# è il passo più fine che si può verificare su 2 anni (Yahoo dà candele da un minuto solo per gli ultimi 7
# giorni); il prezzo si segue poi al secondo (crypto_live.py) o ogni 5 secondi (live.py).
# ---------------------------------------------------------------------------------------------------------
FINESTRA = 1                  # ore in cui vale ogni ordine: a ogni ora piena se ne fa uno nuovo
TENUTA = 24                   # ore al massimo in posizione dopo l'entrata
METODO_ORE = 2          # 2: l'obiettivo di un ribasso non conta nella candela dell'entrata (corretto il 19 novembre 2026)
STOP_ATR = 3                  # protezione sotto l'entrata, in escursioni orarie
PENETRAZIONE = 0.25           # prova prudente: il minimo deve scendere un quarto di escursione sotto il livello
# le tre profondità: fissate dopo la prova su 2 anni di Yahoo e controllate su Kraken (30 giorni); la prova con
# ordini valevoli 2 ore o più è peggiore (le entrate arrivano in un ribasso che continua): per questo 1 ora
LIVELLI_ORE = [
    {"id": "ribasso15", "nome": "Ribasso leggero", "e": 1.5, "desc": "Ordine limite 1,5 escursioni orarie sotto il prezzo"},
    {"id": "ribasso20", "nome": "Ribasso medio", "e": 2, "desc": "Ordine limite 2 escursioni orarie sotto il prezzo"},
    {"id": "ribasso30", "nome": "Ribasso profondo", "e": 3, "desc": "Ordine limite 3 escursioni orarie sotto il prezzo"},
]
ROTTURA_ORE = {"id": "rottura", "nome": "Rottura (confronto)", "desc": "Ordine sopra il massimo delle ultime 24 ore, protezione 1,5 escursioni, obiettivo 3"}
KRAKEN = {"BTC-EUR": ("XBTEUR", "XXBTZEUR"), "ETH-EUR": ("ETHEUR", "XETHZEUR"), "SOL-EUR": ("SOLEUR", "SOLEUR"),
          "XRP-EUR": ("XRPEUR", "XXRPZEUR"), "BNB-EUR": ("BNBEUR", "BNBEUR"), "ADA-EUR": ("ADAEUR", "ADAEUR"),
          "DOGE-EUR": ("DOGEEUR", "XDGEUR"), "LTC-EUR": ("LTCEUR", "XLTCZEUR"), "DOT-EUR": ("DOTEUR", "DOTEUR"),
          "LINK-EUR": ("LINKEUR", "LINKEUR"), "AVAX-EUR": ("AVAXEUR", "AVAXEUR"), "TRX-EUR": ("TRXEUR", "TRXEUR")}


def serie(B):
    """Escursione media (ATR) e massimo delle ultime 24 candele, per ogni candela: gli stessi numeri di atr()
    e livelli(), calcolati una volta sola."""
    n = len(B)
    tr = [0.0] * n
    for k in range(1, n):
        tr[k] = max(B[k][2] - B[k][3], abs(B[k][2] - B[k - 1][4]), abs(B[k][3] - B[k - 1][4]))
    a, m = [None] * n, [None] * n
    for i in range(24, n):
        a[i] = sum(tr[i - 23:i + 1]) / 24
        m[i] = max(b[2] for b in B[i - 23:i + 1])
    return a, m


def ordine_ore(B, i, a, mx, tipo="ribasso", e=3.0, s=STOP_ATR):
    """Entrata, protezione e obiettivo dell'ordine fatto alla chiusura della candela i."""
    c, ai = B[i][4], a[i]
    if tipo == "ribasso":
        ent = c - e * ai
        return {"entrata": ent, "tipo": "limite", "protezione": ent - s * ai, "obiettivo": c}
    return {"entrata": mx[i], "tipo": "sopra", "protezione": mx[i] - 1.5 * ai, "obiettivo": mx[i] + 3 * ai}


def _t(sec):
    return utc(datetime.datetime.fromtimestamp(sec, datetime.timezone.utc))


def episodio(B, i, lv, ai, tipo="ribasso", finestra=FINESTRA, tenuta=TENUTA, pen=0.0):
    """Com'è andato l'ordine fatto alla chiusura della candela i, rigiocando le candele chiuse dopo:
    attesa (la finestra non è finita: ordine ancora valido), scaduto (finestra finita senza entrare), dentro,
    obiettivo, protezione (chiuso) o scaduto_dentro (24 ore in posizione: si vende alla chiusura dell'ultima)."""
    n, e, stop, tgt = len(B), lv["entrata"], lv["protezione"], lv["obiettivo"]
    trig = fill = None
    for k in range(finestra):
        j = i + 1 + k
        if j >= n:
            return {"fase": "attesa"}
        b = B[j]
        if tipo == "ribasso" and b[3] <= e - pen * ai:
            trig, fill = j, min(e, b[1])
            break
        if tipo == "rottura" and b[2] >= e + pen * ai:
            trig, fill = j, max(e, b[1])
            break
    if trig is None:
        return {"fase": "scaduto"}
    base = {"prezzo_entrata": fill, "quando": _t(B[trig][0]), "scade": _t(B[trig][0] + tenuta * 3600)}
    for j in range(trig, min(n, trig + tenuta)):
        b, k = B[j], j - trig
        # Un ribasso ha l'obiettivo al prezzo di partenza, che è anche dove apre di solito la candela dopo: nella candela
        # dell'entrata il suo massimo può essere venuto PRIMA del minimo che fa scattare l'ordine. Non si sa in che ordine
        # sono venuti, quindi lì l'obiettivo non conta (la protezione sì: è il caso peggiore). Contarlo, come si faceva
        # prima del 19 novembre 2026, gonfiava i risultati: sugli scambi veri passava da -0,5 % a +0,4 % per operazione.
        obiettivo_vale = k > 0 or tipo != "ribasso"
        px = nome = None
        if k > 0 and b[1] <= stop:
            px, nome = b[1], "protezione"
        elif k > 0 and b[1] >= tgt:
            px, nome = b[1], "obiettivo"
        elif b[3] <= stop:
            px, nome = stop, "protezione"
        elif obiettivo_vale and b[2] >= tgt:
            px, nome = tgt, "obiettivo"
        if nome:
            return dict(base, fase=nome, chiusura=_t(b[0]), prezzo_uscita=px, rendimento=px / fill - 1 - 2 * COSTO, x=j)
    if n >= trig + tenuta:
        px = B[trig + tenuta - 1][4]
        return dict(base, fase="scaduto_dentro", chiusura=base["scade"], prezzo_uscita=px,
                    rendimento=px / fill - 1 - 2 * COSTO, x=trig + tenuta - 1)
    return dict(base, fase="dentro")


def catena(B, a, mx, tipo="ribasso", e=3.0, s=STOP_ATR, da=200, pen=0.0, finestra=FINESTRA, tenuta=TENUTA):
    """Gli ordini rinnovati ogni ora, uno alla volta, da `da` alla fine dei dati.
    -> (episodi con entrata, ordini fatti, {"ordine": quello ancora valido o None, "posizione": quella aperta o None})."""
    n, i, ordini, episodi, finale = len(B), da, 0, [], {"ordine": None, "posizione": None}
    while i < n:
        lv = ordine_ore(B, i, a, mx, tipo, e, s)
        ordini += 1
        r = episodio(B, i, lv, a[i], tipo, finestra, tenuta, pen)
        if r["fase"] == "scaduto":
            i += 1
            continue
        piano = dict(lv, **r, i=i)
        if r["fase"] == "attesa":
            finale["ordine"] = piano
            break
        episodi.append(piano)
        if r["fase"] == "dentro":
            finale["posizione"] = piano
            break
        i = r["x"]                               # il prossimo ordine alla chiusura della candela di uscita
    return episodi, ordini, finale


def piano_dati(B, p, regola):
    """Un ordine o una posizione, come li usano l'app e il robot."""
    rnd = lambda d: {k: (round(v, 6) if isinstance(v, float) else v) for k, v in d.items()}
    ora = ora_piano(B, p["i"])
    out = {k: v for k, v in p.items() if k not in ("i", "x")}
    return dict(rnd(out), regola=regola, ora=utc(ora), fino=utc(ora + datetime.timedelta(hours=FINESTRA)))


def candele_kraken(sym, adesso=None):
    """Le ultime ~720 candele orarie chiuse di Kraken (in euro): un exchange vero, per il controllo indipendente."""
    pair, key = KRAKEN[sym]
    req = urllib.request.Request("https://api.kraken.com/0/public/OHLC?pair=%s&interval=60" % pair,
                                 headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    if d.get("error"):
        raise RuntimeError("; ".join(d["error"]))
    righe = d["result"].get(key) or next(v for k, v in d["result"].items() if k != "last")
    adesso = time.time() if adesso is None else adesso
    return [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in righe if int(r[0]) + 3600 <= adesso]


def controllo_kraken(log=print, candele_di=candele_kraken):
    """Gli stessi ordini sulle candele di Kraken, per i giorni che offre: la prova indipendente dei dati di Yahoo."""
    rets = {l["id"]: {"base": [], "prudente": []} for l in LIVELLI_ORE}
    giorni, usate = 0, 0
    for sym in KRAKEN:
        try:
            B = candele_di(sym)
        except Exception as e:                               # rete o coppia mancante
            log("[intraday] Kraken %s saltato: %s" % (sym, e))
            continue
        if len(B) < 100:
            continue
        a, m = serie(B)
        usate += 1
        giorni = max(giorni, len(B) // 24)
        for l in LIVELLI_ORE:
            for nome, pen in (("base", 0.0), ("prudente", PENETRAZIONE)):
                rets[l["id"]][nome] += [x["rendimento"] for x in catena(B, a, m, "ribasso", l["e"], da=30, pen=pen)[0]
                                        if x["fase"] != "dentro"]
    if usate < 6:
        return None
    return {"giorni": giorni, "crypto": usate,
            "livelli": {k: {n: stat(v) for n, v in d.items()} for k, d in rets.items()}}


def analizza_ore(log=print, max_age=3600, kraken=True):
    """Gli ordini orari: verifica su 2 anni di candele Yahoo (primo anno, secondo anno, prova prudente), controllo
    su Kraken, e per ogni crypto l'ordine di adesso, le posizioni aperte e gli ultimi 7 giorni (per il robot)."""
    dati = {}
    for sym in simula.CRYPTO:
        try:
            B = candele(sym, max_age)
        except Exception as e:                               # rete, dati mancanti
            log("[intraday] %s saltato: %s" % (sym, e))
            continue
        dati[sym] = (B,) + serie(B)
    if not dati:
        raise ValueError("nessun dato delle crypto")
    regole = [(l["id"], "ribasso", l["e"]) for l in LIVELLI_ORE] + [("rottura", "rottura", 0)]
    acc = {rid: {"anno1": [], "anno2": [], "p1": [], "p2": [], "ordini": 0} for rid, _, _ in regole}
    per = {}
    for sym, (B, a, m) in dati.items():
        meta = B[0][0] + 365 * 86400
        storia, correnti, aperti = [], {}, []
        for rid, tipo, e in regole:
            episodi, ordini, finale = catena(B, a, m, tipo, e or 3.0)
            acc[rid]["ordini"] += ordini
            for x in episodi:
                if x["fase"] != "dentro":
                    acc[rid]["anno1" if B[x["i"]][0] < meta else "anno2"].append(x["rendimento"])
            for x in catena(B, a, m, tipo, e or 3.0, pen=PENETRAZIONE)[0]:
                if x["fase"] != "dentro":
                    acc[rid]["p1" if B[x["i"]][0] < meta else "p2"].append(x["rendimento"])
            if tipo != "ribasso":
                continue                                     # la rottura è solo un confronto: il robot non la usa
            da = B[-1][0] - STORIA_ORE * 3600
            storia += [piano_dati(B, x, rid) for x in episodi if B[x["i"]][0] >= da]
            if finale["ordine"]:
                correnti[rid] = piano_dati(B, finale["ordine"], rid)
                storia.append(correnti[rid])
            if finale["posizione"]:
                aperti.append(piano_dati(B, finale["posizione"], rid))
        ora = ora_piano(B, len(B) - 1)
        per[sym] = {"prezzo": round(B[-1][4], 6), "prezzo_ora": utc(ora), "ora": utc(ora),
                    "fino": utc(ora + datetime.timedelta(hours=FINESTRA)), "ordini": correnti, "posizioni": aperti,
                    "storia_piani": storia}
    giorni = len(next(iter(dati.values()))[0]) / 24
    verifica = {}
    for rid, v in acc.items():
        tutti = v["anno1"] + v["anno2"]
        verifica[rid] = {"anno1": stat(v["anno1"]), "anno2": stat(v["anno2"]), "tutto": stat(tutti),
                         "prudente": {"anno1": stat(v["p1"]), "anno2": stat(v["p2"])},
                         "al_giorno": round(len(tutti) / giorni, 2), "ordini": v["ordini"],
                         "eseguiti": round(len(tutti) / max(1, v["ordini"]), 4)}
    k = None
    if kraken:
        try:
            k = controllo_kraken(log)
        except Exception as e:                               # rete: il resto resta
            log("[intraday] controllo su Kraken saltato: %s" % e)
    return {"generato": datetime.date.today().isoformat(), "metodo": METODO_ORE, "finestra_ore": FINESTRA, "tenuta_ore": TENUTA,
            "stop_escursioni": STOP_ATR, "penetrazione": PENETRAZIONE, "costo_per_lato": COSTO,
            "livelli": LIVELLI_ORE, "rottura": ROTTURA_ORE, "verifica": verifica, "kraken": k, "crypto": per}


def ordini_correnti(log=print, max_age=3600):
    """Solo gli ordini di adesso, per le pagine in diretta (live.py): -> {crypto: {prezzo, ora, fino, ordini}}."""
    out = {}
    for sym in simula.CRYPTO:
        try:
            B = candele(sym, max_age)
        except Exception as e:
            log("[intraday] %s saltato: %s" % (sym, e))
            continue
        a, m = serie(B)
        i, ora = len(B) - 1, ora_piano(B, len(B) - 1)
        out[sym] = {"prezzo": round(B[i][4], 6), "ora": utc(ora), "fino": utc(ora + datetime.timedelta(hours=FINESTRA)),
                    "ordini": [piano_dati(B, dict(ordine_ore(B, i, a, m, "ribasso", l["e"]), fase="attesa", i=i), l["id"])
                               for l in LIVELLI_ORE]}
    return out


def main():
    if "--ore" in sys.argv:
        r = analizza_ore(kraken="--senza-kraken" not in sys.argv)
        f = lambda x: ("%5d ordini, %3.0f%% in guadagno, media %+.2f%%" % (x["n"], 100 * x["p_gain"], 100 * x["media"])) if x.get("n") else "nessuna"
        print("ORDINI OGNI ORA (2 anni, 12 crypto, costi 0,2 % per lato, uno alla volta per moneta e profondità)")
        for l in LIVELLI_ORE + [ROTTURA_ORE]:
            v = r["verifica"][l["id"]]
            print("  %-18s anno 1: %s\n  %-18s anno 2: %s · prudente (anno 2): %s · %.1f al giorno" % (
                l["nome"], f(v["anno1"]), "", f(v["anno2"]), f(v["prudente"]["anno2"]), v["al_giorno"]))
        if r["kraken"]:
            print("\nKRAKEN (%d crypto, %d giorni)" % (r["kraken"]["crypto"], r["kraken"]["giorni"]))
            for l in LIVELLI_ORE:
                k = r["kraken"]["livelli"][l["id"]]
                print("  %-18s %s · prudente: %s" % (l["nome"], f(k["base"]), f(k["prudente"])))
        return 0
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
