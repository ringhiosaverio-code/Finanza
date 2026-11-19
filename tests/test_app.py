"""Test offline di app.py: l'aggiornamento leggero (crypto e reti neurali) parte dall'ultima app generata. Niente rete.

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
    def setUp(self):                                                  # le operazioni delle reti vogliono Kraken e Yahoo: qui no
        for nome in ("rete_robot_app", "rete_ita_app", "rete_ita_robot_app"):
            p = mock.patch.object(app, nome, return_value=None)
            p.start()
            self.addCleanup(p.stop)

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

    def test_l_aggiornamento_leggero_porta_anche_i_risultati_nuovi_della_rete(self):
        nuovo = {"crypto": {}, "ore": {"crypto": {}, "kraken": None}}
        with tempfile.TemporaryDirectory() as t:
            out = os.path.join(t, "app.html")
            app.build(dati(rete={"costi": {"0.002": "vecchi"}}), out)
            with mock.patch.object(app, "crypto_intraday", return_value=nuovo), \
                    mock.patch.object(app, "rete_per_app", return_value={"costi": {"0.002": "nuovi"}}):
                self.assertEqual(app.leggero(out, log=lambda x: None), 0)
            self.assertEqual(app.dati_di(out)["rete"], {"costi": {"0.002": "nuovi"}})
            with mock.patch.object(app, "crypto_intraday", return_value=nuovo), mock.patch.object(app, "rete_per_app", return_value=None):
                self.assertEqual(app.leggero(out, log=lambda x: None), 0)         # senza file nuovo restano quelli di prima
            self.assertEqual(app.dati_di(out)["rete"], {"costi": {"0.002": "nuovi"}})

    def test_l_aggiornamento_leggero_porta_le_operazioni_delle_due_reti(self):
        nuovo = {"crypto": {}, "ore": {"crypto": {}, "kraken": None}}
        with tempfile.TemporaryDirectory() as t:
            out = os.path.join(t, "app.html")
            app.build(dati(rete_ita={"costi": "vecchi"}, rete_ita_robot={"operazioni": ["vecchia"]}, rete_robot={"operazioni": []}), out)
            with mock.patch.object(app, "crypto_intraday", return_value=nuovo), \
                    mock.patch.object(app, "rete_ita_robot_app", return_value={"operazioni": ["nuova"]}), \
                    mock.patch.object(app, "rete_robot_app", return_value={"operazioni": ["crypto"]}):
                self.assertEqual(app.leggero(out, log=lambda x: None), 0)
            d = app.dati_di(out)
            self.assertEqual(d["rete_ita_robot"], {"operazioni": ["nuova"]})
            self.assertEqual(d["rete_robot"], {"operazioni": ["crypto"]})
            self.assertEqual(d["rete_ita"], {"costi": "vecchi"})                  # senza risultati nuovi restano quelli di prima
            with mock.patch.object(app, "crypto_intraday", return_value=nuovo):  # Yahoo non risponde: restano le operazioni di prima
                self.assertEqual(app.leggero(out, log=lambda x: None), 0)
            self.assertEqual(app.dati_di(out)["rete_ita_robot"], {"operazioni": ["nuova"]})

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

    def test_il_controllo_su_kraken_di_un_altro_metodo_non_si_riusa(self):
        vecchio = dati()["intraday"]                                    # senza "metodo": calcolato prima della correzione
        with mock.patch.object(app.intraday, "analizza", return_value={"crypto": {}}), \
                mock.patch.object(app.intraday, "analizza_ore", return_value={"crypto": {}, "kraken": None}):
            r = app.crypto_intraday(log=lambda m: None, leggero=vecchio)
        self.assertIsNone(r["ore"]["kraken"])

    def test_crypto_intraday_leggero_riusa_varianti_e_kraken(self):
        vecchio = dati()["intraday"]
        vecchio["ore"]["metodo"] = app.intraday.METODO_ORE
        with mock.patch.object(app.intraday, "analizza", return_value={"crypto": {}}), \
                mock.patch.object(app.intraday, "varianti", side_effect=AssertionError("non va rifatto")), \
                mock.patch.object(app.intraday, "analizza_ore", return_value={"crypto": {}, "kraken": None}) as ore:
            r = app.crypto_intraday(log=lambda m: None, leggero=vecchio)
        self.assertEqual(r["varianti"], {"v": 1})
        self.assertEqual(r["ore"]["kraken"], {"giorni": 30})
        self.assertFalse(ore.call_args[1]["kraken"])                              # niente controllo su Kraken ogni ora


class ReteNellApp(unittest.TestCase):
    def test_i_pesi_non_finiscono_nell_app(self):
        import json
        with tempfile.TemporaryDirectory() as t:
            with open(os.path.join(t, "rete_modello.json"), "w", encoding="utf-8") as fh:
                json.dump({"costi": {"0.002": {}}, "modelli": {"0.002": {"fuori": True, "iterazione": 3, "rete": {"W": [[1]]},
                                                                           "media": [0.0], "dev": [1.0]}}}, fh)
            with mock.patch.object(app, "ROOT", t):
                r = app.rete_per_app()
        self.assertEqual(r["modelli"]["0.002"], {"fuori": True, "iterazione": 3})

    def test_senza_risultati_non_c_e_la_sezione(self):
        with tempfile.TemporaryDirectory() as t, mock.patch.object(app, "ROOT", t):
            self.assertIsNone(app.rete_per_app())

    def test_la_rete_delle_azioni_italiane_non_ferma_l_app(self):
        import rete_azioni
        righe = []
        with mock.patch.object(rete_azioni, "robot", side_effect=OSError("Yahoo non risponde")), \
                mock.patch.object(rete_azioni, "per_app", side_effect=ValueError("file rovinato")):
            self.assertIsNone(app.rete_ita_robot_app(log=righe.append))
            self.assertIsNone(app.rete_ita_app(log=righe.append))
        self.assertEqual(len(righe), 2)
        self.assertIn("Yahoo non risponde", righe[0])
        with mock.patch.object(rete_azioni, "robot", return_value={"operazioni": []}):
            self.assertEqual(app.rete_ita_robot_app(log=righe.append), {"operazioni": []})


if __name__ == "__main__":
    unittest.main()
