"""Test offline di app.py: l'aggiornamento leggero (solo crypto) parte dall'ultima app generata. Niente rete.

    python3 -m unittest discover -s tests
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402


def dati(**kw):
    d = {"aggiornato": "2030-01-01 18:10", "mercati": {"usa": {"nota": "una </script> finta"}},
         "intraday": {"varianti": {"v": 1}, "ore": {"kraken": {"giorni": 30}, "crypto": {"BTC-EUR": {"ora": "vecchia"}}}}}
    d.update(kw)
    return d


class Leggero(unittest.TestCase):
    def test_i_dati_si_rileggono_dall_app_anche_con_il_testo_che_chiude_uno_script(self):
        with tempfile.TemporaryDirectory() as t:
            out = os.path.join(t, "app.html")
            app.build(dati(), out)
            self.assertEqual(app.dati_di(out), dati())

    def test_senza_app_di_partenza_serve_il_completo(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertIsNone(app.dati_di(os.path.join(t, "non-c-e.html")))
            self.assertEqual(app.leggero(os.path.join(t, "non-c-e.html"), log=lambda m: None), 1)

    def test_rifa_solo_le_crypto_e_tiene_il_resto(self):
        nuovo = {"crypto": {}, "ore": {"crypto": {"BTC-EUR": {"ora": "nuova"}}, "kraken": None}}
        with tempfile.TemporaryDirectory() as t:
            out = os.path.join(t, "app.html")
            app.build(dati(), out)
            with mock.patch.object(app, "crypto_intraday", return_value=nuovo) as m:
                self.assertEqual(app.leggero(out, log=lambda x: None), 0)
            self.assertEqual(m.call_args[1]["leggero"], dati()["intraday"])      # riceve i dati di prima
            d = app.dati_di(out)
            self.assertEqual(d["intraday"]["ore"]["crypto"]["BTC-EUR"]["ora"], "nuova")
            self.assertEqual(d["mercati"], dati()["mercati"])                     # il resto è com'era
            self.assertEqual(d["aggiornato"], "2030-01-01 18:10")

    def test_se_le_crypto_non_arrivano_l_app_resta_com_era(self):
        with tempfile.TemporaryDirectory() as t:
            out = os.path.join(t, "app.html")
            app.build(dati(), out)
            leggi = lambda: open(out, encoding="utf-8").read()
            prima = leggi()
            for nuovo in (None, {"crypto": {}}):                                  # rete assente, oppure senza ordini orari
                with mock.patch.object(app, "crypto_intraday", return_value=nuovo):
                    self.assertEqual(app.leggero(out, log=lambda x: None), 1)
            self.assertEqual(leggi(), prima)

    def test_crypto_intraday_leggero_riusa_varianti_e_kraken(self):
        vecchio = dati()["intraday"]
        with mock.patch.object(app.intraday, "analizza", return_value={"crypto": {}}), \
                mock.patch.object(app.intraday, "varianti", side_effect=AssertionError("non va rifatto")), \
                mock.patch.object(app.intraday, "analizza_ore", return_value={"crypto": {}, "kraken": None}) as ore:
            r = app.crypto_intraday(log=lambda m: None, leggero=vecchio)
        self.assertEqual(r["varianti"], {"v": 1})
        self.assertEqual(r["ore"]["kraken"], {"giorni": 30})
        self.assertFalse(ore.call_args[1]["kraken"])                              # niente controllo su Kraken ogni ora


if __name__ == "__main__":
    unittest.main()
