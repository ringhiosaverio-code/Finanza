#!/usr/bin/env python3
"""Fa ricominciare da capo il robot del motore nel cloud: chiede al server live.py (porta 8770) un reset, che la pagina
del motore applica entro pochi secondi (un robot nuovo, tutte le strategie attive, che investe solo da adesso; le
operazioni vecchie spariscono). Lo usa il pulsante "Ricomincia da capo" dell'app.

    python3 reset_robot.py
"""
import datetime
import json
import sys
import urllib.request

SERVER = "http://127.0.0.1:8770/robot"


def main():
    with urllib.request.urlopen(SERVER, timeout=10) as r:
        v = json.load(r)
    ora = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    v["reset_richiesto"] = ora
    v["rev"] = int(v.get("rev") or 0) + 1000                        # più alto di qualunque salvataggio nel frattempo
    req = urllib.request.Request(SERVER, data=json.dumps(v).encode(), headers={"Content-Type": "application/json"}, method="POST")
    urllib.request.urlopen(req, timeout=10).read()
    print("reset chiesto al motore alle %s" % ora)
    return 0


if __name__ == "__main__":
    sys.exit(main())
