"""Test offline di alpaca_paper.py: i pesi del piano, gli equivalenti americani degli ETF di Borsa Italiana, gli ordini
(solo le parti spostate abbastanza, acquisti nei contanti), l'invio al conto di prova con un Alpaca finto. Niente rete.

    python3 -m unittest discover -s tests
"""

import json
import os
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import alpaca_paper as A  # noqa: E402

FILE = {
    "rete_lungo.json": {"robot_sezioni": {"etf": {"giorno": "2030-01-07", "pesi": {"CSNDX.MI": 0.5, "SJPA.MI": 0.5}}}},
    "strategie_lungo.json": {"mercati": {"etf": {"oggi": {"faber": {"pesi": {"SWDA.MI": 0.5, "VHYL.MI": 0.5}}}}}},
    "crypto_tendenza.json": {"oggi": {"pesi": {"BTC-EUR": 0.3, "TRX-EUR": 0.2}}},
    "diario_rete.json": {"controllo": {"peso": 0.1}},
}


class Alpaca(object):
    """Un conto di prova finto: risponde come l'API di Alpaca e ricorda gli ordini."""
    def __init__(self, aperta=True, posizioni=(), patrimonio=1000.0, contanti=1000.0):
        self.aperta, self.pos, self.patrimonio, self.contanti, self.chiamate = aperta, list(posizioni), patrimonio, contanti, []

    def __call__(self, metodo, percorso, corpo=None):
        self.chiamate.append((metodo, percorso, corpo))
        if percorso == "/v2/account":
            return {"equity": str(self.patrimonio), "cash": str(self.contanti), "currency": "USD", "last_equity": str(self.patrimonio)}
        if percorso == "/v2/positions":
            return self.pos
        if percorso == "/v2/clock":
            return {"is_open": self.aperta}
        if percorso.startswith("/v2/assets"):
            return [{"symbol": "BTC/USD", "tradable": True}, {"symbol": "ETH/USD", "tradable": True}]
        if percorso == "/v2/orders":
            return {"status": "accepted"}
        if metodo == "DELETE":
            return {"status": "accepted"}
        raise AssertionError(percorso)


class ConFile(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        for nome, x in FILE.items():
            with open(os.path.join(self.dir.name, nome), "w", encoding="utf-8") as fh:
                json.dump(x, fh)
        self.uscita = os.path.join(self.dir.name, "alpaca.json")
        self.p = mock.patch.object(A, "ROOT", self.dir.name)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.dir.cleanup()


class Piano(ConFile):
    def test_pesi_come_nell_app(self):
        P = A.pesi_piano()
        self.assertEqual(P["peso_rete"], 0.1)
        w = P["pesi"]
        self.assertAlmostEqual(w["SWDA.MI"], 0.6 + 0.05, places=4)        # 50 % + (20 - 10) % che la rete non usa + Faber
        self.assertAlmostEqual(w["IEAG.MI"], 0.1, places=4)
        self.assertAlmostEqual(w["CSNDX.MI"], 0.05, places=4)             # la rete al 10 %, metà a testa
        self.assertAlmostEqual(w["VHYL.MI"], 0.05, places=4)
        self.assertAlmostEqual(w["BTC-EUR"], 0.03, places=4)

    def test_equivalenti_americani(self):
        ob, fuori = A.obiettivo_usa(A.pesi_piano()["pesi"], crypto_ok={"BTC"})
        self.assertAlmostEqual(ob["URTH"]["peso"], 0.65, places=4)
        self.assertEqual(ob["URTH"]["da"], ["SWDA.MI"])
        self.assertAlmostEqual(ob["VYM"]["peso"] + ob["VYMI"]["peso"], 0.05, places=4)   # VHYL: parte USA e fuori dagli USA
        self.assertIn("BTC/USD", ob)
        self.assertEqual(fuori, ["TRX-EUR"])                               # Alpaca non la tratta: resta in contanti
        for s in ob:
            self.assertNotIn(".MI", s)


class Ordini(unittest.TestCase):
    def test_conto_vuoto_compra_tutto_nei_contanti(self):
        o = A.ordini({"URTH": 0.5, "BNDX": 0.1, "BTC/USD": 0.003}, 1000, {}, 1000)
        self.assertEqual([x["lato"] for x in o], ["compra"] * 3)
        self.assertLessEqual(sum(x["importo"] for x in o), 1000)
        self.assertAlmostEqual(next(x for x in o if x["simbolo"] == "URTH")["importo"], 495.0)   # l'1 % resta in contanti

    def test_piccoli_spostamenti_restano_fermi(self):
        o = A.ordini({"URTH": 0.5, "BNDX": 0.1}, 10000, {"URTH": 5100, "BNDX": 960}, 3940)
        self.assertEqual(o, [])

    def test_vende_quello_che_non_e_piu_nel_piano_e_prima_le_vendite(self):
        o = A.ordini({"URTH": 0.5}, 1000, {"URTH": 300, "EWJ": 200}, 500)
        self.assertEqual(o[0], {"simbolo": "EWJ", "lato": "vende_tutto", "importo": 200})
        self.assertEqual(o[1]["lato"], "compra")
        self.assertEqual(o[1]["simbolo"], "URTH")

    def test_acquisti_ridotti_ai_contanti(self):
        o = A.ordini({"URTH": 0.6, "BNDX": 0.3}, 1000, {}, 450)
        self.assertAlmostEqual(sum(x["importo"] for x in o), 450, delta=0.05)


class Ribilancia(ConFile):
    def test_borsa_aperta_manda_gli_ordini(self):
        api = Alpaca(aperta=True, posizioni=[{"symbol": "BTCUSD", "asset_class": "crypto", "market_value": "100"}])
        self.assertEqual(A.ribilancia(api, log=lambda *a: None, percorso=self.uscita), 0)
        corpi = [c[2] for c in api.chiamate if c[1] == "/v2/orders"]
        self.assertTrue(corpi)
        urth = next(c for c in corpi if c["symbol"] == "URTH")
        self.assertEqual((urth["side"], urth["type"], urth["time_in_force"]), ("buy", "market", "day"))
        self.assertTrue(all(float(c["notional"]) >= 1 for c in corpi))
        btc = [c for c in corpi if c["symbol"] == "BTC/USD"]                # 100 $ di BTC contro 30 $ voluti: vende
        self.assertEqual(btc[0]["side"], "sell")
        self.assertEqual(btc[0]["time_in_force"], "gtc")
        with open(self.uscita, encoding="utf-8") as fh:
            r = json.load(fh)
        self.assertEqual(r["stato"], "ok")
        self.assertEqual(r["posizioni"][0]["simbolo"], "BTC/USD")
        self.assertTrue(all(o["esito"].startswith("inviato") for o in r["ordini"]))

    def test_borsa_chiusa_solo_crypto(self):
        api = Alpaca(aperta=False)
        A.ribilancia(api, log=lambda *a: None, percorso=self.uscita)
        corpi = [c[2] for c in api.chiamate if c[1] == "/v2/orders"]
        self.assertEqual([c["symbol"] for c in corpi], ["BTC/USD"])

    def test_senza_chiavi(self):
        def rifiuta(*a, **k):
            raise urllib.error.HTTPError("https://paper-api.alpaca.markets/v2/account", 403, "forbidden", {}, None)
        self.assertEqual(A.ribilancia(rifiuta, log=lambda *a: None, percorso=self.uscita), 2)
        with open(self.uscita, encoding="utf-8") as fh:
            r = json.load(fh)
        self.assertEqual(r["stato"], "senza chiavi")
        self.assertIn("segreti di rete", r["messaggio"])

    def test_solo_il_conto_di_prova(self):
        self.assertEqual(A.BASE, "https://paper-api.alpaca.markets")


if __name__ == "__main__":
    unittest.main()
