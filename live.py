#!/usr/bin/env python3
"""L'app con le quotazioni in tempo reale, sul tuo computer.

    python3 live.py                  # apre http://127.0.0.1:8770 nel browser
    python3 live.py --rete           # anche dagli altri dispositivi della tua rete di casa (es. il telefono)
    python3 live.py --porta 9000 --no-browser

L'app pubblicata su Claude si aggiorna due volte al giorno: da lì non può collegarsi alle borse,
salvo nell'app desktop di Claude con il browser integrato (pulsante "Prezzi in tempo reale").
Questo programma serve la stessa app (trader/app.html, generata da app.py) dal tuo computer e le
passa le quotazioni di Yahoo Finance; la pagina le chiede ogni 5 secondi:

  azioni USA         in tempo reale durante la seduta (15:30-22:00 ora italiana)
  Borsa Italiana     azioni ed ETF .MI con 15 minuti di ritardo, come tutte le quotazioni gratuite
  crypto e cambio    in tempo reale, anche nel weekend

Le quotazioni si chiedono a Yahoo al massimo una volta ogni 5 secondi per titolo, 20 titoli per
richiesta. Il portafoglio e il conto demo di questa versione restano nel browser che usi.
Per le crypto al secondo, con i piani intraday e gli avvisi, c'è anche crypto_live.py.
Solo libreria standard. Non è consulenza finanziaria.
"""

import argparse
import datetime
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, "trader", "app.html")
UA = "Mozilla/5.0 (compatible; finanza/1.0)"
SPARK = "https://query1.finance.yahoo.com/v7/finance/spark?symbols=%s&range=1d&interval=1d"
PER_RICHIESTA = 20            # Yahoo rifiuta più di 20 simboli in una richiesta
FRESCO = 5.0                  # secondi: sotto questa età una quotazione non si richiede
MAX_SIMBOLI = 120
SIMBOLO = re.compile(r"^[A-Za-z0-9.\-=^]{1,20}$")
RITARDO = {"MIL": 15}         # minuti di ritardo delle quotazioni gratuite, per borsa


def leggi_spark(testo):
    """Risposta di Yahoo spark -> {simbolo: quotazione}."""
    out = {}
    for r in ((json.loads(testo).get("spark") or {}).get("result") or []):
        try:
            m = r["response"][0]["meta"]
        except (KeyError, IndexError, TypeError):
            continue
        p = m.get("regularMarketPrice")
        if not p:
            continue
        out[r.get("symbol") or m.get("symbol")] = {
            "p": p, "prev": m.get("chartPreviousClose") or m.get("previousClose"), "t": m.get("regularMarketTime"),
            "hi": m.get("regularMarketDayHigh"), "lo": m.get("regularMarketDayLow"), "cur": m.get("currency"),
            "ex": m.get("exchangeName"), "ritardo": RITARDO.get(m.get("exchangeName"), 0)}
    return out


def chiedi_yahoo(simboli, timeout=10):
    url = SPARK % urllib.parse.quote(",".join(simboli), safe=",")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return leggi_spark(r.read().decode("utf-8", "replace"))


class Quotazioni:
    """Cache delle quotazioni: ogni simbolo si richiede a Yahoo al massimo una volta ogni FRESCO secondi."""

    def __init__(self, chiedi=chiedi_yahoo, fresco=FRESCO):
        self.chiedi, self.fresco = chiedi, fresco
        self.lock = threading.Lock()
        self.cache = {}                                          # simbolo -> (quando, quotazione)

    def prendi(self, simboli, adesso=None):
        adesso = time.time() if adesso is None else adesso
        with self.lock:
            vecchi = [s for s in simboli if s not in self.cache or adesso - self.cache[s][0] >= self.fresco]
        errori = []
        for i in range(0, len(vecchi), PER_RICHIESTA):
            gruppo = vecchi[i:i + PER_RICHIESTA]
            try:
                nuove = self.chiedi(gruppo)
            except (urllib.error.URLError, OSError, ValueError) as e:      # rete o Yahoo: restano le ultime
                errori.append("Yahoo non risponde (%s)" % str(e)[:80])
                continue
            with self.lock:
                for s in gruppo:
                    if s in nuove:
                        self.cache[s] = (adesso, nuove[s])
        with self.lock:
            return {s: self.cache[s][1] for s in simboli if s in self.cache}, errori


GRAFICO = "https://query2.finance.yahoo.com/v8/finance/chart/%s?range=1mo&interval=1d&includeAdjustedClose=true"


class Aperture:
    """Aperture, chiusure, massimi e minimi ufficiali delle ultime sedute (per il robot "di notte" e "in
    giornata"): [data, apertura, chiusura o None, massimo, minimo]; un grafico per titolo, al massimo uno
    al minuto per titolo."""

    def __init__(self, fresco=60.0):
        self.fresco, self.lock, self.cache = fresco, threading.Lock(), {}

    def prendi(self, simboli, adesso=None):
        import giornata                                          # solo qui: live.py resta leggero
        adesso = time.time() if adesso is None else adesso
        out, errori = {}, []
        for s in simboli[:PER_RICHIESTA]:
            with self.lock:
                c = self.cache.get(s)
            if not c or adesso - c[0] >= self.fresco:
                try:
                    req = urllib.request.Request(GRAFICO % urllib.parse.quote(s), headers={"User-Agent": UA, "Accept": "application/json"})
                    with urllib.request.urlopen(req, timeout=10) as r:
                        righe = giornata.serie_giorno_testo(r.read().decode("utf-8", "replace"))
                    c = (adesso, [[d, round(o, 4), round(cc, 4) if cc else None, round(h, 4), round(l, 4)] for d, o, h, l, cc in righe[-10:]])
                    with self.lock:
                        self.cache[s] = c
                except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
                    errori.append("%s: %s" % (s, str(e)[:60]))
            if c:
                out[s] = c[1]
        return out, errori


def simboli_da(query):
    s = (urllib.parse.parse_qs(query).get("s") or [""])[0]
    out = []
    for x in s.split(","):
        x = x.strip()
        if SIMBOLO.match(x) and x not in out:
            out.append(x)
    return out[:MAX_SIMBOLI]


def server(quot, porta, host="127.0.0.1", aper=None):
    class Gestore(BaseHTTPRequestHandler):
        def invia(self, codice, tipo, corpo):
            self.send_response(codice)
            self.send_header("Content-Type", tipo)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if u.path == "/quotazioni":
                q, err = quot.prendi(simboli_da(u.query))
                corpo = json.dumps({"ora": datetime.datetime.now().isoformat(timespec="seconds"), "quote": q,
                                    "errori": err, "fonte": "Yahoo Finance"}).encode()
                self.invia(200, "application/json", corpo)
            elif u.path == "/aperture" and aper:
                q, err = aper.prendi(simboli_da(u.query))
                self.invia(200, "application/json", json.dumps({"prezzi": q, "errori": err}).encode())
            elif u.path in ("/", "/index.html"):
                try:
                    with open(APP, "rb") as fh:                    # sempre l'ultima app generata da app.py
                        corpo = fh.read()
                except OSError:
                    corpo = ("<p>Non trovo trader/app.html: genera l'app con <code>python3 app.py</code>.</p>").encode()
                    self.invia(404, "text/html; charset=utf-8", corpo)
                    return
                self.invia(200, "text/html; charset=utf-8", corpo)
            else:
                self.send_error(404)

        def log_message(self, *a):
            pass

    return ThreadingHTTPServer((host, porta), Gestore)


def ip_locale():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 80))                             # nessun pacchetto parte: serve solo a scegliere la rete
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "l'indirizzo di questo computer"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--porta", type=int, default=8770)
    ap.add_argument("--no-browser", action="store_true", help="non aprire il browser")
    ap.add_argument("--rete", action="store_true",
                    help="raggiungibile anche dagli altri dispositivi della rete di casa (nessuna password: solo in reti fidate)")
    a = ap.parse_args(argv)
    if not os.path.exists(APP):
        print("[live] manca trader/app.html: genera prima l'app con python3 app.py")
        return 1
    srv = server(Quotazioni(), a.porta, "0.0.0.0" if a.rete else "127.0.0.1", Aperture())
    url = "http://127.0.0.1:%d" % a.porta
    print("[live] l'app con le quotazioni in tempo reale: %s · Ctrl+C per fermare" % url)
    if a.rete:
        print("[live] dagli altri dispositivi della tua rete: http://%s:%d (senza password: solo in reti fidate)" % (ip_locale(), a.porta))
    if not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url + "/#oggi")).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
