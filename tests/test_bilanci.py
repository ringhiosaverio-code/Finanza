"""Test offline di bilanci.py: ogni numero conta solo dalla data di deposito alla SEC, crescite dallo stesso bilancio,
passività ricavate dal totale quando mancano. Niente rete.

    python3 -m unittest discover -s tests
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["FINANZA_SENZA_RETE"] = "1"
import bilanci as B  # noqa: E402

F = {
    "utile": [["2030-02-15", "2029-01-01", "2029-12-31", 100.0, "10-K", "a1"], ["2030-02-15", "2028-01-01", "2028-12-31", 80.0, "10-K", "a1"]],
    "ricavi": [["2030-02-15", "2029-01-01", "2029-12-31", 1000.0, "10-K", "a1"], ["2030-02-15", "2028-01-01", "2028-12-31", 800.0, "10-K", "a1"]],
    "patrimonio": [["2030-02-15", None, "2029-12-31", 500.0, "10-K", "a1"]],
    "passivita": [],
    "totale_passivo": [["2030-02-15", None, "2029-12-31", 2000.0, "10-K", "a1"]],
    "attivita": [["2030-02-15", None, "2029-12-31", 2000.0, "10-K", "a1"]],
    "dividendo": [["2030-02-15", "2029-01-01", "2029-12-31", 2.2, "10-K", "a1"], ["2030-02-15", "2028-01-01", "2028-12-31", 2.0, "10-K", "a1"]],
    "flottante": [["2030-02-15", "2029-06-30", 2000.0]],
}


class Bilanci(unittest.TestCase):
    def test_niente_prima_del_deposito_e_i_numeri_dopo(self):
        giorni = ["2029-06-28", "2029-06-30", "2030-02-01", "2030-03-02", "2030-03-03"]
        prezzi = np.array([10.0, 10.0, 12.0, 20.0, 20.0])
        T = B.tabella(F, giorni, prezzi)
        N = B.NOMI_BILANCI.index
        self.assertTrue(np.all(T[:3] == 0))                                          # prima del 15 febbraio 2030: niente
        r = T[3]
        self.assertEqual(r[N("ha_bilanci")], 1.0)
        self.assertAlmostEqual(r[N("roe")], 100 / 500, places=5)
        self.assertAlmostEqual(r[N("margine")], 0.1, places=5)
        self.assertAlmostEqual(r[N("crescita_ricavi")], 0.25, places=5)
        self.assertAlmostEqual(r[N("debito")], (2000 - 500) / 2000, places=5)      # passività = totale - patrimonio
        self.assertAlmostEqual(r[N("crescita_dividendi")], 0.1, places=5)
        cap = 2000 * 20 / 10                                                         # il flottante portato al prezzo di oggi
        self.assertAlmostEqual(r[N("utili_prezzo")], min(100 / cap, 0.5) * 10, places=5)

    def test_titolo_sconosciuto_a_zero(self):
        T = B.per_titolo("NESSUNO", ["2030-01-01"], np.array([1.0]))
        self.assertTrue(np.all(T == 0))


if __name__ == "__main__":
    unittest.main()
