#!/usr/bin/env python3
"""Ogni minuto mette lo stato del robot del motore (trader/robot_live.json) nel ramo `robot-stato` del repository, come
unico file robot.json in un unico commit (sovrascritto ogni volta), insieme all'ultima app generata (app.html, rifatta
ogni 15 minuti). Il sito GitHub Pages li legge da lì (index.html carica app.html): le operazioni del motore e i dati
nuovi arrivano sul telefono senza passare da Claude. Gira da solo (lo avvia tempo_reale.sh)."""
import json
import os
import shutil
import urllib.request
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
STATO = os.path.join(ROOT, "trader", "robot_live.json")
APP = os.path.join(ROOT, "trader", "app.html")
DIR = os.path.join(ROOT, "trader", "robot-stato")          # una copia di lavoro a parte, solo per quel ramo
RAMO = "robot-stato"
# gli avvisi sul telefono, gratis e senza Claude: l'app ntfy (iPhone e Android) iscritta all'argomento di notifiche.json
NOTIFICHE = os.path.join(ROOT, "notifiche.json")
VISTI = os.path.join(ROOT, "trader", "ntfy_visti.json")
IMPORTANTI = ("piano", "rete_etf", "rete_obbl", "faber", "tendenza")      # questi subito; gli altri in un riassunto ogni ora
NOMI = {"piano": "Il piano con la rete", "rete_etf": "ETF, rete neurale", "rete_obbl": "Obbligazioni, rete neurale",
        "faber": "ETF, media di 10 mesi", "tendenza": "Crypto, tendenza", "segnali": "Crypto, segnali", "rete": "Crypto, rete neurale",
        "rete_ita": "Azioni italiane, rete", "rete_usa": "Azioni USA, rete", "giornata": "Azioni in seduta"}


def manda(titolo, testo, argomento):
    req = urllib.request.Request("https://ntfy.sh/" + argomento, data=testo.encode("utf-8"),
                                 headers={"Title": titolo.encode("utf-8").decode("latin-1", "ignore"), "Tags": "chart_with_upwards_trend"}, method="POST")
    urllib.request.urlopen(req, timeout=20).read()


def comandi():
    """I comandi che arrivano dall'app (anche dal sito GitHub) sull'argomento ntfy "<argomento>-comandi": per ora il
    reset ("Ricomincia da capo" con il capitale scelto). Si esegue solo quello più recente, una volta sola."""
    try:
        with open(NOTIFICHE, encoding="utf-8") as fh:
            argomento = json.load(fh)["argomento"]
        with open(VISTI, encoding="utf-8") as fh:
            v = json.load(fh)
    except (OSError, ValueError, KeyError):
        return
    try:
        with urllib.request.urlopen("https://ntfy.sh/%s-comandi/json?poll=1&since=%s" % (argomento, v.get("comando") or "10m"), timeout=20) as r:
            righe = [json.loads(x) for x in r.read().decode("utf-8").splitlines() if x.strip()]
    except Exception:
        return
    msg = [m for m in righe if m.get("event") == "message"]
    if not msg:
        return
    ultimo = msg[-1]
    v["comando"] = ultimo["id"]
    with open(VISTI, "w", encoding="utf-8") as fh:
        json.dump(v, fh)
    try:
        cmd = json.loads(ultimo.get("message") or "{}")
    except ValueError:
        return
    if "reset" in cmd:
        capitale = int(float(cmd.get("reset") or 10000))
        subprocess.run([sys.executable, os.path.join(ROOT, "reset_robot.py"), "--capitale", str(capitale)], timeout=60)
        print(time.strftime("%H:%M:%S"), "reset dal comando dell'app, %d euro" % capitale, flush=True)


def avvisi(adesso=None):
    """Manda gli avvisi delle operazioni nuove del motore: subito quelle dei conti importanti, le altre in un riassunto
    ogni ora. Ricorda cosa ha già mandato (trader/ntfy_visti.json)."""
    try:
        with open(NOTIFICHE, encoding="utf-8") as fh:
            argomento = json.load(fh)["argomento"]
        with open(STATO, encoding="utf-8") as fh:
            registro = json.load(fh).get("registro") or []
    except (OSError, ValueError, KeyError):
        return
    try:
        with open(VISTI, encoding="utf-8") as fh:
            v = json.load(fh)
    except (OSError, ValueError):
        v = {"ultimo": max((e.get("t", "") for e in registro), default=""), "riassunto": time.time(), "attesa": []}   # la prima volta: niente arretrati
    nuovi = [e for e in registro if e.get("t", "") > v["ultimo"]]
    for e in sorted(nuovi, key=lambda e: e.get("t", "")):
        r = (" %+.2f %%" % (100 * e["r"])) if e.get("r") is not None else ""
        riga = "%s %s%s · %s" % ("Compra" if e.get("azione") == "compra" else "Vende", e.get("sym", ""), r, NOMI.get(e.get("s"), e.get("s")))
        if e.get("s") in IMPORTANTI:
            try:
                manda("Robot: " + NOMI.get(e.get("s"), ""), riga + ("\n" + e["nota"] if e.get("nota") else ""), argomento)
            except Exception:
                pass
        else:
            v["attesa"].append(riga)
        v["ultimo"] = max(v["ultimo"], e.get("t", ""))
    if v["attesa"] and time.time() - v["riassunto"] > 3600:
        try:
            manda("Robot: %d operazioni nell'ultima ora" % len(v["attesa"]), "\n".join(v["attesa"][-12:]) + ("\n…" if len(v["attesa"]) > 12 else ""), argomento)
            v["attesa"], v["riassunto"] = [], time.time()
        except Exception:
            pass
    with open(VISTI, "w", encoding="utf-8") as fh:
        json.dump(v, fh)


def git(*a, cwd=DIR):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, timeout=120)


def prepara():
    if os.path.isdir(os.path.join(DIR, ".git")):
        return
    shutil.rmtree(DIR, ignore_errors=True)
    os.makedirs(DIR)
    url = git("remote", "get-url", "origin", cwd=ROOT).stdout.strip()
    git("init", "-q")
    git("remote", "add", "origin", url)
    git("checkout", "-q", "--orphan", RAMO)
    git("config", "user.name", "Finanza robot")
    git("config", "user.email", "robot@finanza.invalid")


def una_volta(ultimo):
    if not os.path.exists(STATO):
        return ultimo
    m = (os.path.getmtime(STATO), os.path.getmtime(APP) if os.path.exists(APP) else 0.0)
    if m == ultimo:
        return ultimo
    prepara()
    shutil.copy(STATO, os.path.join(DIR, "robot.json"))
    git("add", "robot.json")
    if os.path.exists(APP) and os.path.getsize(APP) > 100_000:                 # l'app intera, per il sito
        shutil.copy(APP, os.path.join(DIR, "app.html"))
        git("add", "app.html")
    if git("rev-parse", "--verify", "HEAD").returncode == 0:
        git("commit", "-q", "--amend", "-m", "Stato del robot")
    else:
        git("commit", "-q", "-m", "Stato del robot")
    r = git("push", "-q", "-f", "origin", "HEAD:" + RAMO)
    if r.returncode != 0:
        print(time.strftime("%H:%M:%S"), "push non riuscito:", r.stderr.strip()[:200], flush=True)
        return ultimo
    return m


def main():
    ultimo = None
    while True:
        try:
            ultimo = una_volta(ultimo)
            avvisi()
            comandi()
        except Exception as e:                                   # rete o git: si riprova al giro dopo
            print(time.strftime("%H:%M:%S"), "errore:", str(e)[:200], flush=True)
        time.sleep(60)


if __name__ == "__main__":
    sys.exit(main())
