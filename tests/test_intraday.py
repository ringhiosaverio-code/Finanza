"""Test offline degli ordini rinnovati ogni ora (intraday.py): livelli, entrata, uscite, avanzamento uno alla volta,
prova prudente, ordini di adesso. Candele finte, niente rete.

    python3 -m unittest discover -s tests
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import intraday as I  # noqa: E402

T0 = 1700006400                                       # un'ora piena (divisibile per 3600)


def piatte(n, prezzo=100.0, mezza=1.0):
    """n candele senza movimento: escursione 2 (da prezzo-1 a prezzo+1), ATR = 2."""
    return [(T0 + k * 3600, prezzo, prezzo + mezza, prezzo - mezza, prezzo) for k in range(n)]


def candela(B, k, o, h, l, c):
    B[k] = (T0 + k * 3600, o, h, l, c)


class Livelli(unittest.TestCase):
    def test_serie_uguale_ad_atr_e_massimo(self):
        B, x = [], 12345
        for k in range(150):
            x = (x * 1103515245 + 12345) % 2 ** 31
            c = 100 + (x % 1000) / 100
            B.append((T0 + k * 3600, c, c + (x % 7) / 3, c - (x % 5) / 3, c + (x % 3) - 1))
        a, m = I.serie(B)
        for i in (24, 60, 149):
            self.assertAlmostEqual(a[i], I.atr(B, i), places=9)
            self.assertAlmostEqual(m[i], max(b[2] for b in B[i - 23:i + 1]), places=9)

    def test_ordine_ribasso_come_livelli(self):
        B = piatte(60)
        a, m = I.serie(B)
        mio = I.ordine_ore(B, 40, a, m, "ribasso", 2, 3)
        vecchio = I.livelli(B, 40, "ribasso", {"tipo": "ribasso", "e": 2, "s": 3})
        for k in ("entrata", "protezione", "obiettivo"):
            self.assertAlmostEqual(mio[k], vecchio[k])
        self.assertAlmostEqual(mio["entrata"], 100 - 2 * 2)             # prezzo - 2 ATR
        self.assertAlmostEqual(mio["protezione"], 100 - 2 * 2 - 3 * 2)  # entrata - 3 ATR
        self.assertAlmostEqual(mio["obiettivo"], 100)                   # il prezzo di partenza

    def test_ordine_rottura(self):
        B = piatte(60)
        a, m = I.serie(B)
        o = I.ordine_ore(B, 40, a, m, "rottura")
        self.assertAlmostEqual(o["entrata"], 101)                       # massimo delle ultime 24 ore
        self.assertAlmostEqual(o["protezione"], 101 - 1.5 * 2)
        self.assertAlmostEqual(o["obiettivo"], 101 + 3 * 2)


class Episodio(unittest.TestCase):
    def setUp(self):
        self.B = piatte(80)
        self.a, self.m = I.serie(self.B)
        self.i = 40
        self.lv = I.ordine_ore(self.B, self.i, self.a, self.m, "ribasso", 1.5)      # entrata 97, protezione 91, obiettivo 100

    def fase(self, B=None, **kw):
        B = B or self.B
        return I.episodio(B, self.i, self.lv, self.a[self.i], **kw)

    def test_non_tocca_il_livello_nell_ora_scade(self):
        self.assertEqual(self.fase()["fase"], "scaduto")

    def test_vale_una_sola_ora(self):
        candela(self.B, self.i + 2, 100, 100.5, 96.0, 98)               # lo tocca, ma un'ora dopo
        self.assertEqual(self.fase()["fase"], "scaduto")
        self.assertNotEqual(self.fase(finestra=2)["fase"], "scaduto")      # con 2 ore di validità entrerebbe

    def test_entra_e_arriva_all_obiettivo(self):
        candela(self.B, self.i + 1, 100, 99.9, 96.5, 98)                # tocca 97: entra a 97 (limite, non peggio)
        candela(self.B, self.i + 2, 98, 100.4, 97.5, 100)               # sopra l'obiettivo 100
        r = self.fase()
        self.assertEqual(r["fase"], "obiettivo")
        self.assertAlmostEqual(r["prezzo_entrata"], 97)
        self.assertAlmostEqual(r["rendimento"], 100 / 97 - 1 - 2 * I.COSTO)
        self.assertEqual(r["x"], self.i + 2)
        self.assertEqual(r["quando"], I._t(T0 + (self.i + 1) * 3600))

    def test_l_obiettivo_non_conta_nella_candela_dell_entrata(self):
        # la stessa candela tocca il livello (97) e arriva sopra l'obiettivo (100): non si sa se il massimo è venuto
        # prima del minimo, cioè prima dell'entrata. Sugli scambi veri contarlo faceva passare un ribasso da -0,5 % a +0,4 %
        B = list(self.B[:self.i + 4])
        candela(B, self.i + 1, 100, 100.4, 96.5, 99)
        candela(B, self.i + 2, 99, 99.5, 98.0, 98.5)                    # le candele dopo restano sotto l'obiettivo
        candela(B, self.i + 3, 98.5, 99.5, 98.0, 99)
        self.assertEqual(self.fase(B)["fase"], "dentro")
        candela(B, self.i + 3, 99, 100.2, 98.5, 100)                    # alla candela dopo l'entrata, sì
        r = self.fase(B)
        self.assertEqual(r["fase"], "obiettivo")
        self.assertEqual(r["x"], self.i + 3)

    def test_la_protezione_conta_nella_candela_dell_entrata(self):
        candela(self.B, self.i + 1, 100, 100.4, 90.0, 99)               # arriva sotto la protezione (91): il caso peggiore
        self.assertEqual(self.fase()["fase"], "protezione")

    def test_la_rottura_conserva_la_regola_di_prima(self):
        lv = I.ordine_ore(self.B, self.i, self.a, self.m, "rottura")     # entrata 103, obiettivo 107
        candela(self.B, self.i + 1, 100, 107.5, 99.9, 106)              # sale dal basso: passa dall'entrata prima dell'obiettivo
        self.assertEqual(I.episodio(self.B, self.i, lv, self.a[self.i], "rottura")["fase"], "obiettivo")

    def test_entra_all_apertura_se_e_gia_sotto(self):
        candela(self.B, self.i + 1, 95, 96, 94, 95.5)                   # apre sotto il limite: si compra all'apertura
        r = self.fase()
        self.assertAlmostEqual(r["prezzo_entrata"], 95)

    def test_protezione(self):
        candela(self.B, self.i + 1, 100, 99.9, 96.5, 98)
        candela(self.B, self.i + 2, 98, 98.5, 90.0, 92)                 # tocca 91
        r = self.fase()
        self.assertEqual(r["fase"], "protezione")
        self.assertAlmostEqual(r["prezzo_uscita"], 91)
        self.assertAlmostEqual(r["rendimento"], 91 / 97 - 1 - 2 * I.COSTO)

    def test_gap_sotto_la_protezione_esce_all_apertura(self):
        candela(self.B, self.i + 1, 100, 99.9, 96.5, 98)
        candela(self.B, self.i + 2, 88, 89, 87, 88)                     # apre già sotto 91
        r = self.fase()
        self.assertEqual(r["fase"], "protezione")
        self.assertAlmostEqual(r["prezzo_uscita"], 88)

    def test_dopo_24_ore_si_vende_alla_chiusura(self):
        candela(self.B, self.i + 1, 100, 99.9, 96.5, 97.5)
        for k in range(self.i + 2, self.i + 1 + 24):                    # 24 candele in posizione, mai protezione né obiettivo
            candela(self.B, k, 97.5, 98.5, 96.5, 97.8)
        r = self.fase()
        self.assertEqual(r["fase"], "scaduto_dentro")
        self.assertAlmostEqual(r["prezzo_uscita"], 97.8)
        self.assertEqual(r["x"], self.i + 24)
        self.assertEqual(r["chiusura"], r["scade"])
        self.assertEqual(r["scade"], I._t(T0 + (self.i + 1) * 3600 + 24 * 3600))

    def test_dentro_se_mancano_candele(self):
        B = piatte(self.i + 4)
        a, m = I.serie(B)
        candela(B, self.i + 1, 100, 99.9, 96.5, 98)
        candela(B, self.i + 2, 98, 99.5, 97.5, 98)                      # in posizione, né protezione né obiettivo
        candela(B, self.i + 3, 98, 99.5, 97.5, 98)
        r = I.episodio(B, self.i, I.ordine_ore(B, self.i, a, m, "ribasso", 1.5), a[self.i])
        self.assertEqual(r["fase"], "dentro")
        self.assertIn("scade", r)

    def test_ordine_ancora_valido_alla_fine_dei_dati(self):
        B = piatte(self.i + 1)
        a, m = I.serie(B)
        r = I.episodio(B, self.i, I.ordine_ore(B, self.i, a, m, "ribasso", 1.5), a[self.i])
        self.assertEqual(r["fase"], "attesa")

    def test_prova_prudente_chiede_un_quarto_di_escursione(self):
        candela(self.B, self.i + 1, 100, 99.9, 96.9, 98)                # tocca 97 per poco: entra solo nella prova normale
        self.assertEqual(self.fase()["fase"] in ("dentro", "obiettivo", "protezione", "scaduto_dentro"), True)
        self.assertEqual(self.fase(pen=0.25)["fase"], "scaduto")        # 96,9 non è sotto 97 - 0,25*2 = 96,5
        candela(self.B, self.i + 1, 100, 99.9, 96.4, 98)
        self.assertNotEqual(self.fase(pen=0.25)["fase"], "scaduto")


class Catena(unittest.TestCase):
    def serie_con_ribassi(self):
        """Candele piatte con tre ribassi improvvisi che poi rientrano."""
        B = piatte(400)
        for k0 in (100, 160, 260):
            candela(B, k0, 100, 100.2, 96.4, 98)
            candela(B, k0 + 1, 98, 100.6, 97.6, 100.3)                  # rientra sopra il prezzo di partenza
        return B

    def test_un_episodio_per_ribasso_e_in_ordine(self):
        B = self.serie_con_ribassi()
        a, m = I.serie(B)
        episodi, ordini, finale = I.catena(B, a, m, "ribasso", 1.5, da=30)
        self.assertEqual(len(episodi), 3)
        self.assertTrue(all(e["fase"] == "obiettivo" for e in episodi))
        self.assertEqual([e["i"] for e in episodi], [99, 159, 259])      # l'ordine nasce alla chiusura della candela prima
        self.assertGreater(ordini, 3)
        self.assertIsNotNone(finale["ordine"])                           # alla fine c'è un ordine ancora valido
        self.assertIsNone(finale["posizione"])

    def test_non_si_sovrappongono(self):
        B = piatte(400)
        for k in range(100, 140):                                        # un ribasso lungo: si entra e si resta dentro
            candela(B, k, 100 - (k - 100) * 0.05, 100.0 - (k - 100) * 0.05 + 0.5, 96 - (k - 100) * 0.05, 99.5 - (k - 100) * 0.05)
        a, m = I.serie(B)
        episodi, _, _ = I.catena(B, a, m, "ribasso", 1.5, da=30)
        self.assertGreaterEqual(len(episodi), 1)
        for prima, dopo in zip(episodi, episodi[1:]):
            self.assertGreaterEqual(dopo["i"], prima["x"])               # il nuovo ordine solo dopo l'uscita

    def test_posizione_ancora_aperta_alla_fine(self):
        B = piatte(210)
        candela(B, 205, 100, 99.9, 96.5, 98)
        for k in range(206, 210):
            candela(B, k, 98, 99.5, 97.5, 98)                           # resta dentro: niente protezione né obiettivo
        a, m = I.serie(B)
        episodi, _, finale = I.catena(B, a, m, "ribasso", 1.5)
        self.assertEqual(finale["posizione"]["fase"], "dentro")
        self.assertIsNone(finale["ordine"])                              # finché c'è la posizione, niente ordini nuovi


class Dati(unittest.TestCase):
    def finta_serie(self, n=900):
        B, x = [], 987
        for k in range(n):
            x = (x * 1103515245 + 12345) % 2 ** 31
            c = 100 + 3 * ((k // 17) % 5) - (x % 100) / 40
            B.append((T0 + k * 3600, c, c + 1 + (x % 5) / 4, c - 1 - (x % 11) / 3, c + (x % 5) / 5 - 0.4))
        return B

    def test_analizza_ore_senza_rete(self):
        B = self.finta_serie()
        with mock.patch.object(I, "candele", return_value=B), mock.patch.object(I.simula, "CRYPTO", ["BTC-EUR", "ETH-EUR"]):
            r = I.analizza_ore(log=lambda m: None, kraken=False)
        self.assertEqual(set(r["verifica"]), {"ribasso15", "ribasso20", "ribasso30", "rottura"})
        for v in r["verifica"].values():
            self.assertIn("anno1", v)
            self.assertIn("prudente", v)
            self.assertGreaterEqual(v["al_giorno"], 0)
        c = r["crypto"]["BTC-EUR"]
        self.assertEqual(set(c), {"prezzo", "prezzo_ora", "ora", "fino", "ordini", "posizioni", "storia_piani"})
        for p in c["storia_piani"]:
            self.assertTrue(p["regola"].startswith("ribasso"))           # la rottura è solo un confronto
            self.assertIn(p["fase"], ("attesa", "dentro", "obiettivo", "protezione", "scaduto_dentro"))
            self.assertIn("ora", p)
            self.assertIn("fino", p)
        for p in c["storia_piani"]:
            if p["fase"] in ("obiettivo", "protezione", "scaduto_dentro"):
                self.assertIn("rendimento", p)
                self.assertIn("prezzo_uscita", p)
        # l'ordine di adesso vale un'ora dalla chiusura dell'ultima candela
        for p in c["ordini"].values():
            self.assertEqual(p["fase"], "attesa")
            self.assertEqual(p["ora"], I.utc(I.ora_piano(B, len(B) - 1)))

    def test_ordini_correnti_tre_per_moneta(self):
        B = self.finta_serie(300)
        with mock.patch.object(I, "candele", return_value=B), mock.patch.object(I.simula, "CRYPTO", ["BTC-EUR"]):
            o = I.ordini_correnti(log=lambda m: None)
        self.assertEqual([p["regola"] for p in o["BTC-EUR"]["ordini"]], ["ribasso15", "ribasso20", "ribasso30"])
        entrate = [p["entrata"] for p in o["BTC-EUR"]["ordini"]]
        self.assertEqual(entrate, sorted(entrate, reverse=True))         # più profondo, più in basso

    def test_controllo_kraken_con_candele_finte(self):
        B = self.finta_serie(700)
        k = I.controllo_kraken(log=lambda m: None, candele_di=lambda sym: B)
        self.assertEqual(k["crypto"], 12)
        self.assertEqual(set(k["livelli"]), {"ribasso15", "ribasso20", "ribasso30"})
        self.assertIsNone(I.controllo_kraken(log=lambda m: None, candele_di=lambda sym: (_ for _ in ()).throw(OSError("no"))))


if __name__ == "__main__":
    unittest.main()
