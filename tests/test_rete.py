"""Test offline di rete.py: barre dagli scambi, caratteristiche senza futuro, esiti con protezione, rete, politica
e gli ordini limite rigiocati sugli scambi. Niente rete.

    python3 -m unittest discover -s tests
"""

import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rete as R  # noqa: E402


def scambi(righe):
    t, p, v, s = zip(*righe)
    return np.array(t, float), np.array(p, float), np.array(v, float), np.array(s, np.int8)


def piatte(n, prezzo=100.0):
    B = {k: np.zeros(n) for k in ("o", "h", "l", "c", "v", "n", "vb", "vs", "st", "hb")}
    for k in "ohlc":
        B[k][:] = prezzo
    B["ls"] = np.full(n, np.inf)
    return B


def mondo(B, t0=0.0):
    return R.Mondo(["X-EUR"], t0, [B])


class Barre(unittest.TestCase):
    def setUp(self):
        self.B = R.barre(scambi([(5, 100, 1, 1), (20, 101, 2, -1), (50, 99.5, 1, 1), (130, 102, 3, -1)]), 0.0, 4)

    def test_apertura_massimo_minimo_chiusura_e_volumi(self):
        B = self.B
        self.assertEqual((B["o"][0], B["h"][0], B["l"][0], B["c"][0]), (100, 101, 99.5, 99.5))
        self.assertEqual((B["v"][0], B["n"][0], B["vb"][0], B["vs"][0]), (4, 3, 2, 2))
        self.assertAlmostEqual(B["st"][0], 1 / 100 + 1.5 / 101)           # mosse tra scambi consecutivi (il primo non ne ha)

    def test_il_prezzo_senza_scambi_resta_quello_di_prima(self):
        B = self.B
        for k in "ohlc":
            self.assertEqual((B[k][1], B[k][3]), (99.5, 102))
        self.assertEqual((B["v"][1], B["n"][1]), (0, 0))
        self.assertEqual((B["o"][2], B["c"][2]), (102, 102))

    def test_prezzo_piu_basso_a_cui_si_e_venduto_e_piu_alto_a_cui_si_e_comprato(self):
        B = self.B
        self.assertEqual(B["ls"][0], 101)                                # una sola vendita a mercato, a 101
        self.assertEqual(B["hb"][0], 100)                                # acquisti a 100 e a 99,5
        self.assertTrue(np.isinf(B["ls"][1]) and B["hb"][1] == 0)        # nessuno scambio
        self.assertEqual((B["ls"][2], B["hb"][2]), (102, 0))

    def test_prima_del_primo_scambio_si_usa_il_primo_prezzo(self):
        B = R.barre(scambi([(130, 7, 1, 1)]), 0.0, 4)
        self.assertEqual(list(B["c"]), [7, 7, 7, 7])


class Finestre(unittest.TestCase):
    def test_massimo_e_minimo_mobili_come_il_calcolo_diretto(self):
        rng = np.random.default_rng(3)
        x = rng.standard_normal((2, 53))
        for W in (1, 4, 7, 20, 53, 60):
            vero = np.array([[x[c, max(0, i - W + 1):i + 1].max() for i in range(53)] for c in range(2)])
            np.testing.assert_allclose(R.finestra_max(x, W), vero)
            vero = np.array([[x[c, max(0, i - W + 1):i + 1].min() for i in range(53)] for c in range(2)])
            np.testing.assert_allclose(R.finestra_min(x, W), vero)


def mondo_casuale(giorni=12, seme=1, monete=2):
    rng = np.random.default_rng(seme)
    n = giorni * 1440
    B = []
    for _ in range(monete):
        c = 100 * np.exp(np.cumsum(rng.standard_normal(n) * 0.0008))
        b = piatte(n)
        b["c"][:] = c
        b["o"][:] = np.concatenate(([100.0], c[:-1]))
        b["h"][:] = np.maximum(b["o"], b["c"]) * (1 + np.abs(rng.standard_normal(n)) * 0.0003)
        b["l"][:] = np.minimum(b["o"], b["c"]) * (1 - np.abs(rng.standard_normal(n)) * 0.0003)
        b["v"][:], b["nt"] = rng.uniform(1, 5, n), None
        b["n"][:] = rng.integers(1, 20, n)
        b["vb"][:], b["vs"][:], b["st"][:] = rng.uniform(0, 2, n), rng.uniform(0, 2, n), rng.uniform(0, 0.01, n)
        b["ls"][:], b["hb"][:] = b["l"], b["h"]
        del b["nt"]
        B.append(b)
    return R.Mondo(["A-EUR", "B-EUR"][:monete], 0.0, B)


class Caratteristiche(unittest.TestCase):
    def test_nessuna_caratteristica_usa_il_futuro(self):
        M1 = mondo_casuale()
        K = R.griglia(M1.n)
        X1 = R.caratteristiche(R.Pronto(M1), K)
        self.assertEqual(X1.shape, (2, len(K), R.N_FEATURE))
        self.assertFalse(np.isnan(X1).any())
        j = 7
        M2 = mondo_casuale()
        taglio = int(K[j])                                               # si cambiano tutte le barre da K[j] in poi
        rng = np.random.default_rng(9)
        for k in ("o", "h", "l", "c", "v", "nt", "vb", "vs", "st", "ls", "hb"):
            a = getattr(M2, k)
            a[:, taglio:] = a[:, taglio:] * rng.uniform(0.5, 2.0, a[:, taglio:].shape)
        X2 = R.caratteristiche(R.Pronto(M2), K)
        np.testing.assert_array_equal(X1[:, :j + 1], X2[:, :j + 1])      # fino a K[j] compreso, uguali
        self.assertFalse(np.array_equal(X1[:, j + 1:], X2[:, j + 1:]))   # dopo, cambiano

    def test_griglia_a_quarti_d_ora_dopo_la_storia_che_serve(self):
        K = R.griglia(20000)
        self.assertEqual(K[0] % 15, 0)
        self.assertGreaterEqual(K[0], R.AVVIO)
        self.assertTrue(np.all(np.diff(K) == 15))


class Etichette(unittest.TestCase):
    def setUp(self):
        self.B = piatte(14000)                                           # prezzo fermo: la volatilità è il minimo (0,05 % all'ora)
        self.K = np.array([10200])
        self.sig = np.array([[R.SIGMA_MIN]])

    def risultato(self, **kw):
        return R.etichette(mondo(self.B), self.K, self.sig, **kw)         # il mondo si fa dopo aver cambiato le barre

    def test_senza_movimenti_si_perdono_solo_i_costi(self):
        r, lock, fermato, ok = self.risultato()
        self.assertTrue(ok.all())
        np.testing.assert_allclose(r[0, 0], (1 - R.COSTO) ** 2 - 1, atol=1e-7)
        self.assertEqual(list(lock[0, 0]), list(map(float, R.ORIZZONTI)))
        self.assertFalse(fermato.any())

    def test_la_protezione_scatta_solo_negli_orizzonti_che_la_vedono(self):
        self.B["l"][10210] = 99.0                                        # 10 minuti dopo l'entrata, sotto ogni protezione
        r, lock, fermato, ok = self.risultato()
        j5, j15 = R.ORIZZONTI.index(5), R.ORIZZONTI.index(15)
        self.assertFalse(fermato[0, 0, j5])                              # 5 minuti: non la vede
        self.assertTrue(fermato[0, 0, j15])
        self.assertEqual(lock[0, 0, j15], 11.0)                          # libero dopo 11 minuti
        stop = 100 * (1 - R.K_STOP * R.SIGMA_MIN * math.sqrt(15 / 60.0))
        np.testing.assert_allclose(r[0, 0, j15], (1 - R.COSTO) ** 2 * stop * (1 - R.SLIP_STOP) / 100 - 1, atol=1e-7)

    def test_il_futuro_che_manca_si_segnala(self):
        M = mondo(piatte(10300))
        r, lock, fermato, ok = R.etichette(M, np.array([10200]), self.sig)
        j = R.ORIZZONTI.index(240)
        self.assertTrue(ok[0, 0, R.ORIZZONTI.index(60)])
        self.assertFalse(ok[0, 0, j])                                    # 4 ore dopo i dati sono finiti

    def test_a_costi_piu_alti_si_perde_di_piu(self):
        r1 = self.risultato(costo=0.001)[0]
        r2 = self.risultato(costo=0.004)[0]
        self.assertTrue(np.all(r1 > r2))


class RetePiccola(unittest.TestCase):
    def test_il_gradiente_e_giusto_su_ogni_peso(self):
        rng = np.random.default_rng(0)
        net = R.Rete([5, 7, 4, 3], 1)
        net.W, net.b = [w.astype(np.float64) for w in net.W], [b.astype(np.float64) for b in net.b]
        X, Y = rng.standard_normal((6, 5)), rng.standard_normal((6, 3))
        perdita = lambda: float(((net.avanti(X) - Y) ** 2).sum() / Y.size)
        out, att = net.avanti(X, tieni=True)
        gW, gb = net.indietro(att, 2.0 * (out - Y) / Y.size)
        peggio = 0.0
        for par, g in list(zip(net.W, gW)) + list(zip(net.b, gb)):
            for idx in np.ndindex(par.shape):
                par[idx] += 1e-6
                su = perdita()
                par[idx] -= 2e-6
                giu = perdita()
                par[idx] += 1e-6
                num = (su - giu) / 2e-6
                peggio = max(peggio, abs(num - g[idx]) / (abs(num) + abs(g[idx]) + 1e-9))
        self.assertLess(peggio, 1e-5)

    def test_impara_una_funzione_semplice(self):
        rng = np.random.default_rng(1)
        X = rng.standard_normal((2000, 4)).astype(np.float32)
        Y = np.stack([X[:, 0] * 0.5 + 0.2, np.maximum(X[:, 1], 0)], axis=1).astype(np.float32)
        net = R.Rete([4, 16, 8, 2], 2)
        perdite = R.addestra(net, X, Y, np.ones_like(Y), 40, lr=3e-3, batch=64, rng=rng)
        self.assertLess(perdite[-1], 0.2 * perdite[0])
        self.assertLess(perdite[-1], 0.02)

    def test_senza_bersaglio_non_si_impara(self):
        X = np.ones((10, 3), np.float32)
        Y = np.full((10, 2), 5.0, np.float32)
        net = R.Rete([3, 4, 2], 0)
        prima = [w.copy() for w in net.W]
        R.addestra(net, X, Y, np.zeros_like(Y), 2, rng=np.random.default_rng(0))
        for a, b in zip(prima, net.W):
            np.testing.assert_allclose(a, b, rtol=1e-3)                  # senza bersagli resta solo il decadimento dei pesi

    def test_salvataggio_e_lettura_danno_le_stesse_uscite(self):
        net = R.Rete([6, 5, 3], 4)
        X = np.random.default_rng(0).standard_normal((4, 6)).astype(np.float32)
        copia = R.Rete.da_dizionario(net.a_dizionario())
        np.testing.assert_allclose(net.avanti(X), copia.avanti(X), atol=1e-5)


class Decisioni(unittest.TestCase):
    def test_compra_solo_se_la_mossa_migliore_batte_l_attesa_del_margine(self):
        Q = np.zeros((1, 3, 1 + len(R.ORIZZONTI)), np.float32)
        Q[0, 0, 1 + 2] = 0.003                                           # +0,3 % a 15 minuti
        Q[0, 1, 1 + 8] = 0.0009                                          # +0,09 %: sotto il margine
        Q[0, 2, 0] = 0.01                                                # aspettare vale di più
        Q[0, 2, 1 + 4] = 0.005
        az = R.politica(Q, margine=0.001)
        self.assertEqual(list(az[0]), [3, 0, 0])

    def test_il_ritmo_toglie_un_costo_per_ora_bloccata(self):
        Q = np.zeros((1, 1, 1 + len(R.ORIZZONTI)), np.float32)
        Q[0, 0, 1 + R.ORIZZONTI.index(60)] = 0.002                       # +0,2 % in 1 ora
        Q[0, 0, 1 + R.ORIZZONTI.index(1440)] = 0.004                     # +0,4 % in 24 ore
        self.assertEqual(R.politica(Q, 0.0, 0.0)[0, 0], 1 + R.ORIZZONTI.index(1440) + 0)
        self.assertEqual(R.politica(Q, 0.0, 0.001)[0, 0], 1 + R.ORIZZONTI.index(60))   # 0,1 %/ora: 24 ore costano 2,4 %

    def test_una_posizione_alla_volta_per_crypto(self):
        N, H = 8, len(R.ORIZZONTI)
        az = np.zeros((1, N), int)
        az[0, [1, 2, 3, 6]] = 3                                          # compra, orizzonte 15 minuti
        Rr = np.full((1, N, H), 0.01, np.float32)
        LK = np.full((1, N, H), 45.0, np.float32)                        # ogni operazione blocca 45 minuti = 3 quarti d'ora
        FE, OK = np.zeros((1, N, H), bool), np.ones((1, N, H), bool)
        T = R.simula(az, Rr, LK, FE, OK)
        self.assertEqual(list(T[:, 1]), [1, 6])                          # la 2 e la 3 cadono mentre si è dentro; la 4 è dopo
        self.assertEqual(T.shape[1], 6)

    def test_senza_futuro_non_si_compra(self):
        az = np.array([[3]])
        T = R.simula(az, np.zeros((1, 1, 11), np.float32), np.ones((1, 1, 11), np.float32), np.zeros((1, 1, 11), bool), np.zeros((1, 1, 11), bool))
        self.assertEqual(len(T), 0)

    def test_statistiche(self):
        T = np.array([[0, 1, 2, 0.01, 15, 0], [0, 5, 3, -0.03, 30, 1]], float)
        s = R.statistiche(T, 1, 100)
        self.assertEqual(s["n"], 2)
        self.assertAlmostEqual(s["media"], -0.01)
        self.assertAlmostEqual(s["vinte"], 0.5)
        self.assertAlmostEqual(s["protezione"], 0.5)
        self.assertAlmostEqual(s["esposizione"], 45 / (100 * R.PASSO))


def ordini(B, t0=0.0):
    return R.prova_ordini_limite(mondo(B, t0), livelli=(1.5,))[1.5]


class OrdiniLimite(unittest.TestCase):
    """80 ore piatte a 100 con un'escursione oraria di 1 (massimo 100,5, minimo 99,5): ordine a 98,5, protezione 95,5."""

    def setUp(self):
        self.B = piatte(80 * 60)
        self.B["h"][10::60], self.B["l"][20::60] = 100.5, 99.5
        self.ora = 40 * 60                                               # l'ordine nasce alla chiusura dell'ora 39

    def test_senza_ribassi_non_si_fa_niente(self):
        self.assertEqual(ordini(self.B)["n"], 0)

    def test_acquisto_eseguito_da_una_vendita_a_mercato_sotto_il_livello_e_obiettivo_dopo(self):
        self.B["l"][self.ora + 5], self.B["ls"][self.ora + 5] = 98.0, 98.0
        self.B["h"][self.ora + 65], self.B["hb"][self.ora + 65] = 100.6, 100.6     # un acquisto a mercato sopra 100, un'ora dopo
        r = ordini(self.B)
        self.assertEqual(r["n"], 1)
        self.assertAlmostEqual(r["media"], (1 - R.COSTO) ** 2 * 100 / 98.5 - 1, places=9)
        self.assertEqual(r["obiettivo"], 1.0)

    def test_un_prezzo_alla_pari_del_livello_non_basta(self):
        self.B["l"][self.ora + 5], self.B["ls"][self.ora + 5] = 98.5, 98.5
        self.assertEqual(ordini(self.B)["n"], 0)

    def test_il_minimo_della_candela_senza_una_vendita_sotto_non_esegue_nel_modo_realistico(self):
        self.B["l"][self.ora + 5] = 98.0                                 # il minimo c'è ma non una vendita a mercato
        self.assertEqual(ordini(self.B)["n"], 0)
        r = R.prova_ordini_limite(mondo(self.B), livelli=(1.5,), realistico=False)[1.5]
        self.assertEqual(r["n"], 1)

    def test_l_obiettivo_non_conta_nel_minuto_dell_entrata(self):
        self.B["l"][self.ora + 5], self.B["ls"][self.ora + 5] = 98.0, 98.0
        self.B["h"][self.ora + 5], self.B["hb"][self.ora + 5] = 100.6, 100.6       # nello stesso minuto: prima o dopo? non si sa
        r = ordini(self.B)
        self.assertEqual(r["obiettivo"], 0.0)                            # niente obiettivo: si esce alla fine, dopo 24 ore

    def test_la_protezione_conta_gia_nel_minuto_dell_entrata(self):
        self.B["l"][self.ora + 5], self.B["ls"][self.ora + 5] = 95.0, 95.0         # scende subito sotto la protezione (95,5)
        r = ordini(self.B)
        self.assertEqual(r["protezione"], 1.0)
        uscita = min(95.5, 100.0) * (1 - R.SLIP_STOP)
        self.assertAlmostEqual(r["media"], (1 - R.COSTO) ** 2 * uscita / 98.5 - 1, places=9)


if __name__ == "__main__":
    unittest.main()
