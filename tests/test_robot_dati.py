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
                mock.patch.dict(G.settimana.MERCATI["usa"], {"universo": ["A", "B"]}), \
                mock.patch.dict(G.settimana.MERCATI["italia"], {"universo": ["C.MI"]}):
            P = G.prezzi_notte(log=lambda m: None)
        self.assertEqual(sorted(P), ["A", "B", "C.MI"])                      # anche le azioni italiane
        self.assertEqual(P["A"][-1][1:], [11, 11.5])

    def test_serie_giorno_con_massimo_e_minimo(self):
        righe = G.serie_giorno_testo(grafico([10, 20], [11, None]))
        self.assertEqual(righe[0], (righe[0][0], 10.0, 10.0, 10.0, 11))
        self.assertEqual(righe[1][4], None)

    def test_seduta_in_corso_niente_chiusura(self):
        # Yahoo, durante la seduta, mette come chiusura di oggi il prezzo del momento
        inizio = 1795012200                                                # 18 nov 2026, 9:30 a New York
        testo = json.loads(grafico([10, 20], [11, 21], inizio=inizio - 86400))
        testo["chart"]["result"][0]["meta"].update({"gmtoffset": -18000, "currentTradingPeriod": {
            "regular": {"start": inizio, "end": inizio + 6.5 * 3600}}})
        testo = json.dumps(testo)
        durante = G.serie_giorno_testo(testo, adesso=inizio + 3600)
        self.assertEqual(durante[-1][4], None)                              # in corso: niente chiusura
        self.assertEqual(durante[-1][2], 20)                                # il massimo fin qui resta
        self.assertEqual(G.serie_notte_testo(testo, adesso=inizio + 3600)[-1], (durante[-1][0], 20.0, None))
        dopo = G.serie_giorno_testo(testo, adesso=inizio + 7 * 3600)
        self.assertEqual(dopo[-1][4], 21)                                   # seduta finita: la chiusura vale
        self.assertEqual(durante[0][4], 11)                                 # i giorni prima non cambiano


class ChiusuraVuota(unittest.TestCase):
    def test_milano_ultima_chiusura_dai_metadati(self):
        # Yahoo a volte lascia vuota la chiusura dell'ultima seduta di Milano ma la dà nei metadati
        t = json.loads(grafico([83.55, 82.79], [83.33, None], inizio=1794816000))
        t["chart"]["result"][0]["meta"].update({"gmtoffset": 3600, "regularMarketTime": 1794933445, "regularMarketPrice": 81.96,
                                                "regularMarketDayHigh": 83.25, "regularMarketDayLow": 81.72,
                                                "currentTradingPeriod": {"regular": {"start": 1794988800, "end": 1795019400}}})
        righe = G.serie_giorno_testo(json.dumps(t), adesso=1794950000)
        self.assertEqual(righe[-1][0], "2026-11-17")
        self.assertEqual(righe[-1][4], 81.96)
        self.assertEqual((righe[-1][2], righe[-1][3]), (83.25, 81.72))
        self.assertEqual(G.serie_notte_testo(json.dumps(t), adesso=1794950000)[-1][2], 81.96)


class Cache(unittest.TestCase):
    def test_cache_scritta_a_seduta_aperta_scade_alla_chiusura(self):
        import tempfile
        fine = 1795035600                                                  # chiusura della seduta descritta
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write('{"chart":{"result":[{"meta":{"currentTradingPeriod":{"pre":{"end":1},"regular":{"timezone":"EST","end":%d,"start":%d}}}}]}}' % (fine, fine - 23400))
        try:
            os.utime(fh.name, (fine - 4 * 3600, fine - 4 * 3600))          # scritta 4 ore prima della chiusura
            self.assertIsNotNone(G.settimana.cache_valida(fh.name, 12, adesso=fine - 60))   # seduta ancora aperta
            self.assertIsNone(G.settimana.cache_valida(fh.name, 12, adesso=fine + 600))     # finita: si riscarica
            os.utime(fh.name, (fine + 400, fine + 400))                    # scritta dopo la chiusura
            self.assertIsNotNone(G.settimana.cache_valida(fh.name, 12, adesso=fine + 3600))
            self.assertIsNone(G.settimana.cache_valida(fh.name, 12, adesso=fine + 400 + 13 * 3600))  # troppo vecchia
        finally:
            os.unlink(fh.name)


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
