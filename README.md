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
python3 app.py                                   # scarica i dati, stima, verifica, scrive trader/app.html
python3 settimana.py                             # i 10 titoli USA, in testo
python3 settimana.py --mercato italia --stile data --durata 63
python3 settimana.py --mercato etf                # anche: bond, oro
python3 settimana.py --asof 2025-06-30           # cosa avrebbe consigliato a quella data
```

Sezioni: Oggi, Il mio portafoglio, Esercitati, Crypto, Cerca un titolo, Altro (Azioni, Funziona?,
Come funziona, esempio di day trade). L'app si aggiorna da sola nei giorni di borsa alle 18:10 e
alle 22:10 (ora italiana), dopo la chiusura di Milano e di New York.

- **Il mio portafoglio**: scrivi cosa possiedi (quantità, prezzo e data d'acquisto) e ogni giorno
  l'app dice una sola cosa per titolo: **TIENI** fino alla data di vendita (il periodo consigliato
  della sua categoria, in giorni di borsa reali), **VENDI** quando la data è passata o il prezzo è
  bloccato, **RINNOVA** se la data è passata ma il giudizio è ancora "Sì"; più qualche **COMPRA** tra
  i "Sì" di oggi che non hai già. I dati stanno nell'archivio privato dell'app: li vedi solo tu.
- **Esercitati**: un conto finto da 10.000 € ai prezzi di chiusura dell'ultimo aggiornamento, con i
  costi (0,1 %, Tobin tax sulle azioni italiane, 0,2 % sulle crypto) e il cambio euro/dollaro.
  Prima di comprare mostra il giudizio, quando vendi confronta il risultato con il piano.
- **Crypto intraday** (`intraday.py`): per ogni crypto due piani validi 24 ore, "compra il
  ribasso" e "compra la rottura", con entrata, protezione, obiettivo e scadenza. Verifica sulle
  candele orarie degli ultimi 2 anni (12 crypto, piani alle 18 e alle 22, costi 0,2 % per lato):
  in guadagno il 29-44 % delle volte, media da -0,4 % a -0,5 % per operazione, in entrambi gli
  anni. In 24 ore il movimento è quasi testa o croce e i costi lo rendono una perdita: l'app dice
  "Per ora no" e suggerisce di provare nel conto demo. Provate anche 9 varianti fissate prima di
  guardare i dati (filtro di tendenza, entrata più profonda, piani di 72 ore o 7 giorni,
  `python3 intraday.py --varianti`): la migliore sul primo anno ha perso anche sul secondo.
- **Crypto**: le 12 principali in euro (Bitcoin, Ethereum, Solana…) con le stesse regole: probabilità
  a 3 mesi di calendario, oscillazione, calo massimo storico (Bitcoin fino a -83 %) e giudizio.

- **Oggi**: i consigli del giorno su cinque categorie, in ordine di probabilità di guadagno:
  ETF azionari, ETF obbligazionari (UCITS su Borsa Italiana, acquistabili dall'Italia), oro e
  materie prime, azioni USA e italiane. Per ognuno: fino a che prezzo comprare, quanto tenere,
  quando vendere, cedole o dividendi degli ultimi 12 mesi e affidabilità. Per ogni categoria la
  regola consigliata è quella con più operazioni in guadagno dal 2017, tra quelle in cui nel 10 %
  dei casi peggiori non si è perso più del 10 %. Oggi: ETF azionari tenuti 3 mesi 71 %, ETF
  obbligazionari 58 % (guadagno tipico +0,4 %: servono per stabilità e cedole), oro 58 %,
  azioni 55-56 % a 1 mese. Le singole obbligazioni non hanno prezzi gratuiti affidabili: ci sono
  gli ETF obbligazionari.
- **Perché sì, perché no**: in Oggi e in Simula ogni strumento ha un giudizio (**Sì**, **Con
  cautela**, **Per ora no**) con una frase semplice e i motivi, ognuno con il suo dato: probabilità
  nella simulazione prudente e nella storia reale, rischio nel 10 % dei casi peggiori, cedole,
  affidabilità, confronto con un ETF sul mondo intero, valuta, prezzo bloccato. Regole fisse: "sì"
  con almeno 60 su 100 e non oltre -10 % in 1 caso su 10 nel periodo consigliato; "no" sotto 50 su
  100, oltre -20 % o con il prezzo bloccato. Il trend (sopra o sotto la media a 200 giorni) diventa
  un motivo solo dove i dati lo confermano: dal 2017 solo per gli ETF obbligazionari (58 contro 51
  su 100); per azioni ed ETF azionari non ha cambiato molto, per l'oro è andato meglio comprare in
  discesa.
- **Titoli USA** e **Titoli italiani**: tre passi. (1) Scegli quanto tenere (2 settimane, 1 mese,
  3 mesi) e come uscire (Prudente, Equilibrato, Lascia correre, Solo data): su ogni bottone c'è
  quante operazioni sono finite in guadagno. (2) Per ogni titolo, **compra** il giorno indicato
  fino a un prezzo massimo. (3) **Vendi** al primo tra obiettivo, protezione e data. I titoli
  sono **in ordine di probabilità di riuscita**, con il perché in parole semplici, quante azioni
  comprare, il grafico e 10.000 simulazioni nel browser.
- **Funziona?**: tre domande. Conta di più il titolo o la regola? Le probabilità dette sono quelle
  vere? I primi 10 hanno fatto meglio?
- **Cerca un titolo**: scrivi un codice ISIN e ottieni le probabilità di guadagno a 1 giorno, 1 settimana,
  1 mese e 1 anno con la loro affidabilità (vedi `simula.py` qui sotto).
- **Day trade**: l'ultimo giro di `finanza.py`.
- **Come funziona**: metodo, cosa è stato scartato e limiti.

### L'algoritmo

1. **Candidati**: i titoli dell'S&P 100 o del FTSE MIB sopra la media a 200 giorni, esclusi quelli
   con il prezzo quasi fermo (volatilità sotto il 10 % annuo, tipico di un'offerta di acquisto).
2. **Probabilità di riuscita** (l'operazione chiude in guadagno, costi inclusi): la frequenza
   storica delle operazioni su titoli *simili*, cioè dello stesso quinto per forza dell'ultimo
   anno (momentum 12-1 diviso per la volatilità), con la stessa regola. La stima è avvicinata
   alla media per non fidarsi dei gruppi piccoli, e non può premiare i più deboli: un effetto
   contrario nei dati è trattato come rumore.
3. **Verifica walk-forward**: ogni anno dal 2021 la stima usa solo gli anni precedenti e viene
   confrontata con com'è andata davvero.

Cosa dicono i dati:

- **Conta più la regola del titolo.** USA: dal 41 % di operazioni in guadagno ("Lascia correre",
  3 mesi) al 59 % ("Solo data", 3 mesi). Ma "Solo data" a 3 mesi perde oltre il 13 % in 1 caso
  su 10.
- **Tra titoli, le differenze sono piccole.** Con le durate brevi la probabilità è la stessa per
  tutti e l'ordine è per forza. A 3 mesi in Italia i più forti sono andati meglio (64 % contro
  55 %). Nella verifica i primi 10 non battono la media in modo statisticamente significativo.
- **Scartati dopo la verifica**: un modello a sei indizi (quando diceva 57 % è andata bene il
  46 %) e la storia del singolo titolo (non predice).
- Titoli di oggi degli indici (bias di sopravvivenza): i numeri assoluti sono un po' ottimisti.

Titoli italiani: prezzi in euro, calendario di Borsa Italiana (verificato sui dati), costo
0,2 % per operazione per la Tobin tax dello 0,1 % sugli acquisti. Dati Yahoo Finance
(query1/query2.finance.yahoo.com) con cache di 12 ore in `trader/cache/daily/`. L'app è
un'istantanea: per aggiornarla rilancia `python3 app.py`.

### Quanto tenere: scelto per ogni strumento

Per ogni strumento la Macchina del Tempo calcola la probabilità prudente e il caso peggiore (1 volta
su 10) a 1 mese, 3 mesi, 6 mesi e 1 anno; `simula.durata_consigliata` sceglie il periodo con la
probabilità più alta tra quelli in cui 1 volta su 10 non si perde più del 10 % (la soglia del "Sì").
Se nessuno rispetta il limite vale la durata della categoria. Prima la durata era unica per categoria
(1 mese le azioni, 3 mesi tutto il resto). Verifica (`verifica.py`, ogni mese dal 2004, stessi
strumenti e mesi, costi inclusi), in guadagno com'era → com'è:

| Gruppo | Fino al 2016 | Dal 2017 |
|---|---|---|
| Tutti (senza crypto) | 57 % → 58 % | 57 % → 60 % |
| ETF azionari | 68 % → 70 % | 68 % → 73 % |
| ETF obbligazionari | 60 % → 68 % | 54 % → 60 % |
| Azioni | 56 % → 57 % | 57 % → 59 % |

1 volta su 10 sotto: -10,0 % e -8,6 % (prima -8,4 % e -8,0 %). Per gli obbligazionari a 1 anno la
stima è stata ottimista (72 % detta, 66 % vera): il giudizio lo scrive.

### Il pacchetto (in cima a Oggi)

I 10 strumenti più forti del giorno (crescita 12-1 mesi divisa per la volatilità a 3 mesi, la stessa
"forza" della classifica) tra azioni USA e italiane, ETF azionari, obbligazionari e oro sopra la media
a 200 giorni, in parti uguali, tenuti per la durata scelta da `verifica.py` (oggi 1 anno). Verifica:
ogni mese dal 2004, con i soli prezzi di quel giorno e i costi, fino al 2016 e dal 2017:

| Cosa si compra, tenuto 1 anno | In guadagno | 1 su 10 sotto | Il peggiore |
|---|---|---|---|
| Uno qualsiasi tra i candidati | 73 % · 68 % | -17 % · -17 % | -80 % · -76 % |
| Solo il primo per probabilità | 74 % · 70 % | -16 % · -7 % | -51 % · -36 % |
| I primi 10 per probabilità | 82 % · 86 % | -15 % · -1 % | -36 % · -12 % |
| 10 a caso tra i candidati | 81 % · 85 % | -12 % · -3 % | -47 % · -24 % |
| **I primi 10 per forza (il pacchetto)** | **82 % · 90 %** | **-5 % · 0 %** | **-45 % · -27 %** |

Dividere e dare tempo conta più che scegliere; la probabilità più alta va spesso agli obbligazionari,
che guadagnano poco. Le azioni sono quelle negli indici oggi (numeri un po' ottimisti); tasse escluse.

## `simula.py`: simula un titolo dal codice ISIN

```bash
python3 simula.py IT0003132476                  # ENI
python3 simula.py US0378331005 IE00B4L5Y983     # Apple e un ETF MSCI World
python3 simula.py AAPL                          # anche dal ticker
```

Trova il ticker dall'ISIN (ricerca di Yahoo Finance, con controllo della cifra di controllo),
scarica fino a 25 anni di prezzi giornalieri e calcola la **probabilità di guadagno a 1 giorno,
1 settimana, 1 mese e 1 anno**:

- **Com'è andata davvero**: su tutte le finestre reali della storia, quante volte il prezzo è salito.
- **Macchina del Tempo**: 10.000 futuri fatti di pezzi veri della storia (per 1 anno, 12 mesi veri
  presi a caso), con tre scenari di crescita: nessuna, **prudente** (la crescita passata ridotta,
  perché le vere differenze tra grandi titoli sono di pochi punti l'anno) e come in passato.
- **Affidabilità** alta, media o bassa per ogni orizzonte: almeno 100 periodi indipendenti e
  scenari d'accordo entro 10 punti per "alta"; almeno 20 ed entro 20 punti per "media".

Nell'app, la sezione **Simula** fa lo stesso scrivendo l'ISIN, il ticker o il nome, per i 176 titoli
già dentro (S&P 100, FTSE MIB, ETF azionari e obbligazionari, oro e quelli aggiunti), con orizzonti
di 1 giorno, 1 settimana, 1 mese, 3 mesi, 6 mesi e 1 anno. Per un ISIN nuovo, `simula.py` lo aggiunge a
`simula_lista.json` e `python3 app.py` lo mette nell'app con prezzi aggiornati. `isin.json` contiene
la corrispondenza ISIN → ticker dei titoli dell'app, verificata uno per uno con la ricerca di Yahoo.

## `verifica.py`: 22 anni di verifica della probabilità e del giudizio

```bash
python3 verifica.py      # richiede numpy; scrive verifica.json (probabilità, durate, pacchetto), che l'app mostra in Funziona?
```

Per tutti gli strumenti dell'app, ogni mese dal 2004, rifà la probabilità prudente di guadagno con
i soli prezzi di quel giorno e la confronta con com'è andata (39.125 previsioni):

- in media è prudente: detta 56 %, vera 58 %, sia prima sia dopo il 2017;
- il giudizio distingue davvero: "Sì" in guadagno il 63 % delle volte (1 su 10 sotto -5 %),
  "Con cautela" il 57 % (1 su 10 sotto -8 %), "Per ora no" il 53 % (1 su 10 sotto -26 %);
- sopra il 70 % le stime sono state troppo ottimiste (vero 62 %): l'app lo segnala;
- tre miglioramenti provati su anni mai visti (miscela con la frequenza del gruppo, ricalibratura
  unica e per gruppo) non prevedono meglio: la stima resta quella prudente;
- a ogni durata della ricerca per titolo (1 giorno, 1 settimana, 1 mese, 3 mesi, 6 mesi, 1 anno) la
  probabilità detta è in media un po' più bassa di quella vera (a 1 anno 66 % contro 69 %), ma tra
  strumenti dello stesso tipo le differenze contano poco: a 1 anno le stime più alte (75 %) sono
  andate come le più basse (69 % contro 70 %). Gli ETF obbligazionari sono l'unico gruppo con stime
  ottimiste. 10 anni non si possono verificare (solo due periodi separati in 25 anni di prezzi).

## `libri.py`: le regole dei libri di trading, provate sui prezzi veri

```bash
python3 libri.py      # richiede numpy; scrive libri.json, che l'app mostra in Altro → Dai libri
```

Le regole più citate su candele, grafici e momenti di entrata, con i parametri scritti nei libri
(non ottimizzati) e fissate prima di guardare i risultati: figure giapponesi di Nison e Bulkowski,
RSI a 2 giorni di Connors, IBS, rottura di volatilità di Williams, NR7 e primo intervallo di Crabel,
massimo a 20 giorni dei Turtles, giro di fine mese, momento della giornata (Gao e altri 2018).
Si giudica fino al 2015 e si controlla dal 2016 (per le candele orarie: primo anno contro secondo).
Una regola regge se, dopo i costi, fa meglio del semplice tenere lo strumento in entrambi i periodi
con t >= 2 (raggruppando per mese). Risultato (novembre 2026): reggono 2 su 29.

- le figure giapponesi non aggiungono niente: lo stesso ribasso senza figura va uguale o meglio;
- l'RSI a 2 giorni funzionava prima del libro (2008) e ha smesso dopo;
- rotture, NR7, Turtles, fine mese e tutte le regole sulle candele orarie (crypto e USA) no;
- aspettare un segnale per entrare costa più che comprare subito;
- regge "dopo un piccolo ribasso" (chiusura sotto la media a 10 giorni): tra le 10 azioni USA più
  forti, quelle in piccolo ribasso hanno fatto +0,5 % nel mese dopo, prima e dopo il 2016. Per le
  azioni italiane e gli ETF no. L'app lo segna come "buon momento" solo lì.

## `giornata.py`: comprare e vendere nella stessa seduta (sezione "In giornata")

```bash
python3 giornata.py   # il piano per la prossima seduta; app.py lo mette nella sezione In giornata
```

Sette regole per la stessa seduta, fissate prima di guardare i dati (ogni giorno dall'apertura alla
chiusura, Oops! di Williams, gap giù, gap giù su titolo in salita, gap su, giorno dopo un forte
ribasso, primo del mese), verificate da `libri.py` su fino a 25 anni di candele giornaliere di azioni
USA, italiane ed ETF, costi inclusi: nessuna resta in guadagno in entrambi i periodi. Comprare
all'apertura e vendere in chiusura ha reso -0,11 % e -0,12 % a operazione; il gap giù rendeva
+0,33 % fino al 2015 e -0,08 % dopo. Il motivo: le azioni guadagnano di notte (USA +10 % l'anno
dalla chiusura all'apertura, +3 % di giorno; Milano +24 % e -11 %).

La sezione mostra il verdetto, il perché, il piano Oops! per la prossima seduta sui 14 titoli più
scambiati (livello, orari, storia della regola su ogni titolo) e un gioco: 240 giornate vere di
azioni USA, ora per ora, in cui decidi entrata, protezione e obiettivo e vedi com'è andata.

## Quotazioni in tempo reale nell'app

L'app pubblicata si rigenera alle 18:10 e alle 22:10; i prezzi in tempo reale arrivano in due modi,
mostrati accanto a ogni prezzo ("ora 128,18 € +0,79 % · 13:17") e nella spia in alto:

1. **App desktop di Claude**: in alto compare il pulsante "Prezzi in tempo reale". La pagina usa il
   browser integrato di Claude (capacità `mcp`, server `host:claude_browser`, strumenti
   `preview_start`, `navigate`, `get_page_text`) in una scheda sua e legge le quotazioni di Yahoo
   Finance ogni 30 secondi; la prima volta chiede il permesso. Funziona solo nell'app desktop e solo
   per chi ha creato l'app (i server locali non sono aperti agli altri, per ora).
2. **Sul tuo computer, con qualsiasi browser**: `python3 live.py` serve la stessa app su
   http://127.0.0.1:8770 e le passa le quotazioni ogni 5 secondi (`--rete` per aprirla anche dal
   telefono sulla rete di casa, senza password: solo in reti fidate).

```bash
python3 live.py
```

Fonte Yahoo Finance (`v7/finance/spark`, 20 titoli per richiesta, cache di 5 secondi per titolo):
azioni USA in tempo reale durante la seduta, Borsa Italiana con 15 minuti di ritardo (le quotazioni
gratuite di Milano sono così), crypto e cambio euro/dollaro in tempo reale. Nella sezione In
giornata il piano mostra anche se il prezzo adesso è sotto il livello. Probabilità e giudizi restano
quelli dell'ultimo aggiornamento.

## `crypto_live.py`: crypto in tempo reale, ogni secondo

```bash
python3 crypto_live.py                # apre http://127.0.0.1:8765 nel browser
python3 crypto_live.py --terminale    # solo nel terminale
```

L'app pubblicata su Claude non può collegarsi alle borse (le app non possono raggiungere siti
esterni) e si aggiorna al massimo due volte al giorno; il tempo reale gira quindi sul tuo computer,
con la sola libreria standard di Python:

- **prezzi** in euro da Kraken (dati pubblici gratuiti), una richiesta al secondo per tutte e 12
  le crypto; se Kraken chiede di rallentare, il programma aspetta e riprova;
- **piani**: gli stessi due di `intraday.py`, nati alle 17 e alle 21 UTC (18 e 22 in Italia d'inverno)
  e ricalcolati poco dopo ogni ora dalle candele orarie di Yahoo (solo candele chiuse);
- **stato** di ogni piano, seguito secondo per secondo come nella verifica: *in attesa*, *dentro*
  (l'entrata è scattata), *chiuso* (protezione, obiettivo o 24 ore passate). Protezione e
  obiettivo contano solo dopo l'entrata; il piano precedente resta visibile finché ci sei dentro;
- **avvisi**, con suono e notifica se li attivi, a ogni passaggio. I livelli già superati prima
  dell'avvio non fanno avviso: la tabella li mostra.

La pagina è servita solo su 127.0.0.1. Nella verifica di 2 anni, con i costi, nessuna regola
intraday ha guadagnato in media: è uno strumento per seguire i piani, non un motivo per usarli.

## Test

```bash
python3 -m unittest discover -s tests                         # settimana, simula, intraday, crypto_live, libri, giornata e live, offline
cd .claude/skills && python3 -m unittest discover -s tests    # le skill trader-*
```

Non è consulenza finanziaria. La maggior parte di chi fa day trading perde soldi.
