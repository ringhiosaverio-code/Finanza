#!/usr/bin/env bash
# Tiene acceso il tempo reale nel cloud: il server live.py (porta 8770, prezzi ogni 5 secondi) e il motore del robot
# (robot_motore.js). Se sono già accesi non fa niente: lo lancia il controllo di ogni ora.
#   bash tempo_reale.sh [file di stato del robot salvato dal cloud ...]
cd "$(dirname "$0")"
LOG=trader/tempo_reale.log
mkdir -p trader
STATI=()
for f in "$@"; do STATI+=(--stato "$f"); done
if ! curl -s -o /dev/null -m 5 http://127.0.0.1:8770/robot/info; then
  setsid nohup python3 live.py --rete --no-browser --porta 8770 "${STATI[@]}" >> "$LOG" 2>&1 < /dev/null &
  for i in $(seq 1 30); do curl -s -o /dev/null -m 2 http://127.0.0.1:8770/robot/info && break; sleep 1; done
  echo "server avviato"
else
  echo "server già acceso"
fi
if ! pgrep -f "node robot_motore.js" > /dev/null; then
  setsid nohup node robot_motore.js >> "$LOG" 2>&1 < /dev/null &
  echo "motore avviato"
else
  echo "motore già acceso"
fi
if ! pgrep -f "pubblica_stato.py" > /dev/null; then
  setsid nohup python3 pubblica_stato.py >> "$LOG" 2>&1 < /dev/null &
  echo "pubblicazione su GitHub avviata"
fi
if ! pgrep -f "aggiorna_dati_loop" > /dev/null; then
  setsid nohup bash -c 'exec -a aggiorna_dati_loop bash -c "while true; do python3 app.py --leggero > /dev/null 2>&1; sleep 900; done"' >> "$LOG" 2>&1 < /dev/null &
  echo "aggiornamento dei dati ogni 15 minuti avviato"
fi
# il guardiano: ogni minuto riaccende server e motore se si sono spenti (senza bisogno di nessuno)
if ! pgrep -f "tempo_reale_guardiano" > /dev/null; then
  setsid nohup bash -c 'exec -a tempo_reale_guardiano bash -c "while true; do sleep 60; bash tempo_reale.sh $* > /dev/null 2>&1; done"' _ "$@" >> "$LOG" 2>&1 < /dev/null &
  echo "guardiano avviato"
fi
