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

## `settimana.py`: i 5 titoli della settimana

```bash
python3 settimana.py                       # i 5 titoli di oggi + trader/settimana.html
python3 settimana.py --asof 2025-06-30     # cosa avrebbe scelto a quella data
python3 settimana.py --tickers AAPL,MSFT,NVDA,KO,XOM,JPM
```

- **Algoritmo** (trasparente, parametri standard della letteratura, non ottimizzati sui dati):
  momentum 12-1 (rendimento da 12 a 1 mese fa) diviso per la volatilità a 3 mesi, solo titoli
  sopra la media a 200 giorni; i 5 punteggi più alti dell'S&P 100.
- **Probabilità di guadagno e guadagno tipico in %** a 7 giorni, 1 mese e 1 anno per ogni titolo:
  quante volte, in condizioni simili, quel titolo era in guadagno dopo quel periodo, con il range
  10-90 %, il numero di casi e quanti sono davvero indipendenti (affidabilità alta / media / bassa).
- **Verifica**: la stessa scelta rifatta ogni settimana degli ultimi ~9 anni con i soli dati di allora,
  costi inclusi, confrontata con il paniere e con SPY, anno per anno e con un test statistico (t)
  che dice se il vantaggio è distinguibile dal caso.

Onestà prima di tutto: oggi il vantaggio storico sul paniere **non è statisticamente significativo**
(t < 2). A metà 2025 lo sembrava (t = 2,36), poi un 2026 negativo l'ha riportato nel rumore: per
questo nessun algoritmo va chiamato "affidabile". L'universo è l'S&P 100 di oggi, quindi la verifica
soffre di bias di sopravvivenza ed è ottimistica. A 1 anno i casi indipendenti sono pochissimi.
I dati vengono da Yahoo Finance (query1/query2.finance.yahoo.com), con una cache di 12 ore in `trader/cache/daily/`.

## Test

```bash
python3 -m unittest discover -s tests                         # settimana.py, offline
cd .claude/skills && python3 -m unittest discover -s tests    # le skill trader-*
```

Non è consulenza finanziaria. La maggior parte di chi fa day trading perde soldi.
