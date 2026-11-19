#!/usr/bin/env python3
"""La rete neurale per le azioni USA in giornata (S&P 100, NYSE e Nasdaq, 09:30-16:00 di New York): lo stesso codice
della rete italiana (rete_azioni.py), con gli orari, i titoli, i costi e le notizie di Wall Street.

    python3 rete_usa.py --studia      # barre da 5 minuti, addestra, verifica: rete_usa_modello.json
    python3 rete_usa.py --oggi        # le operazioni che la rete fa nelle ultime sedute (quelle che il robot rigioca)

Compra durante tutta la seduta (una soglia per ogni ora, come per Milano) e chiude al più tardi alla chiusura.
Non è consulenza finanziaria.
"""

import importlib.util
import os
import sys


def _carica():
    nome = "rete_azioni_usa"
    if nome in sys.modules:
        return sys.modules[nome]
    spec = importlib.util.spec_from_file_location(nome, os.path.join(os.path.dirname(os.path.abspath(__file__)), "rete_azioni.py"))
    m = importlib.util.module_from_spec(spec)
    m.MERCATO_SCELTO = "usa"
    sys.modules[nome] = m
    spec.loader.exec_module(m)
    return m


_m = _carica()
globals().update({k: v for k, v in vars(_m).items() if not k.startswith("__")})

if __name__ == "__main__":
    sys.exit(_m.main())
