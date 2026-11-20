#!/usr/bin/env python3
"""Ogni minuto mette lo stato del robot del motore (trader/robot_live.json) nel ramo `robot-stato` del repository, come
unico file robot.json in un unico commit (sovrascritto ogni volta), insieme all'ultima app generata (app.html, rifatta
ogni 15 minuti). Il sito GitHub Pages li legge da lì (index.html carica app.html): le operazioni del motore e i dati
nuovi arrivano sul telefono senza passare da Claude. Gira da solo (lo avvia tempo_reale.sh).

Ogni lunedì dalle 8 (ora italiana) manda anche il resoconto della settimana: i conti del robot contro SWDA, le
operazioni, il diario della rete dal vivo e le sue scelte. Nei giorni feriali, a borsa USA aperta, ribilancia una volta
il conto di prova su Alpaca (alpaca_paper.py), se ci sono le chiavi.

    python3 pubblica_stato.py                       # il giro di ogni minuto (lo avvia tempo_reale.sh)
    python3 pubblica_stato.py --resoconto           # scrive il resoconto della settimana, senza mandarlo
    python3 pubblica_stato.py --resoconto --manda   # e lo manda subito sul telefono
"""
import datetime
import json
import os
import shutil
import urllib.request
import subprocess
import sys
import time
import zoneinfo

ROOT = os.path.dirname(os.path.abspath(__file__))
STATO = os.path.join(ROOT, "trader", "robot_live.json")
APP = os.path.join(ROOT, "trader", "app.html")
DIR = os.path.join(ROOT, "trader", "robot-stato")          # una copia di lavoro a parte, solo per quel ramo
RAMO = "robot-stato"
# gli avvisi sul telefono, gratis e senza Claude: l'app ntfy (iPhone e Android) iscritta all'argomento di notifiche.json
NOTIFICHE = os.path.join(ROOT, "notifiche.json")
VISTI = os.path.join(ROOT, "trader", "ntfy_visti.json")
RESOCONTO = os.path.join(ROOT, "trader", "resoconto.json")   # l'ultimo resoconto, anche per l'app (ramo robot-stato)
ALPACA = os.path.join(ROOT, "trader", "alpaca.json")         # il conto di prova su Alpaca, per l'app (alpaca_paper.py)
IMPORTANTI = ("piano", "rete_etf", "rete_obbl", "faber", "tendenza")      # questi subito; gli altri in un riassunto ogni ora
NOMI = {"piano": "Il piano con la rete", "rete_etf": "ETF, rete neurale", "rete_obbl": "Obbligazioni, rete neurale",
        "faber": "ETF, media di 10 mesi", "tendenza": "Crypto, tendenza", "segnali": "Crypto, segnali", "rete": "Crypto, rete neurale",
        "rete_ita": "Azioni italiane, rete", "rete_usa": "Azioni USA, rete", "giornata": "Azioni in seduta"}


ROMA = zoneinfo.ZoneInfo("Europe/Rome")
GIORNI = ("lun", "mar", "mer", "gio", "ven", "sab", "dom")
MESI = ("gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic")


def manda(titolo, testo, argomento, etichetta="chart_with_upwards_trend"):
    titolo = titolo.encode("latin-1", "ignore").decode("latin-1")           # le intestazioni HTTP: solo latin-1
    req = urllib.request.Request("https://ntfy.sh/" + argomento, data=testo.encode("utf-8"),
                                 headers={"Title": titolo, "Tags": etichetta}, method="POST")
    urllib.request.urlopen(req, timeout=20).read()


def _num(x, decimali=0):
    """Il numero all'italiana: 10.012,5"""
    t = "{:,.{}f}".format(x, decimali)
    return t.replace(",", "_").replace(".", ",").replace("_", ".")


def _pc(x, decimali=1):
    return ("+" if x >= 0 else "-") + _num(abs(100 * x), decimali) + " %"


def _giorno(d):
    g = datetime.date.fromisoformat(d) if isinstance(d, str) else d
    return "%s %d %s" % (GIORNI[g.weekday()], g.day, MESI[g.month - 1])


def resoconto_testo(stato, diario=None, oggi=None, finora=False):
    """Il resoconto della settimana appena finita (da lunedì a domenica), da mandare il lunedì: (titolo, testo), o
    None se il robot non ha ancora uno storico. I conti partono tutti dal capitale scelto; quelli nati durante la
    settimana contano da lì. oggi: la data del lunedì (datetime.date). finora: chiesto a metà settimana, la settimana
    in corso fino a oggi compreso."""
    storico = [x for x in (stato.get("storico") or []) if x.get("d")]
    oggi = oggi or datetime.datetime.now(ROMA).date()
    finora = finora and oggi.weekday() != 0
    lunedi = oggi - datetime.timedelta(days=oggi.weekday() or 7)                 # il lunedì della settimana appena finita
    fine = [x for x in storico if x["d"] <= oggi.isoformat()] if finora else [x for x in storico if x["d"] < oggi.isoformat()]
    if not fine:
        return None
    fine = fine[-1]
    prima = [x for x in storico if x["d"] < lunedi.isoformat()]
    base = prima[-1] if prima else {}                                            # la chiusura della settimana prima
    capitale = float(stato.get("capitale") or 10000)
    dal = lunedi if prima else max(lunedi, datetime.date.fromisoformat(storico[0]["d"]))
    al = datetime.date.fromisoformat(fine["d"])
    righe = ["Il robot dal %s al %s%s, %s € per conto:" % (_giorno(dal), _giorno(al), "" if prima else " (da quando è ripartito)", _num(capitale))]
    ordine = list(IMPORTANTI) + [k for k in NOMI if k not in IMPORTANTI]
    conti = {}
    for k in ordine + sorted(k for k in fine if k not in NOMI and not k.startswith("_") and k != "d"):
        if not isinstance(fine.get(k), (int, float)):
            continue
        v0 = float(base.get(k) or capitale)
        conti[k] = (float(fine[k]), float(fine[k]) / v0 - 1)
        righe.append("%s: %s € (%s)" % (NOMI.get(k, k), _num(conti[k][0]), _pc(conti[k][1])))
    con_swda = [x for x in storico if x["d"] < fine["d"] and x.get("_swda")]          # un prezzo di partenza prima della fine
    s0 = base.get("_swda") or next((x["_swda"] for x in con_swda if x["d"] >= dal.isoformat()), None)
    if s0 and fine.get("_swda"):
        righe.append("SWDA (il mondo intero, per confronto): %s" % _pc(fine["_swda"] / s0 - 1))
    if len(conti) >= 2:
        meglio = max(conti, key=lambda k: conti[k][1])
        peggio = min(conti, key=lambda k: conti[k][1])
        righe.append("Meglio: %s (%s) · peggio: %s (%s)" % (NOMI.get(meglio, meglio), _pc(conti[meglio][1]), NOMI.get(peggio, peggio), _pc(conti[peggio][1])))
    ops = [e for e in (stato.get("registro") or []) if dal.isoformat() <= (e.get("t") or "")[:10] <= al.isoformat()]
    vendite = [e for e in ops if e.get("azione") != "compra" and e.get("r") is not None]
    if ops:
        vinte = sum(1 for e in vendite if e["r"] >= 0)
        righe.append("")
        righe.append("Operazioni: %d (%d vendite%s)" % (len(ops), len(vendite), ", %d %% in guadagno" % round(100 * vinte / len(vendite)) if vendite else ""))
    G = diario or {}
    chiuse = [v for v in G.get("voci") or [] if v.get("esito") is not None]
    ctl = G.get("controllo") or {}
    if chiuse or ctl:
        righe.append("")
    if chiuse:
        u = chiuse[-1]
        righe.append("La rete dal vivo, settimana dal %s: le sue scelte %s contro %s della media degli ETF." % (
            _giorno(u["giorno"]), _pc(u["esito"], 2), _pc(u["tutti"], 2) if u.get("tutti") is not None else "–"))
    if ctl:
        righe.append("Peso della rete nel piano: %d %% (%s). %s" % (round(100 * ctl.get("peso", 0.2)), ctl.get("stato", ""), ctl.get("messaggio", "")))
    voci = G.get("voci") or []
    if voci and voci[-1].get("scelte"):
        righe.append("Le scelte della rete adesso (dal %s): %s." % (_giorno(voci[-1]["giorno"]), ", ".join(x.replace(".MI", "") for x in voci[-1]["scelte"])))
    return "Resoconto della settimana%s · %s" % (" (finora)" if finora else "", _giorno(oggi)), "\n".join(righe).strip()


def resoconto(adesso=None, subito=False):
    """Il lunedì dalle 8 (ora italiana) manda il resoconto della settimana, una volta sola; se non parte (rete, limite
    di ntfy) riprova ogni mezz'ora, fino a sera. In ogni caso lo scrive in trader/resoconto.json, che va nel ramo
    robot-stato: l'app lo mostra anche quando l'avviso non arriva. subito: adesso (dal comando dell'app)."""
    adesso = adesso or datetime.datetime.now(ROMA)
    if not subito and (adesso.weekday() != 0 or adesso.hour < 8):
        return False
    try:
        with open(NOTIFICHE, encoding="utf-8") as fh:
            argomento = json.load(fh)["argomento"]
        with open(STATO, encoding="utf-8") as fh:
            stato = json.load(fh)
    except (OSError, ValueError, KeyError):
        return False
    try:
        with open(VISTI, encoding="utf-8") as fh:
            v = json.load(fh)
    except (OSError, ValueError):
        v = {}
    if not subito and v.get("resoconto") == adesso.date().isoformat():
        return False
    if not subito and adesso.timestamp() - float(v.get("resoconto_prova") or 0) < 1800:   # l'ultima prova fallita: tra mezz'ora
        return False
    try:
        with open(os.path.join(ROOT, "diario_rete.json"), encoding="utf-8") as fh:
            diario = json.load(fh)
    except (OSError, ValueError):
        diario = None
    r = resoconto_testo(stato, diario, adesso.date(), finora=subito)
    if not r:
        return False
    mandato = True
    try:
        manda(r[0], r[1], argomento, "memo")
    except Exception as e:
        mandato = False
        print(time.strftime("%H:%M:%S"), "resoconto non mandato:", str(e)[:120], flush=True)
    with open(RESOCONTO, "w", encoding="utf-8") as fh:
        json.dump({"titolo": r[0], "testo": r[1], "mandato": mandato,
                   "quando": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, fh, ensure_ascii=False)
    if not subito:
        if mandato:
            v["resoconto"] = adesso.date().isoformat()
        else:
            v["resoconto_prova"] = adesso.timestamp()
        with open(VISTI, "w", encoding="utf-8") as fh:
            json.dump(v, fh)
    if mandato:
        print(time.strftime("%H:%M:%S"), "resoconto della settimana mandato", flush=True)
    return mandato


def comandi():
    """I comandi che arrivano dall'app (anche dal sito GitHub) sull'argomento ntfy "<argomento>-comandi": per ora il
    reset ("Ricomincia da capo" con il capitale scelto) e il resoconto della settimana adesso. Si esegue solo quello più
    recente, una volta sola."""
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
    if "resoconto" in cmd:                                              # "Mandami il resoconto adesso" dall'app
        resoconto(subito=True)
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
    try:                                                                # il controllo dal vivo ha cambiato il peso della rete nel piano?
        with open(os.path.join(ROOT, "diario_rete.json"), encoding="utf-8") as fh:
            ctl = json.load(fh).get("controllo") or {}
        if ctl and v.get("peso_rete") is not None and abs(ctl.get("peso", 0.2) - v["peso_rete"]) > 1e-9:
            manda("Piano: la rete passa al %d %%" % round(100 * ctl["peso"]), ctl.get("messaggio", ""), argomento)
        if ctl:
            v["peso_rete"] = ctl.get("peso", 0.2)
    except (OSError, ValueError):
        pass
    if v["attesa"] and time.time() - v["riassunto"] > 3600:
        try:
            manda("Robot: %d operazioni nell'ultima ora" % len(v["attesa"]), "\n".join(v["attesa"][-12:]) + ("\n…" if len(v["attesa"]) > 12 else ""), argomento)
            v["attesa"], v["riassunto"] = [], time.time()
        except Exception:
            pass
    with open(VISTI, "w", encoding="utf-8") as fh:
        json.dump(v, fh)


def alpaca(adesso=None):
    """Il robot con un broker vero (Alpaca, conto di prova): nei giorni feriali tra le 16 e le 21 ora italiana (borsa USA
    aperta) ribilancia una volta sul piano con alpaca_paper.py. Senza chiavi scrive solo come collegarlo e riprova il
    giorno dopo."""
    adesso = adesso or datetime.datetime.now(ROMA)
    if adesso.weekday() > 4 or not 16 <= adesso.hour < 21:
        return False
    try:
        with open(VISTI, encoding="utf-8") as fh:
            v = json.load(fh)
    except (OSError, ValueError):
        v = {}
    if v.get("alpaca") == adesso.date().isoformat():
        return False
    v["alpaca"] = adesso.date().isoformat()
    with open(VISTI, "w", encoding="utf-8") as fh:
        json.dump(v, fh)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "alpaca_paper.py"), "--ribilancia"], capture_output=True, text=True, timeout=180)
    print(time.strftime("%H:%M:%S"), "alpaca:", (r.stdout.strip().splitlines() or ["fatto"])[-1][:160], flush=True)
    return True


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
    m = (os.path.getmtime(STATO), os.path.getmtime(APP) if os.path.exists(APP) else 0.0,
         os.path.getmtime(RESOCONTO) if os.path.exists(RESOCONTO) else 0.0, os.path.getmtime(ALPACA) if os.path.exists(ALPACA) else 0.0)
    if m == ultimo:
        return ultimo
    prepara()
    shutil.copy(STATO, os.path.join(DIR, "robot.json"))
    git("add", "robot.json")
    for f in (RESOCONTO, ALPACA):                          # l'ultimo resoconto della settimana e il conto Alpaca, per l'app
        if os.path.exists(f):
            shutil.copy(f, os.path.join(DIR, os.path.basename(f)))
            git("add", os.path.basename(f))
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
            resoconto()
            alpaca()
        except Exception as e:                                   # rete o git: si riprova al giro dopo
            print(time.strftime("%H:%M:%S"), "errore:", str(e)[:200], flush=True)
        time.sleep(60)


if __name__ == "__main__":
    if "--resoconto" in sys.argv:
        if "--manda" in sys.argv:
            sys.exit(0 if resoconto(subito=True) else 1)
        with open(STATO, encoding="utf-8") as fh:
            st = json.load(fh)
        try:
            with open(os.path.join(ROOT, "diario_rete.json"), encoding="utf-8") as fh:
                dr = json.load(fh)
        except (OSError, ValueError):
            dr = None
        print("\n".join(resoconto_testo(st, dr, finora=True) or ("(niente: il robot non ha ancora uno storico)",)))
        sys.exit(0)
    sys.exit(main())
