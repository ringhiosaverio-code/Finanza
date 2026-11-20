"""Test offline degli avvisi sui prezzi (pubblica_stato.py): si aggiungono e si tolgono dai comandi dell'app, scattano
una volta sola quando il prezzo passa la soglia, scartano i comandi sbagliati. Niente rete.

    python3 -m unittest discover -s tests
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pubblica_stato as P  # noqa: E402


class Allarmi(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        d = self.dir.name
        with open(os.path.join(d, "notifiche.json"), "w", encoding="utf-8") as fh:
            json.dump({"argomento": "prova"}, fh)
        self.mandati = []
        self.patch = [mock.patch.object(P, "ALLARMI", os.path.join(d, "allarmi.json")),
                      mock.patch.object(P, "NOTIFICHE", os.path.join(d, "notifiche.json")),
                      mock.patch.object(P, "manda", lambda t, x, a, e="", coda=True: self.mandati.append(t))]
        for p in self.patch:
            p.start()

    def tearDown(self):
        for p in self.patch:
            p.stop()
        self.dir.cleanup()

    def attivi(self):
        with open(P.ALLARMI, encoding="utf-8") as fh:
            return json.load(fh)["attivi"]

    def test_scatta_una_volta(self):
        self.assertTrue(P.gestisci_allarme({"allarme": {"sym": "swda.mi", "verso": "sotto", "prezzo": 120}}))
        self.assertTrue(P.gestisci_allarme({"allarme": {"sym": "BTC-EUR", "verso": "sopra", "prezzo": 60000}}))
        self.assertEqual(P.allarmi(lambda s: {"SWDA.MI": 121.0, "BTC-EUR": 55000.0}), 0)
        self.assertEqual(P.allarmi(lambda s: {"SWDA.MI": 119.5, "BTC-EUR": 55000.0}), 1)
        self.assertEqual(self.mandati, ["Prezzo: SWDA sotto 120,00"])
        self.assertEqual(P.allarmi(lambda s: {"SWDA.MI": 119.0, "BTC-EUR": 55000.0}), 0)   # già scattato
        self.assertEqual([x["sym"] for x in self.attivi()], ["BTC-EUR"])

    def test_togli_e_comandi_sbagliati(self):
        P.gestisci_allarme({"allarme": {"sym": "AAPL", "verso": "sopra", "prezzo": 300}})
        i = self.attivi()[0]["id"]
        self.assertFalse(P.gestisci_allarme({"allarme": {"sym": "AAPL; rm", "verso": "sopra", "prezzo": 1}}))
        self.assertFalse(P.gestisci_allarme({"allarme": {"sym": "AAPL", "verso": "dentro", "prezzo": 1}}))
        self.assertFalse(P.gestisci_allarme({"allarme": {"sym": "AAPL", "verso": "sopra", "prezzo": -5}}))
        P.gestisci_allarme({"togli_allarme": i})
        self.assertEqual(self.attivi(), [])

    def test_senza_prezzi_non_scatta(self):
        P.gestisci_allarme({"allarme": {"sym": "ENI.MI", "verso": "sopra", "prezzo": 10}})
        self.assertEqual(P.allarmi(lambda s: {}), 0)
        self.assertEqual(len(self.attivi()), 1)


if __name__ == "__main__":
    unittest.main()
