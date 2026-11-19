#!/usr/bin/env python3
"""Allinea il robot del motore nel cloud (trader/robot_live.json, tenuto da live.py) e quello dell'app pubblicata
(il documento letto dal database dell'artifact). Vince il più nuovo (rev più alta):

- se hai toccato qualcosa nell'app pubblicata (rev più alta là), lo stato va al motore;
- altrimenti lo stato del motore, con le operazioni fatte in tempo reale, va scritto nell'app pubblicata.

    python3 sincronizza_robot.py <documento letto dal database> <file da scrivere nel database>

Stampa una riga JSON come robot_cloud.js: {robot, cambiato, nuovi, testo, motore}. Se il motore non c'è, motore=false
e non tocca niente (allora si usa robot_cloud.js)."""
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
MOTORE = os.path.join(ROOT, "trader", "robot_live.json")
NOMI = {"giornata": "Azioni", "crypto": "Crypto", "rete": "Rete crypto", "rete_ita": "Rete Italia", "usa_notte": "USA notte",
        "ita_notte": "Italia notte"}


ULTIMO = os.path.join(ROOT, "trader", "robot_ultimo_sync.json")


def comandi(s):
    """Quello che decidi tu: sessione aperta o chiusa e conti avviati o fermati."""
    return (json.dumps((s.get("sessione") or {}).get("aperta")), json.dumps(sorted((k, bool(c.get("attiva"))) for k, c in (s.get("conti") or {}).items())))


def chiave(e):
    return (e.get("t"), e.get("s"), e.get("sym"), e.get("azione"), e.get("prezzo"), e.get("nota"))


def main(ingresso, uscita):
    if not os.path.exists(MOTORE):
        print(json.dumps({"motore": False}))
        return 0
    with open(MOTORE, encoding="utf-8") as fh:
        m = json.load(fh)
    try:
        with open(ingresso, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        d = {}
    d = d.get("data", d) if isinstance(d, dict) and "conti" not in d else d
    # hai toccato l'app pubblicata dopo l'ultima sincronizzazione (avviato o fermato un conto, aperta o chiusa la sessione)?
    # Allora vale lei. Le rev dei due lati contano ognuna per sé: si confrontano i comandi, non i numeri.
    ultimo = None
    if os.path.exists(ULTIMO):
        with open(ULTIMO, encoding="utf-8") as fh:
            ultimo = json.load(fh)
    if d.get("conti") and ultimo is not None and comandi(d) != comandi(ultimo):
        d["rev"] = max(d.get("rev") or 0, m.get("rev") or 0) + 1                 # più nuova di quella del motore
        req = urllib.request.Request("http://127.0.0.1:8770/robot", data=json.dumps(d).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()
        with open(ULTIMO, "w", encoding="utf-8") as fh:
            json.dump(d, fh)
        print(json.dumps({"motore": True, "robot": True, "cambiato": False, "nuovi": 0, "testo": "", "verso": "al motore"}))
        return 0
    prima = {chiave(e) for e in d.get("registro", [])}
    nuovi = [e for e in m.get("registro", []) if chiave(e) not in prima and e.get("azione") in ("compra", "vende")]
    with open(uscita, "w", encoding="utf-8") as fh:
        json.dump(m, fh)
    with open(ULTIMO, "w", encoding="utf-8") as fh:
        json.dump(m, fh)
    testo = ""
    if nuovi:
        per = {}
        for e in nuovi:
            per[e.get("s")] = per.get(e.get("s"), 0) + 1
        testo = "Robot: %d operazion%s nuov%s. %s." % (len(nuovi), "e" if len(nuovi) == 1 else "i", "a" if len(nuovi) == 1 else "e",
                                                       ", ".join("%s %d" % (NOMI.get(k, k), n) for k, n in per.items()))
    print(json.dumps({"motore": True, "robot": True, "cambiato": (m.get("rev") or 0) != (d.get("rev") or 0), "nuovi": len(nuovi),
                      "testo": testo[:199], "verso": "all'app"}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
