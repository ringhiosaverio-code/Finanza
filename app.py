#!/usr/bin/env python3
"""Finanza, l'app: un unico file HTML con tutto dentro.

    python3 app.py                  # scarica i dati, analizza, scrive trader/app.html
    python3 app.py --asof 2025-06-30

Schede:
  Consigli USA e Titoli italiani
             i 10 titoli della settimana dell'S&P 100 e del FTSE MIB, con quando entrare, quando vendere (stop, target,
             data), la probabilità di guadagno storica e la Macchina del Tempo (10.000
             simulazioni nel browser) per qualsiasi variante della regola
  Verifica   come sarebbe andato l'algoritmo negli ultimi ~9 anni, tutte le varianti a confronto
  Simula     scrivi un codice ISIN: probabilità di guadagno a 1 giorno, 1 settimana, 1 mese e
             1 anno con la Macchina del Tempo e l'affidabilità di ogni numero (simula.py)
  Day trade  l'ultimo giro di finanza.py (entry -> exit -> Macchina del Tempo -> budget -> risk)
  Metodo     come funziona e i suoi limiti

L'app è un'istantanea: i numeri sono quelli del momento in cui la generi. Per aggiornarla,
rilancia questo script. Non è consulenza finanziaria.
"""

import argparse
import json
import os
import sys

import settimana
import simula
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
TRADER = os.path.join(ROOT, "trader")
TEMPLATE = os.path.join(ROOT, "app_template.html")


def load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def day_trade():
    """L'ultimo giro di finanza.py, se c'è (senza i percorsi campione, che pesano)."""
    tm = load_json(os.path.join(TRADER, "timemachine.json"))
    if not tm:
        return None
    tm["mc"] = {k: v for k, v in tm["mc"].items() if k != "sample_paths"}
    risk = load_json(os.path.join(TRADER, "state", "risk.json"))
    return {"tm": tm, "plan": load_json(os.path.join(TRADER, "plan.json")),
            "orders": load_json(os.path.join(TRADER, "orders.json")),
            "risk": {k: risk.get(k) for k in ("pass", "block", "results")} if risk else None,
            "demo": tm.get("source") == "offline"}


def simulazioni(log=print):
    """La simulazione per ISIN di tutti i titoli dell'app (fino a 25 anni di storia), più quelli
    aggiunti con simula.py (simula_lista.json)."""
    rev = {v: k for k, v in simula.load_isin_map().items()}
    cat = {}
    for m in ("usa", "italia", "etf", "bond", "oro"):
        for s in settimana.MERCATI[m]["universo"]:
            cat[s] = m
    syms = list(cat)

    def one(sym):
        try:
            text = simula.fetch_max(sym)
            meta, dates, closes = simula.series(text)
            s = simula.simulate(dates, closes)
            s["rendimento"] = settimana.div_yield(text)
        except (simula.SimError, ValueError, KeyError) as e:
            log("[app] simulazione di %s saltata: %s" % (sym, e))
            return None
        return {"isin": rev.get(sym), "symbol": sym, "categoria": cat[sym],
                "name": meta.get("longName") or meta.get("shortName") or sym,
                "exchange": meta.get("fullExchangeName") or meta.get("exchangeName") or "",
                "type": meta.get("instrumentType") or "", "currency": meta.get("currency") or "", **s}

    log("[app] simulazione di %d titoli per la sezione Simula..." % len(syms))
    with ThreadPoolExecutor(max_workers=4) as ex:
        out = {s["symbol"]: s for s in ex.map(one, syms) if s}
    for code in simula.load_list():                      # aggiunti con simula.py, prezzi aggiornati
        try:
            s = simula.instrument(code)
        except (simula.SimError, settimana.FetchError, ValueError, KeyError) as e:
            log("[app] %s saltato: %s" % (code, e))
            continue
        out[s["symbol"]] = s
    return out


def build(data, out):
    with open(TEMPLATE, encoding="utf-8") as fh:
        page = fh.read()
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(page.replace("__DATA__", blob))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--asof", help="usa solo i dati fino a questa data (YYYY-MM-DD)")
    ap.add_argument("--out", default=os.path.join(TRADER, "app.html"))
    a = ap.parse_args(argv)
    os.makedirs(TRADER, exist_ok=True)
    mercati = {}
    for m in ("usa", "italia", "etf", "bond", "oro"):
        try:
            mercati[m] = settimana.analizza(None, a.asof, mercato=m)
        except settimana.FetchError as e:
            print("[app] %s saltato: %s" % (m, e))
            continue
        name = "settimana.json" if m == "usa" else "settimana-%s.json" % m
        with open(os.path.join(TRADER, name), "w", encoding="utf-8") as fh:
            json.dump(mercati[m], fh)
    if not mercati:
        print("[app] nessun mercato disponibile")
        return 1
    data = {"mercati": mercati, "daytrade": day_trade(), "simula": simulazioni(),
            "aggiornato": settimana.now_in("Europe/Rome").strftime("%Y-%m-%d %H:%M")}
    out = build(data, a.out)
    print("[app] scritta %s (%d KB)" % (os.path.relpath(out, ROOT), os.path.getsize(out) // 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
