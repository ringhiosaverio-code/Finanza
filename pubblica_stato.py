#!/usr/bin/env python3
"""Ogni minuto mette lo stato del robot del motore (trader/robot_live.json) nel ramo `robot-stato` del repository, come
unico file robot.json in un unico commit (sovrascritto ogni volta), insieme all'ultima app generata (app.html, rifatta
ogni 15 minuti). Il sito GitHub Pages li legge da lì (index.html carica app.html): le operazioni del motore e i dati
nuovi arrivano sul telefono senza passare da Claude. Gira da solo (lo avvia tempo_reale.sh)."""
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
STATO = os.path.join(ROOT, "trader", "robot_live.json")
APP = os.path.join(ROOT, "trader", "app.html")
DIR = os.path.join(ROOT, "trader", "robot-stato")          # una copia di lavoro a parte, solo per quel ramo
RAMO = "robot-stato"


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
        except Exception as e:                                   # rete o git: si riprova al giro dopo
            print(time.strftime("%H:%M:%S"), "errore:", str(e)[:200], flush=True)
        time.sleep(60)


if __name__ == "__main__":
    sys.exit(main())
