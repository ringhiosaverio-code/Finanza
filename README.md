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
python3 finanza.py TSLA                                 # dati live Yahoo
python3 finanza.py TSLA --target 1R --budget 5000 --max-loss 50
```

Esegue in ordine entry → exit → timemachine → budget → risk e si ferma prima del broker:
non invia mai ordini. Alla prima esecuzione crea `trader/config.json` dall'esempio (paper trading attivo);
la cartella `trader/` è esclusa da git.

## Test

```bash
cd .claude/skills && python3 -m unittest discover -s tests
```

Non è consulenza finanziaria. La maggior parte di chi fa day trading perde soldi.
