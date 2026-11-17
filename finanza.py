#!/usr/bin/env python3
"""Finanza: la catena di un day trade in un comando, con la Macchina del Tempo al centro.

    entry -> [ottimizzatore] -> exit -> macchina del tempo -> [filtro] -> budget -> risk -> report

  entry          il setup (breakout del range d'apertura) è scattato?
  ottimizzatore  (--ottimizza) prova ogni stop x target con la Macchina del Tempo
                 e sceglie la combinazione con l'R medio migliore
  exit           stop e target
  macchina       10.000 sessioni simulate + ogni volta che il setup è scattato in passato
  filtro         se l'R medio simulato è sotto --min-edge (default 0) si ferma: niente ordine
  budget         quante azioni per stare dentro la perdita massima
  risk           PASS / BLOCK contro i tuoi limiti
  report         trader/report.html: ventaglio dei prezzi, probabilità, storico, verdetto

Si ferma PRIMA del broker: questo script non invia mai ordini. Per inviarne uno serve
/trader-broker e il tuo "sì" esplicito in chat.

Esempi:
    python3 finanza.py --demo                          # offline, il trade TSLA del 19/10/2026
    python3 finanza.py --demo --ottimizza
    python3 finanza.py TSLA --ottimizza --budget 5000 --max-loss 50

Solo libreria standard, Python 3.8+. Non è consulenza finanziaria.
"""

import argparse
import importlib.util
import json
import math
import os
import subprocess
import sys

import finanza_report

ROOT = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.join(ROOT, ".claude", "skills")
FIX = os.path.join(SKILLS, "tests", "fixtures")
TRADER = os.path.join(ROOT, "trader")
CACHE = os.path.join(TRADER, "cache")
CONFIG = os.path.join(TRADER, "config.json")

DEMO = {
    "symbol": "TSLA",
    "now": "2026-10-19 10:15",
    "entry_offline": os.path.join(FIX, "trader-entry", "TSLA-2026-10-19-5m.json"),
    "tm_offline": os.path.join(FIX, "trader-timemachine", "TSLA-60d5m.json.gz"),
    "target": "1R",
    "seed": 19,
}

STOPS = ["or-mid", "or-low", "pct:1", "pct:2"]
TARGETS = ["1R", "1.5R", "2R", "3R"]
MIN_HISTORY = 10   # sotto questo numero di casi storici lo storico non entra nel punteggio


def tool(skill, script):
    return os.path.join(SKILLS, skill, script)


def rel(path):
    return os.path.relpath(path, ROOT) if path.startswith(ROOT) else path


def step(title, cmd, stop_on_fail=True):
    print("\n" + "=" * 72)
    print(">> " + title)
    print("   " + " ".join(rel(c) for c in cmd))
    print("=" * 72, flush=True)
    rc = subprocess.run(cmd, cwd=ROOT).returncode
    if rc != 0 and stop_on_fail:
        print("\n[finanza] '%s' ha restituito %d: mi fermo qui." % (title, rc))
        sys.exit(rc)
    return rc


def quiet(cmd):
    """Esegue un comando senza stampare; restituisce (rc, stdout, stderr)."""
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def ensure_config(budget, max_loss):
    """Crea trader/config.json dall'esempio (paper: true) e applica gli override."""
    os.makedirs(TRADER, exist_ok=True)
    cfg = load_json(CONFIG)
    if cfg is None:
        cfg = load_json(tool("trader-budget", "config.example.json"))
        print("[finanza] creato trader/config.json dall'esempio (paper trading attivo)")
    if budget is not None:
        cfg["budget"] = budget
    if max_loss is not None:
        cfg["max_loss_per_trade_usd"] = max_loss
    cfg.setdefault("paper", True)
    with open(CONFIG, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    return cfg


def cache_chart(sym):
    """Scarica UNA volta i 60 giorni di candele a 5 minuti e li salva in trader/cache,
    così l'ottimizzatore e la Macchina del Tempo non interrogano Yahoo a ogni prova."""
    path = os.path.join(CACHE, "%s-60d5m.json" % sym)
    spec = importlib.util.spec_from_file_location("trader_tm", tool("trader-timemachine", "timemachine.py"))
    tm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tm)
    try:
        text = tm.fetch_chart(sym)
    except Exception as e:  # TMError o rete
        print("[finanza] non riesco a scaricare il grafico di %s: %s" % (sym, e))
        return None
    os.makedirs(CACHE, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def score(sim_r, hist):
    """Punteggio di una combinazione: R medio simulato, mediato con lo storico se ci sono abbastanza casi."""
    if hist and hist.get("triggered", 0) >= MIN_HISTORY and hist.get("avg_R") is not None:
        return round((sim_r + hist["avg_R"]) / 2, 3)
    return round(sim_r, 3)


def hist_se(hist):
    """Errore standard dell'R medio storico: quanto potrebbe cambiare per puro caso."""
    rs = [t["R"] for t in (hist.get("trades") or [])]
    if len(rs) < 2:
        return None
    m = sum(rs) / len(rs)
    return round(math.sqrt(sum((r - m) ** 2 for r in rs) / (len(rs) - 1) / len(rs)), 3)


def noise_note(rows):
    """Frase onesta: la migliore combinazione si distingue davvero dalle altre?"""
    ok = [r for r in rows if "score" in r]
    if len(ok) < 2 or ok[0].get("hist_se") is None:
        return None
    gap, se = ok[0]["score"] - ok[1]["score"], ok[0]["hist_se"]
    if gap < se:
        return ("La migliore supera la seconda di %.3f R, ma l'incertezza dello storico è circa ±%.3f R: "
                "nessuna combinazione è chiaramente migliore delle altre." % (gap, se))
    return "La migliore supera la seconda di %.3f R, più dell'incertezza dello storico (±%.3f R)." % (gap, se)


def optimize(now, chart, seed, replays):
    """Prova ogni stop x target sulla Macchina del Tempo con lo stesso seme (stessi numeri casuali
    per tutte le prove, così il confronto è equo). Restituisce le righe ordinate dalla migliore."""
    os.makedirs(CACHE, exist_ok=True)
    plan_tmp = os.path.join(CACHE, "opt-plan.json")
    rows = []
    for s in STOPS:
        for t in TARGETS:
            row = {"stop_rule": s, "target_rule": t}
            rc, _, err = quiet([sys.executable, tool("trader-exit", "exit.py"), "plan", "--stop", s,
                                "--target", t, "--write", plan_tmp] + now)
            if rc != 0:
                row["skip"] = (err.strip().splitlines() or ["rifiutato da trader-exit"])[-1]
                rows.append(row)
                continue
            cmd = [sys.executable, tool("trader-timemachine", "timemachine.py"), "run", "--plan", plan_tmp,
                   "--replays", str(replays), "--seed", str(seed), "--json"] + now
            if chart:
                cmd += ["--offline", chart]
            rc, out, err = quiet(cmd)
            if rc != 0:
                row["skip"] = (err.strip().splitlines() or ["errore della Macchina del Tempo"])[-1]
                rows.append(row)
                continue
            d = json.loads(out)
            mc, hist, plan = d["mc"], d.get("history") or {}, d["plan"]
            row.update({
                "stop": plan["stop"], "target": plan["target"], "risk": plan["risk_per_share"],
                "p_target": mc["p_target"], "p_stop": mc["p_stop"], "p_neither": mc["p_neither"],
                "sim_R": mc["avg_R"], "hist_R": hist.get("avg_R"), "hist_n": hist.get("triggered", 0),
                "score": score(mc["avg_R"], hist), "hist_se": hist_se(hist),
            })
            rows.append(row)
    rows.sort(key=lambda r: -r["score"] if "score" in r else float("inf"))
    return rows


def print_optimizer(rows):
    print("\n  %-7s %-5s %8s %8s %7s %7s %8s %8s %8s" % (
        "stop", "target", "prezzo", "target", "%targ", "%stop", "R sim", "R stor", "punti"))
    for i, r in enumerate(rows):
        if "skip" in r:
            print("  %-7s %-5s  saltata: %s" % (r["stop_rule"], r["target_rule"], r["skip"][:52]))
            continue
        hist = "%+.3f" % r["hist_R"] if r["hist_R"] is not None else "   n/d"
        print("  %-7s %-5s %8.2f %8.2f %6.1f%% %6.1f%% %+8.3f %8s %+8.3f%s" % (
            r["stop_rule"], r["target_rule"], r["stop"], r["target"], r["p_target"] * 100,
            r["p_stop"] * 100, r["sim_R"], hist, r["score"], "  <- scelta" if i == 0 else ""))
    note = noise_note(rows)
    if note:
        print("\n  " + note)
    print("  punti = R medio simulato, mediato con lo storico quando ha almeno %d casi." % MIN_HISTORY)
    print("  Attenzione: scegliere il migliore su 60 giorni rischia di adattarsi al passato (overfitting).")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("symbol", nargs="?", help="ticker, es. TSLA")
    p.add_argument("--demo", action="store_true", help="offline sul trade TSLA del 19/10/2026")
    p.add_argument("--stop", default="or-mid", help="or-mid (default), or-low, pct:X, atr:K, price:X")
    p.add_argument("--target", default=None, help="2R (default; 1R in demo), 1.5R, 3R, price:X")
    p.add_argument("--ottimizza", action="store_true", help="sceglie stop e target con la Macchina del Tempo")
    p.add_argument("--min-edge", type=float, default=0.0,
                   help="R medio simulato minimo per proseguire (default 0.0)")
    p.add_argument("--no-filtro", action="store_true", help="non fermarti se l'R medio è sotto --min-edge")
    p.add_argument("--budget", type=float, help="sovrascrive budget in trader/config.json")
    p.add_argument("--max-loss", type=float, help="perdita massima per trade in USD")
    p.add_argument("--replays", type=int, default=10000, help="sessioni simulate (default 10000)")
    p.add_argument("--seed", type=int, help="seme della simulazione, per ripetere gli stessi numeri")
    a = p.parse_args(argv)

    if not a.demo and not a.symbol:
        p.error("serve un ticker oppure --demo")

    sym = DEMO["symbol"] if a.demo else a.symbol.upper()
    target = a.target or (DEMO["target"] if a.demo else "2R")
    stop = a.stop
    seed = a.seed if a.seed is not None else (DEMO["seed"] if a.demo else 19)
    cfg = ensure_config(a.budget, a.max_loss)
    now = ["--now", DEMO["now"]] if a.demo else []
    for f in ("timemachine.json", "orders.json", "report.html"):   # niente residui di un giro precedente
        try:
            os.remove(os.path.join(TRADER, f))
        except OSError:
            pass

    print("[finanza] %s | budget $%s | max perdita/trade $%s | paper=%s"
          % (sym, cfg.get("budget"), cfg.get("max_loss_per_trade_usd"), cfg.get("paper")))

    # 1. entry
    cmd = [sys.executable, tool("trader-entry", "entry.py"), "check", sym, "--setup", "orb", "--write"] + now
    if a.demo:
        cmd += ["--offline", DEMO["entry_offline"]]
    if step("1 Entry Timer: breakout del range d'apertura?", cmd, stop_on_fail=False) != 0:
        print("\n[finanza] Nessun ingresso valido adesso (waiting / expired). Niente da pianificare.")
        return 1

    chart = DEMO["tm_offline"] if a.demo else cache_chart(sym)

    # 2. ottimizzatore
    opt_rows = None
    if a.ottimizza:
        print("\n" + "=" * 72)
        print(">> 2 Ottimizzatore: %d combinazioni stop x target, 2.000 replay ciascuna, seme %d"
              % (len(STOPS) * len(TARGETS), seed))
        print("=" * 72, flush=True)
        opt_rows = optimize(now, chart, seed, 2000)
        print_optimizer(opt_rows)
        best = next((r for r in opt_rows if "score" in r), None)
        if best is None:
            print("\n[finanza] Nessuna combinazione valida: mi fermo.")
            return 1
        stop, target = best["stop_rule"], best["target_rule"]

    # 3. exit
    step("3 Exit Planner: stop %s, target %s" % (stop, target),
         [sys.executable, tool("trader-exit", "exit.py"), "plan", "--stop", stop, "--target", target,
          "--write"] + now)

    # 4. macchina del tempo
    cmd = [sys.executable, tool("trader-timemachine", "timemachine.py"), "run", "--replays", str(a.replays),
           "--seed", str(seed), "--write"] + now
    if chart:
        cmd += ["--offline", chart]
    step("4 Macchina del Tempo: %s replay + storico" % "{:,}".format(a.replays).replace(",", "."), cmd)
    tm = load_json(os.path.join(TRADER, "timemachine.json"))

    # 5. filtro sul vantaggio
    sim_r = tm["mc"]["avg_R"]
    hist = tm.get("history") or {}
    edge_ok = a.no_filtro or sim_r >= a.min_edge
    print("\n[finanza] Filtro: R medio simulato %+.3f (minimo %+.3f)%s -> %s" % (
        sim_r, a.min_edge,
        ", storico %+.3f su %d casi" % (hist["avg_R"], hist.get("triggered", 0)) if hist.get("avg_R") is not None else "",
        "OK" if sim_r >= a.min_edge else ("ignorato (--no-filtro)" if a.no_filtro else "STOP")))
    if hist.get("avg_R") is not None and hist["avg_R"] < 0 <= sim_r:
        print("[finanza] Attenzione: sugli ultimi giorni reali la stessa regola ha perso in media.")

    risk = None
    if edge_ok:
        # 6. budget
        step("6 Budget Manager: dimensione della posizione",
             [sys.executable, tool("trader-budget", "size.py"), "--write"] + now)
        # 7. risk
        step("7 Risk Manager: controllo dei limiti",
             [sys.executable, tool("trader-risk", "check.py")] + now
             + (["--today", DEMO["now"][:10]] if a.demo else []), stop_on_fail=False)
        risk = load_json(os.path.join(TRADER, "state", "risk.json"))

    # 8. report
    out = os.path.join(TRADER, "report.html")
    finanza_report.write(out, tm=tm, plan=load_json(os.path.join(TRADER, "plan.json")),
                         orders=load_json(os.path.join(TRADER, "orders.json")) if edge_ok else None,
                         risk=risk, opt_rows=opt_rows, min_edge=a.min_edge, edge_ok=edge_ok,
                         min_history=MIN_HISTORY, noise=noise_note(opt_rows) if opt_rows else None)

    print("\n" + "-" * 72)
    if not edge_ok:
        print("[finanza] FERMO. La Macchina del Tempo non vede un vantaggio: nessun ordine proposto.")
        rc = 2
    elif risk and risk.get("block", 1) == 0:
        print("[finanza] PASS. Ordine proposto in trader/orders.json.")
        print("          Per inviarlo usa /trader-broker: chiederà il tuo sì esplicito.")
        rc = 0
    else:
        print("[finanza] BLOCK. trader-risk ha fermato l'ordine: leggi il motivo sopra.")
        rc = 1
    print("          Report: %s" % rel(out))
    print("          Non è consulenza finanziaria. Paper trading prima di tutto.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
