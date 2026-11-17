"""Test offline di settimana.py su dati sintetici: niente rete.

    python3 -m unittest discover -s tests
"""

import json
import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import settimana as S  # noqa: E402


def walk(n, drift, vol, seed, start=100.0):
    rnd = random.Random(seed)
    p, out = start, []
    for _ in range(n):
        p *= math.exp(drift + vol * rnd.gauss(0, 1))
        out.append(p)
    return out


def calendar(n):
    import datetime
    d0 = datetime.date(2020, 1, 1)
    return [(d0 + datetime.timedelta(days=i)).isoformat() for i in range(n)]


class NoLookAhead(unittest.TestCase):
    def test_signal_ignores_future_prices(self):
        p = walk(600, 0.0005, 0.01, 1)
        a = S.Stock("A", p)
        b = S.Stock("A", p[:400] + [x * 3 for x in p[400:]])   # futuro stravolto
        for i in (300, 350, 399):
            self.assertEqual(a.signal(i), b.signal(i))

    def test_needs_a_full_year(self):
        s = S.Stock("A", [None] * 50 + walk(300, 0, 0.01, 2))
        self.assertIsNone(s.signal(50 + S.LOOKBACK - 1))
        self.assertIsNotNone(s.signal(50 + S.LOOKBACK))

    def test_indicators_match_direct_formulas(self):
        p = walk(400, 0.0003, 0.012, 3)
        s = S.Stock("A", p)
        i = 380
        self.assertAlmostEqual(s.sma(i), sum(p[i - 199:i + 1]) / 200, places=6)
        r = [math.log(p[k] / p[k - 1]) for k in range(i - 62, i + 1)]
        m = sum(r) / len(r)
        vol = math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1)) * math.sqrt(252)
        self.assertAlmostEqual(s.vol(i), vol, places=6)
        self.assertAlmostEqual(s.mom(i), p[i - 21] / p[i - 252] - 1, places=9)


def flat_stock(n=40, price=100.0, rng=1.0):
    """Titolo piatto con candele di ampiezza costante: ATR = 2 x rng."""
    bars = [(price, price + rng, price - rng, price)] * n
    return [price] * n, bars


class Rule(unittest.TestCase):
    def make(self, tail):
        closes, bars = flat_stock()
        for k, b in enumerate(tail):
            bars[20 + k] = b
            closes[20 + k] = b[3]
        return S.Stock("X", closes, ohlc=bars)          # segnale al giorno 19, ATR = 2

    def test_target_hit(self):
        s = self.make([(100, 101, 99.5, 100.5), (100.5, 115, 100, 112)])
        r = S.trade(s, 19, 3.0, 2.0, 10)
        self.assertEqual((r["outcome"], r["days"]), ("target", 2))
        self.assertAlmostEqual(r["ret"], 112 / 100 - 1)              # target = 100 + 2 x 3 x 2

    def test_gap_below_stop_exits_at_open(self):
        s = self.make([(100, 101, 99.5, 100), (90, 91, 89, 90)])
        r = S.trade(s, 19, 3.0, 2.0, 10)
        self.assertEqual((r["outcome"], round(r["ret"], 4)), ("stop", -0.10))

    def test_both_same_day_counts_as_stop(self):
        s = self.make([(100, 101, 99.5, 100), (100, 120, 80, 100)])
        self.assertEqual(S.trade(s, 19, 3.0, 2.0, 10)["outcome"], "stop")

    def test_limit_not_filled(self):
        s = self.make([(105, 106, 104, 105)])                         # limite = 100 + 0,5 x 2 = 101
        self.assertEqual(S.trade(s, 19, 3.0, 2.0, 10), {"filled": False})

    def test_no_stop_no_target_exits_on_the_date(self):
        s = self.make([(100, 101, 99.5, 100), (100, 120, 60, 95), (95, 96, 94, 97)])
        r = S.trade(s, 19, 0, 0, 3)
        self.assertEqual((r["outcome"], r["days"]), ("tempo", 3))
        self.assertAlmostEqual(r["ret"], -0.03)                       # chiusura del 3o giorno = 97

    def test_rule_grid(self):
        rules = S.all_rules()
        self.assertIn(S.DEFAULT_RULE, rules)
        self.assertNotIn((0, 2.0, 21), rules)
        self.assertEqual(len(rules), 39)

    def test_trading_days_skip_weekends_and_holidays(self):
        days = S.trading_days_after("2026-11-24", 3)                  # giovedì 26 = Thanksgiving
        self.assertEqual(days, ["2026-11-25", "2026-11-27", "2026-11-30"])


class Stats(unittest.TestCase):
    def test_stats(self):
        st = S.stats([-0.1, 0.0, 0.1, 0.2])
        self.assertEqual(st["n"], 4)
        self.assertAlmostEqual(st["p_gain"], 0.5)
        self.assertAlmostEqual(st["median"], 0.05)

    def test_independent_windows(self):
        self.assertEqual(S.independent(list(range(0, 100, 5)), 5), 20)
        self.assertEqual(S.independent(list(range(0, 100, 5)), 21), 4)
        self.assertEqual(S.confidence(30), "alta")
        self.assertEqual(S.confidence(9), "bassa")


class Parse(unittest.TestCase):
    def test_parse_drops_nulls_and_cuts(self):
        doc = {"chart": {"result": [{"meta": {"gmtoffset": 0, "shortName": "X"},
                                     "timestamp": [0, 86400, 172800],
                                     "indicators": {"adjclose": [{"adjclose": [10.0, None, 12.0]}]}}]}}
        meta, out, _ = S.parse(json.dumps(doc))
        self.assertEqual(out, {"1970-01-01": 10.0, "1970-01-03": 12.0})
        _, cut, _ = S.parse(json.dumps(doc), cut="1970-01-02")
        self.assertEqual(list(cut), ["1970-01-01"])

    def test_align_forward_fills_after_first_price(self):
        out = S.align({"A": {"d2": 5.0, "d4": 6.0}}, ["d1", "d2", "d3", "d4"])
        self.assertEqual(out["A"], [None, 5.0, 5.0, 6.0])


class Run(unittest.TestCase):
    def test_strong_steady_trend_is_picked_and_report_is_complete(self):
        n = 900
        stocks = [S.Stock("UP", walk(n, 0.003, 0.008, 10), "Salita")]
        stocks += [S.Stock("R%d" % k, walk(n, 0.0, 0.02, 20 + k)) for k in range(12)]
        market = S.Stock("SPY", walk(n, 0.0003, 0.01, 99))
        r = S.run(stocks, market, calendar(n), 0.001)
        self.assertEqual(r["picks"][0]["symbol"], "UP")
        self.assertLessEqual(len(r["picks"]), S.TOP)
        for p in r["picks"]:
            self.assertEqual(set(p["hold"]), {h for h, _ in S.HORIZONS})
        self.assertEqual(len(r["backtest"]["dates"]), len(r["backtest"]["curves"]["strategia"]))
        self.assertIn("t_eccesso", r["backtest"]["metrics"])
        self.assertEqual(len(r["pooled"]), len(S.all_rules()))
        self.assertEqual(len(r["future_days"]), max(S.HOLDS) + 1)


if __name__ == "__main__":
    unittest.main()
