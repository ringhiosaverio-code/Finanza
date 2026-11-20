#!/usr/bin/env python3
"""Le reti neurali delle azioni sulle barre orarie di Yahoo: 2 anni di storia (circa 500 sedute) invece dei 60 giorni
delle barre da 5 minuti. Lo stesso codice di rete_azioni.py, con una barra di un'ora.

    python3 rete_ore.py --studia            # azioni italiane: rete_azioni_ore_modello.json
    python3 rete_ore.py --studia --usa      # azioni USA: rete_usa_ore_modello.json

Non è consulenza finanziaria.
"""

import importlib.util
import os
import sys


def mercato(nome):
    """Il modulo rete_azioni caricato per un mercato orario ("italia_ore" o "usa_ore")."""
    chiave = "rete_azioni_" + nome
    if chiave in sys.modules:
        return sys.modules[chiave]
    spec = importlib.util.spec_from_file_location(chiave, os.path.join(os.path.dirname(os.path.abspath(__file__)), "rete_azioni.py"))
    m = importlib.util.module_from_spec(spec)
    m.MERCATO_SCELTO = nome
    sys.modules[chiave] = m
    spec.loader.exec_module(m)
    return m


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    usa = "--usa" in argv
    if usa:
        argv.remove("--usa")
    m = mercato("usa_ore" if usa else "italia_ore")
    # sulle barre orarie le finestre di prova sono più lunghe: ci sono 2 anni di sedute
    m.FINESTRE = dict(giorni_test=60, giorni_val=45, embargo=2, min_addestramento=120, max_finestre=8, margine_fine=1.0)
    return m.main(argv)


if __name__ == "__main__":
    sys.exit(main())
