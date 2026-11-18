"""Test offline di giornata.py: le regole nella stessa seduta e il piano. Niente rete.

    python3 -m unittest discover -s tests
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import giornata as G  # noqa: E402


def serie(n=260, prezzo=100.0):
    """n sedute piatte: apertura e chiusura al prezzo, massimo +1, minimo -1."""
    d = ["2020-%02d-%02d" % (1 + k // 28 % 12, 1 + k % 28) for k in range(n)]
    O = [prezzo] * n
    return d, O[:], [prezzo + 1] * n, [prezzo - 1] * n, O[:]


class Regole(unittest.TestCase):
    def test_oops_compra_al_minimo_di_ieri_e_vende_in_chiusura(self):
        d, O, H, L, C = serie()
        O[250], L[250], H[250], C[250] = 98.0, 97.5, 100.5, 100.0      # apre sotto il minimo di ieri (99), risale
        ops = dict(G.operazioni(d, O, H, L, C, "oops"))
        self.assertAlmostEqual(ops[d[250]], 100.0 / 99.0 - 1)
        self.assertEqual(len(ops), 1)

    def test_oops_niente_se_non_risale(self):
        d, O, H, L, C = serie()
        O[250], L[250], H[250], C[250] = 98.0, 97.0, 98.5, 98.2
        self.assertEqual(G.operazioni(d, O, H, L, C, "oops"), [])

    def test_gap_giu_di_almeno_un_escursione_media(self):
        d, O, H, L, C = serie()
        O[250], L[250], H[250], C[250] = 97.0, 96.5, 99.5, 99.0        # escursione media 2: gap di -3 %
        ops = dict(G.operazioni(d, O, H, L, C, "gapgiu"))
        self.assertAlmostEqual(ops[d[250]], 99.0 / 97.0 - 1)
        O[250] = 99.5                                                  # gap di -0,5 %: troppo piccolo
        self.assertNotIn(d[250], dict(G.operazioni(d, O, H, L, C, "gapgiu")))

    def test_ogni_giorno_e_primo_del_mese(self):
        d, O, H, L, C = serie()
        self.assertEqual(len(G.operazioni(d, O, H, L, C, "ogni")), 260 - 201)
        primi = [x for x, _ in G.operazioni(d, O, H, L, C, "primo")]
        self.assertTrue(primi and all(x.endswith("-01") for x in primi))

    def test_storia_con_i_costi(self):
        d, O, H, L, C = serie()
        O[250], L[250], H[250], C[250] = 98.0, 97.5, 100.5, 100.0
        s = G.storia(d, O, H, L, C, 0.001)
        self.assertEqual(s["n"], 1)
        self.assertAlmostEqual(s["media"], round(100.0 / 99.0 - 1 - 0.001, 5))
        self.assertEqual(s["p_gain"], 1.0)


class Lettore(unittest.TestCase):
    def test_volumi_in_valuta_e_seduta_vuota_dai_metadati(self):
        ts = [1767600000 + k * 86400 for k in range(3)]               # tre giorni di gennaio 2026
        res = {"meta": {"gmtoffset": 0, "regularMarketTime": ts[2] + 3600, "regularMarketPrice": 11.0,
                        "regularMarketDayHigh": 11.5, "regularMarketDayLow": 10.4,
                        "currentTradingPeriod": {"regular": {"start": ts[2] + 86400, "end": ts[2] + 90000}}},
               "timestamp": ts, "indicators": {"quote": [{"open": [10, 10.2, None], "high": [10.5, 10.6, None],
                                                           "low": [9.8, 10, None], "close": [10.2, 10.4, None],
                                                           "volume": [1000, 2000, None]}],
                                               "adjclose": [{"adjclose": [10.2, 10.4, None]}]}}
        text = json.dumps({"chart": {"result": [res]}})
        with mock.patch.object(G.simula, "fetch_max", return_value=text), \
                mock.patch.object(G.simula.time, "time", return_value=ts[2] + 50000), \
                mock.patch.object(G.settimana.time, "time", return_value=ts[2] + 50000):
            d, O, H, L, C, V = G.giornaliere("X")
        self.assertEqual(len(d), 3)
        self.assertEqual((H[-1], L[-1], C[-1]), (11.5, 10.4, 11.0))
        self.assertAlmostEqual(V[0], 1000 * 10.2)


if __name__ == "__main__":
    unittest.main()
