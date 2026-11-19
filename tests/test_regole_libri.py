"""Test offline di regole_libri.py: uscite (stop prima dell'obiettivo, ordine stop), gap della tesi, Rosenbloom. Niente rete.

    python3 -m unittest discover -s tests
"""

import datetime
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import regole_libri as RL  # noqa: E402


def sedute(barre_per_giorno, giorni=25, da=datetime.date(2030, 1, 7)):
    """Orari (UTC) di barre orarie dalle 9 alle 17 ora italiana, solo giorni feriali."""
    t, g = [], da
    while len({datetime.datetime.fromtimestamp(x, RL.ROMA).date() for x in t}) < giorni:
        if g.weekday() < 5:
            for k in range(barre_per_giorno):
                t.append(datetime.datetime(g.year, g.month, g.day, 9 + k, 0, tzinfo=RL.ROMA).timestamp())
        g += datetime.timedelta(days=1)
    return np.array(t)


class Uscite(unittest.TestCase):
    def test_nella_stessa_barra_vale_lo_stop(self):
        o, h, l, c = (np.array(x, float) for x in ([100, 100], [103, 101], [98, 100], [100, 100]))
        self.assertEqual(RL.esci(o, h, l, c, 0, 1, 100, 99, 102), (99, 0, "stop"))

    def test_obiettivo_e_chiusura(self):
        o, h, l, c = (np.array(x, float) for x in ([100, 100, 101], [100.5, 101, 103], [99.5, 99.8, 100.5], [100, 101, 102]))
        self.assertEqual(RL.esci(o, h, l, c, 0, 2, 100, 99, 102.5)[2], "obiettivo")
        self.assertEqual(RL.esci(o, h, l, c, 0, 1, 100, 99, 105), (101, 1, "chiusura"))

    def test_con_un_ordine_stop_la_barra_d_entrata_non_conta(self):
        o, h, l, c = (np.array(x, float) for x in ([97, 100], [100.5, 100.5], [96, 99.5], [100, 100.2]))
        self.assertEqual(RL.esci(o, h, l, c, 0, 1, 100, 99, 104, ordine_stop=True), (100.2, 1, "chiusura"))
        self.assertEqual(RL.esci(o, h, l, c, 0, 1, 100, 99, 104)[2], "stop")


class Tesi(unittest.TestCase):
    def test_gap_all_apertura_e_uscita_in_giornata(self):
        t = sedute(9)
        n = len(t)
        c = np.full(n, 100.0)
        o, h, l = c.copy(), c * 1.001, c * 0.999
        d0 = 22 * 9                                                       # la 23ª seduta apre il 3 % sotto
        o[d0:d0 + 9] = c[d0:d0 + 9] = 97.0
        h[d0:d0 + 9], l[d0:d0 + 9] = 97.2, 96.8
        h[d0 + 3] = 102.5                                                 # poi risale oltre la chiusura di ieri +2 %
        ops = RL.regole_tesi(t, o, h, l, c, 0.0)
        per = {nome: (r, m) for nome, g, r, m in ops}
        self.assertIn("gap_sperti", per)
        self.assertIn("altucher", per)
        self.assertEqual(per["altucher"][1], "obiettivo")
        self.assertAlmostEqual(per["altucher"][0], 102.0 / 97.0 - 1, places=6)

    def test_niente_gap_niente_operazioni(self):
        t = sedute(9)
        c = np.full(len(t), 100.0)
        ops = RL.regole_tesi(t, c, c * 1.001, c * 0.999, c, 0.001)
        self.assertFalse([x for x in ops if x[0] in ("gap_sperti", "altucher")])


class Rosenbloom(unittest.TestCase):
    def test_crypto_esce_entro_24_ore_e_le_azioni_in_giornata(self):
        rng = np.random.default_rng(3)
        n = 3000
        c = 100 * np.exp(np.cumsum(rng.standard_normal(n) * 0.006 + 0.0004))
        o = np.r_[c[0], c[:-1]]
        h, l = np.maximum(o, c) * 1.003, np.minimum(o, c) * 0.997
        t = 1.9e9 + 3600.0 * np.arange(n)
        ops = RL.regole_rosenbloom(t, o, h, l, c, 0.002, ore_max=24)
        self.assertTrue(ops)
        self.assertTrue({x[0] for x in ops} <= {"impulse_buy", "cradle"})
        self.assertTrue(all(x[3] in ("stop", "obiettivo", "chiusura") for x in ops))
        ts = sedute(9, giorni=60)
        m = len(ts)
        ops2 = RL.regole_rosenbloom(ts, o[:m], h[:m], l[:m], c[:m], 0.001, tz=RL.ROMA)
        self.assertTrue(all(-0.2 < x[2] < 0.2 for x in ops2))

    def test_riassunto(self):
        ops = [("altucher", "2030-01-01", 0.01, "obiettivo"), ("altucher", "2030-06-01", -0.01, "stop")]
        r = RL.riassunto(ops, "2030-03-01")["altucher"]
        self.assertEqual((r["n"], r["vinte"], r["meta"][0]["n"], r["meta"][1]["n"]), (2, 0.5, 1, 1))
        self.assertEqual(r["uscite"], {"stop": 1, "obiettivo": 1, "chiusura": 0})


if __name__ == "__main__":
    unittest.main()
