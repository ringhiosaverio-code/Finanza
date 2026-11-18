#!/usr/bin/env node
// Il robot nel cloud: fa girare il robot dell'app sullo stato salvato, senza nessuno davanti.
//
//   node robot_cloud.js stato.json nuovo.json [trader/app.html]
//
// Apre l'app appena generata da app.py (trader/app.html) in un Chromium senza finestra, le passa lo
// stato del robot salvato nell'archivio dell'app (stato.json) e lascia che il robot rifaccia le
// operazioni con i prezzi ufficiali e le candele orarie, esattamente come quando apri l'app: è lo
// stesso codice. Scrive il nuovo stato in nuovo.json e stampa un riassunto in JSON:
//   {robot, cambiato, nuovi, testo, conti, errori}
// "testo" è la notifica (meno di 200 caratteri). Quello che il robot ha già registrato non cambia.
// Serve Playwright con Chromium (già presente nell'ambiente cloud).

const fs = require('fs');
const path = require('path');
const {chromium} = require('playwright');

const ordina = x => Array.isArray(x) ? x.map(ordina) : x && typeof x === 'object'
  ? Object.fromEntries(Object.keys(x).sort().map(k => [k, ordina(x[k])])) : x;
const uguale = (a, b) => JSON.stringify(ordina(a)) === JSON.stringify(ordina(b));

async function main() {
  const [ingresso, uscita, app = path.join(__dirname, 'trader', 'app.html')] = process.argv.slice(2);
  if (!ingresso || !uscita) { console.error('uso: node robot_cloud.js stato.json nuovo.json [trader/app.html]'); return 2; }
  let stato = JSON.parse(fs.readFileSync(ingresso, 'utf8'));
  if (stato && stato.data && (stato.data.conti || stato.data.notte)) stato = stato.data;     // documento con involucro
  if (!stato || stato.vuoto || !(stato.conti || stato.notte)) {
    console.log(JSON.stringify({robot: false, cambiato: false, nuovi: 0, testo: '', conti: [], errori: []}));
    return 0;
  }
  const browser = await chromium.launch();
  const errori = [];
  try {
    const page = await browser.newPage({locale: 'it-IT', timezoneId: 'Europe/Rome'});
    page.on('pageerror', e => errori.push(String(e).slice(0, 200)));
    await page.addInitScript(s => { try { localStorage.setItem('finanza-robot', s); } catch (e) {} }, JSON.stringify(stato));
    await page.goto('file://' + path.resolve(app) + '#giornata');
    await page.waitForFunction(() => typeof ROBOT !== 'undefined' && ROBOT && ROBOT.versione === 2, null, {timeout: 60000});
    const r = await page.evaluate(() => {
      robotGiro();                                                     // un giro in più, a dati caricati
      const R = JSON.parse(JSON.stringify(ROBOT));
      const conti = Object.keys(STRATEGIE).filter(k => R.conti[k].attiva || R.conti[k].n)
        .map(k => ({k, nome: STRATEGIE[k].breve, r: valoreConto(ROBOT, k) / ROBOT_CAPITALE - 1, aperta: R.conti[k].attiva}));
      return {R, conti, nomi: Object.fromEntries(Object.entries(STRATEGIE).map(([k, S]) => [k, S.breve]))};
    });
    if (errori.length) throw new Error('errori nella pagina: ' + errori.join(' | '));
    const prima = new Set(((stato.versione === 2 && stato.registro) || []).map(e => JSON.stringify(ordina(e))));
    const nuovi = (r.R.registro || []).filter(e => !prima.has(JSON.stringify(ordina(e)))).sort((a, b) => a.t < b.t ? -1 : 1);
    const pc = x => (x > 0 ? '+' : '') + (x * 100).toLocaleString('it-IT', {minimumFractionDigits: 1, maximumFractionDigits: 1}) + ' %';
    const tk = s => String(s).replace(/\.MI$|-EUR$/, '');
    const op = e => `${r.nomi[e.s] || e.s}: ${e.azione === 'compra' ? 'compra' : 'vende'} ${e.sym.includes(',') ? e.sym.split(',').length + ' titoli' : tk(e.sym)}${e.r != null ? ' ' + pc(e.r) : ''}`;
    let testo = '';
    if (nuovi.length) {
      const conti = r.conti.map(c => `${c.nome} ${pc(c.r)}`).join(', ');
      testo = `Robot: ${nuovi.length === 1 ? '1 operazione nuova' : nuovi.length + ' operazioni nuove'}. `;
      const per = {};
      for (const e of nuovi) per[e.s] = (per[e.s] || 0) + 1;
      const dettaglio = nuovi.length <= 3 ? nuovi.map(op).join('; ') : Object.entries(per).map(([k, n]) => `${r.nomi[k] || k} ${n}`).join(', ');
      testo += (testo.length + dettaglio.length < 120 ? dettaglio + '. ' : '') + `Conti: ${conti}.`;
      if (testo.length > 199) testo = testo.slice(0, 196) + '...';
    }
    const cambiato = !uguale(stato, r.R);
    if (cambiato) fs.writeFileSync(uscita, JSON.stringify(r.R));
    console.log(JSON.stringify({robot: true, cambiato, nuovi: nuovi.length, testo, conti: r.conti, errori}));
    return 0;
  } finally {
    await browser.close();
  }
}

main().then(c => process.exit(c), e => { console.error('[robot_cloud] ' + (e && e.message || e)); process.exit(1); });
