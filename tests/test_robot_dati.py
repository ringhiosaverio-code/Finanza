"""Test offline dei dati del robot: aperture e chiusure ufficiali (giornata.py), aste da live.py. Niente rete.

    python3 -m unittest discover -s tests
"""

import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import giornata as G  # noqa: E402
import live as L  # noqa: E402


def grafico(aperture, chiusure, adj=None, inizio=1767600000):
    ts = [inizio + k * 86400 for k in range(len(aperture))]
    return json.dumps({"chart": {"result": [{"meta": {"gmtoffset": 0}, "timestamp": ts, "indicators": {
        "quote": [{"open": aperture, "high": aperture, "low": aperture, "close": chiusure}],
        "adjclose": [{"adjclose": adj or chiusure}]}}]}})


class SerieNotte(unittest.TestCase):
    def test_apertura_corretta_e_chiusura_mancante_oggi(self):
        righe = G.serie_notte_testo(grafico([10, 20, 21], [11, 22, None], adj=[5.5, 22, None]))
        self.assertEqual(len(righe), 3)
        self.assertAlmostEqual(righe[0][1], 10 * 5.5 / 11)                  # apertura corretta come la chiusura
        self.assertEqual(righe[0][2], 5.5)
        self.assertEqual(righe[2][2], None)                                 # seduta in corso
        self.assertEqual(righe[2][1], 21)

    def test_prezzi_notte_per_titolo(self):
        with mock.patch.object(G.simula, "fetch_max", return_value=grafico([10, 11], [10.5, 11.5])), \
                mock.patch.dict(G.settimana.MERCATI["usa"], {"universo": ["A", "B"]}):
            P = G.prezzi_notte(log=lambda m: None)
        self.assertEqual(sorted(P), ["A", "B"])
        self.assertEqual(P["A"][-1][1:], [11, 11.5])


class Aste(unittest.TestCase):
    def test_aperture_da_yahoo_con_cache_di_un_minuto(self):
        chiamate = []

        def finta(req, timeout=10):
            chiamate.append(req.full_url)
            return io.BytesIO(grafico([10, 11], [10.5, None]).encode())

        a = L.Aperture()
        with mock.patch.object(L.urllib.request, "urlopen", side_effect=finta):
            out, err = a.prendi(["MMM", "COF"], adesso=100.0)
            a.prendi(["MMM"], adesso=130.0)                                  # ancora fresco: nessuna richiesta
            a.prendi(["MMM"], adesso=161.0)
        self.assertEqual(sorted(out), ["COF", "MMM"])
        self.assertEqual(out["MMM"][-1][2], None)
        self.assertEqual(len(chiamate), 3)
        self.assertEqual(err, [])


if __name__ == "__main__":
    unittest.main()
