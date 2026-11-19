#!/usr/bin/env python3
"""Ogni minuto mette lo stato del robot del motore (trader/robot_live.json) nel ramo `robot-stato` del repository, come
unico file robot.json in un unico commit (sovrascritto ogni volta). Il sito GitHub Pages lo legge da lì: le operazioni del
motore arrivano sul telefono senza passare da Claude. Gira da solo (lo avvia tempo_reale.sh)."""
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
STATO = os.path.join(ROOT, "trader", "robot_live.json")
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
    m = os.path.getmtime(STATO)
    if m == ultimo:
        return ultimo
    prepara()
    shutil.copy(STATO, os.path.join(DIR, "robot.json"))
    git("add", "robot.json")
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
    ultimo = 0.0
    while True:
        try:
            ultimo = una_volta(ultimo)
        except Exception as e:                                   # rete o git: si riprova al giro dopo
            print(time.strftime("%H:%M:%S"), "errore:", str(e)[:200], flush=True)
        time.sleep(60)


if __name__ == "__main__":
    sys.exit(main())
