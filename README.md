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

## Test

```bash
cd .claude/skills && python3 -m unittest discover -s tests
```

Non è consulenza finanziaria. La maggior parte di chi fa day trading perde soldi.
