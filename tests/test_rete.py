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


class Costi(unittest.TestCase):
    def test_cambiare_il_costo_dopo_equivale_a_rifare_le_etichette(self):
        M = mondo_casuale(giorni=12, seme=4)
        D = R.Dati(M, costo=0.002)
        r2 = R.etichette(M, D.K, D.sig, costo=0.0005)[0]
        np.testing.assert_allclose(D.con_costo(0.0005).R, r2, atol=2e-6)
        np.testing.assert_allclose(D.con_costo(0.002).R, D.R, atol=2e-6)       # lo stesso costo: niente cambia
        self.assertEqual(D.con_costo(0.0005).costo, 0.0005)
        self.assertEqual(D.costo, 0.002)                                       # l'originale non si tocca


class Cancello(unittest.TestCase):
    def test_si_compra_solo_se_il_guadagno_e_credibile(self):
        s = lambda n, media, dev: {"n": n, "media": media, "dev": dev}
        self.assertFalse(R.credibile(s(10, 0.01, 0.01)))                       # poche operazioni
        self.assertFalse(R.credibile(s(100, -0.001, 0.01)))                    # in perdita
        self.assertFalse(R.credibile(s(25, 0.001, 0.02)))                      # positivo ma dentro il rumore (t = 0,25)
        self.assertTrue(R.credibile(s(100, 0.004, 0.02)))                      # t = 2


class ModelloFinale(unittest.TestCase):
    def test_dal_json_al_modello_e_ai_valori(self):
        net = R.Rete([R.N_FEATURE, 6, 1 + len(R.ORIZZONTI)], 3)
        m = R.da_json({"rete": net.a_dizionario(7), "media": [0.0] * R.N_FEATURE, "dev": [1.0] * R.N_FEATURE, "margine": None,
                       "fuori": True, "iterazione": 4})
        self.assertTrue(math.isinf(m["margine"]))
        self.assertTrue(m["fuori"])
        M = mondo_casuale(giorni=12, seme=2)
        k = int(R.griglia(M.n)[3])
        Q, sig = R.valori_a(m, M, k)
        self.assertEqual(Q.shape, (2, 1 + len(R.ORIZZONTI)))
        X = R.caratteristiche(R.Pronto(M), np.array([k]))[:, 0, :]
        np.testing.assert_allclose(Q, net.avanti(np.clip(X, -6, 6)) * R.ESCALA, atol=1e-5)
        self.assertTrue(np.all(sig >= R.SIGMA_MIN))
        self.assertTrue(np.all(R.politica(Q[None], m["margine"])[0] == 0))     # margine infinito: aspetta sempre

    def test_il_modello_per_un_costo_che_non_c_e(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "m.json")
            net = R.Rete([R.N_FEATURE, 4, 1 + len(R.ORIZZONTI)], 1)
            blocco = {"rete": net.a_dizionario(), "media": [0.0] * R.N_FEATURE, "dev": [1.0] * R.N_FEATURE, "margine": 0.001, "fuori": False}
            with open(p, "w") as fh:
                json.dump({"modelli": {"0.002": blocco, "0.0005": blocco}}, fh)
            self.assertEqual(R.carica_modello(None, p)[1], 0.002)               # il più alto
            self.assertEqual(R.carica_modello(0.0005, p)[1], 0.0005)
            with self.assertRaises(ValueError):
                R.carica_modello(0.01, p)


class Studio(unittest.TestCase):
    """Tutto il percorso su dati finti e piccoli (poche iterazioni): addestramento, verifica a finestre, riassunto, modello."""

    @classmethod
    def setUpClass(cls):
        cls.D = R.Dati(mondo_casuale(giorni=44, seme=7, monete=2))
        cls.wins = R.finestre(cls.D, giorni_test=6, giorni_val=5, embargo=1, min_addestramento=8, max_finestre=2)

    def test_finestre_in_ordine_e_senza_sovrapposizioni(self):
        self.assertEqual(len(self.wins), 2)
        for w in self.wins:
            self.assertLessEqual(w["addestramento"][1], w["scelta"][0])
            self.assertLessEqual(w["scelta"][1], w["test"][0])
        self.assertLessEqual(self.wins[0]["test"][1], self.wins[1]["test"][0])

    def test_valuta_costo_e_riassumi(self):
        ris = R.valuta_costo(self.D, self.wins, 0.002, iterazioni=2, epoche=1)
        self.assertEqual(set(ris["strategie"]), {"q", "previsione", "ribasso", "momento", "sempre_1g"})
        for nome in ris["strategie"]:
            self.assertEqual(len(ris["strategie"][nome]), 2)
            st = R.riassumi(self.D, ris, nome)
            self.assertEqual(st["giorni"], len(st["conto"]))
            self.assertAlmostEqual(st["conto"][-1] if st["conto"] else 0.0, st["totale"], places=3)
        self.assertEqual(len(ris["curve_q"]), 2)
        self.assertEqual(len(ris["curve_q"][0]), 2)

    def test_comprare_sempre_costa_i_costi_e_resta_fuori_non_costa_niente(self):
        ris = R.valuta_costo(self.D, self.wins, 0.002, iterazioni=1, epoche=1)
        sempre = R.riassumi(self.D, ris, "sempre_1g")
        self.assertGreater(sempre["n"], 0)
        self.assertGreater(sempre["esposizione"], 0.9)                           # sempre dentro
        for nome in ("q", "previsione"):
            st = R.riassumi(self.D, ris, nome)
            if st["n"] == 0:
                self.assertEqual(st["totale"], 0.0)

    def test_modello_finale(self):
        D = R.Dati(mondo_casuale(giorni=60, seme=8, monete=2))
        m = R.modello_finale(D, 0.002, iterazioni=2)
        self.assertIn("fuori", m)
        self.assertEqual(m["rete"].dims[-1], 1 + len(R.ORIZZONTI))
        if m["fuori"]:
            self.assertTrue(math.isinf(m["margine"]))

    def test_sovradattamento_ha_addestramento_e_test_per_ogni_finestra(self):
        o = R.sovradattamento(self.D, self.wins, iterazioni=1)
        self.assertEqual(len(o), len(self.wins))
        for riga in o:
            self.assertEqual(set(riga), {"addestramento", "test"})
            self.assertGreaterEqual(riga["addestramento"]["n"], riga["test"]["n"] * 0)     # nessun errore, anche senza operazioni

    def test_il_json_non_contiene_infiniti(self):
        import json
        pulito = R._pulisci({"margine": float("inf"), "n": np.int64(3), "x": np.array([1.0, np.nan]), "t": (1, 2.5)})
        self.assertEqual(json.loads(json.dumps(pulito)), {"margine": None, "n": 3, "x": [1.0, None], "t": [1, 2.5]})

    def test_incondizionato_e_informazione(self):
        inc = R.incondizionato(self.D)
        self.assertEqual([x["orizzonte"] for x in inc], list(R.ORIZZONTI))
        info = R.ic_per_orizzonte(self.D, self.wins)
        self.assertEqual(len(info["medio"]), len(R.ORIZZONTI))
        self.assertEqual(len(info["quinti"][0]), 6)


class MuroDeiCosti(unittest.TestCase):
    def test_le_mosse_crescono_con_l_orizzonte_e_i_secondi_senza_scambi_si_contano(self):
        rng = np.random.default_rng(0)
        t = np.cumsum(rng.exponential(5.0, 40000)) + 1_700_000_000.0           # uno scambio ogni 5 secondi circa
        p = 100 * np.exp(np.cumsum(rng.standard_normal(len(t)) * 0.0004))
        dati = (t, p, np.ones(len(t)), np.ones(len(t), np.int8))
        orig_g, orig_c = R.giorni_continui, R.carica_scambi
        R.giorni_continui, R.carica_scambi = (lambda sym: ["2030-01-01"]), (lambda sym, g: dati)
        try:
            o = R.studio_orizzonti(simboli=("X-EUR",), giorni=1)
        finally:
            R.giorni_continui, R.carica_scambi = orig_g, orig_c
        x = o["crypto"]["X-EUR"]
        med = [r["mediana"] for r in x["per_orizzonte"]]
        self.assertEqual(med, sorted(med))                                     # più tempo, più mossa
        self.assertLess(x["secondi_con_scambi"], 0.3)                          # uno scambio ogni ~5 s: la maggior parte dei secondi è vuota
        self.assertAlmostEqual(x["scambi_ora"], 3600 / 5.0, delta=60)
        self.assertEqual(o["orizzonti"][0], 1)
        self.assertEqual(x["per_orizzonte"][0]["oltre"], 0.0)                  # a un secondo non c'è una mossa che valga 0,4 %


if __name__ == "__main__":
    unittest.main()


def modello_che_compra(azione, valore=0.5):
    """Una rete che vuole sempre la stessa mossa (1..len(ORIZZONTI)), `valore` % meglio di aspettare."""
    net = R.Rete([R.N_FEATURE, 4, 1 + len(R.ORIZZONTI)], 0)
    net.W[-1][:] = 0.0
    net.b[-1][:] = 0.0
    net.b[-1][azione] = valore
    return R.da_json({"rete": net.a_dizionario(), "media": [0.0] * R.N_FEATURE, "dev": [1.0] * R.N_FEATURE, "margine": None, "fuori": True})


class Rigioca(unittest.TestCase):
    """Le operazioni che il robot dell'app rigioca: una alla volta per crypto, entrata all'apertura del minuto, uscita
    all'apertura del minuto in cui finisce la durata o alla protezione; quelle non ancora finite restano aperte."""

    def iso(self, M, k):
        import datetime
        return datetime.datetime.fromtimestamp(M.t0 + 60 * k, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def test_una_alla_volta_e_le_aperte_alla_fine(self):
        import datetime
        M = mondo_casuale(giorni=9, seme=3)
        j = R.ORIZZONTI.index(60) + 1
        chiuse, aperte, vant = R.rigioca(modello_che_compra(j), M, M.n - 2 * 1440, M.n, margine=0.001, costo=0.002)
        self.assertGreater(len(chiuse), 30)
        self.assertTrue(1 <= len(aperte) <= 2)
        self.assertEqual(set(vant), {"A-EUR", "B-EUR"})
        quando = lambda s: datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).timestamp()
        per = {}
        for o in chiuse:
            c, k = M.simboli.index(o["sym"]), int((quando(o["t"]) - M.t0) // 60)
            self.assertGreaterEqual(k, R.AVVIO)
            self.assertAlmostEqual(o["prezzo"], M.o[c, k], places=6)                  # si entra all'apertura del minuto
            self.assertLess(o["protezione"], o["prezzo"])
            self.assertAlmostEqual(o["r"], (1 - 0.002) ** 2 * o["prezzo_uscita"] / o["prezzo"] - 1, places=5)
            if o["motivo"] == "scadenza":
                self.assertEqual(o["t_uscita"], self.iso(M, k + 60))
                self.assertAlmostEqual(o["prezzo_uscita"], M.o[c, k + 60], places=6)
            else:
                self.assertEqual(o["motivo"], "protezione")
                self.assertLessEqual(quando(o["t_uscita"]), quando(o["t"]) + 3600)
                self.assertLessEqual(o["prezzo_uscita"], o["protezione"])
            per.setdefault(o["sym"], []).append(o)
        for ops in per.values():
            for a, b in zip(ops, ops[1:]):
                self.assertGreaterEqual(b["t"], a["t_uscita"])
        for o in aperte:                                                              # finirebbero oltre i dati
            self.assertGreater(quando(o["scade"]), M.t0 + 60 * (M.n - 1))
            self.assertNotIn("t_uscita", o)

    def test_il_modello_fuori_resta_fuori_se_non_si_impone_un_margine(self):
        M = mondo_casuale(giorni=8, seme=4)
        chiuse, aperte, _ = R.rigioca(modello_che_compra(3), M, M.n - 1440, M.n)
        self.assertEqual((chiuse, aperte), ([], []))
