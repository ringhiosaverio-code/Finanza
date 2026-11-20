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
Come funziona, esempio di day trade). L'app si aggiorna da sola ogni ora: alle 18 e alle 22 dei giorni
di borsa (ora italiana, dopo la chiusura di Milano e di New York) tutto, nelle altre ore solo crypto e reti
neurali con `python3 app.py --leggero`, che riparte dall'ultima app generata (meno di un minuto).

- **Il mio portafoglio**: scrivi cosa possiedi (quantità, prezzo e data d'acquisto) e ogni giorno
  l'app dice una sola cosa per titolo: **TIENI** fino alla data di vendita (il periodo consigliato
  della sua categoria, in giorni di borsa reali), **VENDI** quando la data è passata o il prezzo è
  bloccato, **RINNOVA** se la data è passata ma il giudizio è ancora "Sì"; più qualche **COMPRA** tra
  i "Sì" di oggi che non hai già. I dati stanno nell'archivio privato dell'app: li vedi solo tu.
- **Esercitati**: un conto finto da 10.000 € ai prezzi di chiusura dell'ultimo aggiornamento, con i
  costi (0,1 %, Tobin tax sulle azioni italiane, 0,2 % sulle crypto) e il cambio euro/dollaro.
  Prima di comprare mostra il giudizio, quando vendi confronta il risultato con il piano.
- **Crypto, ordini ogni ora** (`intraday.py`) — **perdono, ritirati il 19 novembre 2026**. A ogni ora piena,
  per ognuna delle 12 crypto, tre ordini "compra il ribasso" validi un'ora: entrata a 1,5, 2 o 3
  escursioni medie orarie (ATR delle ultime 24 candele) sotto il prezzo, protezione 3 escursioni sotto
  l'entrata, obiettivo il prezzo di partenza, uscita comunque dopo 24 ore, una posizione alla volta per
  crypto e profondità. La prima verifica (18 novembre) li dava in guadagno (+0,2 % / +0,6 % a operazione
  nel secondo anno, anche su Kraken) ed era sbagliata: nella candela in cui scatta l'ordine contava come
  obiettivo raggiunto anche il massimo, che può essere venuto prima del minimo (l'obiettivo è il prezzo di
  partenza e la candela dopo apre proprio lì). Corretto (l'obiettivo conta dalla candela dopo l'entrata) e
  rifatto minuto per minuto sugli scambi veri di Kraken, 400 giorni e 12 crypto, con l'ordine che scatta
  solo se qualcuno vende a mercato sotto il suo prezzo: leggero -0,60 %, medio -0,61 %, profondo -0,49 % per
  operazione dopo i costi (0,2 % per lato), negativo in ogni periodo di 60 giorni. Le candele di Yahoo
  corrette danno lo stesso (da -0,5 % a -1,0 %). Il controllo su Kraken di allora usava le stesse candele
  con la stessa regola: non era indipendente. Il robot li esegue lo stesso, come esercitazione; nella sezione Crypto
  c'è il verdetto "Per ora no" e la spiegazione dell'errore. `python3 intraday.py --ore` rifà la verifica sulle candele;
  `python3 rete_dati.py` scarica gli scambi di Kraken (400 giorni, circa 75 minuti) e `python3 rete.py --ordini-limite`
  la rifà minuto per minuto sugli scambi. I due
  piani al giorno di prima (rottura compresa, media da -0,4 % a -0,5 %) restano come "Come eravamo partiti".
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

### Di notte: la sola regola breve che regge (momento notturno)

Cercando un algoritmo per guadagnare in giornata sono state provate anche le strategie pubblicate di
recente: ORB a 60 minuti sui titoli "in gioco" (volume della prima ora 1,5 volte la media; Zarattini
e Aziz 2023-24) e la "zona di rumore" sugli indici USA (Zarattini, Barbon e Aziz 2024), su azioni e
crypto. Nessuna guadagna, nemmeno con costi bassi (`libri.py`, prova "recenti").

L'unica regola breve che regge è il contrario dell'intraday: il **momento notturno** (Lou, Polk e
Skouras 2019). Ogni giorno i 10 titoli USA con la media più alta dei rendimenti delle ultime 21
notti, comprati in chiusura (ordine MOC) e venduti all'apertura del giorno dopo (ordine MOO). Su 25
anni (`libri.py`, prova "momento_notte"):

| Costi tra entrata e uscita | L'anno, dal 2001 | L'anno, dal 2016 | Calo massimo | Regge |
|---|---|---|---|---|
| 0,02 % | +23 % | +15 % | -28 % | sì |
| 0,05 % | +14 % | +6 % | -35 % | no (t 1,6 nella seconda metà) |
| 0,10 % | +1 % | -6 % | -72 % | no |

In guadagno 22 anni su 26 (con 0,02 %), il peggiore il 2022 (-18 %); con 5 o 20 titoli, 10 o 63
notti cambia poco. Funziona solo con costi da aste e commissioni dello 0,01 % per ordine (almeno
5.000 € per titolo con una commissione minima di 0,50 €); con una commissione fissa di 5-10 € su
cifre piccole perde. Titoli di oggi (numeri un po' ottimisti), tasse escluse, rischio delle notizie
notturne. `giornata.piano_notte` fa la lista per la prossima chiusura; l'app la mostra in In giornata.

### Il robot: compra e vende da solo, in conti finti

Il robot segue gli algoritmi dell'app senza interventi, con un conto finto da 10.000 € per strategia e niente soldi veri. Non invia ordini a nessun broker: le operazioni sono simulate a prezzi reali (Yahoo Finance).

- **Azioni in seduta** (esercitazione, in media perde): sui 14 titoli più scambiati di USA e Milano. Se la seduta apre sotto il minimo di ieri, compra quando il prezzo risale lì e vende in chiusura. Compra e vende solo a borsa aperta, dal lunedì al venerdì (New York 9:30–16:00, Milano 9:00–17:30), mai di notte. Costi: quelli scelti in Commissioni.
- **Crypto, ordini ogni ora** (esercitazione, in media perde): ogni ora mette tre ordini "compra il ribasso" per crypto, ognuno con 1/36 del capitale (12 crypto per 3 profondità); l'ordine vale un'ora, poi si esce alla protezione, all'obiettivo o dopo 24 ore. 24 ore su 24. Nella verifica corretta del 19 novembre 2026 perde in media lo 0,4-0,6 % per operazione (vedi sopra): lo tengo acceso perché le operazioni si vedano lavorare, ma non è una strategia che guadagna. Il piano di 24 ore di prima non c'è più.
- **Crypto, rete neurale** (esercitazione): le operazioni che la rete neurale di `rete.py` decide ogni minuto sugli scambi
  di Kraken degli ultimi 3 giorni (`rete_live.robot_crypto`), rigiocate nel conto con 1/12 del capitale per posizione, una
  per crypto. Compra solo dove la rete stima che l'operazione chiuda in guadagno con una probabilità almeno pari alla
  soglia che ha scelto sul periodo più recente (vedi sotto, "Scegliere le operazioni che chiudono in guadagno"), anche
  senza il via libera della verifica: così la vedi lavorare e imparare, sapendo che nella verifica non ha ancora saputo
  distinguere le operazioni vincenti. Ogni operazione mostra la probabilità stimata. Le posizioni aperte si chiudono dal
  vivo (protezione, fine della durata) o con i dati del prossimo aggiornamento.
- **Azioni italiane, rete neurale** (esercitazione): lo stesso con la rete di `rete_azioni.py` sui titoli del FTSE MIB,
  decisioni ogni 5 minuti della seduta (barre di Yahoo, 15 minuti di ritardo), 1/8 del capitale per posizione, tutto
  chiuso al più tardi alle 17:30. Stessa scelta per probabilità, stessa avvertenza.
- **Strategie di notte ritirate**: il robot non compra più azioni a borsa chiusa. Le posizioni rimaste da prima si chiudono alla prossima apertura. La verifica di notte resta nei libri.

**Operazioni in diretta.** Il registro in cima alla scheda elenca ogni operazione, tutte o solo azioni o solo crypto, con l'ora (con i secondi per quelle di oggi), il prezzo, l'importo investito o incassato, il risultato e la fonte (in diretta, prezzi ufficiali, candele orarie). Una riga in alto compare in tutte le pagine mentre una sessione è aperta, e ogni operazione nuova avvisa (con notifica del dispositivo, se hai concesso gli avvisi e la pagina è in un'altra scheda). Il registro tiene le ultime 1000 operazioni.

**Sessioni.** Inizia sessione (da oggi, o rigiocando l'ultima settimana o le ultime due) e Termina sessione: crypto e azioni in giornata si vendono subito al prezzo di adesso, i piani in attesa si annullano, poi il robot si ferma. Ogni strategia si avvia e si ferma da sola.

In diretta solo con la pagina aperta e i prezzi in tempo reale: `python3 live.py` sul computer (ogni 5 secondi), oppure "Prezzi in tempo reale" nell'app desktop di Claude (ogni 30 secondi). A pagina chiusa il cloud rifà le operazioni ogni ora (l'intervallo più breve che la pianificazione consente), con i dati dell'ultimo aggiornamento (`robot_cloud.js`), senza cambiare quelle già registrate e con un avviso per le operazioni nuove.

Il robot salva a ogni operazione e lo storico ogni 10 minuti. Verifica: rigiocando da inizio novembre 2026, le operazioni in seduta coincidono con il calcolo in Python (stesse liste, stessi risultati); le crypto usano la stessa logica già verificata sulle candele orarie.
### I dati di oggi: seduta in corso e chiusura mancante

Durante la seduta Yahoo mette come chiusura della barra di oggi il prezzo del momento: `giornata`
(`serie_notte_testo`, `serie_giorno_testo`) la considera una chiusura solo a seduta finita
(`settimana.seduta_in_corso`, dagli orari della seduta nei metadati). Se invece Yahoo lascia vuota
la chiusura dell'ultima seduta (capita con Milano) la prende dai metadati (`chiusura_mancante`). Le
cache dei grafici (12 ore) si rinnovano anche quando la seduta che descrivono è finita dopo che sono
state scritte (`settimana.cache_valida`): così l'aggiornamento delle 22:10 ha le chiusure USA del
giorno.

## `crypto_lungo.py`: crypto a medio e lungo termine

```bash
python3 crypto_lungo.py      # stampa i risultati; app.py li mette nella sezione Crypto
```

Sulle chiusure giornaliere in euro delle 12 crypto dell'app, con regole fissate prima di guardare:
compra e tieni contro la **regola della tendenza** (dentro quando la chiusura di ieri è sopra la media
dei suoi ultimi 200 o 50 giorni, fuori in euro quando è sotto, 0,2 % a ogni cambio), su tutta la
storia di ogni crypto (dal primo anno, saltando quello del lancio) e su un paniere a pesi uguali
ribilanciato ogni mese, divisa in due metà; quante volte si è chiuso in guadagno tenendo 1 mese, 1, 2
e 4 anni (Bitcoin ed Ethereum); 12 rate mensili contro tutto subito; e se oggi ogni crypto è sopra o
sotto le sue medie. Risultati al 17 novembre 2026: su Bitcoin la tendenza ha ridotto il calo massimo
(-65 % con 200 giorni, -62 % con 50, contro -83 %) con una crescita simile; non ha battuto sempre il
compra e tieni; nella seconda metà dei dati tutte le crypto sono cresciute molto meno. La sezione
dell'app aggiunge gli studi pubblicati (Liu e Tsyvinski 2021, Detzel e altri 2021, Zarattini, Pagani e
Barbon 2025, Fondo Monetario 2022, BlackRock 2024, Vanguard) e le tasse italiane dal 2026 (33 %).

## Quotazioni in tempo reale nell'app

L'app pubblicata si rigenera ogni ora (le azioni alle 18 e alle 22); i prezzi in tempo reale arrivano in due modi,
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
- **ordini**: i tre ordini orari di `intraday.py` (ribasso leggero, medio e profondo), rifatti due
  minuti e mezzo dopo ogni ora piena dalle candele orarie di Yahoo (solo candele chiuse);
- **stato** di ogni ordine, seguito secondo per secondo come nella verifica: *in attesa* (vale
  un'ora), *dentro* (l'entrata è scattata), *chiuso* (protezione, obiettivo o 24 ore passate).
  Protezione e obiettivo contano solo dopo l'entrata; una posizione resta visibile finché ci sei
  dentro, anche quando l'ordine di quell'ora è scaduto;
- **avvisi**, con suono e notifica se li attivi, a ogni passaggio. I livelli già superati prima
  dell'avvio non fanno avviso: la tabella li mostra.

La pagina è servita solo su 127.0.0.1. Gli ordini orari, nella verifica corretta, perdono in media
dopo i costi: è uno strumento per seguire un'idea, non una promessa di guadagno.

## La rete neurale: `rete_dati.py`, `rete.py`, `rete_live.py`

Una rete neurale scritta da zero (solo numpy) che impara a fare operazioni sulle crypto scegliendo da sola quando comprare
e per quanto tenere, da 1 minuto a 2 giorni, con apprendimento per rinforzo. **Fuori campione, con i costi dell'app
(0,2 % per lato), non guadagna**: nei mesi in cui non vede niente che valga i costi resta fuori (4
finestre su 6), e quando si fa convincere perde. Impara bene il passato (in media +1,18 % per operazione nel periodo
in cui ha imparato) e non lo ripete sul futuro (-0,31 % su periodi mai visti): sovradattamento. Anche con costi più
bassi la rete non batte due regole semplici di confronto.

**I dati.** `python3 rete_dati.py` scarica ogni scambio delle 12 crypto su Kraken in euro, 401 giorni (dal 2025-10-14 al
2026-11-18, circa 34 milioni di scambi, 75 minuti): Kraken dà solo le ultime 720 candele, ma conserva ogni scambio. Su Bitcoin
c'è uno scambio ogni ~5 secondi e solo nel 13 % dei secondi ce n'è almeno uno; sulle altre
molto meno (Polkadot 1,3 %).

**Perché non ogni secondo.** Un'operazione completa costa 0,4 % tra entrata e uscita. Su Bitcoin la mossa
tipica del prezzo è 0.0000 % a 1 secondo, 0.021 % a 1 minuto, 0.17 % a 1 ora e 0.92 % a 1 giorno; una mossa
più grande dei costi c'è lo 0 % delle volte a 1 secondo, lo 0.1 % a 1 minuto, il 20 % a 1 ora e il
75 % a 1 giorno. Per questo la rete decide ogni minuto (i suoi numeri non cambiano più spesso) e può
scegliere durate da 1 minuto a 2 giorni; `rete_live.py` guarda comunque i prezzi ogni secondo, per le protezioni e le uscite.

**Come impara.** Ogni quarto d'ora, per ogni crypto, la rete vede 36 numeri che usano solo il passato (rendimenti su 12 scale
di tempo, volatilità, posizione tra minimo e massimo, flusso di acquisti e vendite a mercato, ora e giorno, mercato intero)
e dà un valore a ogni mossa: aspettare, o comprare e tenere 1, 5, 15, 30 minuti, 1, 2, 4, 8, 12 ore, 1 o 2 giorni. Ogni
acquisto ha una protezione (2.5 volatilità orarie x radice delle ore), i costi ci sono tutti e una crypto ha una sola posizione
alla volta, quindi la rete deve scegliere anche quando aspettare. Due modi di imparare, confrontati: (1) Q-learning su
decisioni di durata diversa: il valore di una mossa è il guadagno netto più il valore, scontato, di quando si torna liberi;
il prezzo non dipende dalle nostre operazioni, quindi di ogni istante si sa cosa sarebbe successo con ogni mossa, e
l'"esperienza" è la storia riletta a ogni iterazione con la rete dell'iterazione prima; (2) previsione diretta del guadagno
netto di ogni orizzonte. Una sola rete (3 strati) per tutte le crypto, come nell'articolo di Sirignano e Cont (2019).

**Come l'ho verificata.** A finestre mobili (6 test da 30 giorni, l'ultimo è l'ultimo mese): si addestra sul passato, si
sceglie con il mese dopo, si misura sul mese ancora dopo, mai visto, con 2 giorni di intervallo tra l'uno e l'altro perché
l'esito di un'operazione guarda avanti fino a 2 giorni. Per comprare, nel mese di scelta il guadagno deve valere almeno
1.5 errori standard sopra zero su almeno 20 operazioni, altrimenti la rete resta fuori. Nessun numero del test serve a scegliere
qualcosa. A confronto, due regole semplici fissate prima di guardare (ribasso a 4 ore, rialzo a 1 giorno) e comprare sempre e
tenere 1 giorno. Il codice ha un test sul futuro: nessuna caratteristica cambia se si cambiano le barre dopo l'istante di
decisione.

**Risultati fuori campione, 180 giorni, costi 0,2 % per lato.**

| | operazioni | media per operazione | conto |
|---|---|---|---|
| Rete, apprendimento per rinforzo | 270 | -0,97 % | -20,8 % |
| Rete, previsione diretta | 392 | -0,17 % | -5,9 % |
| Regola: ribasso a 4 ore | 924 | -0,17 % | -12,9 % |
| Regola: rialzo a 1 giorno | 360 | -0,03 % | -3,1 % |
| Comprare sempre e tenere 1 giorno | 2211 | -0,45 % | -87,4 % |

Il conto somma i guadagni netti di ogni operazione, ognuna con 1/12 del capitale; gli intervalli al 90 % (a blocchi di 7 giorni) e
lo Sharpe sono nell'app. La correlazione di rango tra la previsione della rete e quello che succede va da -0,004 a
+0,079 a seconda dell'orizzonte: la rete sa quasi niente di quello che farà il prezzo. Con costi più bassi, riaddestrando da
capo per ogni livello (✓: conto positivo con l'intervallo al 90 % tutto sopra zero):

| costo | rete, rinforzo | rete, previsione | regola: ribasso a 4 ore | regola: rialzo a 1 giorno |
|---|---|---|---|---|
| 0,20 % per lato | -20,8 % (270 op.) | -5,9 % (392 op.) | -12,9 % (924 op.) | -3,1 % (360 op.) |
| 0,10 % per lato | -15,5 % (474 op.) | -7,4 % (587 op.) | +2,5 % (924 op.) | +2,8 % (360 op.) |
| 0,05 % per lato | -7,6 % (486 op.) | -13,2 % (819 op.) | +10,2 % ✓ (924 op.) | +5,8 % (360 op.) |
| 0,02 % per lato | +15,0 % (1322 op.) | -10,4 % (899 op.) | +14,9 % ✓ (924 op.) | +7,5 % (360 op.) |

A 0,05 % per lato o meno la regola semplice "ribasso a 4 ore" guadagna in modo credibile: un vantaggio piccolo (il
prezzo dopo un calo tende a risalire) c'è, ma solo con costi che un cliente piccolo di solito non ha, e la rete non lo trova
meglio della regola. In tutti i casi il modello finale (addestrato su tutto tranne l'ultimo mese, scelto sull'ultimo mese)
resta fuori: nell'ultimo mese non c'era un guadagno credibile.

**Limiti.** 401 giorni sono un solo ciclo di mercato, e questo è stato in gran parte un ribasso; le coppie in euro di Kraken sono
sottili; non si può vendere allo scoperto; i costi veri di un cliente piccolo su Kraken potrebbero essere più alti dello
0,2 % per lato (non ho potuto leggere il tariffario). Le conclusioni sono quelle della letteratura: Jaquart, Dann e
Weinhardt (2021, *Journal of Finance and Data Science*) trovano che a 1-60 minuti i modelli battono il caso ma la strategia
perde dopo i costi; Fischer e Krauss (2018, *European Journal of Operational Research*) che il vantaggio delle reti LSTM
sull'S&P 500 sparisce dal 2010. La verifica degli ordini orari di prima (sezione Crypto intraday) era sbagliata per un errore
di ordine dentro la candela, corretto il 19 novembre: vedi sopra.

**Scegliere le operazioni che chiudono in guadagno.** Una seconda rete, con gli stessi numeri in ingresso, impara da
tutte le operazioni possibili del passato e dal loro esito la **probabilità che un'operazione chiuda in guadagno** dopo i
costi (una probabilità per durata, entropia incrociata). È quella che usa il robot dell'app: compra solo dove la probabilità
della durata migliore arriva a una soglia che la rete sceglie sul periodo più recente, provando a prendere il meglio 0,2 %,
0,5 %, 1 %, 2 %, 5 %, 10 % o 20 % delle occasioni e tenendo la quota con la media per operazione più alta (su almeno 20
operazioni). Verifica a finestre come sopra, costi 0,2 % per lato: le operazioni scelte così sono state 384, in guadagno
il 37 %, in media -0,62 % (conto -19,5 %); tutte le occasioni, senza scegliere, vincono il
39 % con una media di -0,51 %. La soglia ha avuto il via libera della verifica in 2 finestre su 6.
Le stime della rete non distinguono le operazioni vincenti: dove stima il 50 % o più (29786 occasioni) la stima media è il
54 % e ha vinto davvero il 40 %.

| Prendere solo… | operazioni | in guadagno | media | conto |
|---|---|---|---|---|
| il meglio 0,2 % | 145 | 39 % | -0,68 % | -8,4 % |
| il meglio 0,5 % | 217 | 41 % | -0,71 % | -13,2 % |
| il meglio 1 % | 267 | 42 % | -0,80 % | -18,3 % |
| il meglio 2 % | 396 | 42 % | -0,65 % | -23,4 % |
| il meglio 5 % | 663 | 43 % | -0,49 % | -32,4 % |
| il meglio 10 % | 878 | 41 % | -0,49 % | -42,7 % |
| il meglio 20 % | 1099 | 41 % | -0,35 % | -38,3 % |

Il modello del robot (addestrato fino al 2026-11-18) compra dal 64 % di probabilità stimata, il meglio
1 % delle occasioni, senza il via libera della verifica. Ogni sera alle 18 si riaddestra con gli scambi
nuovi (`python3 rete_dati.py --giorni 3`, poi `python3 rete.py --robot`) e il diario degli addestramenti (`esperienza` nel
JSON, e nell'app) tiene cosa ha scelto ogni volta: così si vede se, con più dati, comincia a scegliere meglio.

**Dal vivo.** `python3 rete_live.py` fa girare la rete in un conto finto: prezzi di Kraken ogni secondo, decisione ogni minuto,
protezione e scadenze ogni secondo, riaddestramento ogni giorno con i dati nuovi (stesso cancello: se non c'è un guadagno
credibile resta fuori). La pagina (http://127.0.0.1:8766) mostra per ogni crypto il vantaggio di comprare sull'attesa. Di serie non
compra mai, perché nessun modello ha passato il cancello; `--margine 0.001` la costringe a comprare per vedere come impara e cosa
perde, e `--costo 0.0005` usa il modello addestrato con costi più bassi. Il registro è in `trader/rete_esperienza.json`.

```bash
python3 rete_dati.py                # gli scambi di Kraken, circa 75 minuti
python3 rete.py --studia            # addestra e verifica (circa 30 minuti), scrive rete_modello.json
python3 rete.py --sovradattamento   # aggiunge il confronto tra periodo di addestramento e periodo mai visto
python3 rete.py --ordini-limite     # gli ordini orari di intraday.py sugli scambi veri
python3 rete.py --probabilita       # la scelta per probabilità di guadagno: verifica a finestre e modello del robot (circa 30 minuti)
python3 rete.py --robot             # solo il modello del robot, con gli scambi fino a ieri (ogni sera)
python3 rete_live.py                # la rete dal vivo
```

## La rete neurale sulle azioni italiane: `rete_azioni.py`

La stessa rete delle crypto (stesso codice di addestramento e di verifica, `rete.py`) sui 43 titoli
del FTSE MIB, in giornata: ogni 5 minuti della seduta, dalle 9:10, per ogni titolo vede 24 numeri che usano solo il
passato (rendimenti da 5 minuti a 5 sedute, volatilità, apertura e salto da ieri, posizione nel minimo-massimo di oggi,
volumi, ora e giorno, mercato intero) e sceglie se aspettare o comprare e tenere 5, 15, 30 minuti, 1, 2, 4 ore o fino
alla chiusura. Tutto si chiude entro le 17:30 (niente posizioni di notte), con una protezione sotto l'entrata e costi
dello 0,1 % per lato (per chi compra e vende nello stesso giorno la Tobin tax non si paga). Dati: barre da 5 minuti di
Yahoo, le sole gratuite a questo passo, quindi solo gli ultimi 60 giorni: 60 sedute, dal 2026-08-28 al 2026-11-19.

**Risultati fuori campione, 30 sedute** (3 finestre da 14 giorni, addestramento su tutto quello che viene prima, scelta sulle
2 settimane prima del test, un giorno di intervallo; stesso cancello delle crypto):

| | costi 0,10 % per lato | costi 0,05 % per lato |
|---|---|---|
| Rete, apprendimento per rinforzo | 200, -0,40 % a op., conto -1,9 % | 412, -0,14 % a op., conto -1,3 % |
| Rete, previsione diretta | resta fuori (0 op.) | resta fuori (0 op.) |
| Rete, probabilità di guadagno (come il robot) | 363, -0,34 % a op., conto -2,9 % | 114, +0,02 % a op., conto +0,0 % |
| Regola: compra alle 9:10, vendi in chiusura | 1290, -0,11 % a op., conto -3,3 % | 1290, -0,01 % a op., conto -0,3 % |
| Regola: dopo un'ora in ribasso, tieni un'ora | 829, -0,17 % a op., conto -3,3 % | 829, -0,07 % a op., conto -1,4 % |
| Regola: dopo un'ora in rialzo, tieni un'ora | 815, -0,14 % a op., conto -2,7 % | 815, -0,04 % a op., conto -0,8 % |

A 0,1 % per lato la rete per rinforzo resta fuori in 2 finestre su 3; quando entra perde (200 operazioni, in media -0,40 %).
A 0,05 % per lato la rete per rinforzo resta fuori in 2 finestre su 3; quando entra perde (412 operazioni, in media -0,14 %). Comprare sempre perde i costi e un po' di più (-0,20 % a 5 minuti,
-0,29 % tenendo fino alla chiusura), e la correlazione di rango tra la previsione della rete e quello che succede
va da -0,019 a +0,001: in queste sedute la rete non sa niente del prossimo movimento. 60 sedute sono
poche (un solo periodo di mercato, nessun anno intero): servirebbero anni di barre da 5 minuti, che gratis non ci sono.

**Scegliere le operazioni che chiudono in guadagno.** Come per le crypto, una seconda rete stima la probabilità che
ogni operazione chiuda in guadagno dopo i costi, e il robot compra solo dalla soglia che la rete sceglie sulle 2 settimane
più recenti. Sulle stesse sedute mai viste, a 0,1 % per lato: 363 operazioni scelte, in guadagno il 37 %, in
media -0,34 % (conto -2,9 %); tutte le occasioni vincono il 35 %, in media -0,22 %. Dove la
rete stima il 50 % o più (5456 occasioni) vince davvero il 38 %: per ora non sa distinguere le
operazioni vincenti.

| Prendere solo… | operazioni | in guadagno | media | conto |
|---|---|---|---|---|
| il meglio 0,2 % | 74 | 42 % | +0,09 % | +0,2 % |
| il meglio 0,5 % | 146 | 38 % | -0,10 % | -0,4 % |
| il meglio 1 % | 252 | 38 % | -0,10 % | -0,6 % |
| il meglio 2 % | 403 | 37 % | -0,18 % | -1,6 % |
| il meglio 5 % | 726 | 40 % | -0,18 % | -3,0 % |
| il meglio 10 % | 1023 | 44 % | -0,17 % | -4,1 % |
| il meglio 20 % | 1409 | 41 % | -0,20 % | -6,6 % |

Il modello del robot (sedute fino al 2026-11-19) compra dal 54 % stimato, il meglio 10 % delle
occasioni, senza il via libera della verifica. Ogni sera dei giorni feriali alle 18 `python3 rete_azioni.py --studia` rifà
verifica e modelli con la seduta del giorno. Yahoo dà le barre da 5 minuti solo degli ultimi 60 giorni: quelle già scaricate
si tengono in un archivio (`trader/cache/rete_azioni/archivio`), così ogni giorno la rete ha una seduta in più da cui
imparare (l'archivio vive nella cartella di lavoro: se la si rifà da capo, riparte dagli ultimi 60 giorni).

```bash
python3 rete_azioni.py --studia     # scarica le barre, addestra e verifica (circa 2 minuti), scrive rete_azioni_modello.json
python3 rete_azioni.py --oggi       # le operazioni che la rete fa nelle ultime 3 sedute (quelle che il robot rigioca)
```

### Ogni ora della seduta, e anche a New York: `rete_usa.py`

La rete vede probabilità più alte all'apertura, quando i titoli si muovono di più: con una soglia sola comprava quasi solo
alle 9. Ora il robot usa una soglia per ogni ora di ogni seduta (`soglie_per_ora`): la soglia imparata, abbassata fino al
meglio 2 % delle occasioni di quell'ora. Così compra dall'apertura alla chiusura.

La stessa rete, con lo stesso codice, gira sulle azioni USA (S&P 100, 09:30-16:00 di New York, 78 barre da 5 minuti,
costi di 0,05 % per lato, notizie su Wall Street): `rete_usa.py` carica `rete_azioni.py` con `MERCATO_SCELTO = "usa"`.
Nel robot ha il suo conto, "Azioni USA, rete neurale" (in euro: conta il guadagno del titolo in dollari, senza il cambio).
Si riaddestra ogni sera con le sedute già chiuse.

```bash
python3 rete_usa.py --studia     # barre da 5 minuti dei titoli USA, addestra e verifica: rete_usa_modello.json
python3 rete_usa.py --oggi       # le operazioni della rete nelle ultime 3 sedute
```

## Perché la borsa sale o scende: i mercati che la muovono

Tutte le reti vedono anche i mercati che muovono gli altri (`segnali.MOTORI`): futures su S&P 500 e Nasdaq (Wall Street
guida anche Milano e le crypto), VIX (la paura), tasso USA a 10 anni, petrolio, oro ed euro/dollaro, con il movimento
nell'ultima ora e nell'ultimo giorno diviso per quanto si muovono di solito. Per le azioni in giornata dalle barre da 5
minuti, per le crypto (401 giorni di scambi) dalle barre orarie di Yahoo (2 anni); solo barre già chiuse prima di ogni
decisione. Lo studio dei segnali di ogni rete dice quali contano: sulle azioni italiane in giornata il più legato a
quello che succede dopo è il petrolio dell'ultimo giorno, poi il giorno della settimana e i futures di Wall Street.

## L'universo allargato della rete del medio periodo: `universo_esteso.py`

La rete del medio periodo impara da 368 titoli invece di 188: in più il Nasdaq 100, circa 90 grandi azioni europee
(euro, Regno Unito, Svizzera, nord Europa; costi 0,3 % per le tasse sulle transazioni) e 26 ETF di settore, di fattore e
di area quotati a Milano. Con 5 reti nella media (una sola dipendeva troppo dal caso: +0,45 % o +0,66 % a settimana con
due partenze diverse), sugli anni mai visti: tutti i titoli a una settimana +0,38 % contro +0,14 % (t 3,4); le 3 scelte
settimanali tra 40 ETF +0,53 % contro +0,16 % (t 4,4); il piano con la rete +15,8 % l'anno, Sharpe 1,56, calo -14,3 %.

## I bilanci delle aziende nella rete: `bilanci.py`

Per le azioni USA la rete del medio periodo vede anche il bilancio, dai dati XBRL della SEC (data.sec.gov, con un nome
generico, senza dati personali): utili sul valore di borsa (value), redditività del patrimonio e margine (quality),
crescita dei ricavi, passività sulle attività, crescita del dividendo. Ogni numero conta solo dal giorno in cui è stato
depositato alla SEC. Il codice SEC di ogni titolo si trova confrontando i nomi e confermando con il ticker (165 su 171).
Con la stessa verifica: azioni USA a un mese +1,35 % contro +1,15 % senza bilanci (la media fa +1,24 %); nel resto
nessuna differenza oltre il caso. Il piano con la rete: +15,4 % l'anno, Sharpe 1,56, calo massimo -12,8 %.

## Il portafoglio con la rete neurale: `portafoglio.py`

Le strategie che hanno funzionato messe insieme, settimana per settimana, con i costi, dal 2021 al 2026: anni che la rete
non aveva visto (ogni anno impara solo da quelli prima). Il piano con la rete (50 % SWDA, 20 % le scelte settimanali
della rete sugli ETF, 10 % Faber, 10 % obbligazioni in euro, 10 % crypto in tendenza) ha fatto +13,9 % l'anno, volatilità
9,4 %, Sharpe 1,44, calo massimo -12,9 %; il solo SWDA +13,1 %, Sharpe 1,01, calo -18,9 %; il classico 80/20 +10,1 %,
Sharpe 0,95. Le sole scelte della rete sugli ETF: +20,4 % l'anno, Sharpe 1,49, calo -12,3 % (tasse escluse, e vanno
ruotate ogni settimana). Il robot segue il piano nel conto "Il piano con la rete", ribilanciato ogni lunedì.

```bash
python3 portafoglio.py     # i pezzi, la rete fuori campione e le combinazioni: portafoglio.json (mezzo minuto)
```

## Le altre funzioni del piano

Nella pagina "Il piano": il **calcolatore dell'obiettivo** (quanto capitale serve per guadagnare una cifra a settimana,
al netto delle tasse, e quanto oscilla), **il tuo portafoglio e il piano** (cosa comprare e vendere per seguire il piano
della settimana, con le tasse stimate), **dove puoi arrivare** (migliaia di futuri dal ricampionamento a blocchi delle
settimane vere del portafoglio), **la rete dal vivo** (`diario_rete.json`: le scelte di ogni settimana e il risultato
vero una settimana dopo) e **gli avvisi sul telefono** con ntfy (`notifiche.json`: subito i conti del piano, ogni ora un
riassunto degli altri). Il robot si può far ripartire con 1.000, 5.000, 10.000 o 50.000 € per strategia; il comando
arriva al motore anche dal sito GitHub, con ntfy. `carry_crypto.py` misura il carry delle crypto sui futures di Kraken:
quest'anno circa il 3 % su Bitcoin ed Ethereum, zero o in perdita sulle altre.

## Costi e tasse: cambiare solo quando conviene

Con le tasse italiane (26 % sui guadagni degli ETF quando si vende, senza compensare le perdite degli ETF) cambiare le
scelte ogni settimana costa moltissimo. `portafoglio.py` simula il conto che segue la rete sugli ETF con costi e tasse
vere: cambiando ogni settimana +29,1 % lordo diventa +10,4 % netto (127 cambi l'anno), meno di SWDA tenuto (+10,6 %
netto). Tenendo un ETF finché la sua probabilità resta entro un margine dal terzo migliore (margine scelto ogni anno
sugli anni prima, di solito 1-2 punti) resta +15,0 % l'anno netto con 84 cambi. Il robot usa il margine imparato.

## Il piano (pagina dell'app)

La pagina "Il piano" mette insieme tutto quello che l'app ha imparato e si aggiorna da sola a ogni aggiornamento: lo
stato del mercato (borsa USA rispetto alla media di 200 giorni, quanti ETF sono sopra la media di 10 mesi, quanto la
tendenza delle crypto tiene in euro), il modo migliore per guadagnare a breve, medio e lungo termine con i numeri della
verifica, e le occasioni di oggi per ETF, obbligazioni (dalle più sicure), azioni USA e italiane e crypto, segnando
quando regole, rete neurale e libri sono d'accordo.

## Come guadagnano i professionisti, e cosa ne abbiamo preso

Dalle fonti verificate: quasi tutti quelli che comprano e vendono in giornata perdono (Barber, Lee, Liu e Odean su
Taiwan: meno dell'1 % guadagna in modo affidabile dopo i costi; in Brasile il 97 % perde). Chi fa soldi in giornata sono
i market maker (Virtu: un solo giorno in perdita su 1.238), con costi minimi, sconti dalle borse e tecnologia, non una
strategia copiabile. I fondi istituzionali guadagnano soprattutto con le tendenze di settimane e mesi (AQR: un secolo di
prove), tenendo il rischio costante (Moreira e Muir, Journal of Finance 2017); sulle crypto il momento è uno dei tre
fattori (Liu, Tsyvinski e Wu, Journal of Finance 2022) e il carry tra futures e pronti può superare il 40 % l'anno, ma
precede i crolli (BIS, working paper 1087).

`crypto_tendenza.py` prova la tendenza come i fondi sulle crypto: ogni giorno, per ogni crypto, la media di tre momenti
(1, 3 e 12 mesi positivi), peso = segnale x volatilità obiettivo / volatilità dell'ultimo mese, il resto in euro, solo
acquisti, 0,2 % di costi sulla parte scambiata. Dal 2017 al 2026 sulle 12 crypto: +21 % l'anno, volatilità 22 %, Sharpe
0,99, calo massimo -43 % (tutte in parti uguali: -87 %; solo Bitcoin: -83 %). Nella metà recente (2022-2026): +11,8 %
l'anno, Sharpe 0,69, calo massimo -24 %, meglio di Bitcoin (Sharpe 0,58, -52 %) e del paniere (0,39, -70 %). Il robot la
segue nel conto "Crypto, tendenza come i fondi", ribilanciato una volta al giorno.

```bash
python3 crypto_tendenza.py     # chiusure giornaliere, studio e pesi di oggi: crypto_tendenza.json
```

## Le strategie dei libri migliori: `strategie_lungo.py`

Le regole di tendenza e momento dei libri più apprezzati, provate dal 2017 al 2026 sui mercati dell'app con i costi:
Antonacci ("Dual Momentum Investing"), Faber ("A Quantitative Approach to Tactical Asset Allocation"), Clenow ("Stocks
on the Move") e la tendenza dei fondi AQR con volatilità obiettivo. In questi anni di borse in salita comprare e tenere
un paniere diversificato ha guadagnato di più (ETF in parti uguali +10,4 % l'anno, azioni USA in parti uguali +15,7 %),
ma con cali fino al -34/-39 %. Le regole dei libri tagliano le perdite: Faber sugli ETF +7,4 % l'anno con calo massimo
-14 % (SWDA -34 %) e Sharpe 0,87 contro 0,82; Clenow sulle azioni italiane calo -9 % contro -42 % dell'indice. Il robot
segue Faber nel conto "ETF, media di 10 mesi", ribilanciato a fine mese.

```bash
python3 strategie_lungo.py     # 10 anni di chiusure giornaliere, strategie e pesi del mese: strategie_lungo.json
```

## Medio e lungo periodo con la rete neurale: `rete_lungo.py`

Ogni settimana, per 188 titoli (azioni USA e italiane, ETF azionari e obbligazionari, oro, crypto), la rete vede il titolo
(momento di un anno, tre mesi, un mese, una settimana, media di 200 giorni, massimo di 52 settimane, volatilità, categoria)
e il mondo, del giorno prima: S&P 500 e FTSE MIB nell'ultimo mese, S&P 500 sulla media di 200 giorni, VIX e la sua
variazione, tasso a 10 anni e curva dei tassi (10 anni meno 3 mesi), dollaro, petrolio, oro, credito (HYG contro LQD),
euro/dollaro, Fear & Greed. Stima la probabilità di chiudere in guadagno dopo i costi tra 7, 30 e 91 giorni.

Verifica anno per anno (2021-2026): ogni anno impara solo dagli esiti chiusi prima, poi sceglie ogni settimana il meglio
10 %. A una settimana le scelte fanno +0,71 % contro +0,18 % di tutti i titoli, +0,20 % della regola del momento e +0,25 %
di titoli a caso con la stessa miscela di categorie (t 3,0); a un mese +2,47 % contro +1,36 % (t 1,2, non basta); a tre
mesi la differenza è nel rumore. I dati più legati al mese dopo sono quelli del mondo: dopo un mese in calo di FTSE MIB e
S&P 500, e con il VIX alto, i rendimenti dopo sono stati in media più alti (il premio per la paura).

```bash
python3 rete_lungo.py      # chiusure giornaliere (10 anni), studio dei segnali, verifica, scelte di oggi: rete_lungo.json (un minuto)
```

## Le regole della tesi di Sperti e del libro di Rosenbloom: `regole_libri.py`

```bash
python3 regole_libri.py      # 2 anni di barre da 60 minuti (Yahoo), circa un minuto; scrive regole_libri.json
```

Le regole intraday di due testi, scritte in codice come sono descritte e provate sui titoli del FTSE MIB (e, per
Rosenbloom, sulle 12 crypto) con barre da 60 minuti dal 2024-01-04 al 2026-11-19: dalla tesi di Claudio Sperti
"Silloge di metodi operativi per il trading azionario intraday" (Università di Bologna, 2010) l'Opening Gap all'1 %,
l'Opening Gap al 2 % di James Altucher, l'80-20 di Larry Connors e l'Oops di Larry Williams, con stop all'1 %, obiettivi
come nella tesi e uscita in chiusura; dal libro di Corey Rosenbloom "Guida completa al trading" l'impulse buy (dopo un
nuovo massimo di prezzo e di momentum MACD 3/10, compra sul ritorno alla media esponenziale a 20, stop sotto quella a
50, obiettivo il massimo dell'impulso) e il bullish cradle (ritorno sull'incrocio rialzista delle medie a 20 e 50,
obiettivo 2 volte il rischio). Costi 0,1 % per lato sulle azioni e 0,2 % sulle crypto; se nella stessa ora si toccano
stop e obiettivo vale lo stop; con un ordine stop la barra d'entrata non conta (il minimo è venuto prima).

| Mercato | Regola | operazioni | in guadagno | media | prima metà | seconda metà |
|---|---|---|---|---|---|---|
| azioni | Opening Gap al 2 % di James Altucher (tesi di Sperti) | 721 | 33 % | -0,05 % | -0,11 % | +0,00 % |
| azioni | 80-20 di Larry Connors (tesi di Sperti) | 56 | 41 % | -0,13 % | -0,10 % | -0,15 % |
| azioni | Opening Gap all'1 % (tesi di Sperti) | 2293 | 36 % | -0,13 % | -0,15 % | -0,12 % |
| azioni | Oops di Larry Williams, versione della tesi | 975 | 42 % | -0,16 % | -0,21 % | -0,12 % |
| azioni | Bullish cradle di Rosenbloom | 1643 | 36 % | -0,22 % | -0,21 % | -0,22 % |
| azioni | Impulse buy di Rosenbloom | 1588 | 33 % | -0,25 % | -0,23 % | -0,26 % |
| crypto | Bullish cradle di Rosenbloom | 1367 | 29 % | -0,53 % | -0,55 % | -0,52 % |
| crypto | Impulse buy di Rosenbloom | 1139 | 24 % | -0,60 % | -0,65 % | -0,58 % |

Nessuna regola guadagna dopo i costi; la più vicina al pareggio è l'Opening Gap al 2 % di Altucher (il rimbalzo dopo
un'apertura molto sotto c'è, ma vale circa quanto i costi). La tesi riporta i risultati prima delle commissioni e con
la leva fino a 20 volte, che moltiplica anche le perdite.

## Test

```bash
python3 -m unittest discover -s tests                         # settimana, simula, intraday, crypto_live, libri, giornata, notte, robot, crypto_lungo, live, app, rete, rete_live, rete_azioni, segnali e regole_libri, offline
cd .claude/skills && python3 -m unittest discover -s tests    # le skill trader-*
```

Non è consulenza finanziaria. La maggior parte di chi fa day trading perde soldi.
