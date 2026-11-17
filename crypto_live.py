#!/usr/bin/env python3
"""Crypto in tempo reale: prezzi ogni secondo, livelli dei piani intraday e avvisi.

    python3 crypto_live.py                # apre http://127.0.0.1:8765 nel browser
    python3 crypto_live.py --terminale    # stampa i prezzi nel terminale ogni secondo
    python3 crypto_live.py --porta 9000 --no-browser

Gira sul TUO computer: l'app pubblicata su Claude non può collegarsi alle borse (il sistema delle
app blocca ogni collegamento a siti esterni), quindi il tempo reale passa da qui.

  prezzi    Kraken, dati pubblici gratuiti (api.kraken.com), una richiesta al secondo per tutte e
            12 le crypto in euro; se Kraken chiede di rallentare, aspetta e riprova da solo
  piani     i due piani intraday dell'app (compra il ribasso, compra la rottura), ricalcolati ogni
            ora dalle candele orarie di Yahoo Finance (intraday.py), con la loro verifica di 2 anni
  avvisi    quando il prezzo tocca un'entrata, una protezione o un obiettivo: la riga si colora,
            compare nell'elenco degli avvisi e, se lo permetti, suona e manda una notifica

La pagina è servita solo su 127.0.0.1 (non è raggiungibile da altri computer).
Solo libreria standard, Python 3.8+. Non è consulenza finanziaria: nella verifica di 2 anni,
con i costi, nessuna regola intraday ha guadagnato in media.
"""

import argparse
import datetime
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import intraday
import simula

UA = "Mozilla/5.0 (compatible; finanza/1.0)"
KRAKEN = "https://api.kraken.com/0/public/Ticker?pair="
# simbolo dell'app -> (coppia da chiedere a Kraken, chiave nella risposta)
COPPIE = {
    "BTC-EUR": ("XBTEUR", "XXBTZEUR"), "ETH-EUR": ("ETHEUR", "XETHZEUR"), "SOL-EUR": ("SOLEUR", "SOLEUR"),
    "XRP-EUR": ("XRPEUR", "XXRPZEUR"), "BNB-EUR": ("BNBEUR", "BNBEUR"), "ADA-EUR": ("ADAEUR", "ADAEUR"),
    "DOGE-EUR": ("DOGEEUR", "XDGEUR"), "LTC-EUR": ("LTCEUR", "XLTCZEUR"), "DOT-EUR": ("DOTEUR", "DOTEUR"),
    "LINK-EUR": ("LINKEUR", "LINKEUR"), "AVAX-EUR": ("AVAXEUR", "AVAXEUR"), "TRX-EUR": ("TRXEUR", "TRXEUR"),
}
NOMI = {"BTC-EUR": "Bitcoin", "ETH-EUR": "Ethereum", "SOL-EUR": "Solana", "XRP-EUR": "XRP", "BNB-EUR": "BNB",
        "ADA-EUR": "Cardano", "DOGE-EUR": "Dogecoin", "LTC-EUR": "Litecoin", "DOT-EUR": "Polkadot",
        "LINK-EUR": "Chainlink", "AVAX-EUR": "Avalanche", "TRX-EUR": "TRON"}


def ora():
    return datetime.datetime.now().strftime("%H:%M:%S")


def adesso():
    return datetime.datetime.now(datetime.timezone.utc)


def da_utc(s):
    return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M UTC").replace(tzinfo=datetime.timezone.utc)


def leggi_kraken(timeout=5):
    """Ultimo prezzo, apertura del giorno (UTC), massimo e minimo 24 ore, per tutte le coppie."""
    url = KRAKEN + ",".join(p for p, _ in COPPIE.values())
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    if d.get("error"):
        raise RuntimeError("; ".join(d["error"]))
    res, out = d.get("result", {}), {}
    for sym, (pair, key) in COPPIE.items():
        v = res.get(key) or res.get(pair)
        if v:
            out[sym] = {"prezzo": float(v["c"][0]), "apertura": float(v["o"]), "max24": float(v["h"][1]),
                        "min24": float(v["l"][1])}
    return out


CHIUSO = ("obiettivo", "protezione", "scaduto", "scaduto_dentro")
PASSO = {"attesa": 0, "dentro": 1, "obiettivo": 2, "protezione": 2, "scaduto": 2, "scaduto_dentro": 2}


def avanza(p, prezzo, quando):
    """Fa avanzare un piano (ribasso o rottura) al prezzo di adesso, come la verifica: prima l'entrata,
    poi protezione, obiettivo o scadenza. Ritorna gli eventi nuovi: entrata, protezione, obiettivo, scadenza."""
    eventi, fine = [], da_utc(p["fino"])
    if p["fase"] == "attesa":
        if quando >= fine:
            p["fase"] = "scaduto"                            # l'ordine non è scattato: nessuna operazione
            return eventi
        if (prezzo <= p["entrata"]) if p["regola"] == "ribasso" else (prezzo >= p["entrata"]):
            fill = min(p["entrata"], prezzo) if p["regola"] == "ribasso" else max(p["entrata"], prezzo)
            p.update(fase="dentro", prezzo_entrata=fill, quando=intraday.utc(quando))
            eventi.append("entrata")
    if p["fase"] == "dentro":
        uscita = None
        if prezzo <= p["protezione"]:
            p["fase"], uscita = "protezione", p["protezione"]
        elif prezzo >= p["obiettivo"]:
            p["fase"], uscita = "obiettivo", p["obiettivo"]
        elif quando >= fine:
            p["fase"], uscita = "scaduto_dentro", prezzo
        if uscita is not None:
            p.update(chiusura=intraday.utc(quando),
                     rendimento=round(uscita / p["prezzo_entrata"] - 1 - 2 * intraday.COSTO, 6))
            eventi.append("scadenza" if p["fase"] == "scaduto_dentro" else p["fase"])
    return eventi


def da_seguire(crypto):
    """I piani ribasso e rottura da seguire: quello in corso e quello precedente, finché valgono."""
    out = {}
    for sym, x in crypto.items():
        if sym not in COPPIE:
            continue
        for r in ("ribasso", "rottura"):
            out[(sym, r, x["ora"])] = dict(x["piani"][r], sym=sym, regola=r, ora=x["ora"], fino=x["fino"], attuale=True)
        for p in x.get("precedenti", []):
            out[(sym, p["regola"], p["ora"])] = dict(p, sym=sym, attuale=False)
    return out


class Stato:
    """Prezzi, piani e avvisi condivisi tra il lettore e la pagina."""

    def __init__(self):
        self.lock = threading.Lock()
        self.prezzi, self.piani, self.verifica, self.seguiti = {}, {}, {}, {}
        self.eventi, self.n_eventi = [], 0
        self.aggiornato, self.errore, self.piani_ora = None, None, None

    def unisci(self, crypto, verifica):
        """Nuovi piani dalle candele orarie. Di uno stesso piano tiene la fase più avanti tra quella
        vista dal vivo e quella rigiocata sulle candele. Al primo calcolo, i livelli già superati
        prima dell'avvio non fanno avviso: la tabella li mostra comunque."""
        nuovi, primo = da_seguire(crypto), not self.seguiti
        for k, p in nuovi.items():
            vecchio = self.seguiti.get(k)
            if vecchio is not None and PASSO[vecchio["fase"]] >= PASSO[p["fase"]]:
                vecchio["attuale"] = p["attuale"]
                nuovi[k] = vecchio
            else:
                if vecchio is not None and vecchio["fase"] == "dentro" and p["fase"] in CHIUSO:
                    self.avviso(p, p["fase"] if p["fase"] != "scaduto_dentro" else "scadenza", None, "candele orarie")
                p["silenzio"] = primo
        self.seguiti = nuovi
        self.piani = {s: {k: x[k] for k in ("ora", "fino", "storia", "prezzo", "prezzo_ora")}
                      for s, x in crypto.items() if s in COPPIE}
        self.verifica = verifica
        self.piani_ora = ora()

    def aggiorna_piani(self):
        r = intraday.analizza(log=lambda m: None, max_age=600)
        with self.lock:
            self.unisci(r["crypto"], r["verifica"])

    def avviso(self, p, evento, prezzo, fonte="Kraken"):
        valore = {"entrata": p.get("prezzo_entrata"), "protezione": p["protezione"], "obiettivo": p["obiettivo"],
                  "scadenza": prezzo}[evento]
        self.eventi.append({"ora": ora(), "sym": p["sym"], "nome": NOMI[p["sym"]], "regola": p["regola"],
                            "piano": p["ora"], "evento": evento, "valore": valore, "prezzo": prezzo,
                            "rendimento": p.get("rendimento"), "protezione": p["protezione"],
                            "obiettivo": p["obiettivo"], "fonte": fonte})
        self.eventi, self.n_eventi = self.eventi[-200:], self.n_eventi + 1

    def controlla_livelli(self, sym, prezzo, quando=None):
        quando = quando or adesso()
        for p in self.seguiti.values():
            if p["sym"] != sym:
                continue
            eventi, zitto = avanza(p, prezzo, quando), p.pop("silenzio", False)
            for e in eventi:
                if not zitto:
                    self.avviso(p, e, prezzo)

    def leggi(self):
        nuovi = leggi_kraken()
        with self.lock:
            for sym, v in nuovi.items():
                vecchio = self.prezzi.get(sym, {}).get("prezzo")
                v["direzione"] = 0 if vecchio is None or vecchio == v["prezzo"] else (1 if v["prezzo"] > vecchio else -1)
                self.prezzi[sym] = v
                self.controlla_livelli(sym, v["prezzo"])
            self.aggiornato, self.errore = ora(), None

    def json(self):
        with self.lock:
            seguiti = [{k: v for k, v in p.items() if k != "silenzio"} for p in self.seguiti.values()]
            return json.dumps({"aggiornato": self.aggiornato, "errore": self.errore, "prezzi": self.prezzi,
                               "piani": self.piani, "seguiti": seguiti, "verifica": self.verifica,
                               "piani_ora": self.piani_ora, "eventi": self.eventi[::-1], "n_eventi": self.n_eventi,
                               "nomi": NOMI})


def lettore(stato, ogni=1.0):
    attesa = ogni
    while True:
        t0 = time.time()
        try:
            stato.leggi()
            attesa = ogni
        except (urllib.error.URLError, OSError, ValueError, RuntimeError) as e:
            with stato.lock:
                stato.errore = "Kraken non risponde (%s): riprovo tra %d s" % (str(e)[:80], min(30, attesa * 2))
            attesa = min(30, attesa * 2)                     # rallenta se Kraken chiede di aspettare
        time.sleep(max(0.0, attesa - (time.time() - t0)))


def pianificatore(stato):
    """Ricalcola i piani poco dopo ogni ora, quando Yahoo ha chiuso la candela oraria."""
    while True:
        try:
            stato.aggiorna_piani()
        except Exception as e:                               # rete o dati: i prezzi continuano lo stesso
            with stato.lock:
                stato.errore = "Piani non aggiornati (%s)" % str(e)[:80]
        t = time.time()
        time.sleep(3600 - t % 3600 + 150)


PAGINA = r"""<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Crypto dal vivo</title><style>
:root{--bg:#f3f5f8;--s:#fff;--s2:#edf0f5;--ink:#10151d;--ink2:#465062;--mu:#737d8f;--line:#e0e4eb;--good:#0a7a0a;--crit:#b42c2c;--goodbg:#e8f6e8;--critbg:#fbeaea;--warn:#fff6de;--acc:#2453c9;--accbg:#e8eefc}
@media (prefers-color-scheme:dark){:root{--bg:#0d1015;--s:#151920;--s2:#1c212a;--ink:#eef0f3;--ink2:#b5bcc8;--mu:#818b9a;--line:#262c37;--good:#35c435;--crit:#f07272;--goodbg:#14281a;--critbg:#301a1a;--warn:#2c2414;--acc:#6f95f2;--accbg:#18223a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;font-variant-numeric:tabular-nums}
main{max-width:1180px;margin:0 auto;padding:20px 16px 48px}h1{margin:0;font-size:24px}.sub{color:var(--ink2);margin:4px 0 0}
.bar{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin:14px 0}.dot{width:10px;height:10px;border-radius:50%;background:var(--good);display:inline-block;margin-right:6px}
.dot.off{background:var(--crit)}button{font:inherit;border:1px solid var(--line);background:var(--s);color:var(--ink);border-radius:999px;padding:5px 14px;cursor:pointer}
.card{background:var(--s);border:1px solid var(--line);border-radius:14px;padding:16px;margin-top:14px}.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap;vertical-align:top}th{color:var(--mu);font-size:12px;text-transform:uppercase;letter-spacing:.03em}
th.l,td.l{text-align:left}.ph,.og .note{display:none}.px{font-weight:700;font-size:16px;transition:background .3s}.up{color:var(--good)}.down{color:var(--crit)}.flashu{background:var(--goodbg)}.flashd{background:var(--critbg)}
.lv{font-size:13px;color:var(--ink2)}.lv b{color:var(--ink)}.note{color:var(--mu);font-size:13px}
.tag{display:inline-block;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.03em;border-radius:6px;padding:0 6px;margin-right:4px;background:var(--s2);color:var(--ink2)}
.tag.in{background:var(--accbg);color:var(--acc)}.tag.ok{background:var(--goodbg);color:var(--good)}.tag.ko{background:var(--critbg);color:var(--crit)}
.prev{margin-top:6px;padding-top:6px;border-top:1px dashed var(--line)}
.ev{display:flex;gap:10px;padding:6px 0;border-bottom:1px solid var(--line);font-size:14px;white-space:normal}.ev .t{color:var(--mu);width:70px;flex:none}
.alert{background:var(--warn);border-radius:12px;padding:10px 14px;margin-top:14px;color:var(--ink2);font-size:14px}.err{color:var(--crit)}
@media (max-width:720px){.tbl thead{display:none}.tbl tr{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 10px;padding:10px 0;border-bottom:1px solid var(--line)}
.tbl td{border:0;padding:2px 0;white-space:normal}.tbl td.og{text-align:left}.tbl td.pi{grid-column:1/-1;text-align:left;margin-top:6px}
.ph,.og .note{display:none}.tbl .ph,.tbl .og .note{display:inline}.tbl td.pi::before{content:attr(data-k);display:block;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.03em;color:var(--mu)}}
</style></head><body><main>
<h1>Crypto dal vivo</h1><p class="sub">Prezzi in euro da Kraken, aggiornati ogni secondo. Per ogni crypto i due piani intraday dell'app, validi 24 ore: a che punto sono (in attesa, dentro, chiusi) e un avviso quando scatta l'entrata, la protezione, l'obiettivo o la scadenza.</p>
<div class="bar"><span id="st"><span class="dot"></span>collegamento…</span><button id="perm" type="button">Attiva suono e notifiche</button></div>
<p class="sub" id="pi"></p>
<div class="alert" id="ver"></div>
<div class="card scroll"><table class="tbl"><thead><tr><th class="l">Crypto</th><th>Prezzo</th><th>Oggi</th><th>24 ore min / max</th><th class="l">Compra il ribasso</th><th class="l">Compra la rottura</th></tr></thead><tbody id="tb"></tbody></table></div>
<div class="card"><b>Avvisi</b><div id="evs" class="note" style="margin-top:6px">Ancora nessun avviso. I livelli già superati prima dell'avvio non fanno avviso: li vedi nella tabella.</div></div>
<p class="note">"Oggi" è la variazione dalla mezzanotte UTC (l'una di notte in Italia). I livelli nascono dalle candele orarie di Yahoo Finance, i prezzi dal vivo vengono da Kraken: possono differire di qualche decimo di punto. Risultati con i costi (0,2 % per lato). Non è consulenza finanziaria: gli ordini veri si mettono dalla tua piattaforma, questa pagina non compra e non vende nulla.</p>
</main><script>
const $ = s => document.querySelector(s);
const dec = x => Math.abs(x) < 1 ? 5 : Math.abs(x) < 10 ? 4 : Math.abs(x) < 1000 ? 2 : 0;
const nf = (x, d) => Number(x).toLocaleString('it-IT', {minimumFractionDigits: d, maximumFractionDigits: d});
const f = x => x == null ? '' : nf(x, dec(x)) + ' €';
const pc = x => x == null ? '' : (x > 0 ? '+' : '') + nf(x * 100, 2) + ' %';
const hm = s => { const d = new Date(s.replace(' UTC', 'Z').replace(' ', 'T')), oggi = new Date().toDateString() === d.toDateString();
  return d.toLocaleString('it-IT', oggi ? {hour: '2-digit', minute: '2-digit'} : {weekday: 'short', hour: '2-digit', minute: '2-digit'}); };
const hh = h => { const d = new Date(); d.setUTCHours(h, 0, 0, 0); return d.toLocaleTimeString('it-IT', {hour: '2-digit', minute: '2-digit'}); };
const COSTO = 0.002;
let suono = false, visti = null, ctx = null;
$('#perm').onclick = async () => { suono = true; try { ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) {}
  try { if ('Notification' in window) await Notification.requestPermission(); } catch (e) {} $('#perm').textContent = 'Suono e notifiche attivi'; };
function bip() { if (!ctx) return; const o = ctx.createOscillator(), g = ctx.createGain(); o.connect(g); g.connect(ctx.destination); o.frequency.value = 880; g.gain.value = .08; o.start(); o.stop(ctx.currentTime + .25); }
function cella(p, q) {
  const lv = (d) => `<span class="down">prot. ${f(p.protezione)}${d ? ' (' + pc(p.protezione / q - 1) + ')' : ''}</span> · <span class="up">obiett. ${f(p.obiettivo)}${d ? ' (' + pc(p.obiettivo / q - 1) + ')' : ''}</span>`;
  if (p.fase === 'attesa') return `<span class="lv"><span class="tag">in attesa</span>${p.regola === 'ribasso' ? 'compra a' : 'compra sopra'} <b>${f(p.entrata)}</b> <span class="note">(manca ${pc(p.entrata / q - 1)})</span><br>poi ${lv(false)}</span>`;
  if (p.fase === 'dentro') { const r = q / p.prezzo_entrata - 1 - 2 * COSTO;
    return `<span class="lv"><span class="tag in">dentro</span>a <b>${f(p.prezzo_entrata)}</b> dalle ${hm(p.quando)} · ora <b class="${r >= 0 ? 'up' : 'down'}">${pc(r)}</b><br>${lv(true)}</span>`; }
  if (p.fase === 'obiettivo') return `<span class="lv"><span class="tag ok">chiuso</span>obiettivo raggiunto alle ${hm(p.chiusura)}: <b class="up">${pc(p.rendimento)}</b><br><span class="note">entrata ${f(p.prezzo_entrata)}</span></span>`;
  if (p.fase === 'protezione') return `<span class="lv"><span class="tag ko">chiuso</span>protezione toccata alle ${hm(p.chiusura)}: <b class="down">${pc(p.rendimento)}</b><br><span class="note">entrata ${f(p.prezzo_entrata)}</span></span>`;
  if (p.fase === 'scaduto_dentro') return `<span class="lv"><span class="tag">scaduto</span>24 ore passate, si vende: <b class="${p.rendimento >= 0 ? 'up' : 'down'}">${pc(p.rendimento)}</b></span>`;
  return `<span class="lv note"><span class="tag">scaduto</span>l'ordine non è scattato: nessuna operazione</span>`;
}
function testo(e) {
  const R = `<b>${e.nome}</b>, ${e.regola === 'ribasso' ? 'compra il ribasso' : 'compra la rottura'} (piano delle ${hm(e.piano)}): `;
  const fonte = e.fonte === 'Kraken' ? '' : ' <span class="note">(visto sulle candele orarie)</span>';
  if (e.evento === 'entrata') return R + `<b>entrata</b> a ${f(e.valore)}. Ora protezione ${f(e.protezione)} e obiettivo ${f(e.obiettivo)}.` + fonte;
  if (e.evento === 'obiettivo') return R + `<b>obiettivo</b> raggiunto a ${f(e.valore)}: vendi. Risultato ${pc(e.rendimento)} con i costi.` + fonte;
  if (e.evento === 'protezione') return R + `<b>protezione</b> toccata a ${f(e.valore)}: vendi. Risultato ${pc(e.rendimento)} con i costi.` + fonte;
  return R + `<b>24 ore passate</b>: vendi${e.prezzo ? ' a circa ' + f(e.prezzo) : ''}. Risultato ${pc(e.rendimento)} con i costi.` + fonte;
}
const titolo = e => `${e.nome}: ${{entrata: 'entrata', obiettivo: 'obiettivo raggiunto', protezione: 'protezione toccata', scadenza: 'piano scaduto, vendi'}[e.evento]}`;
async function giro() {
  let D; try { D = await (await fetch('/dati', {cache: 'no-store'})).json(); } catch (e) { $('#st').innerHTML = '<span class="dot off"></span><span class="err">il programma non risponde: è ancora acceso?</span>'; return; }
  $('#st').innerHTML = D.errore ? `<span class="dot off"></span><span class="err">${D.errore}</span>` : `<span class="dot"></span>aggiornato alle ${D.aggiornato || '…'}`;
  const P0 = Object.values(D.piani || {})[0];
  $('#pi').innerHTML = P0 ? `<b>Piani delle ${hm(P0.ora)}, validi fino alle ${hm(P0.fino)}.</b> Nuovi piani ogni giorno alle ${hh(17)} e alle ${hh(21)}, come nella verifica; controllati ogni ora, l'ultima alle ${D.piani_ora}.` : 'Calcolo i piani dalle candele orarie…';
  if (D.verifica && D.verifica.ribasso) { const v = D.verifica, g = s => s && s.n ? `${Math.round(s.p_gain * 100)} % in guadagno, media ${pc(s.media)}` : 'n/d';
    $('#ver').innerHTML = `<b>Verifica di 2 anni, costi inclusi:</b> compra il ribasso ${g(v.ribasso.tutto)} · compra la rottura ${g(v.rottura.tutto)} · compra e vendi dopo 24 ore ${g(v.tempo.tutto)}. Nessuna regola intraday ha guadagnato in media: se provi, fallo prima nel conto demo dell'app.`; }
  const S = D.seguiti || [];
  $('#tb').innerHTML = Object.keys(D.nomi).map(s => { const x = D.prezzi[s]; if (!x) return '';
    const v = x.prezzo / x.apertura - 1, cl = x.direzione > 0 ? 'flashu' : x.direzione < 0 ? 'flashd' : '';
    const col = r => { const cur = S.find(p => p.sym === s && p.regola === r && p.attuale);
      const prev = S.filter(p => p.sym === s && p.regola === r && !p.attuale && p.fase === 'dentro');
      return (cur ? cella(cur, x.prezzo) : '…') + prev.map(p => `<div class="prev lv">Piano precedente, vale fino alle ${hm(p.fino)}:<br>${cella(p, x.prezzo)}</div>`).join(''); };
    return `<tr><td class="l"><b>${D.nomi[s]}</b> <span class="note">${s.replace('-EUR', '')}</span></td><td class="px ${cl}">${f(x.prezzo)}</td><td class="og ${v >= 0 ? 'up' : 'down'}">${pc(v)}<span class="note"> oggi</span></td>
      <td class="lv"><span class="ph">24 ore </span>${nf(x.min24, dec(x.min24))} / ${nf(x.max24, dec(x.max24))}</td><td class="l pi" data-k="Compra il ribasso">${col('ribasso')}</td><td class="l pi" data-k="Compra la rottura">${col('rottura')}</td></tr>`; }).join('');
  const E = D.eventi || [];
  if (E.length) $('#evs').innerHTML = E.map(e => `<div class="ev"><span class="t">${e.ora}</span><span>${testo(e)}</span></div>`).join('');
  if (visti !== null && D.n_eventi > visti) {
    if (suono) bip();
    E.slice(0, Math.min(3, D.n_eventi - visti)).forEach(e => { try { if (suono && Notification.permission === 'granted') new Notification(titolo(e), {body: e.prezzo ? f(e.prezzo) : ''}); } catch (err) {} });
  }
  visti = D.n_eventi || 0;
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


FASE = {"attesa": "attesa", "dentro": "DENTRO", "obiettivo": "obiett.", "protezione": "protez.",
        "scaduto": "scaduto", "scaduto_dentro": "scaduto"}


def terminale(stato):
    while True:
        time.sleep(1)
        with stato.lock:
            righe = []
            for s, v in stato.prezzi.items():
                stati = [stato.seguiti.get((s, r, stato.piani[s]["ora"]), {}).get("fase") if s in stato.piani else None
                         for r in ("ribasso", "rottura")]
                righe.append("%-10s %14s  %+6.2f %%   ribasso %-8s rottura %-8s" % (
                    NOMI[s].split()[0], "%.*f" % (5 if v["prezzo"] < 1 else 2, v["prezzo"]),
                    100 * (v["prezzo"] / v["apertura"] - 1), FASE.get(stati[0], "…"), FASE.get(stati[1], "…")))
            avvisi = ["%s  %s, %s: %s" % (e["ora"], e["nome"], e["regola"], e["evento"]) for e in stato.eventi[-5:][::-1]]
            err = stato.errore
        sys.stdout.write("\x1b[2J\x1b[H" + "Crypto dal vivo · %s (Kraken, in euro)\n\n" % ora() + "\n".join(righe) +
                         ("\n\nUltimi avvisi:\n" + "\n".join(avvisi) if avvisi else "") +
                         ("\n\n" + err if err else "") + "\n\nCtrl+C per uscire.\n")
        sys.stdout.flush()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--porta", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="non aprire il browser")
    ap.add_argument("--terminale", action="store_true", help="solo prezzi nel terminale")
    ap.add_argument("--ogni", type=float, default=1.0, help="secondi tra un aggiornamento e l'altro (minimo 1)")
    a = ap.parse_args(argv)
    stato = Stato()
    threading.Thread(target=lettore, args=(stato, max(1.0, a.ogni)), daemon=True).start()
    threading.Thread(target=pianificatore, args=(stato,), daemon=True).start()
    if a.terminale:
        try:
            terminale(stato)
        except KeyboardInterrupt:
            return 0
    srv = server(stato, a.porta)
    url = "http://127.0.0.1:%d" % a.porta
    print("[crypto_live] prezzi da Kraken ogni %g s · pagina su %s · Ctrl+C per fermare" % (max(1.0, a.ogni), url))
    if not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
