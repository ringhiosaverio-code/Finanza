"""Test offline di libri.py: figure di candele, RSI, regole e criterio "regge". Niente rete.

    python3 -m unittest discover -s tests
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import libri as L  # noqa: E402


def discesa(n=20, da=100.0, passo=1.0):
    """n candele in discesa: apertura sopra, chiusura sotto, escursione di 1."""
    C = np.array([da - passo * k for k in range(n)])
    O = C + 0.4
    return O, O + 0.1, C - 0.1, C


class Figure(unittest.TestCase):
    def aggiungi(self, O, H, L_, C, o, h, l, c):
        return (np.append(O, o), np.append(H, h), np.append(L_, l), np.append(C, c))

    def test_engulfing_dopo_un_ribasso(self):
        O, H, L_, C = discesa()
        O, H, L_, C = self.aggiungi(O, H, L_, C, C[-1] - 0.2, O[-1] + 0.6, C[-1] - 0.3, O[-1] + 0.5)
        f = L.figure(O, H, L_, C)
        self.assertTrue(f["Engulfing rialzista"][-1])
        self.assertFalse(f["Tre soldati bianchi"][-1])

    def test_martello(self):
        O, H, L_, C = discesa()
        c = C[-1] - 1
        O, H, L_, C = self.aggiungi(O, H, L_, C, c - 0.2, c + 0.02, c - 1.5, c)   # corpo 0,2, ombra sotto 1,3
        self.assertTrue(L.figure(O, H, L_, C)["Martello"][-1])

    def test_nessuna_figura_senza_ribasso(self):
        O, H, L_, C = (x[::-1].copy() for x in discesa())                        # in salita
        O, H, L_, C = self.aggiungi(O, H, L_, C, C[-1] - 0.2, C[-1] + 1.2, C[-1] - 0.3, C[-1] + 1.0)
        self.assertFalse(any(v[-1] for v in L.figure(O, H, L_, C).values()))


class Indicatori(unittest.TestCase):
    def test_rsi_2(self):
        self.assertAlmostEqual(L.rsi(np.array([10, 9, 8, 7, 6.0]))[-1], 0.0)
        self.assertAlmostEqual(L.rsi(np.array([6, 7, 8, 9, 10.0]))[-1], 100.0)

    def test_sma(self):
        np.testing.assert_allclose(L.sma(np.array([1, 2, 3, 4.0]), 2)[1:], [1.5, 2.5, 3.5])


class Regole(unittest.TestCase):
    def test_giro_di_fine_mese_dal_penultimo_giorno(self):
        d = ["2024-01-%02d" % k for k in range(25, 32)] + ["2024-02-%02d" % k for k in range(1, 8)]
        C = np.arange(1.0, len(d) + 1)
        ops = L.operazioni_giorno(d, C, C, C, C, "mese")
        self.assertEqual([(o[0], o[1]) for o in ops], [("2024-01-30", 4)])
        self.assertAlmostEqual(ops[0][2], C[d.index("2024-01-30") + 4] / C[d.index("2024-01-30")] - 1)

    def test_regge_solo_se_meglio_del_tenere_in_entrambi_i_periodi(self):
        buono = {"n": 100, "extra": 0.002, "t": 2.5, "media": 0.004}
        self.assertTrue(L.regge(buono, buono))
        self.assertFalse(L.regge(buono, dict(buono, t=1.5)))
        self.assertFalse(L.regge(buono, dict(buono, media=-0.001)))
        self.assertFalse(L.regge(dict(buono, extra=-0.001), buono))

    def test_riassunto_conta_i_costi_e_raggruppa_per_mese(self):
        ops = [("2020-%02d-01" % (1 + k % 12), 10, 0.01 * (1 if k % 2 else -0.5), 0.0) for k in range(60)]
        r = L.riassunto(ops, 0.0)
        self.assertEqual(r["n"], 60)
        self.assertEqual(r["mesi"], 12)
        self.assertAlmostEqual(r["media"], 0.0025, 5)
        self.assertAlmostEqual(r["p_gain"], 0.5)


if __name__ == "__main__":
    unittest.main()
