#!/usr/bin/env python3
"""La rete neurale dal vivo: guarda le 12 crypto ogni secondo, decide ogni minuto, impara ogni giorno. Conto finto.

    python3 rete_live.py                 # apre http://127.0.0.1:8766 nel browser, con i costi dell'app (0,2 % per lato)
    python3 rete_live.py --costo 0.0005  # lo stesso, in un mondo con costi più bassi (il modello è quello addestrato lì)
    python3 rete_live.py --margine 0.001 # la fa comprare anche se la verifica non le dà il via libera (per vedere come impara)
    python3 rete_live.py --terminale     # solo nel terminale
    python3 rete_live.py --senza-impara  # non riaddestra la rete con i dati nuovi

Serve prima `python3 rete_dati.py` (gli scambi di Kraken) e `python3 rete.py --studia` (la rete, rete_modello.json).

Cosa fa, e a che ritmo:
  - ogni secondo: il prezzo di tutte e 12 le crypto da Kraken (una richiesta); con quello controlla ogni posizione
    aperta (protezione sotto il prezzo di entrata, scadenza dell'orizzonte scelto) e aggiorna il conto;
  - ogni minuto: riguarda ogni crypto con gli stessi 36 numeri dell'addestramento (rendimenti, volatilità, flusso di
    acquisti e vendite, ora e giorno: solo passato) e la rete dà un valore a ogni mossa (aspettare o comprare e
    tenere da 1 minuto a 2 giorni), costi e occasioni future comprese. Compra solo se la mossa migliore batte
    l'attesa del margine scelto in addestramento; i suoi 36 numeri cambiano al più una volta al minuto, quindi decidere più spesso non darebbe
    informazione in più;
  - ogni giorno: scarica gli scambi nuovi e riaddestra la rete (la scelta sull'ultimo mese, lo stesso cancello della
    verifica: se non c'è un guadagno credibile resta fuori), tenendo il registro delle versioni;
  - gli scambi (e il verso, acquisto o vendita) si leggono a rotazione, una crypto al secondo.
Con i costi di oggi la rete di solito resta fuori: lo vedi dal vantaggio di comprare sull'attesa, sempre negativo.
Nella verifica del 19 novembre 2026 nessun modello ha passato il cancello, quindi di serie non compra mai; con --margine
la costringi a comprare quando la mossa migliore batte l'attesa di quel margine, per vedere cosa farebbe (e cosa perde).

Registro in trader/rete_esperienza.json (decisioni riassunte, operazioni, versioni). La pagina è servita solo su
127.0.0.1. Solo numpy e la libreria standard. Non è consulenza finanziaria: il conto è finto, nessun ordine parte.
"""

import argparse
import datetime
import json
import math
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

import crypto_live
import rete
import rete_dati

ROOT = os.path.dirname(os.path.abspath(__file__))
REGISTRO = os.path.join(ROOT, "trader", "rete_esperienza.json")
CAPITALE = 10000.0
GIORNI_STORIA = 9                                          # giorni di scambi tenuti in memoria (servono 7 più 1 ora)
NOMI = crypto_live.NOMI


def ora_utc(t=None):
    return datetime.datetime.fromtimestamp(time.time() if t is None else t, datetime.timezone.utc).strftime("%H:%M:%S")


def con_margine(modello, margine):
    """Lo stesso modello, ma costretto a comprare quando la mossa migliore batte l'attesa di `margine` (in frazioni),
    anche se la verifica non gli ha dato il via libera. None: il modello com'è."""
    if margine is None:
        return modello
    return dict(modello, margine=float(margine), fuori=False, imposto=True)


# ---------------------------------------------------------------- il conto finto

class Conto:
    """Un conto finto: una posizione alla volta per crypto, ognuna con 1/N del capitale. I costi sono quelli dell'app:
    si compra con quota x (1 - costo) / prezzo e si incassa quantità x prezzo x (1 - costo)."""

    def __init__(self, simboli, costo=rete.COSTO, capitale=CAPITALE):
        self.simboli, self.costo, self.capitale = list(simboli), costo, capitale
        self.quota = capitale / len(self.simboli)
        self.cassa, self.posizioni, self.operazioni = capitale, {}, []

    def compra(self, sym, prezzo, t, minuti, protezione):
        """Apre una posizione se la crypto è libera e c'è cassa. Ritorna la posizione o None."""
        if sym in self.posizioni or self.cassa < self.quota - 1e-9 or prezzo <= 0:
            return None
        self.cassa -= self.quota
        p = {"sym": sym, "entrata": prezzo, "quando": t, "minuti": int(minuti), "scade": t + 60.0 * minuti,
             "protezione": protezione, "qty": self.quota * (1 - self.costo) / prezzo, "speso": self.quota}
        self.posizioni[sym] = p
        return p

    def vendi(self, sym, prezzo, t, motivo):
        p = self.posizioni.pop(sym, None)
        if p is None:
            return None
        incasso = p["qty"] * prezzo * (1 - self.costo)
        self.cassa += incasso
        op = {"sym": sym, "entrata": p["entrata"], "uscita": prezzo, "quando": p["quando"], "chiusura": t, "minuti": p["minuti"],
              "motivo": motivo, "r": incasso / p["speso"] - 1}
        self.operazioni.append(op)
        return op

    def controlla(self, sym, prezzo, t):
        """Protezione o scadenza di una posizione, al prezzo di adesso. Ritorna l'operazione chiusa o None."""
        p = self.posizioni.get(sym)
        if p is None:
            return None
        if prezzo <= p["protezione"]:
            return self.vendi(sym, min(prezzo, p["protezione"]) * (1 - rete.SLIP_STOP), t, "protezione")
        if t >= p["scade"]:
            return self.vendi(sym, prezzo, t, "scadenza")
        return None

    def valore(self, prezzi):
        return self.cassa + sum(p["qty"] * prezzi.get(s, p["entrata"]) * (1 - self.costo) for s, p in self.posizioni.items())


# ---------------------------------------------------------------- gli scambi e le barre

class Storia:
    """Gli scambi recenti di ogni crypto (dalla cache di rete_dati.py e da Kraken, fino a adesso) e le barre da un minuto
    che se ne ricavano, sulla stessa griglia per tutte le crypto."""

    def __init__(self, simboli=None, giorni=GIORNI_STORIA):
        self.simboli, self.giorni = list(simboli or rete_dati.COPPIE), giorni
        self.t = {s: np.zeros(0) for s in self.simboli}
        self.p = {s: np.zeros(0) for s in self.simboli}
        self.v = {s: np.zeros(0) for s in self.simboli}
        self.sd = {s: np.zeros(0, dtype=np.int8) for s in self.simboli}
        self.cursore = {}
        self.lock = threading.Lock()
        self.ritmo = rete_dati.Ritmo(3.0, 4.0)

    def carica(self, log=print):
        """Gli ultimi `giorni` giorni: quelli completi dalla cache (scaricando quelli che mancano), poi oggi da Kraken."""
        rete_dati.scarica(self.giorni, self.simboli, fili=3, log=log)
        oggi = datetime.datetime.now(datetime.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        for s in self.simboli:
            g = rete.giorni_continui(s)[-(self.giorni - 1):]
            t, p, v, sd = rete.carica_scambi(s, g) if g else (np.zeros(0), np.zeros(0), np.zeros(0), np.zeros(0, np.int8))
            ti, pi, vi, si, cur = rete_dati.scarica_da(s, oggi - 1, self.ritmo)
            with self.lock:
                self.t[s], self.p[s] = np.concatenate([t, ti]), np.concatenate([p, pi])
                self.v[s], self.sd[s] = np.concatenate([v, vi]), np.concatenate([sd, si])
                self.cursore[s] = cur

    def aggiorna(self, sym):
        """Gli scambi nuovi di una crypto, da dove si era arrivati."""
        ti, pi, vi, si, cur = rete_dati.scarica_da(sym, self.t[sym][-1] if len(self.t[sym]) else time.time() - 3600,
                                                    self.ritmo, self.cursore.get(sym))
        if len(ti) == 0:
            self.cursore[sym] = cur
            return 0
        with self.lock:
            nuovo = ti > self.t[sym][-1] if len(self.t[sym]) else np.ones(len(ti), bool)
            self.t[sym] = np.concatenate([self.t[sym], ti[nuovo]])
            self.p[sym] = np.concatenate([self.p[sym], pi[nuovo]])
            self.v[sym] = np.concatenate([self.v[sym], vi[nuovo]])
            self.sd[sym] = np.concatenate([self.sd[sym], si[nuovo]])
            self.cursore[sym] = cur
        return int(nuovo.sum())

    def mondo(self, adesso=None):
        """Le barre da un minuto fino al minuto in corso (compreso: le caratteristiche lo ignorano). Ritorna (Mondo, k):
        k è l'indice del minuto in corso, cioè dove si decide adesso."""
        adesso = time.time() if adesso is None else adesso
        k_assoluto = int(adesso // 60)
        t0 = float((k_assoluto // 1440 - self.giorni + 1) * 1440 * 60)      # mezzanotte UTC di `giorni - 1` giorni fa
        n = k_assoluto - int(t0 // 60) + 1
        with self.lock:
            B = [rete.barre((self.t[s], self.p[s], self.v[s], self.sd[s]), t0, n) for s in self.simboli]
        return rete.Mondo(self.simboli, t0, B), n - 1


# ---------------------------------------------------------------- l'agente

class Agente:
    """Il modello e il conto: ogni minuto decide, ogni secondo gestisce quello che è aperto."""

    def __init__(self, modello, costo, simboli=None):
        self.modello, self.costo = modello, costo
        self.simboli = list(simboli or rete_dati.COPPIE)
        self.conto = Conto(self.simboli, costo)
        self.vista = {}                                        # l'ultima valutazione di ogni crypto, per la pagina
        self.ultimo_minuto = None
        self.n_decisioni = 0
        self.eventi = []

    def decidi(self, M, k, prezzi, t):
        """Una decisione, per tutte le crypto, con le barre fino al minuto k (non compreso). Apre le posizioni che la
        politica dice di aprire, al prezzo di adesso. Ritorna le operazioni aperte."""
        Q, sig = rete.valori_a(self.modello, M, k)
        az = rete.politica(Q[None], self.modello["margine"], self.modello.get("ritmo", 0.0))[0]
        aperte = []
        for i, s in enumerate(self.simboli):
            buy = Q[i, 1:]
            j = int(buy.argmax())
            self.vista[s] = {"migliore_minuti": int(rete.ORIZZONTI[j]), "valore": float(buy[j]), "attesa": float(Q[i, 0]),
                             "vantaggio": float(buy[j] - Q[i, 0]), "azione": int(az[i]),
                             "valori": [float(x) for x in buy], "sigma": float(sig[i])}
            if az[i] > 0 and s in prezzi:
                h = rete.ORIZZONTI[int(az[i]) - 1]
                stop = prezzi[s] * (1.0 - min(rete.K_STOP * sig[i] * math.sqrt(h / 60.0), 0.9))
                p = self.conto.compra(s, prezzi[s], t, h, stop)
                if p:
                    aperte.append(p)
                    self.eventi.append({"t": t, "sym": s, "evento": "compra", "prezzo": prezzi[s], "minuti": h, "protezione": stop,
                                        "vantaggio": self.vista[s]["vantaggio"]})
        self.n_decisioni += 1
        return aperte

    def passo(self, M_fn, prezzi, t):
        """Ogni secondo: gestisce le posizioni; al primo secondo (dopo i primi 5) di ogni minuto, decide."""
        chiuse = []
        for s in list(self.conto.posizioni):
            if s in prezzi:
                op = self.conto.controlla(s, prezzi[s], t)
                if op:
                    chiuse.append(op)
                    self.eventi.append({"t": t, "sym": s, "evento": "vende", "prezzo": op["uscita"], "motivo": op["motivo"], "r": op["r"]})
        minuto = int(t // 60)
        if minuto != self.ultimo_minuto and t % 60 >= 5:
            self.ultimo_minuto = minuto
            M, k = M_fn(t)
            self.decidi(M, k, prezzi, t)
        self.eventi = self.eventi[-300:]
        return chiuse


# ---------------------------------------------------------------- stato condiviso e fili

class Stato:
    def __init__(self, agente, costo):
        self.lock = threading.Lock()
        self.agente, self.costo = agente, costo
        self.margine_imposto = agente.modello["margine"] if agente.modello.get("imposto") else None
        self.prezzi, self.aperture, self.errore, self.aggiornato = {}, {}, None, None
        self.versioni = [{"t": time.time(), "fuori": agente.modello["fuori"], "iterazione": agente.modello.get("iterazione"),
                          "margine": None if math.isinf(agente.modello["margine"]) else agente.modello["margine"], "origine": "rete_modello.json"}]
        self.avviato = time.time()

    def json(self):
        with self.lock:
            a = self.agente
            pr = {s: v["prezzo"] for s, v in self.prezzi.items()}
            conto = a.conto
            return json.dumps({
                "aggiornato": self.aggiornato, "errore": self.errore, "costo": self.costo, "orizzonti": list(rete.ORIZZONTI),
                "prezzi": self.prezzi, "vista": a.vista, "nomi": NOMI,
                "posizioni": [dict(p, ora=pr.get(s, p["entrata"])) for s, p in conto.posizioni.items()],
                "operazioni": conto.operazioni[-60:][::-1], "n_operazioni": len(conto.operazioni),
                "cassa": conto.cassa, "valore": conto.valore(pr), "capitale": conto.capitale, "decisioni": a.n_decisioni,
                "eventi": a.eventi[::-1][:40], "versioni": self.versioni[::-1][:20],
                "modello": {"fuori": a.modello["fuori"], "margine": None if math.isinf(a.modello["margine"]) else a.modello["margine"],
                            "iterazione": a.modello.get("iterazione"), "imposto": bool(a.modello.get("imposto"))},
                "attivo_da": self.avviato})

    def salva(self):
        try:
            os.makedirs(os.path.dirname(REGISTRO), exist_ok=True)
            with self.lock:
                a = self.agente
                dati = {"costo": self.costo, "versioni": self.versioni, "operazioni": a.conto.operazioni[-500:],
                        "eventi": a.eventi[-100:], "valore": a.conto.valore({s: v["prezzo"] for s, v in self.prezzi.items()}),
                        "decisioni": a.n_decisioni}
            tmp = REGISTRO + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(dati, fh)
            os.replace(tmp, REGISTRO)
        except OSError:
            pass


def lettore_prezzi(stato, storia):
    """Ogni secondo: i prezzi, le posizioni, e ogni minuto la decisione."""
    while True:
        t = time.time()
        try:
            nuovi = crypto_live.leggi_kraken()
            with stato.lock:
                stato.prezzi.update(nuovi)
                stato.aggiornato, stato.errore = ora_utc(), None
                prezzi = {s: v["prezzo"] for s, v in stato.prezzi.items()}
                chiuse = stato.agente.passo(lambda tt: storia.mondo(tt), prezzi, t)
            if chiuse:
                stato.salva()
        except Exception as e:                               # rete o dati: si riprova al prossimo secondo
            with stato.lock:
                stato.errore = "Prezzi non aggiornati (%s)" % str(e)[:80]
        time.sleep(max(0.05, 1.0 - (time.time() - t)))


def lettore_scambi(stato, storia):
    """Gli scambi, una crypto al secondo a rotazione: servono per il verso (acquisto o vendita) di ogni scambio."""
    while True:
        for s in storia.simboli:
            try:
                storia.aggiorna(s)
            except Exception:
                pass
            time.sleep(1.0)


def impara(stato, costo, ogni_ore, log=print):
    """Ogni `ogni_ore` ore: riaddestra la rete con tutti i dati (scaricando quelli nuovi), la scelta sull'ultimo mese e lo
    stesso cancello della verifica. La versione nuova sostituisce la vecchia solo se non peggiora: se la vecchia comprava
    e la nuova resta fuori, o viceversa, decide il margine sull'ultimo mese; tutto finisce nel registro delle versioni."""
    while True:
        time.sleep(ogni_ore * 3600)
        try:
            rete_dati.scarica(400, log=lambda m: None)
            D = rete.Dati(rete.carica_mondo(max_giorni=300))
            m = rete.modello_finale(D, costo)
            with stato.lock:
                stato.agente.modello = con_margine({"rete": m["rete"], "media": m["media"], "dev": m["dev"], "margine": m["margine"],
                                                    "fuori": m["fuori"], "iterazione": m["iterazione"], "tipo": "q", "ritmo": 0.0},
                                                   stato.margine_imposto)
                stato.versioni.append({"t": time.time(), "fuori": m["fuori"], "iterazione": m["iterazione"],
                                       "margine": None if math.isinf(m["margine"]) else m["margine"], "origine": "riaddestrata con i dati nuovi",
                                       "giorni": int(D.giorni)})
            stato.salva()
        except Exception as e:
            log("[rete_live] riaddestramento saltato: %s" % str(e)[:100])


# ---------------------------------------------------------------- la pagina

PAGINA = r"""<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rete neurale dal vivo</title><style>
:root{--bg:#f3f5f8;--s:#fff;--s2:#edf0f5;--ink:#10151d;--ink2:#465062;--mu:#737d8f;--line:#e0e4eb;--good:#0a7a0a;--crit:#b42c2c;--goodbg:#e8f6e8;--critbg:#fbeaea;--warn:#fff6de;--acc:#2453c9;--accbg:#e8eefc}
@media (prefers-color-scheme:dark){:root{--bg:#0d1015;--s:#151920;--s2:#1c212a;--ink:#eef0f3;--ink2:#b5bcc8;--mu:#818b9a;--line:#262c37;--good:#35c435;--crit:#f07272;--goodbg:#14281a;--critbg:#301a1a;--warn:#2c2414;--acc:#6f95f2;--accbg:#18223a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;font-variant-numeric:tabular-nums}
main{max-width:1180px;margin:0 auto;padding:20px 16px 48px}h1{margin:0;font-size:24px}.sub{color:var(--ink2);margin:4px 0 0}
.bar{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin:14px 0}.dot{width:10px;height:10px;border-radius:50%;background:var(--good);display:inline-block;margin-right:6px}.dot.off{background:var(--crit)}
.card{background:var(--s);border:1px solid var(--line);border-radius:14px;padding:16px;margin-top:14px}.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th{color:var(--mu);font-size:12px;text-transform:uppercase;letter-spacing:.03em}
th.l,td.l{text-align:left}.px{font-weight:700}.up{color:var(--good)}.down{color:var(--crit)}.note{color:var(--mu);font-size:13px}
.tag{display:inline-block;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.03em;border-radius:6px;padding:0 6px;background:var(--s2);color:var(--ink2)}.tag.in{background:var(--accbg);color:var(--acc)}
.alert{background:var(--warn);border-radius:12px;padding:10px 14px;margin-top:14px;color:var(--ink2);font-size:14px}.err{color:var(--crit)}
.ev{display:flex;gap:10px;padding:5px 0;border-bottom:1px solid var(--line);font-size:14px}.ev .t{color:var(--mu);width:70px;flex:none}
</style></head><body><main>
<h1>Rete neurale dal vivo</h1><p class="sub">Prezzi in euro da Kraken ogni secondo; la rete decide ogni minuto e gestisce le posizioni ogni secondo; conto finto, nessun ordine parte.</p>
<div class="bar"><span id="st"><span class="dot"></span>collegamento…</span></div>
<div class="alert" id="mod"></div>
<div class="card"><b>Conto</b> <span id="conto" class="note"></span></div>
<div class="card scroll"><table><thead><tr><th class="l">Crypto</th><th>Prezzo</th><th class="l">Mossa migliore</th><th>Vantaggio di comprare sull'attesa</th><th class="l">Posizione</th></tr></thead><tbody id="tb"></tbody></table></div>
<div class="card"><b>Operazioni e avvisi</b><div id="evs" class="note" style="margin-top:6px">Ancora niente: la rete aspetta finché la mossa migliore non batte l'attesa del suo margine.</div></div>
<div class="card"><b>Esperienza: le versioni della rete</b><div id="ver" class="note" style="margin-top:6px"></div></div>
<p class="note">"Vantaggio di comprare sull'attesa": la differenza tra il valore della mossa migliore (comprare e tenere per quella durata) e quello di aspettare, entrambi calcolati dalla rete con i costi e le occasioni future dentro. Si compra solo se supera il margine imparato in addestramento; se non c'è un margine credibile la rete resta fuori. Non è consulenza finanziaria.</p>
</main><script>
const $ = s => document.querySelector(s);
const nf = (x, d) => Number(x).toLocaleString('it-IT', {minimumFractionDigits: d, maximumFractionDigits: d});
const dec = x => Math.abs(x) < 1 ? 5 : Math.abs(x) < 10 ? 4 : Math.abs(x) < 1000 ? 2 : 0;
const pc = (x, d = 2) => x == null ? '' : (x > 0 ? '+' : '') + nf(x * 100, d) + ' %';
const durata = m => m < 60 ? m + ' min' : m < 1440 ? (m / 60) + ' h' : (m / 1440) + ' g';
const ora = t => new Date(t * 1000).toLocaleTimeString('it-IT');
async function giro() {
  let D; try { D = await (await fetch('/dati', {cache: 'no-store'})).json(); } catch (e) { $('#st').innerHTML = '<span class="dot off"></span><span class="err">il programma non risponde: è ancora acceso?</span>'; return; }
  $('#st').innerHTML = D.errore ? `<span class="dot off"></span><span class="err">${D.errore}</span>` : `<span class="dot"></span>aggiornato alle ${D.aggiornato || '…'} · ${D.decisioni} decisioni`;
  const m = D.modello;
  $('#mod').innerHTML = `<b>Costi: ${nf(D.costo * 100, 2)} % per lato.</b> ${m.imposto ? `<b>Margine imposto a mano (${pc(m.margine)})</b>: la rete compra anche se la verifica non le ha dato il via libera. Serve a vedere come impara e cosa perde.` : m.fuori ? 'La rete, nell\'ultimo mese di scelta, non ha visto un guadagno credibile: <b>resta fuori</b>, quindi non compra mai. Guarda lo stesso e ti mostra cosa vale ogni mossa.' : `La rete compra quando la mossa migliore batte l'attesa di ${pc(m.margine)} (iterazione ${m.iterazione}).`}`;
  $('#conto').textContent = `· valore ${nf(D.valore, 2)} € su ${nf(D.capitale, 0)} · cassa ${nf(D.cassa, 2)} € · ${D.n_operazioni} operazioni chiuse`;
  $('#tb').innerHTML = Object.keys(D.nomi).map(s => { const x = D.prezzi[s], v = D.vista[s]; if (!x) return '';
    const p = D.posizioni.find(q => q.sym === s);
    const pos = p ? `<span class="tag in">dentro</span> a ${nf(p.entrata, dec(p.entrata))}, ora <b class="${p.ora >= p.entrata ? 'up' : 'down'}">${pc(p.ora / p.entrata - 1)}</b> · protezione ${nf(p.protezione, dec(p.protezione))} · fino alle ${ora(p.scade)}` : '<span class="note">libera</span>';
    return `<tr><td class="l"><b>${D.nomi[s]}</b> <span class="note">${s.replace('-EUR', '')}</span></td><td class="px">${nf(x.prezzo, dec(x.prezzo))} €</td>
      <td class="l">${v ? (v.azione ? `<b>compra e tieni ${durata(v.migliore_minuti)}</b>` : `<span class="note">aspetta (la migliore sarebbe ${durata(v.migliore_minuti)})</span>`) : '…'}</td>
      <td class="${v && v.vantaggio > 0 ? 'up' : 'down'}">${v ? pc(v.vantaggio) : ''}</td><td class="l">${pos}</td></tr>`; }).join('');
  const E = D.eventi || [];
  if (E.length) $('#evs').innerHTML = E.map(e => `<div class="ev"><span class="t">${ora(e.t)}</span><span><b>${D.nomi[e.sym] || e.sym}</b>: ${e.evento === 'compra' ? `compra a ${nf(e.prezzo, dec(e.prezzo))} € e tiene ${durata(e.minuti)} (protezione ${nf(e.protezione, dec(e.protezione))})` : `vende a ${nf(e.prezzo, dec(e.prezzo))} € per ${e.motivo}: ${pc(e.r)} con i costi`}</span></div>`).join('');
  $('#ver').innerHTML = (D.versioni || []).map(v => `<div>${new Date(v.t * 1000).toLocaleString('it-IT')} · ${v.fuori ? 'resta fuori' : 'compra (iterazione ' + v.iterazione + ', margine ' + pc(v.margine) + ')'} · ${v.origine}${v.giorni ? ', ' + v.giorni + ' giorni di dati' : ''}</div>`).join('');
}
giro(); setInterval(giro, 1000);
</script></body></html>"""


def server(stato, porta):
    class Gestore(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/dati"):
                body, tipo = stato.json().encode(), "application/json"
            elif self.path in ("/", "/index.html"):
                body, tipo = PAGINA.encode(), "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", tipo)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    return ThreadingHTTPServer(("127.0.0.1", porta), Gestore)


def terminale(stato):
    while True:
        time.sleep(1)
        with stato.lock:
            a = stato.agente
            righe = []
            for s, v in sorted(a.vista.items()):
                x = stato.prezzi.get(s)
                if x:
                    righe.append("%-9s %12s  %-22s vantaggio di comprare %+6.2f %%  %s" % (
                        NOMI[s].split()[0], "%.*f" % (5 if x["prezzo"] < 1 else 2, x["prezzo"]),
                        "COMPRA %d min" % v["migliore_minuti"] if v["azione"] else "aspetta", 100 * v["vantaggio"],
                        "DENTRO" if s in a.conto.posizioni else ""))
            msg = "\033[H\033[J%s · conto %.2f € · %d operazioni · %s\n%s" % (
                ora_utc(), a.conto.valore({s: v["prezzo"] for s, v in stato.prezzi.items()}), len(a.conto.operazioni),
                stato.errore or "ok", "\n".join(righe))
        print(msg, flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--costo", type=float, default=None, help="costo per lato del modello (default: quello più alto, 0,2 %%)")
    ap.add_argument("--margine", type=float, default=None,
                    help="costringe la rete a comprare quando la mossa migliore batte l'attesa di questo margine (es. 0.001 = 0,1 %%)")
    ap.add_argument("--porta", type=int, default=8766)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--terminale", action="store_true")
    ap.add_argument("--senza-impara", action="store_true", help="non riaddestrare la rete con i dati nuovi")
    ap.add_argument("--impara-ogni", type=float, default=24.0, help="ore tra un riaddestramento e l'altro")
    a = ap.parse_args(argv)
    try:
        modello, costo = rete.carica_modello(a.costo)
    except (OSError, ValueError) as e:
        print("[rete_live] %s" % e)
        return 1
    modello = con_margine(modello, a.margine)
    print("[rete_live] modello a costi %.2f %% per lato: %s" % (100 * costo, "resta fuori" if modello["fuori"] else "margine %g%s" % (
        modello["margine"], " (imposto a mano)" if modello.get("imposto") else "")))
    storia = Storia()
    print("[rete_live] carico gli scambi recenti (scarica quelli che mancano)…")
    storia.carica(log=lambda m: None)
    stato = Stato(Agente(modello, costo), costo)
    for f, args in ((lettore_prezzi, (stato, storia)), (lettore_scambi, (stato, storia))):
        threading.Thread(target=f, args=args, daemon=True).start()
    if not a.senza_impara:
        threading.Thread(target=impara, args=(stato, costo, a.impara_ogni), daemon=True).start()
    if a.terminale:
        try:
            terminale(stato)
        except KeyboardInterrupt:
            pass
        return 0
    srv = server(stato, a.porta)
    url = "http://127.0.0.1:%d" % a.porta
    print("[rete_live] la rete dal vivo: %s · Ctrl+C per fermare" % url)
    if not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    stato.salva()
    return 0


if __name__ == "__main__":
    sys.exit(main())
