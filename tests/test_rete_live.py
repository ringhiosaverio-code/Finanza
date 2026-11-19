"""Test offline di rete_live.py: il conto finto, le barre dagli scambi recenti e la decisione di ogni minuto. Niente rete.

    python3 -m unittest discover -s tests
"""

import math
import os
import sys
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["FINANZA_SENZA_RETE"] = "1"                                  # i segnali esterni solo dalla cache: niente rete
import rete as R  # noqa: E402
import rete_live as L  # noqa: E402

SIMBOLI = ["A-EUR", "B-EUR"]


class Conto(unittest.TestCase):
    def setUp(self):
        self.c = L.Conto(SIMBOLI, costo=0.002, capitale=1000.0)

    def test_compra_con_un_dodicesimo_del_capitale_meno_il_costo(self):
        p = self.c.compra("A-EUR", 100.0, 1000.0, 60, 95.0)
        self.assertAlmostEqual(self.c.cassa, 500.0)
        self.assertAlmostEqual(p["qty"], 500 * 0.998 / 100)
        self.assertEqual(p["scade"], 1000.0 + 3600)

    def test_una_posizione_alla_volta_per_crypto(self):
        self.assertIsNotNone(self.c.compra("A-EUR", 100.0, 0, 60, 95.0))
        self.assertIsNone(self.c.compra("A-EUR", 100.0, 1, 60, 95.0))
        self.assertAlmostEqual(self.c.cassa, 500.0)
        self.assertIsNotNone(self.c.compra("B-EUR", 10.0, 1, 5, 9.5))

    def test_senza_cassa_non_compra(self):
        self.c.cassa = 10.0
        self.assertIsNone(self.c.compra("A-EUR", 100.0, 0, 60, 95.0))

    def test_vendita_con_costi_come_nell_app(self):
        self.c.compra("A-EUR", 100.0, 0, 60, 95.0)
        op = self.c.vendi("A-EUR", 101.0, 120.0, "scadenza")
        self.assertAlmostEqual(op["r"], 0.998 * 0.998 * 1.01 - 1, places=9)
        self.assertAlmostEqual(self.c.cassa, 1000 + 500 * op["r"], places=6)
        self.assertEqual(self.c.operazioni, [op])
        self.assertIsNone(self.c.vendi("A-EUR", 101.0, 130.0, "x"))             # non c'è più

    def test_la_protezione_scatta_e_si_esegue_un_po_peggio(self):
        self.c.compra("A-EUR", 100.0, 0, 60, 95.0)
        self.assertIsNone(self.c.controlla("A-EUR", 96.0, 10.0))
        op = self.c.controlla("A-EUR", 94.0, 20.0)
        self.assertEqual(op["motivo"], "protezione")
        self.assertAlmostEqual(op["uscita"], 94.0 * (1 - R.SLIP_STOP))          # il prezzo era già sotto: si esce lì, peggio

    def test_scadenza_dell_orizzonte(self):
        self.c.compra("A-EUR", 100.0, 0, 5, 95.0)
        self.assertIsNone(self.c.controlla("A-EUR", 100.5, 299.0))
        self.assertEqual(self.c.controlla("A-EUR", 100.5, 300.0)["motivo"], "scadenza")

    def test_valore_del_conto(self):
        self.c.compra("A-EUR", 100.0, 0, 60, 95.0)
        self.assertAlmostEqual(self.c.valore({"A-EUR": 110.0}), 500 + 500 * 0.998 / 100 * 110 * 0.998)


def scambi_finti(t0, minuti, prezzo=100.0):
    """Uno scambio al minuto (acquisto nei minuti pari, vendita in quelli dispari)."""
    t = t0 + 60.0 * np.arange(minuti) + 10.0
    p = prezzo * (1 + 0.0005 * np.sin(np.arange(minuti) / 50.0))
    return t, p, np.ones(minuti), np.where(np.arange(minuti) % 2 == 0, 1, -1).astype(np.int8)


class Barre(unittest.TestCase):
    def test_le_barre_arrivano_fino_al_minuto_in_corso(self):
        st = L.Storia(SIMBOLI, giorni=9)
        adesso = 1_800_000_000 + 12 * 3600 + 30.0
        k_ass = int(adesso // 60)
        t0 = float((k_ass // 1440 - 8) * 86400)
        for s in SIMBOLI:
            st.t[s], st.p[s], st.v[s], st.sd[s] = scambi_finti(t0, k_ass - int(t0 // 60))
        M, k = st.mondo(adesso)
        self.assertEqual(M.t0, t0)
        self.assertEqual(M.n, k + 1)
        self.assertEqual(k, k_ass - int(t0 // 60))
        self.assertEqual(t0 + 60 * k, k_ass * 60)                               # il minuto in corso comincia qui
        self.assertGreater(k, R.AVVIO)                                          # la storia basta per le caratteristiche


class Agente(unittest.TestCase):
    def modello(self, margine=0.0, buono=None):
        """Una rete a zero pesi: le uscite sono i bias, cioè valori fissi per mossa (in unità dell'1 %)."""
        net = R.Rete([R.N_FEATURE, 4, 1 + len(R.ORIZZONTI)], 0)
        net.W = [np.zeros_like(w) for w in net.W]
        net.b[-1] = np.zeros(1 + len(R.ORIZZONTI), np.float32)
        if buono is not None:
            net.b[-1][1 + R.ORIZZONTI.index(buono)] = 0.5                         # +0,5 % per quella durata
        return {"rete": net, "media": np.zeros(R.N_FEATURE, np.float32), "dev": np.ones(R.N_FEATURE, np.float32),
                "margine": margine, "fuori": False, "iterazione": 1, "tipo": "q", "ritmo": 0.0}

    def mondo(self):
        st = L.Storia(SIMBOLI, giorni=9)
        adesso = 1_800_000_000 + 12 * 3600 + 30.0
        t0 = float((int(adesso // 60) // 1440 - 8) * 86400)
        for s in SIMBOLI:
            st.t[s], st.p[s], st.v[s], st.sd[s] = scambi_finti(t0, int(adesso // 60) - int(t0 // 60))
        return st, adesso

    def test_compra_la_mossa_migliore_se_batte_l_attesa(self):
        st, adesso = self.mondo()
        a = L.Agente(self.modello(margine=0.001, buono=240), 0.002, SIMBOLI)
        M, k = st.mondo(adesso)
        aperte = a.decidi(M, k, {"A-EUR": 100.0, "B-EUR": 10.0}, adesso)
        self.assertEqual(len(aperte), 2)
        for p in aperte:
            self.assertEqual(p["minuti"], 240)
            self.assertLess(p["protezione"], p["entrata"])
        self.assertAlmostEqual(a.vista["A-EUR"]["vantaggio"], 0.005, places=6)

    def test_se_resta_fuori_non_compra_ma_mostra_i_valori(self):
        st, adesso = self.mondo()
        m = self.modello(margine=float("inf"), buono=240)
        m["fuori"] = True
        a = L.Agente(m, 0.002, SIMBOLI)
        M, k = st.mondo(adesso)
        self.assertEqual(a.decidi(M, k, {"A-EUR": 100.0, "B-EUR": 10.0}, adesso), [])
        self.assertEqual(a.vista["A-EUR"]["migliore_minuti"], 240)
        self.assertEqual(a.conto.posizioni, {})

    def test_decide_una_volta_al_minuto_dopo_i_primi_secondi_e_gestisce_ogni_secondo(self):
        st, adesso = self.mondo()
        a = L.Agente(self.modello(margine=0.001, buono=5), 0.002, SIMBOLI)
        prezzi = {"A-EUR": 100.0, "B-EUR": 10.0}
        t = (int(adesso // 60) + 1) * 60.0                                       # inizio di un minuto
        chiamate = []
        fn = lambda tt: (chiamate.append(tt) or st.mondo(tt))
        a.passo(fn, prezzi, t + 1)                                               # troppo presto: non decide
        self.assertEqual(chiamate, [])
        a.passo(fn, prezzi, t + 6)                                               # decide e compra
        self.assertEqual(len(chiamate), 1)
        self.assertEqual(set(a.conto.posizioni), {"A-EUR", "B-EUR"})
        a.passo(fn, prezzi, t + 7)                                               # stesso minuto: non decide di nuovo
        self.assertEqual(len(chiamate), 1)
        chiuse = a.passo(fn, {"A-EUR": 50.0, "B-EUR": 10.0}, t + 8)               # A crolla: scatta la protezione
        self.assertEqual([op["sym"] for op in chiuse], ["A-EUR"])
        self.assertEqual(a.eventi[-1]["evento"], "vende")
        chiuse = a.passo(fn, prezzi, t + 6 + 5 * 60)                              # dopo 5 minuti scade B (e A è già fuori)
        self.assertTrue(any(op["sym"] == "B-EUR" and op["motivo"] == "scadenza" for op in chiuse))


class MargineImposto(unittest.TestCase):
    def test_costringe_a_comprare_un_modello_che_resta_fuori(self):
        fuori = {"rete": None, "margine": float("inf"), "fuori": True, "iterazione": 14}
        m = L.con_margine(fuori, 0.001)
        self.assertEqual((m["margine"], m["fuori"], m["imposto"]), (0.001, False, True))
        self.assertTrue(fuori["fuori"])                                          # l'originale non cambia
        self.assertIs(L.con_margine(fuori, None), fuori)

    def test_lo_stato_ricorda_il_margine_imposto_per_il_riaddestramento(self):
        m = L.con_margine(Agente().modello(margine=float("inf")), 0.002)
        stato = L.Stato(L.Agente(m, 0.002, SIMBOLI), 0.002)
        self.assertEqual(stato.margine_imposto, 0.002)
        self.assertIsNone(L.Stato(L.Agente(Agente().modello(margine=0.001), 0.002, SIMBOLI), 0.002).margine_imposto)


class StoriaFinta(L.Storia):
    """Gli scambi di due crypto finte, senza Kraken."""
    ADESSO = 1_800_000_000 + 12 * 3600 + 30.0

    def __init__(self, simboli=None, giorni=11):
        super().__init__(SIMBOLI, giorni=giorni)
        t0 = float((int(self.ADESSO // 60) // 1440 - giorni + 1) * 86400)
        for s in SIMBOLI:
            self.t[s], self.p[s], self.v[s], self.sd[s] = scambi_finti(t0, int(self.ADESSO // 60) - int(t0 // 60))

    def carica(self, log=None):
        return None

    def mondo(self, adesso=None):
        return super().mondo(self.ADESSO)


class RobotDellApp(unittest.TestCase):
    def probabile(self, soglia=0.6):
        net = R.Rete([R.N_FEATURE, 4, len(R.ORIZZONTI)], 0)
        net.W = [np.zeros_like(w) for w in net.W]
        net.b[-1] = np.full(len(R.ORIZZONTI), math.log(0.3 / 0.7), np.float32)
        net.b[-1][R.ORIZZONTI.index(60)] = math.log(0.7 / 0.3)
        return R.da_json({"rete": net.a_dizionario(), "media": [0.0] * R.N_FEATURE, "dev": [1.0] * R.N_FEATURE, "tipo": "probabilita",
                          "soglia": soglia, "quota": 0.005, "fuori": True, "iterazione": 2, "addestrato": "2030-01-01"})

    def test_sceglie_la_rete_della_probabilita(self):
        with mock.patch.object(L, "Storia", StoriaFinta), mock.patch.object(R, "carica_probabilita", lambda c: (self.probabile(), 0.002)):
            r = L.robot_crypto(giorni=1, log=lambda m: None)
        self.assertEqual((r["tipo"], r["soglia"], r["quota"], r["margine"], r["costo"]), ("probabilita", 0.6, 0.005, None, 0.002))
        self.assertGreater(len(r["operazioni"]), 10)
        self.assertTrue(all(abs(o["probabilita"] - 0.7) < 1e-4 and o["minuti"] == 60 for o in r["operazioni"]))
        self.assertEqual(set(r["prezzi"]), set(SIMBOLI))

    def test_senza_la_probabilita_il_margine_imposto(self):
        a = Agente()
        q = a.modello(margine=float("inf"), buono=240)                       # resta fuori: compra solo con il margine imposto
        with mock.patch.object(L, "Storia", StoriaFinta), mock.patch.object(R, "carica_probabilita", lambda c: None), \
                mock.patch.object(R, "carica_modello", lambda c: (q, 0.002)):
            r = L.robot_crypto(giorni=1, log=lambda m: None)
        self.assertEqual((r["tipo"], r["margine"], r["soglia"]), ("q", L.MARGINE_ROBOT, None))
        self.assertTrue(r["operazioni"])
        self.assertTrue(all("vantaggio" in o for o in r["operazioni"]))


class Pagina(unittest.TestCase):
    def test_lo_stato_si_serializza(self):
        import json
        m = Agente().modello(margine=float("inf"))
        m["fuori"] = True
        stato = L.Stato(L.Agente(m, 0.002, SIMBOLI), 0.002)
        stato.prezzi = {"A-EUR": {"prezzo": 100.0, "apertura": 99.0, "max24": 101.0, "min24": 98.0, "direzione": 0}}
        d = json.loads(stato.json())
        self.assertIsNone(d["modello"]["margine"])                                # l'infinito non è JSON
        self.assertTrue(d["modello"]["fuori"])
        self.assertAlmostEqual(d["valore"], L.CAPITALE)


if __name__ == "__main__":
    unittest.main()
