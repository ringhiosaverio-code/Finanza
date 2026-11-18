"""Test offline di intraday.py (stato dei piani, candele chiuse) e crypto_live.py (avvisi): niente rete.

    python3 -m unittest discover -s tests
"""

import datetime
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import crypto_live as L  # noqa: E402
import intraday as I  # noqa: E402

T0 = 1_700_000_000 - 1_700_000_000 % 86400 + 16 * 3600      # una candela che si apre alle 16 UTC


def candele(n=60, prima=100.0, dopo=98.5, escursione=1.0):
    """n candele orarie piatte (massimo e minimo a +-escursione/2): fino alla 40, che chiude alle 17 UTC,
    al prezzo "prima"; dopo, al prezzo "dopo", tra l'entrata (97) e l'obiettivo (100) del ribasso."""
    return [[T0 - (40 - k) * 3600] + [(prima if k <= 40 else dopo) + d for d in (0, escursione / 2, -escursione / 2, 0)]
            for k in range(n)]


def utc(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)


class Fase(unittest.TestCase):
    def setUp(self):
        self.B = candele()
        self.i = 40
        self.assertEqual(I.ora_piano(self.B, self.i).hour, 17)
        self.lv = I.livelli(self.B, self.i, "ribasso")         # atr 1: entrata 97, protezione 94, obiettivo 100

    def test_livelli_ribasso(self):
        self.assertAlmostEqual(self.lv["entrata"], 97)
        self.assertAlmostEqual(self.lv["protezione"], 94)
        self.assertAlmostEqual(self.lv["obiettivo"], 100)

    def test_in_attesa_se_l_entrata_non_scatta(self):
        self.assertEqual(I.fase(self.B, self.i, "ribasso")["fase"], "attesa")

    def test_dentro_poi_obiettivo(self):
        B = [list(b) for b in self.B]
        B[42][3] = 96.5                                        # tocca l'entrata (97)
        f = I.fase(B, self.i, "ribasso")
        self.assertEqual((f["fase"], f["prezzo_entrata"]), ("dentro", 97))
        B[45][2] = 100.5                                       # poi l'obiettivo (100)
        f = I.fase(B, self.i, "ribasso")
        self.assertEqual(f["fase"], "obiettivo")
        self.assertAlmostEqual(f["rendimento"], 100 / 97 - 1 - 2 * I.COSTO)

    def test_protezione_prima_dell_obiettivo_nella_stessa_candela(self):
        B = [list(b) for b in self.B]
        B[42][3] = 93.0                                        # entrata e protezione nella stessa candela
        B[42][2] = 101.0
        self.assertEqual(I.fase(B, self.i, "ribasso")["fase"], "protezione")

    def test_obiettivo_prima_dell_entrata_non_conta(self):
        B = [list(b) for b in self.B]
        B[41][2] = 101.0                                       # l'obiettivo arriva prima dell'entrata
        self.assertEqual(I.fase(B, self.i, "ribasso")["fase"], "attesa")

    def test_scadenza(self):
        B = candele(n=70)
        self.assertEqual(I.fase(B, self.i, "ribasso")["fase"], "scaduto")
        B = [list(b) for b in B]
        B[42][3] = 96.5
        f = I.fase(B, self.i, "ribasso")
        self.assertEqual(f["fase"], "scaduto_dentro")
        self.assertAlmostEqual(f["rendimento"], 98.5 / 97 - 1 - 2 * I.COSTO)

    def test_piani_recenti_solo_alle_17_e_alle_21_nelle_ultime_24_ore(self):
        rec = I.piani_recenti(self.B)
        self.assertTrue(rec)
        for j in rec:
            self.assertIn(I.ora_piano(self.B, j).hour, (17, 21))
            self.assertGreater(j, len(self.B) - 1 - I.ORE)
        self.assertEqual(rec, sorted(rec, reverse=True))


class Varianti(unittest.TestCase):
    def test_le_regole_dell_app_sono_le_prime_tre_varianti(self):
        B = [list(b) for b in candele(n=80)]
        B[42][3] = 96.5
        for (nome, v), r in zip(I.VARIANTI[:3], ("ribasso", "rottura", "tempo")):
            self.assertEqual(I.esito(B, 40, r), I.esito(B, 40, v["tipo"], v), nome)

    def test_filtro_di_tendenza(self):
        giu = [[T0 - (600 - k) * 3600, 200 - k / 10, 0, 0, 200 - k / 10] for k in range(700)]
        su = [[b[0], 0, 0, 0, 100 + k / 10] for k, b in enumerate(giu)]
        self.assertFalse(I.filtro(giu, 600, "tendenza"))
        self.assertTrue(I.filtro(su, 600, "tendenza"))
        self.assertEqual(I.esito(giu, 600, "tempo", dict(I.PARAMETRI["tempo"], filtro="tendenza")), "no")


class Candele(unittest.TestCase):
    def test_tiene_solo_le_candele_chiuse(self):
        ora = T0 + 3 * 3600 + 1200                             # scaricate 20 minuti dopo l'inizio della candela
        ts = [T0, T0 + 3600, T0 + 7200, T0 + 3 * 3600, ora - 5]  # l'ultima ora in corso e il punto "adesso"
        res = {"chart": {"result": [{"timestamp": ts, "indicators": {"quote": [
            {"open": [1] * 5, "high": [2] * 5, "low": [0.5] * 5, "close": [1.5] * 5}]}}]}}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(I, "CACHE", d):
            path = os.path.join(d, "X-EUR.json")
            with open(path, "w") as fh:
                json.dump(res, fh)
            os.utime(path, (ora, ora))
            with mock.patch.object(I.time, "time", return_value=ora + 1):
                B = I.candele("X-EUR")
        self.assertEqual([b[0] for b in B], ts[:3])


def piano(fase="attesa", regola="ribasso", fino="2030-01-02 17:00 UTC", **kw):
    p = {"sym": "BTC-EUR", "regola": regola, "ora": "2030-01-01 17:00 UTC", "fino": fino, "attuale": True,
         "entrata": 97.0 if regola == "ribasso" else 103.0, "protezione": 94.0 if regola == "ribasso" else 101.5,
         "obiettivo": 100.0 if regola == "ribasso" else 106.0, "fase": fase}
    p.update(kw)
    return p


ADESSO = datetime.datetime(2030, 1, 1, 20, 0, tzinfo=datetime.timezone.utc)


class Avanza(unittest.TestCase):
    def test_protezione_e_obiettivo_non_contano_prima_dell_entrata(self):
        p = piano(regola="rottura")                            # prezzo sotto la protezione: normale, non sei dentro
        self.assertEqual(L.avanza(p, 100.0, ADESSO), [])
        self.assertEqual(p["fase"], "attesa")
        p = piano()                                            # ribasso: obiettivo = prezzo di partenza
        self.assertEqual(L.avanza(p, 100.5, ADESSO), [])

    def test_entrata_poi_obiettivo(self):
        p = piano()
        self.assertEqual(L.avanza(p, 96.8, ADESSO), ["entrata"])
        self.assertEqual((p["fase"], p["prezzo_entrata"]), ("dentro", 96.8))
        self.assertEqual(L.avanza(p, 98.0, ADESSO), [])
        self.assertEqual(L.avanza(p, 100.1, ADESSO), ["obiettivo"])
        self.assertAlmostEqual(p["rendimento"], 100 / 96.8 - 1 - 2 * I.COSTO, 6)
        self.assertEqual(L.avanza(p, 90.0, ADESSO), [])        # chiuso: niente altri avvisi

    def test_rottura_entra_al_prezzo_se_salta_sopra(self):
        p = piano(regola="rottura")
        self.assertEqual(L.avanza(p, 103.5, ADESSO), ["entrata"])
        self.assertEqual(p["prezzo_entrata"], 103.5)
        self.assertEqual(L.avanza(p, 101.4, ADESSO), ["protezione"])

    def test_scadenza(self):
        dopo = ADESSO + datetime.timedelta(days=2)
        p = piano()
        self.assertEqual(L.avanza(p, 96.0, dopo), [])          # scaduto prima di entrare: nessun avviso
        self.assertEqual(p["fase"], "scaduto")
        p = piano(fase="dentro", prezzo_entrata=97.0)
        self.assertEqual(L.avanza(p, 98.0, dopo), ["scadenza"])
        self.assertEqual(p["fase"], "scaduto_dentro")


def crypto(fase="attesa", ora="2030-01-01 17:00 UTC", fino="2030-01-02 17:00 UTC", precedenti=()):
    p = piano(fase=fase)
    q = piano(regola="rottura")
    tempo = {"entrata": 100.0, "fase": "dentro"}
    pul = lambda d: {k: v for k, v in d.items() if k not in ("sym", "regola", "ora", "fino", "attuale")}
    return {"BTC-EUR": {"prezzo": 100.0, "prezzo_ora": ora, "ora": ora, "fino": fino, "storia": {},
                        "piani": {"ribasso": pul(p), "rottura": pul(q), "tempo": tempo},
                        "precedenti": list(precedenti)}}


class Stato(unittest.TestCase):
    def test_nessun_avviso_per_i_livelli_gia_superati_all_avvio(self):
        s = L.Stato()
        s.unisci(crypto(), {})
        s.controlla_livelli("BTC-EUR", 96.0, ADESSO)           # già sotto l'entrata al primo prezzo
        self.assertEqual(s.eventi, [])
        self.assertEqual(s.seguiti[("BTC-EUR", "ribasso", "2030-01-01 17:00 UTC")]["fase"], "dentro")
        s.controlla_livelli("BTC-EUR", 100.2, ADESSO)          # da qui in poi gli avvisi ci sono
        self.assertEqual([e["evento"] for e in s.eventi], ["obiettivo"])
        self.assertEqual(s.n_eventi, 1)

    def test_avviso_all_entrata_dopo_l_avvio(self):
        s = L.Stato()
        s.unisci(crypto(), {})
        s.controlla_livelli("BTC-EUR", 99.0, ADESSO)
        s.controlla_livelli("BTC-EUR", 96.9, ADESSO)
        self.assertEqual([(e["regola"], e["evento"]) for e in s.eventi], [("ribasso", "entrata")])

    def test_il_ricalcolo_non_torna_indietro_e_tiene_il_piano_precedente(self):
        s = L.Stato()
        s.unisci(crypto(), {})
        s.controlla_livelli("BTC-EUR", 99.0, ADESSO)
        s.controlla_livelli("BTC-EUR", 96.9, ADESSO)           # dentro dal vivo; le candele dicono ancora attesa
        vecchi = [{k: v for k, v in piano(regola=r).items() if k not in ("sym", "attuale")} for r in ("ribasso", "rottura")]
        s.unisci(crypto(ora="2030-01-01 21:00 UTC", fino="2030-01-02 21:00 UTC", precedenti=vecchi), {})
        k = ("BTC-EUR", "ribasso", "2030-01-01 17:00 UTC")
        self.assertEqual(s.seguiti[k]["fase"], "dentro")
        self.assertFalse(s.seguiti[k]["attuale"])
        self.assertTrue(s.seguiti[("BTC-EUR", "ribasso", "2030-01-01 21:00 UTC")]["attuale"])
        dati = json.loads(s.json())
        self.assertEqual(len(dati["seguiti"]), 4)
        self.assertNotIn("silenzio", json.dumps(dati))


def ordine(rid="ribasso20", ora="2030-01-01 20:00 UTC", fase="attesa", **kw):
    """Un ordine orario come lo dà intraday.analizza_ore: vale un'ora, entrata 97, protezione 94, obiettivo 100."""
    d = {"regola": rid, "ora": ora, "fino": "2030-01-01 21:00 UTC", "entrata": 97.0, "protezione": 94.0,
         "obiettivo": 100.0, "fase": fase}
    d.update(kw)
    return d


def crypto_ore(ordini=(), posizioni=(), ora="2030-01-01 20:00 UTC"):
    return {"BTC-EUR": {"prezzo": 100.0, "prezzo_ora": ora, "ora": ora, "fino": "2030-01-01 21:00 UTC",
                        "ordini": {o["regola"]: o for o in ordini}, "posizioni": list(posizioni), "storia_piani": []}}


class OrdiniOrari(unittest.TestCase):
    def test_un_ordine_orario_vale_un_ora_poi_si_esce_al_piu_tardi_dopo_24_ore(self):
        p = dict(ordine(), sym="BTC-EUR", attuale=True)
        self.assertEqual(L.avanza(p, 96.8, ADESSO), ["entrata"])
        self.assertEqual((p["fase"], p["prezzo_entrata"]), ("dentro", 96.8))
        self.assertEqual(p["scade"], I.utc(ADESSO + datetime.timedelta(hours=I.TENUTA)))
        dopo = ADESSO + datetime.timedelta(hours=5)             # l'ordine è scaduto da un pezzo, la posizione no
        self.assertEqual(L.avanza(p, 98.0, dopo), [])
        self.assertEqual(p["fase"], "dentro")
        self.assertEqual(L.avanza(p, 98.0, ADESSO + datetime.timedelta(hours=I.TENUTA, minutes=1)), ["scadenza"])
        self.assertEqual(p["fase"], "scaduto_dentro")
        self.assertAlmostEqual(p["rendimento"], 98.0 / 96.8 - 1 - 2 * I.COSTO, 6)

    def test_l_ordine_che_non_scatta_in_un_ora_scade_senza_operazione(self):
        p = dict(ordine(), sym="BTC-EUR", attuale=True)
        self.assertEqual(L.avanza(p, 99.0, ADESSO + datetime.timedelta(hours=2)), [])
        self.assertEqual(p["fase"], "scaduto")

    def test_il_ribasso_orario_entra_al_prezzo_se_apre_sotto_il_livello(self):
        p = dict(ordine("ribasso30"), sym="BTC-EUR", attuale=True)
        self.assertEqual(L.avanza(p, 95.0, ADESSO), ["entrata"])
        self.assertEqual(p["prezzo_entrata"], 95.0)
        self.assertEqual(L.avanza(p, 93.9, ADESSO), ["protezione"])
        self.assertAlmostEqual(p["rendimento"], 94.0 / 95.0 - 1 - 2 * I.COSTO, 6)

    def test_da_seguire_prende_gli_ordini_di_adesso_e_le_posizioni_aperte(self):
        aperta = ordine("ribasso15", ora="2030-01-01 17:00 UTC", fase="dentro", prezzo_entrata=96.9,
                        scade="2030-01-02 17:30 UTC")
        seguiti = L.da_seguire(crypto_ore([ordine("ribasso20"), ordine("ribasso30")], [aperta]))
        self.assertEqual(sorted(k[1] for k in seguiti), ["ribasso15", "ribasso20", "ribasso30"])
        self.assertTrue(seguiti[("BTC-EUR", "ribasso20", "2030-01-01 20:00 UTC")]["attuale"])
        self.assertFalse(seguiti[("BTC-EUR", "ribasso15", "2030-01-01 17:00 UTC")]["attuale"])

    def test_stato_segue_gli_ordini_e_avvisa_all_entrata_dopo_l_avvio(self):
        s = L.Stato()
        s.unisci(crypto_ore([ordine("ribasso15"), ordine("ribasso20"), ordine("ribasso30")]), {})
        s.controlla_livelli("BTC-EUR", 99.0, ADESSO)
        self.assertEqual(s.eventi, [])
        s.controlla_livelli("BTC-EUR", 96.9, ADESSO)            # sotto l'entrata (97): scattano tutti e tre
        self.assertEqual(sorted(e["regola"] for e in s.eventi), ["ribasso15", "ribasso20", "ribasso30"])
        self.assertEqual({e["evento"] for e in s.eventi}, {"entrata"})

    def test_all_avvio_le_posizioni_gia_dentro_non_fanno_avviso(self):
        dentro = ordine("ribasso20", ora="2030-01-01 17:00 UTC", fase="dentro", prezzo_entrata=96.9,
                        scade="2030-01-02 17:30 UTC")
        s = L.Stato()
        s.unisci(crypto_ore([ordine("ribasso15")], [dentro]), {})
        s.controlla_livelli("BTC-EUR", 100.5, ADESSO)           # l'obiettivo di una posizione che c'era già: tabella sì, avviso no
        self.assertEqual(s.eventi, [])
        self.assertEqual(s.seguiti[("BTC-EUR", "ribasso20", "2030-01-01 17:00 UTC")]["fase"], "obiettivo")

    def test_il_ricalcolo_non_perde_una_posizione_entrata_dal_vivo(self):
        s = L.Stato()
        s.unisci(crypto_ore([ordine("ribasso15")]), {})
        s.controlla_livelli("BTC-EUR", 96.9, ADESSO)            # dentro dal vivo: le candele ancora non lo sanno
        s.unisci(crypto_ore([ordine("ribasso15", ora="2030-01-01 21:00 UTC", fino="2030-01-01 22:00 UTC")],
                            ora="2030-01-01 21:00 UTC"), {})
        vecchia = s.seguiti[("BTC-EUR", "ribasso15", "2030-01-01 20:00 UTC")]
        self.assertEqual(vecchia["fase"], "dentro")
        self.assertFalse(vecchia["attuale"])
        self.assertTrue(s.seguiti[("BTC-EUR", "ribasso15", "2030-01-01 21:00 UTC")]["attuale"])
        s.controlla_livelli("BTC-EUR", 100.2, ADESSO)           # esce all'obiettivo dal vivo
        self.assertEqual([e["evento"] for e in s.eventi if e["evento"] != "entrata"], ["obiettivo"])

    def test_un_ordine_scaduto_senza_entrata_sparisce_al_ricalcolo(self):
        s = L.Stato()
        s.unisci(crypto_ore([ordine("ribasso15")]), {})
        s.unisci(crypto_ore([ordine("ribasso15", ora="2030-01-01 21:00 UTC", fino="2030-01-01 22:00 UTC")],
                            ora="2030-01-01 21:00 UTC"), {})
        self.assertEqual(list(s.seguiti), [("BTC-EUR", "ribasso15", "2030-01-01 21:00 UTC")])

    def test_aggiorna_piani_usa_gli_ordini_orari(self):
        r = {"crypto": crypto_ore([ordine("ribasso20")]), "verifica": {"ribasso20": {"anno2": {"n": 1}}}}
        s = L.Stato()
        with mock.patch.object(L.intraday, "analizza_ore", return_value=r) as m:
            s.aggiorna_piani()
        self.assertFalse(m.call_args[1]["kraken"])               # niente controllo su Kraken a ogni ora
        self.assertEqual(list(s.seguiti), [("BTC-EUR", "ribasso20", "2030-01-01 20:00 UTC")])
        self.assertEqual(s.piani["BTC-EUR"]["ora"], "2030-01-01 20:00 UTC")
        self.assertIsNone(s.piani["BTC-EUR"]["storia"])          # il formato orario non ha la "storia" dei due piani
        self.assertIn("ribasso20", json.loads(s.json())["verifica"])


class Kraken(unittest.TestCase):
    def test_legge_tutte_le_coppie_con_le_chiavi_di_kraken(self):
        result = {}
        for i, (sym, (pair, key)) in enumerate(L.COPPIE.items()):
            result[key] = {"c": [str(10 + i), "1"], "o": str(9 + i), "h": ["0", str(11 + i)], "l": ["0", str(8 + i)]}
        body = json.dumps({"error": [], "result": result}).encode()
        with mock.patch.object(L.urllib.request, "urlopen", return_value=io.BytesIO(body)) as u:
            out = L.leggi_kraken()
        self.assertEqual(set(out), set(L.COPPIE))
        self.assertEqual(out["BTC-EUR"], {"prezzo": 10.0, "apertura": 9.0, "max24": 11.0, "min24": 8.0})
        self.assertIn("XBTEUR", u.call_args[0][0].full_url)

    def test_errore_di_kraken(self):
        body = json.dumps({"error": ["EAPI:Rate limit exceeded"], "result": {}}).encode()
        with mock.patch.object(L.urllib.request, "urlopen", return_value=io.BytesIO(body)):
            with self.assertRaises(RuntimeError):
                L.leggi_kraken()


if __name__ == "__main__":
    unittest.main()
