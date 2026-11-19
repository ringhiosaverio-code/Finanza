// Il motore del robot nel cloud: tiene aperta la pagina di live.py (http://127.0.0.1:8770/?motore=1) in un Chromium
// senza finestra, così il robot decide con i prezzi ogni 5 secondi giorno e notte, anche a telefono chiuso. Lo stato va
// al server (POST /robot) e i telefoni lo mostrano. Ogni 15 minuti ricarica la pagina (l'app rigenerata ogni 15 minuti), e se la
// pagina si blocca la riapre.
//
//   node robot_motore.js [http://127.0.0.1:8770]
const {chromium} = require('playwright');
const BASE = process.argv[2] || 'http://127.0.0.1:8770';
const URL = BASE + '/?motore=1#giornata';
const ora = () => new Date().toISOString().slice(0, 19);
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({timezoneId: 'Europe/Rome', locale: 'it-IT'});
  let page = null, aperta = 0;
  const apri = async () => {
    try { if (page) await page.close(); } catch (e) {}
    page = await ctx.newPage();
    page.on('pageerror', e => console.log(ora(), 'errore nella pagina:', String(e).slice(0, 200)));
    await page.goto(URL, {waitUntil: 'load', timeout: 60e3});
    aperta = Date.now();
    console.log(ora(), 'motore aperto');
  };
  for (;;) {
    try {
      if (!page || Date.now() - aperta > 900e3) await apri();
      const ok = await page.evaluate(() => typeof LIVE !== 'undefined' && LIVE.fonte === 'locale').catch(() => false);
      if (!ok && Date.now() - aperta > 60e3) await apri();       // server non raggiunto: si riprova
    } catch (e) {
      console.log(ora(), 'riapro:', String(e).slice(0, 150));
      await new Promise(r => setTimeout(r, 10e3));
      page = null;
    }
    await new Promise(r => setTimeout(r, 30e3));
  }
})();
