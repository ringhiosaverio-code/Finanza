"""Test offline di simula.py: niente rete.

    python3 -m unittest discover -s tests
"""

import json
import math
import os
import random
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import simula as M  # noqa: E402


def series(n, drift, vol, seed=1, start=100.0):
    rnd = random.Random(seed)
    p, out = start, []
    for _ in range(n):
        p *= math.exp(drift + vol * rnd.gauss(0, 1))
        out.append(p)
    return ["D%05d" % i for i in range(n)], out


class Isin(unittest.TestCase):
    def test_valid_codes(self):
        for c in ("US0378331005", "IT0003132476", "IE00B4L5Y983", "it0000072618"):
            self.assertTrue(M.isin_ok(c), c)

    def test_wrong_check_digit_or_format(self):
        for c in ("US0378331006", "IT000313247", "1T0003132476", "ENI.MI", ""):
            self.assertFalse(M.isin_ok(c), c)

    def test_resolve_rejects_a_mistyped_isin_before_searching(self):
        with self.assertRaises(M.SimError):
            M.resolve("IT0003132477")

    def test_pick_quote_prefers_the_home_market(self):
        qs = [{"symbol": "STMPA.PA", "exchange": "PAR", "quoteType": "EQUITY"},
              {"symbol": "STMMI.MI", "exchange": "MIL", "quoteType": "EQUITY"},
              {"symbol": "STM", "exchange": "NYQ", "quoteType": "EQUITY"}]
        self.assertEqual(M.pick_quote(qs, "NL0000226223")["symbol"], "STMMI.MI")
        self.assertEqual(M.pick_quote(qs, "US0000000000")["symbol"], "STM")
        self.assertIsNone(M.pick_quote([{"symbol": "X", "quoteType": "OPTION"}]))


class Series(unittest.TestCase):
    def test_parses_and_drops_an_unfinished_session(self):
        now = int(time.time())
        doc = {"chart": {"result": [{
            "meta": {"gmtoffset": 0, "currentTradingPeriod": {"regular": {"end": now + 3600}}},
            "timestamp": [now - 2 * 86400, now - 86400, now],
            "indicators": {"adjclose": [{"adjclose": [10.0, None, 11.0]}]}}]}}
        meta, dates, closes = M.series(json.dumps(doc))
        self.assertEqual(closes, [10.0])                 # nullo saltato, oggi non finito tolto

    def test_error_from_yahoo(self):
        with self.assertRaises(M.SimError):
            M.series(json.dumps({"chart": {"result": None, "error": {"description": "No data found"}}}))


class Simulate(unittest.TestCase):
    def setUp(self):
        self.dates, self.closes = series(2600, 0.0006, 0.015, seed=3)
        self.s = M.simulate(self.dates, self.closes, n=4000)

    def test_shape(self):
        self.assertEqual([r["giorni"] for r in self.s["orizzonti"]], [1, 5, 21, 63, 252])
        for r in self.s["orizzonti"]:
            self.assertEqual(set(r["scenari"]), {"zero", "prudente", "passato"})
            self.assertIn(r["affidabilita"]["livello"], ("alta", "media", "bassa"))
        self.assertEqual(len(self.s["ventaglio"]), 13)
        self.assertEqual(len(self.s["grafico"]["dates"]), len(self.s["grafico"]["close"]))

    def test_today_state_matches_direct_formulas(self):
        c, st = self.closes, self.s["stato"]
        self.assertEqual(st["sopra_media200"], c[-1] > sum(c[-200:]) / 200)
        self.assertAlmostEqual(st["anno"], c[-1] / c[-253] - 1, places=4)
        self.assertAlmostEqual(st["dal_massimo"], c[-1] / max(c[-252:]) - 1, places=4)
        self.assertTrue(0.15 < st["vol3m"] < 0.35)                     # 1,5 % al giorno ~ 24 % l'anno

    def test_history_counts_real_windows(self):
        one = self.s["orizzonti"][0]["storico"]
        ups = sum(1 for a, b in zip(self.closes, self.closes[1:]) if b > a) / (len(self.closes) - 1)
        self.assertAlmostEqual(one["p_gain"], ups, places=3)
        self.assertEqual(one["indipendenti"], len(self.closes) - 1)

    def test_more_growth_more_gains_and_prudent_in_between(self):
        y = self.s["orizzonti"][-1]["scenari"]
        self.assertLessEqual(y["zero"]["p_gain"], y["prudente"]["p_gain"])
        self.assertLessEqual(y["prudente"]["p_gain"], y["passato"]["p_gain"])
        g = self.s["crescita"]
        self.assertTrue(0 < g["prudente"] < g["passato"])   # crescita passata alta: la prudente la riduce

    def test_one_year_reliability_is_low_with_ten_years_of_data(self):
        self.assertEqual(self.s["orizzonti"][-1]["affidabilita"]["livello"], "bassa")
        self.assertEqual(self.s["orizzonti"][0]["affidabilita"]["livello"], "alta")

    def test_reliability_rules(self):
        self.assertEqual(M.reliability(500, 0.02)["livello"], "alta")
        self.assertEqual(M.reliability(50, 0.02)["livello"], "media")
        self.assertEqual(M.reliability(500, 0.30)["livello"], "bassa")

    def test_too_short(self):
        d, c = series(30, 0, 0.01)
        with self.assertRaises(M.SimError):
            M.simulate(d, c)


if __name__ == "__main__":
    unittest.main()
