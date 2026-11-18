"""Test offline di crypto_lungo.py: medie, regola della tendenza con i costi, misure, a rate o subito. Niente rete.

    python3 -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import crypto_lungo as CL  # noqa: E402


class Medie(unittest.TestCase):
    def test_media_mobile(self):
        self.assertEqual(CL.medie([1, 2, 3, 4], 2), [None, 1.5, 2.5, 3.5])

    def test_compra_e_tieni(self):
        r, dentro, cambi = CL.rendimenti([10, 11, 12.1], None)
        self.assertEqual((dentro, cambi), (1.0, 0))
        self.assertAlmostEqual(r[0], 0.1)
        self.assertAlmostEqual(r[1], 0.1)

    def test_tendenza_decide_con_la_chiusura_di_ieri_e_paga_i_cambi(self):
        c = [10, 10, 12, 13, 9, 8]                   # media a 2: None, 10, 11, 12.5, 11, 8.5
        r, dentro, cambi = CL.rendimenti(c, 2, costo=0.01)
        # giorno 0: senza media, fuori. 1: 10 non è sopra 10, fuori. 2: 12 > 11 dentro (paga), 3: 13 > 12.5 dentro, 4: 9 < 11 esce (paga)
        self.assertEqual(r[0], 0.0)
        self.assertEqual(r[1], 0.0)
        self.assertAlmostEqual(r[2], 13 / 12 - 1 - 0.01)
        self.assertAlmostEqual(r[3], 9 / 13 - 1)
        self.assertAlmostEqual(r[4], -0.01)
        self.assertEqual(cambi, 2)
        self.assertAlmostEqual(dentro, 2 / 5)

    def test_misure(self):
        m = CL.misure([0.1, -0.5, 0.2])
        self.assertAlmostEqual(m["calo"], -0.5)
        self.assertLess(m["anno"], 0)


class Rate(unittest.TestCase):
    def test_in_salita_tutto_subito_vince(self):
        c = [100 * 1.001 ** i for i in range(800)]
        R = CL.rate({"BTC-EUR": (["d"] * 800, c)})["BTC-EUR"]
        self.assertEqual(R["subito_vince"], 1.0)
        self.assertGreater(R["subito"]["tipico"], R["rate"]["tipico"])

    def test_in_discesa_le_rate_perdono_meno(self):
        c = [100 * 0.999 ** i for i in range(800)]
        R = CL.rate({"BTC-EUR": (["d"] * 800, c)})["BTC-EUR"]
        self.assertEqual(R["subito_vince"], 0.0)
        self.assertGreater(R["rate"]["peggiore"], R["subito"]["peggiore"])


class Oggi(unittest.TestCase):
    def test_sopra_e_sotto_la_media(self):
        c = [100.0] * 250 + [120.0] * 5
        x = CL.oggi({"BTC-EUR": ([str(i) for i in range(255)], c)})[0]
        self.assertTrue(x["sopra200"])
        self.assertEqual(x["giorni"], 5)


if __name__ == "__main__":
    unittest.main()
