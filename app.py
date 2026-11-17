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
    for m in ("usa", "italia"):
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
    out = build({"mercati": mercati, "daytrade": day_trade()}, a.out)
    print("[app] scritta %s (%d KB)" % (os.path.relpath(out, ROOT), os.path.getsize(out) // 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
