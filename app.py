#!/usr/bin/env python3
"""Finanza, l'app: un unico file HTML con tutto dentro.

    python3 app.py                  # scarica i dati, analizza, scrive trader/app.html
    python3 app.py --asof 2025-06-30
    python3 app.py --leggero        # solo le crypto intraday, dall'ultima app (qualche secondo: per ogni ora)

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

import crypto_lungo
import giornata
import intraday
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


def simulazioni(mercati, log=print):
    """La simulazione per ISIN di tutti gli strumenti dell'app (fino a 25 anni di storia), crypto
    comprese, più quelli aggiunti con simula.py (simula_lista.json). Ogni strumento porta con sé il
    periodo consigliato (hold) della sua categoria e il calendario con cui contare i giorni."""
    rev = {v: k for k, v in simula.load_isin_map().items()}
    cat = {}
    for m in ("usa", "italia", "etf", "bond", "oro"):
        for s in settimana.MERCATI[m]["universo"]:
            cat[s] = m
    for s in simula.CRYPTO:
        cat[s] = "crypto"
    hold = {m: int(r["consigliata"]["key"].split("|")[1]) for m, r in mercati.items()}
    hold["crypto"] = 91                                   # 3 mesi di calendario: le crypto non chiudono mai

    def extra(s):
        cal_mercato = "usa" if s.get("cal") == "borsa" and not s["symbol"].endswith(".MI") else "italia"
        s["calendario"] = "sempre" if s.get("cal") == "sempre" else cal_mercato
        return s

    def one(sym):
        try:
            text = simula.fetch_max(sym)
            meta, dates, closes = simula.series(text)
            s = simula.simulate(dates, closes, cal="sempre" if cat[sym] == "crypto" else "borsa")
            s["rendimento"] = settimana.div_yield(text)
        except (simula.SimError, ValueError, KeyError) as e:
            log("[app] simulazione di %s saltata: %s" % (sym, e))
            return None
        name = meta.get("longName") or meta.get("shortName") or sym
        if cat[sym] == "crypto":
            name = name.replace(" EUR", "")
        return extra({"isin": rev.get(sym), "symbol": sym, "categoria": cat[sym], "hold_cat": hold.get(cat[sym], 21),
                      "name": name, "exchange": meta.get("fullExchangeName") or meta.get("exchangeName") or "",
                      "type": meta.get("instrumentType") or "", "currency": meta.get("currency") or "", **s})

    syms = list(cat)
    log("[app] simulazione di %d strumenti (crypto comprese)..." % len(syms))
    with ThreadPoolExecutor(max_workers=4) as ex:
        out = {s["symbol"]: s for s in ex.map(one, syms) if s}
    for code in simula.load_list():                      # aggiunti con simula.py, prezzi aggiornati
        try:
            s = simula.instrument(code)
        except (simula.SimError, settimana.FetchError, ValueError, KeyError) as e:
            log("[app] %s saltato: %s" % (code, e))
            continue
        fund = s.get("type") in ("ETF", "MUTUALFUND")
        s["hold_cat"] = 91 if s.get("cal") == "sempre" else (63 if fund else 21)
        out[s["symbol"]] = extra(s)
    for s in out.values():                               # per quanto tenere: la durata dello strumento,
        s["hold"] = s.get("durata") or s["hold_cat"]     # altrimenti quella della categoria
    return out


def crypto_lungo_termine(log=print):
    """Crypto a medio e lungo termine: compra e tieni, tendenza 200/50, durate, a rate (crypto_lungo.py)."""
    try:
        return crypto_lungo.analisi(log)
    except Exception as e:                                   # rete o dati: l'app si genera lo stesso
        log("[app] crypto a lungo termine saltate: %s" % e)
        return None


def piano_giornata(log=print):
    """Il piano per la prossima seduta in giornata (giornata.py)."""
    try:
        return giornata.piani(log)
    except Exception as e:                                   # rete o dati: l'app si genera lo stesso
        log("[app] giornata saltata: %s" % e)
        return None


def crypto_intraday(log=print, leggero=None):
    """Ordini crypto rinnovati ogni ora con la loro verifica (intraday.analizza_ore), e i due piani al giorno di
    prima con le varianti provate, come confronto (intraday.py). leggero: i dati dell'ultima app; se ci sono, le
    varianti e il controllo su Kraken (che non cambiano da un'ora all'altra) si prendono da lì."""
    try:
        r = intraday.analizza(log)
        r["varianti"] = (leggero or {}).get("varianti") or intraday.varianti(log)
        try:
            r["ore"] = intraday.analizza_ore(log, kraken=not leggero)
            vecchio = (leggero or {}).get("ore") or {}
            if vecchio.get("kraken") and vecchio.get("metodo") == intraday.METODO_ORE:    # solo se calcolato allo stesso modo
                r["ore"]["kraken"] = vecchio["kraken"]
        except Exception as e:                               # rete o dati: restano i piani di prima
            log("[app] ordini orari saltati: %s" % e)
        return r
    except Exception as e:                                   # rete o dati: l'app si genera lo stesso
        log("[app] intraday saltato: %s" % e)
        return None


def rete_per_app():
    """I risultati della rete neurale (python3 rete.py --studia, in rete_modello.json) senza i pesi: servono alla
    sezione Crypto dell'app. None se non sono mai stati calcolati."""
    try:
        with open(os.path.join(ROOT, "rete_modello.json"), encoding="utf-8") as fh:
            r = json.load(fh)
    except (OSError, ValueError):
        return None
    for m in list((r.get("modelli") or {}).values()) + list((r.get("probabilita") or {}).values()):
        for k in ("rete", "media", "dev"):
            m.pop(k, None)
    return r


def rete_robot_app(log=print):
    """Le operazioni della rete neurale sulle crypto per il robot dell'app (rete_live.robot_crypto): servono gli
    scambi di Kraken (cache di rete_dati.py, più quelli che mancano) e rete_modello.json. None se non si può."""
    try:
        import rete_live
        return rete_live.robot_crypto(log=log)
    except Exception as e:                                     # rete, dati o modello mancanti: l'app si genera lo stesso
        log("[app] rete neurale per il robot saltata: %s" % str(e)[:160])
        return None


def rete_ita_app(log=print):
    """I risultati della rete neurale per le azioni italiane (python3 rete_azioni.py --studia) senza i pesi, o None."""
    try:
        import rete_azioni
        return rete_azioni.per_app()
    except Exception as e:                                     # numpy mancante o file rovinato: l'app si genera lo stesso
        log("[app] rete delle azioni italiane saltata: %s" % str(e)[:160])
        return None


def rete_ita_robot_app(log=print):
    """Le operazioni della rete neurale sulle azioni italiane nelle ultime sedute, per il robot dell'app
    (rete_azioni.robot: barre da 5 minuti di Yahoo e rete_azioni_modello.json). None se non si può."""
    try:
        import rete_azioni
        return rete_azioni.robot(log=log)
    except Exception as e:                                     # rete, dati o modello mancanti: l'app si genera lo stesso
        log("[app] rete delle azioni italiane per il robot saltata: %s" % str(e)[:160])
        return None


def rete_usa_app(log=print):
    """I risultati della rete neurale per le azioni USA (python3 rete_usa.py --studia) senza i pesi, o None."""
    try:
        import rete_usa
        return rete_usa.per_app()
    except Exception as e:
        log("[app] rete delle azioni USA saltata: %s" % str(e)[:160])
        return None


def rete_usa_robot_app(log=print):
    """Le operazioni della rete neurale sulle azioni USA nelle ultime sedute, per il robot. None se non si può."""
    try:
        import rete_usa
        if not os.path.exists(rete_usa.MODELLO):
            return None
        return rete_usa.robot(log=log)
    except Exception as e:
        log("[app] rete delle azioni USA per il robot saltata: %s" % str(e)[:160])
        return None


def segnali_robot_app(log=print):
    """Gli ordini sui segnali delle 30 crypto per il robot (rete_live.robot_segnali), o None."""
    try:
        import rete_live
        return rete_live.robot_segnali(log=log)
    except Exception as e:
        log("[app] ordini sui segnali saltati: %s" % str(e)[:160])
        return None


def tendenza_app(log=print):
    """La tendenza come i fondi sulle crypto (crypto_tendenza.py), rifatta con i prezzi di oggi, o None."""
    try:
        import crypto_tendenza
        return crypto_tendenza.studia(log=lambda m: None)
    except Exception as e:
        log("[app] tendenza crypto saltata: %s" % str(e)[:160])
        return None


def strategie_lungo_app(log=print):
    """Le strategie dei libri (Antonacci, Faber, Clenow) sui mercati dell'app (strategie_lungo.py), o None."""
    try:
        import strategie_lungo
        return strategie_lungo.studia(log=lambda m: None)
    except Exception as e:
        log("[app] strategie dei libri saltate: %s" % str(e)[:160])
        return None


def rete_lungo_app(log=print):
    """La rete del medio e lungo periodo (python3 rete_lungo.py), o None."""
    try:
        import rete_lungo
        return rete_lungo.per_app()
    except Exception as e:
        log("[app] rete del medio e lungo periodo saltata: %s" % str(e)[:160])
        return None


def sentimento(log=print):
    """Il Fear & Greed di oggi e di una settimana fa, e il giorno delle ultime notizie scaricate da GDELT (per l'app)."""
    try:
        import datetime as dt
        import segnali
        fg = segnali.fear_greed(log=log)
        if not fg:
            return None
        oggi = max(fg)
        prima = (dt.date.fromisoformat(oggi) - dt.timedelta(days=7)).isoformat()
        notizie = segnali.notizie("crypto", "bitcoin OR cryptocurrency OR crypto", log=lambda m: None)
        return {"data": oggi, "valore": fg[oggi], "prima": fg.get(prima), "notizie": max(notizie) if notizie else None}
    except Exception as e:                                     # rete o file: l'app si genera lo stesso
        log("[app] sentimento saltato: %s" % str(e)[:120])
        return None


def fonti_segnali():
    try:
        import segnali
        return [list(x) for x in segnali.FONTI]
    except Exception:
        return None


def calendari():
    """I giorni di borsa dal 2024 al 2027 (NYSE e Borsa Italiana): servono all'app per contare la data
    di vendita di un titolo comprato in un giorno qualsiasi."""
    out = {}
    for c, idx, cfg in (("usa", "SPY", settimana.MERCATI["usa"]), ("italia", "FTSEMIB.MI", settimana.MERCATI["italia"])):
        meta, closes, _ = settimana.parse(settimana.fetch(idx), None, cfg["fuso"], cfg["chiusura"])
        past = [d for d in sorted(closes) if d >= "2024-01-01"]          # i giorni in cui la borsa ha aperto davvero
        out[c] = past + settimana.trading_days_after(past[-1], 300, c)   # poi le festività note
    return out


def cambio():
    """Quanti euro vale un dollaro, all'ultima chiusura (per il conto demo)."""
    try:
        meta, closes, _ = settimana.parse(settimana.fetch("EURUSD=X"))
        last = closes[max(closes)]
        return {"USD": round(1 / last, 6), "data": max(closes)}
    except (settimana.FetchError, ValueError, KeyError):
        return None


def build(data, out):
    with open(TEMPLATE, encoding="utf-8") as fh:
        page = fh.read()
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:                         # prima un file a parte: se si interrompe,
        fh.write(page.replace("__DATA__", blob))                          # l'app di prima resta intera
    os.replace(tmp, out)
    return out


INIZIO_DATI = '<script type="application/json" id="data">'


def dati_di(path):
    """I dati incorporati in un'app già generata, o None se il file non c'è o non si legge."""
    try:
        with open(path, encoding="utf-8") as fh:
            page = fh.read()
        a = page.index(INIZIO_DATI) + len(INIZIO_DATI)
        return json.loads(page[a:page.index("</script>", a)].replace("<\\/", "</"))
    except (OSError, ValueError):
        return None


def leggero(out, log=print):
    """Aggiornamento leggero, per il controllo di ogni ora: rifà solo i dati crypto intraday (candele orarie e ordini
    di adesso) e le operazioni delle due reti neurali (crypto e azioni italiane) sull'ultima app generata, senza
    riscaricare i dieci anni di prezzi del resto. Ritorna 0 se ha
    riscritto l'app, 1 se manca un'app da cui partire o i dati crypto non ci sono (serve allora l'aggiornamento completo)."""
    data = dati_di(out)
    if not data:
        log("[app] manca un'app da cui partire: serve l'aggiornamento completo")
        return 1
    nuovo = crypto_intraday(log, leggero=data.get("intraday") or {})
    if not nuovo or not nuovo.get("ore"):
        log("[app] dati crypto non disponibili: serve l'aggiornamento completo")
        return 1
    data["intraday"] = nuovo
    data["rete"] = rete_per_app() or data.get("rete")                     # i risultati della rete, se sono stati rifatti
    data["rete_robot"] = rete_robot_app(log) or data.get("rete_robot")    # le operazioni della rete per il robot
    data["rete_ita"] = rete_ita_app(log) or data.get("rete_ita")          # la rete delle azioni italiane
    data["sentimento"] = sentimento(log) or data.get("sentimento")
    data["regole_libri"] = load_json(os.path.join(ROOT, "regole_libri.json")) or data.get("regole_libri")
    data["segnali_fonti"] = fonti_segnali() or data.get("segnali_fonti")
    data["rete_ita_robot"] = rete_ita_robot_app(log) or data.get("rete_ita_robot")
    data["rete_usa"] = rete_usa_app(log) or data.get("rete_usa")          # la rete delle azioni USA
    data["rete_usa_robot"] = rete_usa_robot_app(log) or data.get("rete_usa_robot")
    data["rete_lungo"] = rete_lungo_app(log) or data.get("rete_lungo")    # medio e lungo periodo
    data["segnali_robot"] = segnali_robot_app(log) or data.get("segnali_robot")   # crypto: ordini sui segnali
    data["crypto_tendenza"] = tendenza_app(log) or data.get("crypto_tendenza")    # crypto: tendenza come i fondi
    data["strategie_lungo"] = strategie_lungo_app(log) or data.get("strategie_lungo")   # ETF e azioni: le regole dei libri
    build(data, out)
    log("[app] scritta %s (%d KB), solo crypto e reti neurali aggiornate" % (os.path.relpath(out, ROOT), os.path.getsize(out) // 1024))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--asof", help="usa solo i dati fino a questa data (YYYY-MM-DD)")
    ap.add_argument("--out", default=os.path.join(TRADER, "app.html"))
    ap.add_argument("--leggero", action="store_true",
                    help="aggiorna solo le crypto intraday dall'ultima app generata (qualche secondo, per ogni ora)")
    a = ap.parse_args(argv)
    os.makedirs(TRADER, exist_ok=True)
    if a.leggero:
        return leggero(a.out)
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
    data = {"mercati": mercati, "daytrade": day_trade(), "simula": simulazioni(mercati),
            "calendari": calendari(), "cambio": cambio(), "intraday": crypto_intraday(), "rete": rete_per_app(), "rete_robot": rete_robot_app(),
            "rete_ita": rete_ita_app(), "rete_ita_robot": rete_ita_robot_app(),
            "rete_usa": rete_usa_app(), "rete_usa_robot": rete_usa_robot_app(), "rete_lungo": rete_lungo_app(),
            "segnali_robot": segnali_robot_app(), "crypto_tendenza": tendenza_app(), "strategie_lungo": strategie_lungo_app(),
            "sentimento": sentimento(), "segnali_fonti": fonti_segnali(),
            "regole_libri": load_json(os.path.join(ROOT, "regole_libri.json")),
            "verifica25": load_json(os.path.join(ROOT, "verifica.json")),
            "libri": load_json(os.path.join(ROOT, "libri.json")),
            "giornata": piano_giornata(),
            "crypto_lungo": crypto_lungo_termine(),
            "aggiornato": settimana.now_in("Europe/Rome").strftime("%Y-%m-%d %H:%M")}
    out = build(data, a.out)
    print("[app] scritta %s (%d KB)" % (os.path.relpath(out, ROOT), os.path.getsize(out) // 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
