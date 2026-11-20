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


if __name__ == "__main__":
    unittest.main()
