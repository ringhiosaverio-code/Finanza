"""Test offline di segnali.py: i segnali giornalieri, l'allineamento al giorno prima (niente futuro), il sentimento e le
notizie, con le fonti finte. Niente rete.

    python3 -m unittest discover -s tests
"""

import json
import math
import os
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["FINANZA_SENZA_RETE"] = "1"                                  # i segnali esterni solo dalla cache: niente rete
import segnali as S  # noqa: E402


def giorni(n, da="2030-01-01"):
    import datetime
    d0 = datetime.date.fromisoformat(da)
    return [(d0 + datetime.timedelta(days=k)).isoformat() for k in range(n)]


class TabellaGiornaliera(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(1)
        n = 400
        self.c = 100 * np.exp(np.cumsum(rng.standard_normal(n) * 0.02))
        self.o = self.c * (1 + rng.standard_normal(n) * 0.003)
        self.h = np.maximum(self.o, self.c) * (1 + np.abs(rng.standard_normal(n)) * 0.01)
        self.l = np.minimum(self.o, self.c) * (1 - np.abs(rng.standard_normal(n)) * 0.01)

    def test_forma_e_valori_sensati(self):
        T = S.tabella_giornaliera(self.o, self.h, self.l, self.c)
        self.assertEqual(T.shape, (400, len(S.NOMI_GIORNALIERI)))
        self.assertFalse(np.isnan(T).any())
        F = S.NOMI_GIORNALIERI.index
        self.assertTrue(np.all(T[:, F("max52")] <= 0))                       # mai sopra il massimo di 52 settimane
        self.assertTrue(np.all(np.abs(T[:, F("rsi2")]) <= 1))
        self.assertTrue(set(np.unique(T[:, F("nr7")])) <= {0.0, 1.0})

    def test_il_giorno_d_usa_solo_i_giorni_fino_a_d(self):
        T1 = S.tabella_giornaliera(self.o, self.h, self.l, self.c)
        c2 = self.c.copy()
        c2[300:] *= 1.5                                                   # si cambia il futuro dal giorno 300
        T2 = S.tabella_giornaliera(self.o, np.maximum(self.h, c2), self.l, c2)
        np.testing.assert_allclose(T1[:300], T2[:300], atol=1e-6)

    def test_atr(self):
        a = S.atr_giornaliero(self.o, self.h, self.l, self.c)
        self.assertEqual(len(a), 400)
        self.assertTrue(np.all(a > 0))


class AlGiornoPrima(unittest.TestCase):
    def test_si_usa_il_giorno_prima_gia_chiuso(self):
        gd = giorni(5)
        val = np.arange(5, dtype=np.float32)[:, None]
        out = S.per_giorno(gd, val, [gd[0], gd[2], "2030-01-10"])
        np.testing.assert_array_equal(out[:, 0], [0.0, 1.0, 4.0])          # il primo giorno non ha un giorno prima: zero

    def test_i_buchi_prendono_l_ultimo_giorno_disponibile(self):
        gd = ["2030-01-01", "2030-01-02", "2030-01-06"]
        out = S.per_giorno(gd, np.array([[1.0], [2.0], [3.0]], np.float32), ["2030-01-05", "2030-01-07"])
        np.testing.assert_array_equal(out[:, 0], [2.0, 3.0])

    def test_sentimento_del_giorno_prima_e_variazione(self):
        fg = {g: 20 + k for k, g in enumerate(giorni(20))}
        out = S.sentimento_per_giorno([giorni(20)[10]], fg)
        self.assertAlmostEqual(float(out[0, 0]), (29 - 50) / 25.0)         # il valore del giorno 9
        self.assertAlmostEqual(float(out[0, 1]), 7 / 25.0)                 # +7 punti in una settimana
        self.assertTrue(np.all(S.sentimento_per_giorno(["2030-01-05"], {}) == 0))

    def test_notizie_contro_la_media_del_mese_prima(self):
        serie = {g: [100.0, 0.0] for g in giorni(40)}
        serie[giorni(40)[35]] = [300.0, 2.0]                                # un giorno con il triplo delle notizie, tono alto
        out = S.notizie_per_giorno(serie, [giorni(40)[36], giorni(40)[20]])
        self.assertAlmostEqual(float(out[0, 0]), math.log(301 / 101), places=4)
        self.assertGreater(float(out[0, 1]), 1.0)
        self.assertAlmostEqual(float(out[1, 0]), 0.0, places=6)


class Fonti(unittest.TestCase):
    def test_fear_greed_dalla_cache_e_dalla_rete(self):
        with tempfile.TemporaryDirectory() as t, mock.patch.object(S, "CACHE", t):
            self.assertEqual(S.fear_greed(), {})                            # senza rete e senza cache: niente
            risposta = json.dumps({"data": [{"value": "10", "timestamp": "1893456000"}, {"value": "30", "timestamp": "1893369600"}]})
            with mock.patch.dict(os.environ, {"FINANZA_SENZA_RETE": "0"}), mock.patch.object(S, "_get", return_value=risposta):
                fg = S.fear_greed()
            self.assertEqual(fg, {"2030-01-01": 10, "2029-12-31": 30})
            self.assertEqual(S.fear_greed(), fg)                            # ora dalla cache

    def test_notizie_da_gdelt_si_accumulano_e_se_dice_di_no_si_aspetta(self):
        vol = [{"date": "20300101T000000Z", "value": 5}, {"date": "20300101T120000Z", "value": 7}, {"date": "20300102T000000Z", "value": 3}]
        tono = [{"date": "20300101T000000Z", "value": -1.0}, {"date": "20300101T120000Z", "value": 1.0}, {"date": "20300102T000000Z", "value": 2.0}]
        with tempfile.TemporaryDirectory() as t, mock.patch.object(S, "CACHE", t), mock.patch.dict(os.environ, {"FINANZA_SENZA_RETE": "0"}):
            with mock.patch.object(S, "_gdelt", side_effect=[vol, tono]):
                n = S.notizie("prova", "x")
            self.assertEqual(n["2030-01-01"], [12.0, 0.0])
            self.assertEqual(n["2030-01-02"], [3.0, 2.0])
            os.utime(os.path.join(t, "notizie", "prova.json"), (0, 0))      # vecchia: si riprova, e GDELT dice di no
            with mock.patch.object(S, "_gdelt", return_value=None) as g:
                self.assertEqual(S.notizie("prova", "x"), n)                # restano quelle di prima
                self.assertEqual(S.notizie("prova", "x"), n)
            self.assertEqual(g.call_count, 1)                               # dopo un no, per 6 ore non si chiede più

    def test_le_fonti_hanno_autore_e_contenuto(self):
        self.assertGreater(len(S.FONTI), 10)
        for a, b in S.FONTI:
            self.assertTrue(a and b)


if __name__ == "__main__":
    unittest.main()
