"""Test offline di live.py: lettura di Yahoo spark, cache delle quotazioni, simboli ammessi. Niente rete.

    python3 -m unittest discover -s tests
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import live as L  # noqa: E402


def spark(*righe):
    """righe: (simbolo, prezzo, chiusura di ieri, borsa) -> testo come lo manda Yahoo."""
    return json.dumps({"spark": {"result": [
        {"symbol": s, "response": [{"meta": {"symbol": s, "regularMarketPrice": p, "chartPreviousClose": c,
                                             "regularMarketTime": 1795000000, "regularMarketDayHigh": p + 1,
                                             "regularMarketDayLow": p - 1, "currency": "EUR", "exchangeName": ex}}]}
        for s, p, c, ex in righe], "error": None}})


class Spark(unittest.TestCase):
    def test_legge_prezzo_chiusura_e_ritardo(self):
        q = L.leggi_spark(spark(("SWDA.MI", 128.1, 127.2, "MIL"), ("BTC-EUR", 58000.0, 59000.0, "CCC")))
        self.assertEqual(q["SWDA.MI"]["p"], 128.1)
        self.assertEqual(q["SWDA.MI"]["prev"], 127.2)
        self.assertEqual(q["SWDA.MI"]["ritardo"], 15)
        self.assertEqual(q["BTC-EUR"]["ritardo"], 0)

    def test_salta_i_titoli_senza_prezzo(self):
        t = json.loads(spark(("A", 10.0, 9.0, "NMS")))
        t["spark"]["result"].append({"symbol": "B", "response": [{"meta": {"symbol": "B"}}]})
        t["spark"]["result"].append({"symbol": "C"})
        self.assertEqual(list(L.leggi_spark(json.dumps(t))), ["A"])


class Cache(unittest.TestCase):
    def test_chiede_a_gruppi_di_20_e_non_richiede_prima_di_5_secondi(self):
        chiamate = []

        def finta(simboli):
            chiamate.append(list(simboli))
            return {s: {"p": 1.0} for s in simboli}

        q = L.Quotazioni(chiedi=finta)
        simboli = ["S%02d" % i for i in range(45)]
        out, err = q.prendi(simboli, adesso=100.0)
        self.assertEqual(len(out), 45)
        self.assertEqual([len(c) for c in chiamate], [20, 20, 5])
        q.prendi(simboli, adesso=103.0)                       # ancora fresche: nessuna richiesta
        self.assertEqual(len(chiamate), 3)
        q.prendi(simboli[:3], adesso=106.0)
        self.assertEqual(chiamate[-1], simboli[:3])

    def test_se_yahoo_non_risponde_restano_le_ultime(self):
        stato = {"giu": False}

        def finta(simboli):
            if stato["giu"]:
                raise OSError("rete giù")
            return {s: {"p": 2.0} for s in simboli}

        q = L.Quotazioni(chiedi=finta)
        q.prendi(["A"], adesso=0.0)
        stato["giu"] = True
        out, err = q.prendi(["A"], adesso=60.0)
        self.assertEqual(out["A"]["p"], 2.0)
        self.assertTrue(err and "Yahoo" in err[0])


class Simboli(unittest.TestCase):
    def test_solo_simboli_validi_senza_doppioni(self):
        self.assertEqual(L.simboli_da("s=AAPL,SWDA.MI,EURUSD%3DX,%3Cscript%3E,AAPL,,BTC-EUR"),
                         ["AAPL", "SWDA.MI", "EURUSD=X", "BTC-EUR"])
        self.assertEqual(len(L.simboli_da("s=" + ",".join("X%d" % i for i in range(300)))), L.MAX_SIMBOLI)


if __name__ == "__main__":
    unittest.main()
