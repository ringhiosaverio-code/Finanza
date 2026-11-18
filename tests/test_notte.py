"""Test offline del momento notturno (giornata.py) e delle strategie intraday recenti (libri.py). Niente rete.

    python3 -m unittest discover -s tests
"""

import datetime
import json
import math
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import giornata as G  # noqa: E402
import libri as Lb  # noqa: E402


def grafico(aperture, chiusure, inizio=1767600000):
    ts = [inizio + k * 86400 for k in range(len(aperture))]
    return json.dumps({"chart": {"result": [{"meta": {"gmtoffset": 0}, "timestamp": ts, "indicators": {
        "quote": [{"open": aperture, "high": aperture, "low": aperture, "close": chiusure}],
        "adjclose": [{"adjclose": chiusure}]}}]}})


class Notti(unittest.TestCase):
    def test_rendimenti_notturni_con_l_apertura_di_oggi(self):
        text = grafico([10, 11, 12.1], [10.5, 11.5, None])                 # oggi: aperta, non ancora chiusa
        with mock.patch.object(G.simula, "fetch_max", return_value=text):
            date, rend, chiusura, giorno = G.notti("X")
        self.assertEqual(len(rend), 2)
        self.assertAlmostEqual(rend[0], math.log(11 / 10.5))
        self.assertAlmostEqual(rend[1], math.log(12.1 / 11.5))
        self.assertEqual(chiusura, 11.5)

    def test_piano_sceglie_le_notti_migliori_e_le_date(self):
        def finte(sym):
            k = int(sym[1:])
            return (["d"] * 30, [0.001 * k] * 30, 100.0, "2026-11-17")

        universo = ["S%d" % k for k in range(30)]
        lunedi_mattina = datetime.datetime(2026, 11, 16, 9, 0)              # New York, prima dell'apertura
        with mock.patch.object(G, "notti", side_effect=finte), mock.patch.object(G, "prezzi_notte", return_value={}), \
                mock.patch.dict(G.settimana.MERCATI["usa"], {"universo": universo}):
            p = G.piano_notte(log=lambda m: None, adesso=lunedi_mattina)
        self.assertEqual([t["symbol"] for t in p["titoli"]], ["S%d" % k for k in range(29, 19, -1)])
        self.assertEqual((p["compra"], p["vendi"]), ("2026-11-16", "2026-11-17"))
        sera = datetime.datetime(2026, 11, 16, 17, 0)                       # dopo la chiusura: domani
        with mock.patch.object(G, "notti", side_effect=finte), mock.patch.object(G, "prezzi_notte", return_value={}), \
                mock.patch.dict(G.settimana.MERCATI["usa"], {"universo": universo}):
            p = G.piano_notte(log=lambda m: None, adesso=sera)
        self.assertEqual((p["compra"], p["vendi"]), ("2026-11-17", "2026-11-18"))


def sedute(n, prezzo=100.0, vol=1000.0, ore=7):
    """n sedute piatte di `ore` candele (t, o, h, l, c, v)."""
    out = []
    for i in range(n):
        d = "2026-01-%02d" % (i + 1) if i < 28 else "2026-02-%02d" % (i - 27)
        out.append((d, [(i * 86400 + k * 3600, prezzo, prezzo + .2, prezzo - .2, prezzo, vol) for k in range(ore)]))
    return out


class Recenti(unittest.TestCase):
    def test_zona_di_rumore_compra_quando_esce_sopra_e_vende_in_chiusura(self):
        S = sedute(20)
        d, bars = S[-1]
        nuove = [bars[0]] + [(t, 100, 101.5, 100, 101.0, v) for t, o, h, l, c, v in bars[1:-1]] + [(bars[-1][0], 101, 102, 101, 101.5, 1000)]
        S[-1] = (d, nuove)
        ops = Lb.zona_rumore(S, scoperto=False)
        self.assertEqual(len(ops), 1)
        self.assertAlmostEqual(ops[0][1], 101.5 / 101.0 - 1)

    def test_orb_solo_sui_titoli_con_volume_anomalo(self):
        S = sedute(20)
        d, bars = S[-1]
        prima = (bars[0][0], 100, 100.6, 99.9, 100.5, 5000)                  # prima ora in salita, volume 5 volte
        S[-1] = (d, [prima] + [(t, 100.5, 100.8, 100.48, 100.7, v) for t, o, h, l, c, v in bars[1:]])   # sopra la protezione (100,46)
        lunghi, corti = Lb.orb_in_gioco({"X": S, "Y": sedute(20)}, top=20)
        self.assertEqual(len(lunghi), 1)
        self.assertAlmostEqual(lunghi[0][1], 100.7 / 100.5 - 1)
        self.assertEqual(corti, [])


if __name__ == "__main__":
    unittest.main()
