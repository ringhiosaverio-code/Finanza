# Finanza

Le 11 skill di day trading di [Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
(licenza MIT, vedi `.claude/skills/LICENSE-day-trader-skill`), copiate in `.claude/skills/` così da
funzionare come comandi di progetto: `/trader-scanner`, `/trader-news`, `/trader-entry`, `/trader-exit`,
`/trader-timemachine`, `/trader-budget`, `/trader-risk`, `/trader-broker`, `/trader-alerts`,
`/trader-analyst`, `/trader-pelosi`.

Solo Python 3.8+ con la libreria standard, nessun pip install.

## `finanza.py`: la catena di un trade in un comando

```bash
python3 finanza.py --demo                               # offline: il trade TSLA del 19/10/2026
python3 finanza.py --demo --ottimizza                   # + sceglie stop e target con la Macchina del Tempo
python3 finanza.py TSLA --ottimizza --budget 5000 --max-loss 50
```

```
entry -> [ottimizzatore] -> exit -> Macchina del Tempo -> [filtro] -> budget -> risk -> report
```

- **Macchina del Tempo**: 10.000 simulazioni del resto della giornata, ricostruite dalle candele
  a 5 minuti degli ultimi 60 giorni, più ogni volta che la stessa regola è scattata davvero.
- **Ottimizzatore** (`--ottimizza`): prova 16 combinazioni (stop `or-mid`, `or-low`, `pct:1`, `pct:2`
  x target 1R, 1,5R, 2R, 3R) con lo stesso seme e sceglie l'R medio migliore. Dice anche se la
  differenza con la seconda è più piccola dell'incertezza dello storico, cioè se la scelta è solo rumore.
- **Filtro sul vantaggio**: se l'R medio simulato è sotto `--min-edge` (default 0) si ferma prima
  del budget e non propone ordini (`--no-filtro` per disattivarlo).
- **Report**: `trader/report.html`, con ventaglio dei prezzi, esiti, ottimizzatore, ordine proposto
  e storico, in tema chiaro e scuro, leggibile anche su telefono.
- I dati di Yahoo vengono scaricati una sola volta per ogni esecuzione (`trader/cache/`).

Si ferma sempre prima del broker: non invia mai ordini. Alla prima esecuzione crea
`trader/config.json` dall'esempio (paper trading attivo); la cartella `trader/` è esclusa da git.
Codici di uscita: 0 PASS, 1 BLOCK o nessun ingresso, 2 fermato dal filtro.

## `app.py`: tutto in un'app

```bash
python3 app.py                       # scarica i dati, analizza, scrive trader/app.html
python3 settimana.py                 # i 10 titoli USA, solo in testo
python3 settimana.py --mercato italia # i 10 titoli italiani
python3 settimana.py --asof 2025-06-30
```

Un unico file HTML con cinque schede:

- **Titoli USA** e **Titoli italiani**: i 10 titoli della settimana dell'S&P 100 e del FTSE MIB. Per ognuno **quando entrare** (ordine limite alla
  prossima seduta a ultima chiusura + 0,5 ATR; se non si esegue, niente operazione), **quando
  vendere** (alla prima tra stop-loss, target e una data precisa di borsa) e **quante azioni**
  per il tuo capitale e il tuo rischio massimo. La **probabilità di guadagno** viene da tre fonti:
  la stessa regola rifatta sul passato del titolo in condizioni simili, su tutte le scelte passate
  dell'algoritmo, e la **Macchina del Tempo** (10.000 simulazioni nel browser con candele vere
  dell'ultimo anno). Stop (1,5 / 2 / 3 ATR / nessuno), target (1,5R / 2R / 3R / nessuno) e durata
  (2 settimane / 1 mese / 3 mesi) si cambiano e tutto si ricalcola.
- **Verifica**: la scelta rifatta ogni settimana dal 2017 con i soli dati di allora, per ciascun
  mercato, contro il paniere e l'indice (SPY o FTSE MIB), anno per anno, con il test statistico (t) e tutte le 39 varianti della regola.
- **Day trade**: l'ultimo giro di `finanza.py`.
- **Metodo**: come funziona e i suoi limiti.

L'**algoritmo** è il momentum 12-1 (rendimento da 12 a 1 mese fa) diviso per la volatilità a
3 mesi, solo per i titoli sopra la media a 200 giorni e con volatilità almeno del 10 % annuo
(sotto, il prezzo è di solito bloccato da un'offerta di acquisto, come Iveco). I parametri sono
quelli standard della letteratura e non sono adattati ai dati.

**Titoli italiani**: FTSE MIB più qualche grande titolo vicino all'indice (43 in tutto), prezzi in
euro, calendario di Borsa Italiana (Venerdì Santo, Pasquetta, Ferragosto, 24-26 e 31 dicembre
inclusi, verificato sui dati), costo 0,2 % per operazione perché c'è la Tobin tax dello 0,1 %
sugli acquisti. L'indice FTSE MIB di Yahoo è senza dividendi: il confronto giusto è con il paniere.

Cosa dicono i dati, senza abbellimenti:

- Il vantaggio storico sul paniere **non è statisticamente significativo** (t < 2), né per gli
  USA (+5 % l'anno, t = 0,9) né per l'Italia (+1,7 % l'anno, t = 0,4).
- Gli stop stretti peggiorano i risultati: con 2 ATR lo stop scatta quasi una volta su due.
  Per questo lo stop predefinito è 3 ATR, ma anche così "compra e tieni" ha una probabilità di
  guadagno più alta. Lo stop serve a limitare le perdite grosse, non ad aumentare i guadagni.
- L'universo è la composizione di oggi degli indici (bias di sopravvivenza): i numeri assoluti
  sono ottimistici.

L'app è un'istantanea: per aggiornarla rilancia `python3 app.py`. I dati vengono da Yahoo Finance
(query1/query2.finance.yahoo.com) con una cache di 12 ore in `trader/cache/daily/`.

## Test

```bash
python3 -m unittest discover -s tests                         # settimana.py e la regola, offline
cd .claude/skills && python3 -m unittest discover -s tests    # le skill trader-*
```

Non è consulenza finanziaria. La maggior parte di chi fa day trading perde soldi.
