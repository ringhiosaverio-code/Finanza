#!/usr/bin/env python3
"""Finanza: esegue in sequenza la catena di un day trade usando le skill trader-*.

    entry -> exit -> timemachine -> budget -> risk

Si ferma PRIMA del broker: questo script non invia mai ordini. Il risultato
finale è trader/orders.json con il verdetto PASS / BLOCK di trader-risk; per
inviarlo serve /trader-broker e il tuo "sì" esplicito in chat.

Esempi:
    python3 finanza.py TSLA                       # dati live Yahoo, ora attuale
    python3 finanza.py TSLA --target 1R --budget 5000 --max-loss 50
    python3 finanza.py --demo                     # offline, il trade TSLA del 19/10/2026

Solo libreria standard, Python 3.8+. Non è consulenza finanziaria.
"""

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.join(ROOT, ".claude", "skills")
FIX = os.path.join(SKILLS, "tests", "fixtures")
TRADER = os.path.join(ROOT, "trader")
CONFIG = os.path.join(TRADER, "config.json")

DEMO = {
    "symbol": "TSLA",
    "now": "2026-10-19 10:15",
    "entry_offline": os.path.join(FIX, "trader-entry", "TSLA-2026-10-19-5m.json"),
    "tm_offline": os.path.join(FIX, "trader-timemachine", "TSLA-60d5m.json.gz"),
    "target": "1R",
    "seed": "19",
}


def tool(skill, script):
    return os.path.join(SKILLS, skill, script)


def step(title, cmd, stop_on_fail=True):
    print("\n" + "=" * 70)
    print(">> " + title)
    print("   " + " ".join(os.path.relpath(c, ROOT) if c.startswith(ROOT) else c for c in cmd))
    print("=" * 70, flush=True)
    rc = subprocess.run(cmd, cwd=ROOT).returncode
    if rc != 0 and stop_on_fail:
        print("\n[finanza] '%s' ha restituito %d: mi fermo qui." % (title, rc))
        sys.exit(rc)
    return rc


def ensure_config(budget, max_loss):
    """Crea trader/config.json dall'esempio (paper: true) e applica gli override."""
    os.makedirs(TRADER, exist_ok=True)
    if os.path.exists(CONFIG):
        with open(CONFIG, encoding="utf-8") as fh:
            cfg = json.load(fh)
    else:
        with open(tool("trader-budget", "config.example.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
        print("[finanza] creato trader/config.json dall'esempio (paper trading attivo)")
    if budget is not None:
        cfg["budget"] = budget
    if max_loss is not None:
        cfg["max_loss_per_trade_usd"] = max_loss
    cfg["paper"] = True if "paper" not in cfg else cfg["paper"]
    with open(CONFIG, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    return cfg


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("symbol", nargs="?", help="ticker, es. TSLA")
    p.add_argument("--demo", action="store_true", help="offline sul trade TSLA del 19/10/2026")
    p.add_argument("--stop", default="or-mid", help="or-mid (default), or-low, pct:X, atr:K, price:X")
    p.add_argument("--target", default="2R", help="2R (default), 1R, 1.5R, price:X")
    p.add_argument("--budget", type=float, help="sovrascrive budget in trader/config.json")
    p.add_argument("--max-loss", type=float, help="perdita massima per trade in USD")
    p.add_argument("--replays", default="10000", help="sessioni simulate dalla Time Machine")
    p.add_argument("--skip-timemachine", action="store_true")
    a = p.parse_args(argv)

    if not a.demo and not a.symbol:
        p.error("serve un ticker oppure --demo")

    sym = DEMO["symbol"] if a.demo else a.symbol.upper()
    target = DEMO["target"] if a.demo and a.target == "2R" else a.target
    cfg = ensure_config(a.budget, a.max_loss)
    now = ["--now", DEMO["now"]] if a.demo else []

    print("[finanza] %s | budget $%s | max perdita/trade $%s | paper=%s"
          % (sym, cfg.get("budget"), cfg.get("max_loss_per_trade_usd"), cfg.get("paper")))

    # 1. entry: il setup è scattato?
    cmd = [sys.executable, tool("trader-entry", "entry.py"), "check", sym, "--setup", "orb", "--write"] + now
    if a.demo:
        cmd += ["--offline", DEMO["entry_offline"]]
    if step("1/5 Entry Timer: breakout del range d'apertura?", cmd, stop_on_fail=False) != 0:
        print("\n[finanza] Nessun ingresso valido adesso (waiting / expired). Niente da pianificare.")
        return 1

    # 2. exit: stop e target prima di entrare
    step("2/5 Exit Planner: stop e target",
         [sys.executable, tool("trader-exit", "exit.py"), "plan", "--stop", a.stop, "--target", target,
          "--write"] + now)

    # 3. time machine: le probabilità oneste
    if not a.skip_timemachine:
        cmd = [sys.executable, tool("trader-timemachine", "timemachine.py"), "run", "--replays", a.replays,
               "--write"] + now
        if a.demo:
            cmd += ["--offline", DEMO["tm_offline"], "--seed", DEMO["seed"]]
        step("3/5 Time Machine: %s replay + storico" % a.replays, cmd)

    # 4. budget: quante azioni
    step("4/5 Budget Manager: dimensione della posizione",
         [sys.executable, tool("trader-budget", "size.py"), "--write"] + now)

    # 5. risk: PASS o BLOCK
    rc = step("5/5 Risk Manager: controllo dei limiti",
              [sys.executable, tool("trader-risk", "check.py")] + now
              + (["--today", DEMO["now"][:10]] if a.demo else []), stop_on_fail=False)

    print("\n" + "-" * 70)
    if rc == 0:
        print("[finanza] PASS. Ordine proposto in trader/orders.json.")
        print("          Per inviarlo usa /trader-broker: chiederà il tuo sì esplicito.")
    else:
        print("[finanza] BLOCK. trader-risk ha fermato l'ordine: leggi il motivo sopra.")
    print("          Non è consulenza finanziaria. Paper trading prima di tutto.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
