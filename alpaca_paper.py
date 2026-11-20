#!/usr/bin/env python3
"""Il robot con un broker vero, in modalità di prova: Alpaca "paper trading" (soldi finti, ordini veri sul mercato
simulato di Alpaca, con i prezzi veri). Segue il piano con la rete dell'app, con gli stessi pesi del conto "Il piano con
la rete" del robot: SWDA, obbligazioni, le scelte della rete sugli ETF (con il peso deciso dal vivo), la regola di Faber
e la tendenza delle crypto. Alpaca tratta solo titoli americani e crypto: al posto degli ETF di Borsa Italiana usa i loro
equivalenti quotati negli USA (stesso indice o il più vicino). Ribilancia al più una volta al giorno, a borsa USA aperta,
e solo le parti che si sono spostate abbastanza dal loro peso (così non paga costi per niente).

    python3 alpaca_paper.py --prova [--capitale 100000]   # senza chiavi e senza rete: i pesi e gli ordini che farebbe
    python3 alpaca_paper.py --conto                       # il conto di prova su Alpaca (servono le chiavi)
    python3 alpaca_paper.py --ribilancia                  # manda gli ordini al conto di prova e scrive trader/alpaca.json

Le chiavi: SOLO quelle del conto di prova (Paper) di Alpaca, mai nel codice e mai in chat. Si mettono nelle impostazioni
dell'ambiente del cloud, tra i segreti di rete (Network secrets) per l'host paper-api.alpaca.markets: intestazione
APCA-API-KEY-ID con la Key ID e APCA-API-SECRET-KEY con la Secret Key. Il proxy del cloud le aggiunge da solo alle
richieste: qui non passano mai. In alternativa, le variabili d'ambiente APCA_API_KEY_ID e APCA_API_SECRET_KEY.
Il programma parla solo con paper-api.alpaca.markets: non può toccare un conto vero. Non è consulenza finanziaria.
"""

import datetime
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = "https://paper-api.alpaca.markets"          # solo il conto di prova: l'indirizzo del conto vero non è nel codice
USCITA = os.path.join(ROOT, "trader", "alpaca.json")
MINIMO = 1.0              # Alpaca: gli ordini frazionari vanno da 1 dollaro in su
SOGLIA = 0.02             # si ribilancia una parte quando si sposta di più del 2 % del conto...
SOGLIA_RELATIVA = 0.2     # ...o, per le parti piccole, di più del 20 % del suo peso
RISERVA = 0.01            # l'1 % resta in contanti: un ordine a mercato può costare un po' più del previsto

# gli ETF di Borsa Italiana e il loro equivalente negli USA: stesso indice o il più vicino; quando non c'è un solo ETF
# per tutto il mondo, la parte USA e quella fuori dagli USA (circa 70 e 30 come nell'indice MSCI World)
EQUIVALENTI = {
    "SWDA.MI": "URTH", "XDWD.MI": "URTH", "IEAG.MI": "BNDX", "CSSPX.MI": "IVV", "IUSA.MI": "IVV", "VUSA.MI": "VOO",
    "CSNDX.MI": "QQQM", "EIMI.MI": "IEMG", "VWRL.MI": "VT", "VWCE.MI": "VT", "ISAC.MI": "ACWI", "SMEA.MI": "IEUR",
    "XMEU.MI": "IEUR", "EXSA.MI": "IEUR", "VEUR.MI": "VGK", "CSEMU.MI": "EZU", "IMIB.MI": "EWI",
    "VHYL.MI": {"VYM": 0.45, "VYMI": 0.55}, "IDVY.MI": "FDD", "SJPA.MI": "EWJ", "CSCA.MI": "EWC",
    "SGLD.MI": "GLD", "PHAG.MI": "SLV", "CMOD.MI": "BCI",
    "XDWT.MI": "IXN", "XDWH.MI": "IXJ", "XDWF.MI": "IXG", "XDWI.MI": "EXI", "XDWC.MI": "RXI", "XDWS.MI": "KXI",
    "XDW0.MI": "IXC", "XDWU.MI": "JXI", "XDWM.MI": "MXI", "INRG.MI": "ICLN", "GDX.MI": "GDX", "SMH.MI": "SMH",
    "XDEV.MI": {"VLUE": 0.7, "IVLU": 0.3}, "IWQU.MI": {"QUAL": 0.7, "IQLT": 0.3}, "IWMO.MI": {"MTUM": 0.7, "IMTM": 0.3},
    "XDEM.MI": {"MTUM": 0.7, "IMTM": 0.3}, "MVOL.MI": "ACWV",
}
# le crypto che Alpaca tratta (si ricontrolla l'elenco vero quando ci sono le chiavi)
CRYPTO_ALPACA = {"AAVE", "AVAX", "BAT", "BCH", "BTC", "CRV", "DOGE", "DOT", "ETH", "GRT", "LINK", "LTC", "MKR", "PEPE",
                 "SHIB", "SOL", "SUSHI", "UNI", "XRP", "XTZ", "YFI"}


def _num(x, decimali=0):
    """Il numero all'italiana: 100.000,00"""
    t = "{:,.{}f}".format(x, decimali)
    return t.replace(",", "_").replace(".", ",").replace("_", ".")


def _carica(nome):
    try:
        with open(os.path.join(ROOT, nome), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def pesi_piano():
    """I pesi del conto "Il piano con la rete" del robot (come pesiPiano nell'app): SWDA 50 % più quello che la rete non
    usa, obbligazioni 10 %, le scelte della rete sugli ETF con il peso deciso dal vivo (20 % all'inizio), la regola di
    Faber 10 % e la tendenza delle crypto 10 % (quello che le due regole tengono fuori resta in contanti)."""
    L, S, T, G = _carica("rete_lungo.json"), _carica("strategie_lungo.json"), _carica("crypto_tendenza.json"), _carica("diario_rete.json")
    re = ((L or {}).get("robot_sezioni") or {}).get("etf")
    if not re or not re.get("pesi"):
        return None
    ctl = (G or {}).get("controllo") or {}
    pr = ctl.get("peso") if ctl.get("peso") is not None else 0.2
    P = {}

    def add(s, w):
        if w > 0.0005:
            P[s] = P.get(s, 0.0) + w
    add("SWDA.MI", 0.5 + (0.2 - pr))
    add("IEAG.MI", 0.1)
    for s, w in re["pesi"].items():
        add(s, pr * w)
    try:
        fab = S["mercati"]["etf"]["oggi"]["faber"]["pesi"]
    except (KeyError, TypeError):
        fab = {}
    for s, w in fab.items():
        add(s, 0.1 * w)
    for s, w in (((T or {}).get("oggi") or {}).get("pesi") or {}).items():
        add(s, 0.1 * w)
    return {"giorno": re.get("giorno"), "peso_rete": pr, "pesi": {s: round(w, 4) for s, w in P.items()}}


def obiettivo_usa(pesi, crypto_ok=None):
    """Dai pesi del piano ai simboli di Alpaca: {simbolo: {"peso", "da"}} e l'elenco di quelli che non ci sono (restano
    in contanti)."""
    crypto_ok = CRYPTO_ALPACA if crypto_ok is None else crypto_ok
    ob, fuori = {}, []
    for s, w in pesi.items():
        if s.endswith("-EUR") or s.endswith("-USD"):                          # le crypto: BTC-EUR diventa BTC/USD
            base = s.split("-")[0]
            parti = {base + "/USD": 1.0} if base in crypto_ok else None
        else:
            e = EQUIVALENTI.get(s)
            parti = {e: 1.0} if isinstance(e, str) else e
        if not parti:
            fuori.append(s)
            continue
        for u, q in parti.items():
            x = ob.setdefault(u, {"peso": 0.0, "da": []})
            x["peso"] = round(x["peso"] + w * q, 5)
            if s not in x["da"]:
                x["da"].append(s)
    return ob, fuori


def ordini(obiettivo, patrimonio, posizioni, contanti=None):
    """Gli ordini per portare il conto sui pesi: prima le vendite, poi gli acquisti (che stanno nei contanti più quello
    che liberano le vendite). obiettivo: {simbolo: peso}; posizioni: {simbolo: valore di mercato}. Si muove solo una
    parte che si è spostata più del 2 % del conto o del 20 % del suo peso, e mai per meno di 1 dollaro."""
    vendite, acquisti = [], []
    for s in sorted(set(obiettivo) | set(posizioni)):
        w, ho = obiettivo.get(s, 0.0), posizioni.get(s, 0.0)
        if w <= 0:
            if ho >= MINIMO:
                vendite.append({"simbolo": s, "lato": "vende_tutto", "importo": round(ho, 2)})
            continue
        voglio = patrimonio * w * (1 - RISERVA)
        d = voglio - ho
        if abs(d) < max(MINIMO, min(SOGLIA_RELATIVA * max(voglio, ho), SOGLIA * patrimonio)):
            continue
        (acquisti if d > 0 else vendite).append({"simbolo": s, "lato": "compra" if d > 0 else "vende", "importo": round(abs(d), 2)})
    if contanti is not None and acquisti:
        cassa = contanti + sum(v["importo"] for v in vendite)
        tot = sum(a["importo"] for a in acquisti)
        if tot > cassa:
            f = max(cassa, 0.0) / tot
            for a in acquisti:
                a["importo"] = round(a["importo"] * f, 2)
            acquisti = [a for a in acquisti if a["importo"] >= MINIMO]
    return vendite + acquisti


def chiama(metodo, percorso, corpo=None, timeout=30):
    """Una richiesta al conto di prova. Le chiavi le aggiunge il proxy del cloud (segreti di rete); se ci sono le
    variabili d'ambiente si usano quelle."""
    h = {"APCA-API-KEY-ID": os.environ.get("APCA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY") or "dal-proxy",
         "APCA-API-SECRET-KEY": os.environ.get("APCA_API_SECRET_KEY") or os.environ.get("ALPACA_SECRET_KEY") or "dal-proxy",
         "Accept": "application/json", "User-Agent": "finanza-paper"}
    dati = None
    if corpo is not None:
        dati = json.dumps(corpo).encode("utf-8")
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + percorso, data=dati, headers=h, method=metodo)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        t = r.read()
    return json.loads(t) if t else None


def spiega(e):
    """L'errore in parole: chiavi mancanti, host non consentito, o altro."""
    t = str(e)
    if isinstance(e, urllib.error.HTTPError) and e.code in (401, 403):
        return "senza chiavi", "Alpaca non riconosce le chiavi: aggiungi Key ID e Secret Key del conto di prova (Paper) tra i segreti di rete dell'ambiente, per paper-api.alpaca.markets."
    if "403" in t or "Tunnel" in t or "Forbidden" in t:
        return "senza chiavi", "Il cloud non raggiunge ancora paper-api.alpaca.markets: si apre quando aggiungi le chiavi tra i segreti di rete dell'ambiente."
    return "errore", "Alpaca non ha risposto: %s" % t[:160]


def _simbolo(p):
    """Le posizioni crypto arrivano come BTCUSD: si riportano a BTC/USD, come negli ordini."""
    s = p.get("symbol", "")
    if p.get("asset_class") == "crypto" and "/" not in s and s.endswith("USD"):
        return s[:-3] + "/USD"
    return s


def manda_ordine(api, o):
    s = o["simbolo"]
    if o["lato"] == "vende_tutto":
        return api("DELETE", "/v2/positions/" + urllib.parse.quote(s.replace("/", ""), safe=""))
    corpo = {"symbol": s, "notional": "%.2f" % o["importo"], "side": "buy" if o["lato"] == "compra" else "sell",
             "type": "market", "time_in_force": "gtc" if "/" in s else "day"}
    return api("POST", "/v2/orders", corpo)


def scrivi(x, percorso=None):
    percorso = percorso or USCITA
    try:
        with open(percorso, encoding="utf-8") as fh:
            prima = json.load(fh)
    except (OSError, ValueError):
        prima = {}
    x["ordini"] = (prima.get("ordini") or [])[-60:] if "ordini" not in x else ((prima.get("ordini") or []) + x["ordini"])[-60:]
    x["aggiornato"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    os.makedirs(os.path.dirname(percorso), exist_ok=True)
    with open(percorso, "w", encoding="utf-8") as fh:
        json.dump(x, fh, ensure_ascii=False, separators=(",", ":"))
    return x


def ribilancia(api=chiama, log=print, percorso=None, manda=True):
    """Legge il conto di prova, calcola gli ordini per stare sul piano e li manda (le azioni solo a borsa aperta, le
    crypto sempre). Scrive tutto in trader/alpaca.json per l'app. Ritorna 0 se è andato, 2 senza chiavi, 1 errore."""
    piano = pesi_piano()
    if not piano:
        scrivi({"stato": "errore", "messaggio": "Manca il piano: serve prima python3 rete_lungo.py."}, percorso)
        return 1
    try:
        conto = api("GET", "/v2/account")
        pos = api("GET", "/v2/positions") or []
        orologio = api("GET", "/v2/clock") or {}
        try:
            crypto_ok = {a["symbol"].split("/")[0] for a in api("GET", "/v2/assets?asset_class=crypto&status=active") or [] if a.get("tradable")}
        except Exception:
            crypto_ok = CRYPTO_ALPACA
    except Exception as e:
        stato, msg = spiega(e)
        log("[alpaca] " + msg)
        scrivi({"stato": stato, "messaggio": msg, "piano": piano}, percorso)
        return 2 if stato == "senza chiavi" else 1
    patrimonio, contanti = float(conto.get("equity") or 0), float(conto.get("cash") or 0)
    posizioni = {_simbolo(p): float(p.get("market_value") or 0) for p in pos}
    ob, fuori = obiettivo_usa(piano["pesi"], crypto_ok)
    lista = ordini({s: x["peso"] for s, x in ob.items()}, patrimonio, posizioni, contanti)
    aperta = bool(orologio.get("is_open"))
    fatti = []
    for o in lista:
        if "/" not in o["simbolo"] and not aperta:
            o["esito"] = "rimandato: borsa USA chiusa"
        elif not manda:
            o["esito"] = "solo calcolato"
        else:
            try:
                r = manda_ordine(api, o) or {}
                o["esito"] = "inviato" + (" (%s)" % r.get("status") if isinstance(r, dict) and r.get("status") else "")
            except Exception as e:
                o["esito"] = "rifiutato: " + str(getattr(e, "reason", e))[:100]
        o["t"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        fatti.append(o)
        log("[alpaca] %s %s %.2f $ · %s" % (o["lato"], o["simbolo"], o["importo"], o["esito"]))
    righe = [{"simbolo": s, "valore": round(v, 2), "peso": round(v / patrimonio, 4) if patrimonio else 0.0,
              "obiettivo": (ob.get(s) or {}).get("peso", 0.0), "da": (ob.get(s) or {}).get("da", [])} for s, v in sorted(posizioni.items(), key=lambda x: -x[1])]
    scrivi({"stato": "ok", "messaggio": "", "piano": piano, "obiettivo": ob, "fuori": fuori, "borsa_aperta": aperta,
            "conto": {"patrimonio": round(patrimonio, 2), "contanti": round(contanti, 2), "valuta": conto.get("currency", "USD"),
                      "ieri": float(conto.get("last_equity") or patrimonio)},
            "posizioni": righe, "ordini": [o for o in fatti if o["esito"] != "rimandato: borsa USA chiusa"]}, percorso)
    return 0


def prova(capitale=100000.0, log=print):
    """Senza chiavi e senza rete: il piano, i simboli di Alpaca e gli ordini per un conto di prova vuoto."""
    piano = pesi_piano()
    if not piano:
        log("[alpaca] manca il piano: serve prima python3 rete_lungo.py")
        return 1
    ob, fuori = obiettivo_usa(piano["pesi"])
    log("[alpaca] il piano del %s, rete al %d %%: %d ETF e crypto su Alpaca, %.1f %% in contanti%s" % (
        piano["giorno"], round(100 * piano["peso_rete"]), len(ob), 100 * (1 - sum(x["peso"] for x in ob.values())),
        (" (non su Alpaca: %s)" % ", ".join(fuori)) if fuori else ""))
    for s, x in sorted(ob.items(), key=lambda kv: -kv[1]["peso"]):
        log("  %-9s %5.2f %%  al posto di %s" % (s, 100 * x["peso"], ", ".join(x["da"])))
    lista = ordini({s: x["peso"] for s, x in ob.items()}, capitale, {}, capitale)
    log("[alpaca] su un conto vuoto da %s $: %d ordini, %s $ in tutto" % (_num(capitale), len(lista), _num(sum(o["importo"] for o in lista), 2)))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--prova" in argv:
        cap = float(argv[argv.index("--capitale") + 1]) if "--capitale" in argv else 100000.0
        return prova(cap)
    if "--conto" in argv:
        try:
            c = chiama("GET", "/v2/account")
            print(json.dumps({k: c.get(k) for k in ("status", "currency", "equity", "cash", "buying_power")}, indent=1))
            return 0
        except Exception as e:
            print("[alpaca] " + spiega(e)[1])
            return 2
    if "--ribilancia" in argv:
        return ribilancia()
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
