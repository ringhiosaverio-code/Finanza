"""Test offline di rete_lungo.py: AUC, scelte settimanali, studio dei segnali e addestramento su dati finti. Niente rete.

    python3 -m unittest discover -s tests
"""

import os
import sys
import types
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["FINANZA_SENZA_RETE"] = "1"
import rete_lungo as L  # noqa: E402


def finti(n_settimane=300, titoli=20, seme=0):
    """Campioni finti: il primo dato (g_anno) predice davvero il rendimento."""
    rng = np.random.default_rng(seme)
    n = n_settimane * titoli
    X = rng.standard_normal((n, len(L.NOMI_FEATURE))).astype(np.float32)
    R = (0.01 * X[:, [0]] + 0.02 * rng.standard_normal((n, len(L.ORIZZONTI)))).astype(np.float32)
    g = 736000 + 7 * np.repeat(np.arange(n_settimane), titoli)
    C = types.SimpleNamespace(X=X, R=R, OK=np.ones_like(R, bool), g=g, settimana=g // 7,
                              sym=np.tile(np.array(["T%d" % k for k in range(titoli)]), n_settimane),
                              cat=np.array(["usa"] * n), ultimi=[])
    return C


class Misure(unittest.TestCase):
    def test_auc(self):
        self.assertAlmostEqual(L.auc(np.array([0.1, 0.2, 0.8, 0.9]), np.array([0, 0, 1, 1])), 1.0)
        self.assertAlmostEqual(L.auc(np.array([0.9, 0.8, 0.2, 0.1]), np.array([0, 0, 1, 1])), 0.0)
        self.assertIsNone(L.auc(np.array([0.1, 0.2]), np.array([1, 1])))

    def test_scelte_settimanali_prendono_il_meglio_di_ogni_settimana(self):
        C = finti(10, 20)
        sc, tu, scarti = L.scelte_settimanali(C, np.arange(len(C.X)), C.R[:, 1], 1, quota=0.1)
        self.assertEqual(len(sc), 10 * 2)
        self.assertEqual(len(tu), 10 * 20)
        self.assertTrue(np.all(scarti > 0))                                         # col rendimento vero si sceglie sempre meglio

    def test_lo_studio_trova_il_dato_che_conta(self):
        S = L.studio_segnali(finti(200, 20))
        self.assertEqual(S[0]["nome"], "g_anno")
        self.assertGreater(S[0]["ic"]["tutte"][0], 0.2)
        self.assertFalse(any(s["nome"].startswith("cat_") for s in S))


class Addestramento(unittest.TestCase):
    def test_la_rete_impara_il_dato_che_conta(self):
        C = finti(300, 20)
        tr, va = np.arange(0, 4000), np.arange(4000, 5000)
        m = L.addestra(C, tr, va, epoche=6)
        P = L.stima(m, C.X[5000:])
        self.assertGreater(L.auc(P[:, 1], (C.R[5000:, 1] > 0).astype(int)), 0.6)


class PesiDelRobot(unittest.TestCase):
    def test_le_migliori_della_sezione_in_parti_uguali_dal_lunedi(self):
        o = {"7": [{"sym": "A", "categoria": "usa"}, {"sym": "E1", "categoria": "etf"}, {"sym": "B1", "categoria": "bond"},
                   {"sym": "E2", "categoria": "oro"}, {"sym": "E3", "categoria": "etf"}, {"sym": "E4", "categoria": "etf"}]}
        r = L.pesi_robot(o, 3, "2026-11-19", ("etf", "oro"))
        self.assertEqual(r["giorno"], "2026-11-16")                                 # il lunedì della settimana
        self.assertEqual(r["pesi"], {"E1": 0.3333, "E2": 0.3333, "E3": 0.3333})


class ObiettivoRelativo(unittest.TestCase):
    def test_uno_a_chi_fa_meglio_della_meta_degli_altri_nella_settimana(self):
        C = finti(3, 4)
        C.R[:, 0] = np.array([1, 2, 3, 4] * 3, np.float32) * (np.repeat([1, -1, 1], 4)).astype(np.float32)
        Y = L.bersagli(C, "relativo")
        np.testing.assert_array_equal(Y[:4, 0], [0, 0, 1, 1])                     # settimana in salita: i due migliori
        np.testing.assert_array_equal(Y[4:8, 0], [1, 1, 0, 0])                    # settimana in calo: chi perde meno
        np.testing.assert_array_equal(L.bersagli(C, "assoluto")[4:8, 0], [0, 0, 0, 0])

    def test_l_insieme_impara_anche_il_dato_che_conta(self):
        C = finti(300, 20)
        m = L.addestra(C, np.arange(0, 4000), np.arange(4000, 5000), epoche=4, insieme=3, obiettivo="relativo")
        P = L.stima(m, C.X[5000:])
        self.assertGreater(L.auc(P[:, 1], (C.R[5000:, 1] > 0).astype(int)), 0.6)


class Diario(unittest.TestCase):
    def test_una_voce_a_settimana_con_i_prezzi_del_giorno_della_scelta(self):
        import tempfile
        C = types.SimpleNamespace(ultimi=[("E1", "etf", "2030-01-07", 10.0, None), ("E2", "etf", "2030-01-07", 20.0, None)])
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "d.json")
            G = L.aggiorna_diario({"giorno": "2030-01-07", "pesi": {"E1": 0.5}}, C, p)
            G = L.aggiorna_diario({"giorno": "2030-01-07", "pesi": {"E2": 0.5}}, C, p)      # stessa settimana: niente voce nuova
        self.assertEqual(len(G["voci"]), 1)
        self.assertEqual(G["voci"][0]["scelte"], ["E1"])
        self.assertEqual(G["voci"][0]["prezzi"], {"E1": 10.0, "E2": 20.0})
        self.assertIsNone(G["voci"][0]["esito"])


class Isteresi(unittest.TestCase):
    def test_si_tiene_chi_e_ancora_vicino_ai_migliori(self):
        o = {"7": [{"sym": "A", "categoria": "etf", "probabilita": 0.60}, {"sym": "B", "categoria": "etf", "probabilita": 0.58},
                   {"sym": "C", "categoria": "etf", "probabilita": 0.57}, {"sym": "D", "categoria": "etf", "probabilita": 0.555},
                   {"sym": "E", "categoria": "etf", "probabilita": 0.50}]}
        r = L.pesi_con_isteresi(o, 3, "2030-01-09", ("etf",), ["D", "E"], 0.02)
        self.assertEqual(r["tenuti"], ["D"])                                         # D è a 1,5 punti dal terzo: si tiene; E no
        self.assertEqual(sorted(r["pesi"]), ["A", "B", "D"])
        self.assertEqual(L.pesi_con_isteresi(o, 3, "2030-01-09", ("etf",), ["D"], 0.0)["tenuti"], [])

    def test_le_tasse_si_pagano_solo_sui_guadagni_e_cambiare_meno_conviene(self):
        import portafoglio as PF
        sett = {w: {"A": (0.6 if w % 2 else 0.55, 0.01), "B": (0.55 if w % 2 else 0.6, 0.01), "C": (0.5, 0.0)} for w in range(100, 140)}
        v0, c0 = PF.simula_isteresi(sett, 0.0, scelte=1)
        v1, c1 = PF.simula_isteresi(sett, 0.1, scelte=1)
        self.assertLess(c1, c0)                                                      # con il margine si cambia meno
        self.assertGreater(v1[-1], v0[-1])                                           # e restano più soldi dopo costi e tasse


class ControlloDalVivo(unittest.TestCase):
    def voci(self, scarti):
        return [{"esito": 0.01 + d, "tutti": 0.01} for d in scarti]

    def test_la_regola_fissata_prima(self):
        self.assertEqual(L.controllo_peso(self.voci([0.01] * 5))["peso"], 0.20)            # poche settimane: in prova
        rng = np.random.default_rng(0)
        meglio = list(0.004 + 0.002 * rng.standard_normal(20))
        peggio = list(-0.004 + 0.002 * rng.standard_normal(20))
        pari = [0.001, -0.001] * 10
        self.assertEqual(L.controllo_peso(self.voci(meglio))["peso"], 0.30)
        self.assertEqual(L.controllo_peso(self.voci(peggio))["peso"], 0.0)
        self.assertEqual(L.controllo_peso(self.voci(pari))["peso"], 0.20)
        self.assertEqual(L.controllo_peso(self.voci(peggio))["stato"], "tolta dal piano")


if __name__ == "__main__":
    unittest.main()
