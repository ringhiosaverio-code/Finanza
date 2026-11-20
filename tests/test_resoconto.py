"""Test offline del resoconto del lunedì (pubblica_stato.py): la settimana da lunedì a domenica, i conti contro la
chiusura della settimana prima (o il capitale, se il robot è ripartito durante la settimana), SWDA per confronto, le
operazioni, il diario della rete; mandato una volta sola, il lunedì dalle 8. Niente rete.

    python3 -m unittest discover -s tests
"""

import datetime
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pubblica_stato as P  # noqa: E402

LUNEDI = datetime.date(2030, 1, 14)
STATO = {
    "capitale": 10000,
    "storico": [
        {"d": "2030-01-05", "piano": 9990, "rete": 10050, "_swda": 99.0},
        {"d": "2030-01-06", "piano": 10000, "rete": 10000, "_swda": 100.0},    # la chiusura della settimana prima
        {"d": "2030-01-09", "piano": 10050, "rete": 9950, "_swda": 100.5},
        {"d": "2030-01-13", "piano": 10100, "rete": 9900, "rete_usa": 10300, "_swda": 101.0},   # domenica
        {"d": "2030-01-14", "piano": 10200, "rete": 9000, "_swda": 90.0},       # il lunedì stesso: non conta
    ],
    "registro": [
        {"t": "2030-01-06T20:00:00.000Z", "s": "rete", "azione": "compra"},            # la settimana prima
        {"t": "2030-01-08T09:00:00.000Z", "s": "rete", "azione": "compra"},
        {"t": "2030-01-08T11:00:00.000Z", "s": "rete", "azione": "vende", "r": 0.01},
        {"t": "2030-01-12T11:00:00.000Z", "s": "rete", "azione": "vende", "r": -0.02},
        {"t": "2030-01-14T07:00:00.000Z", "s": "rete", "azione": "vende", "r": 0.03},  # il lunedì dopo
    ],
}
DIARIO = {"voci": [{"giorno": "2030-01-02", "scelte": ["CSNDX.MI", "SJPA.MI"], "esito": 0.012, "tutti": 0.004},
                   {"giorno": "2030-01-09", "scelte": ["SGLD.MI", "VHYL.MI", "EIMI.MI"], "esito": None, "tutti": None}],
          "controllo": {"peso": 0.2, "stato": "in prova", "messaggio": "Il diario ha 1 settimane chiuse."}}


class Testo(unittest.TestCase):
    def test_settimana_intera(self):
        titolo, t = P.resoconto_testo(STATO, DIARIO, LUNEDI)
        self.assertEqual(titolo, "Resoconto della settimana · lun 14 gen")
        self.assertIn("Il robot dal lun 7 gen al dom 13 gen, 10.000 € per conto:", t)
        self.assertIn("Il piano con la rete: 10.100 € (+1,0 %)", t)
        self.assertIn("Crypto, rete neurale: 9.900 € (-1,0 %)", t)
        self.assertIn("Azioni USA, rete: 10.300 € (+3,0 %)", t)        # nato durante la settimana: dal capitale
        self.assertIn("SWDA (il mondo intero, per confronto): +1,0 %", t)
        self.assertIn("Meglio: Azioni USA, rete (+3,0 %) · peggio: Crypto, rete neurale (-1,0 %)", t)
        self.assertIn("Operazioni: 3 (2 vendite, 50 % in guadagno)", t)
        self.assertIn("settimana dal mer 2 gen: le sue scelte +1,20 % contro +0,40 % della media degli ETF", t)
        self.assertIn("Peso della rete nel piano: 20 % (in prova)", t)
        self.assertIn("Le scelte della rete adesso (dal mer 9 gen): SGLD, VHYL, EIMI.", t)
        self.assertNotIn("10.200", t)                                     # il valore del lunedì non entra
        self.assertLess(len(t.encode("utf-8")), 4000)                     # ntfy: al più 4096 byte

    def test_ripartito_durante_la_settimana(self):
        st = {"storico": [{"d": "2030-01-10", "piano": 10000}, {"d": "2030-01-12", "piano": 9800}], "registro": []}
        _, t = P.resoconto_testo(st, None, LUNEDI)
        self.assertIn("dal gio 10 gen al sab 12 gen (da quando è ripartito)", t)
        self.assertIn("Il piano con la rete: 9.800 € (-2,0 %)", t)       # dal capitale, 10.000 € di default
        self.assertNotIn("SWDA", t)
        self.assertNotIn("Operazioni", t)

    def test_finora_a_meta_settimana(self):
        st = {"capitale": 1000, "storico": [{"d": "2030-01-13", "piano": 1000}, {"d": "2030-01-15", "piano": 1010},
                                            {"d": "2030-01-16", "piano": 1020}], "registro": []}
        titolo, t = P.resoconto_testo(st, None, datetime.date(2030, 1, 16), finora=True)
        self.assertEqual(titolo, "Resoconto della settimana (finora) · mer 16 gen")
        self.assertIn("Il robot dal lun 14 gen al mer 16 gen, 1.000 € per conto:", t)
        self.assertIn("Il piano con la rete: 1.020 € (+2,0 %)", t)          # oggi compreso
        titolo, t = P.resoconto_testo(STATO, None, LUNEDI, finora=True)    # il lunedì: la settimana appena finita
        self.assertEqual(titolo, "Resoconto della settimana · lun 14 gen")

    def test_senza_storico(self):
        self.assertIsNone(P.resoconto_testo({"storico": []}, None, LUNEDI))
        self.assertIsNone(P.resoconto_testo({"storico": [{"d": "2030-01-14", "piano": 1}]}, None, LUNEDI))


class Invio(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        d = self.dir.name
        for nome, x in (("stato.json", STATO), ("notifiche.json", {"argomento": "prova"}), ("visti.json", {"ultimo": ""})):
            with open(os.path.join(d, nome), "w", encoding="utf-8") as fh:
                json.dump(x, fh)
        self.mandati = []
        self.patch = [mock.patch.object(P, "STATO", os.path.join(d, "stato.json")),
                      mock.patch.object(P, "NOTIFICHE", os.path.join(d, "notifiche.json")),
                      mock.patch.object(P, "VISTI", os.path.join(d, "visti.json")),
                      mock.patch.object(P, "RESOCONTO", os.path.join(d, "resoconto.json")),
                      mock.patch.object(P, "ROOT", d),
                      mock.patch.object(P, "manda", lambda titolo, testo, argomento, etichetta="", coda=True: self.mandati.append((titolo, argomento)))]
        for p in self.patch:
            p.start()

    def tearDown(self):
        for p in self.patch:
            p.stop()
        self.dir.cleanup()

    def test_solo_il_lunedi_dalle_8_una_volta(self):
        ora = lambda g, h: datetime.datetime(2030, 1, g, h, 5, tzinfo=P.ROMA)
        self.assertFalse(P.resoconto(ora(13, 10)))                         # domenica
        self.assertFalse(P.resoconto(ora(14, 7)))                          # lunedì prima delle 8
        self.assertTrue(P.resoconto(ora(14, 8)))
        self.assertFalse(P.resoconto(ora(14, 9)))                          # già mandato
        self.assertEqual(self.mandati, [("Resoconto della settimana · lun 14 gen", "prova")])
        self.assertTrue(P.resoconto(ora(15, 9), subito=True))              # "Mandami il resoconto adesso"
        self.assertEqual(self.mandati[-1], ("Resoconto della settimana (finora) · mar 15 gen", "prova"))

    def test_se_non_parte_riprova_ogni_mezzora_e_resta_per_l_app(self):
        def rotto(*a, **k):
            raise OSError("429")
        with mock.patch.object(P, "manda", rotto):
            self.assertFalse(P.resoconto(datetime.datetime(2030, 1, 14, 8, 1, tzinfo=P.ROMA)))
        with open(P.RESOCONTO, encoding="utf-8") as fh:
            r = json.load(fh)
        self.assertFalse(r["mandato"])                                     # l'app lo mostra lo stesso
        self.assertIn("Il piano con la rete: 10.100 €", r["testo"])
        self.assertFalse(P.resoconto(datetime.datetime(2030, 1, 14, 8, 20, tzinfo=P.ROMA)))   # troppo presto per riprovare
        self.assertEqual(self.mandati, [])
        self.assertTrue(P.resoconto(datetime.datetime(2030, 1, 14, 8, 32, tzinfo=P.ROMA)))
        with open(P.RESOCONTO, encoding="utf-8") as fh:
            self.assertTrue(json.load(fh)["mandato"])


class Coda(unittest.TestCase):
    """Gli avvisi rifiutati da ntfy restano nell'app e si rimandano più tardi, una volta sola."""
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        d = self.dir.name
        with open(os.path.join(d, "notifiche.json"), "w", encoding="utf-8") as fh:
            json.dump({"argomento": "prova"}, fh)
        self.patch = [mock.patch.object(P, n, os.path.join(d, f)) for n, f in
                      (("NOTIFICHE", "notifiche.json"), ("VISTI", "visti.json"), ("AVVISI", "avvisi.json"), ("CODA", "coda.json"))]
        for p in self.patch:
            p.start()
        self.rete = True
        self.partiti = []

        def urlopen(req, timeout=0):
            if not self.rete:
                raise OSError("429")
            self.partiti.append(req.get_header("Title"))
            return mock.MagicMock()
        self.u = mock.patch.object(P.urllib.request, "urlopen", urlopen)
        self.u.start()

    def tearDown(self):
        self.u.stop()
        for p in self.patch:
            p.stop()
        self.dir.cleanup()

    def test_rifiutato_poi_rimandato(self):
        self.rete = False
        with self.assertRaises(OSError):
            P.manda("Robot: Faber", "Compra SWDA", "prova")
        with open(P.AVVISI, encoding="utf-8") as fh:
            self.assertEqual([(x["titolo"], x["mandato"]) for x in json.load(fh)], [("Robot: Faber", False)])
        self.assertEqual(P.riprova_coda(1000.0), 0)                       # ntfy rifiuta ancora
        self.rete = True
        self.assertEqual(P.riprova_coda(1300.0), 0)                       # troppo presto: ogni 10 minuti
        self.assertEqual(P.riprova_coda(1700.0), 1)
        self.assertEqual(self.partiti, ["Robot: Faber"])
        self.assertEqual(P.riprova_coda(2400.0), 0)                       # una volta sola
        with open(P.AVVISI, encoding="utf-8") as fh:
            L = json.load(fh)
        self.assertEqual([(x["titolo"], x["mandato"]) for x in L], [("Robot: Faber", True)])   # niente doppioni

    def test_senza_coda_non_si_rimanda(self):
        self.rete = False
        with self.assertRaises(OSError):
            P.manda("Resoconto", "testo", "prova", coda=False)
        self.rete = True
        self.assertEqual(P.riprova_coda(5000.0), 0)


if __name__ == "__main__":
    unittest.main()
