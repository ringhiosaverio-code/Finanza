"""Test offline di rete_azioni.py: la griglia delle sedute, caratteristiche senza futuro, esiti chiusi entro la seduta
e le operazioni che il robot rigioca. Niente rete: barre finte.

    python3 -m unittest discover -s tests
"""

import datetime
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["FINANZA_SENZA_RETE"] = "1"                                  # i segnali esterni solo dalla cache: niente rete
import rete  # noqa: E402
import rete_azioni as A  # noqa: E402

ROMA = A.ROMA
H = len(A.ORIZZONTI)


def giorni_feriali(n, da=datetime.date(2030, 1, 7)):
    out, g = [], da
    while len(out) < n:
        if g.weekday() < 5:
            out.append(g)
        g += datetime.timedelta(days=1)
    return out


def righe_finte(sedute=8, seme=1, ultima=A.BARRE, salta=()):
    """Barre da 5 minuti di una seduta dopo l'altra, 09:00-17:25 ora italiana; l'ultima seduta ha `ultima` barre."""
    rng = np.random.default_rng(seme)
    out, prezzo = [], 10.0
    for s, g in enumerate(giorni_feriali(sedute)):
        prezzo *= float(np.exp(rng.standard_normal() * 0.01))                    # il salto della notte
        for j in range(A.BARRE if s < sedute - 1 else ultima):
            if (s, j) in salta:
                continue
            t = datetime.datetime(g.year, g.month, g.day, 9, 0, tzinfo=ROMA) + datetime.timedelta(minutes=A.BARRA * j)
            o = prezzo
            prezzo *= float(np.exp(rng.standard_normal() * 0.002))
            h, l = max(o, prezzo) * (1 + abs(rng.standard_normal()) * 0.0005), min(o, prezzo) * (1 - abs(rng.standard_normal()) * 0.0005)
            out.append((int(t.timestamp()), o, h, l, prezzo, float(rng.integers(100, 5000))))
    return out


def barre_finte(sedute=8, titoli=3, ultima=A.BARRE, salta=()):
    return A.Barre(["T%d.MI" % i for i in range(titoli)], [righe_finte(sedute, 10 + i, ultima, salta) for i in range(titoli)])


def modello_che_compra(azione, valore=0.5, margine=None):
    """Una rete che vuole sempre la stessa mossa: `azione` 1..H (comprare e tenere ORIZZONTI[azione - 1]) vale
    `valore` % più di aspettare, qualunque cosa veda."""
    net = rete.Rete([A.N_FEATURE, 4, 1 + H], 0)
    net.W[-1][:] = 0.0
    net.b[-1][:] = 0.0
    net.b[-1][azione] = valore                                                    # in unità di rete.ESCALA (1 %)
    return rete.da_json({"rete": net.a_dizionario(), "media": [0.0] * A.N_FEATURE, "dev": [1.0] * A.N_FEATURE,
                         "margine": margine, "fuori": margine is None, "iterazione": 1})


def ora_roma(s):
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).astimezone(ROMA)


class Griglia(unittest.TestCase):
    def test_sedute_per_barre_in_ora_italiana(self):
        B = barre_finte(sedute=6, titoli=2)
        self.assertEqual((B.S, B.C, B.n), (6, 2, 6 * A.BARRE))
        self.assertEqual(B.o.shape, (2, 6 * A.BARRE))
        prima = datetime.datetime.fromtimestamp(B.T[0], ROMA)
        self.assertEqual((prima.hour, prima.minute), (9, 0))
        ultima_di_oggi = datetime.datetime.fromtimestamp(B.T[A.BARRE - 1], ROMA)
        self.assertEqual((ultima_di_oggi.hour, ultima_di_oggi.minute), (17, 25))
        self.assertTrue(B.vera.all())
        self.assertEqual(B.ultima, B.n - 1)

    def test_una_barra_che_manca_resta_al_prezzo_di_prima_senza_volume(self):
        B = barre_finte(sedute=6, titoli=1, salta={(2, 40)})
        g = 2 * A.BARRE + 40
        self.assertFalse(B.vera[0, g])
        for k in "ohlc":
            self.assertEqual(getattr(B, k)[0, g], B.c[0, g - 1])
        self.assertEqual(B.v[0, g], 0)

    def test_la_seduta_a_meta(self):
        B = barre_finte(sedute=7, titoli=2, ultima=30)
        self.assertEqual(B.ultima, 6 * A.BARRE + 29)
        self.assertFalse(B.vera[:, B.ultima + 1:].any())
        G = A.decisioni_possibili(B)                                             # per imparare: solo sedute finite
        self.assertLess(G.max(), 6 * A.BARRE)
        G2 = A.decisioni_possibili(B, solo_complete=False)                       # per il robot: anche quella in corso
        self.assertEqual(G2.max(), B.ultima)
        self.assertTrue(np.all(G2 % A.BARRE >= A.PRIMA))                         # dalla terza barra della seduta
        self.assertTrue(np.all(G2 // A.BARRE >= A.SEDUTE_STORIA))


class CaratteristicheAzioni(unittest.TestCase):
    def test_nessuna_caratteristica_usa_il_futuro(self):
        B1 = barre_finte(sedute=8, titoli=3)
        G = A.decisioni_possibili(B1)
        X1, s1 = A.caratteristiche(B1, G)
        self.assertEqual(X1.shape, (3, len(G), A.N_FEATURE))
        self.assertFalse(np.isnan(X1).any())
        j = 150
        B2 = barre_finte(sedute=8, titoli=3)
        taglio = int(G[j])                                                       # si cambiano tutte le barre da G[j] in poi
        rng = np.random.default_rng(4)
        for k in ("o", "h", "l", "c", "v"):
            a = getattr(B2, k)
            a[:, taglio:] = a[:, taglio:] * rng.uniform(0.5, 2.0, a[:, taglio:].shape)
        X2, s2 = A.caratteristiche(B2, G)
        np.testing.assert_array_equal(X1[:, :j + 1], X2[:, :j + 1])              # fino a G[j] compreso, uguali
        np.testing.assert_array_equal(s1[:, :j + 1], s2[:, :j + 1])
        self.assertFalse(np.array_equal(X1[:, j + 1:], X2[:, j + 1:]))           # dopo, cambiano


class EsitiAzioni(unittest.TestCase):
    def piatta(self, sedute=7):
        B = barre_finte(sedute=sedute, titoli=1)
        for k in "ohlc":
            getattr(B, k)[:] = 20.0
        return B

    def test_senza_movimenti_si_perdono_solo_i_costi(self):
        B = self.piatta()
        G = A.decisioni_possibili(B)
        sig = np.full((1, len(G)), 0.01)
        R, LK, FE, OK = A.esiti(B, G, sig, costo=0.001)
        self.assertTrue(OK.all())
        np.testing.assert_allclose(R, (1 - 0.001) ** 2 - 1, atol=1e-6)
        self.assertFalse(FE.any())

    def test_tutto_si_chiude_entro_la_seduta(self):
        B = self.piatta()
        s = 5                                                                    # la prima seduta con abbastanza storia
        B.c[0, s * A.BARRE + A.BARRE - 1] = 21.0                                 # la chiusura della seduta
        G = np.array([s * A.BARRE + 2, s * A.BARRE + 90])
        sig = np.full((1, 2), 0.01)
        R, LK, FE, OK = A.esiti(B, G, sig, costo=0.0)
        ic = A.ORIZZONTI.index(510)
        self.assertAlmostEqual(float(R[0, 0, ic]), 21.0 / 20.0 - 1, places=6)   # fino alla chiusura: si esce a 21
        self.assertAlmostEqual(float(LK[0, 0, ic]), (A.BARRE - 2) * A.BARRA)
        # alle 16:30 un'ora o quattro ore finiscono comunque alla chiusura
        for h in (120, 240, 510):
            self.assertAlmostEqual(float(R[0, 1, A.ORIZZONTI.index(h)]), 0.05, places=6)
            self.assertAlmostEqual(float(LK[0, 1, A.ORIZZONTI.index(h)]), (A.BARRE - 90) * A.BARRA)
        self.assertAlmostEqual(float(R[0, 1, A.ORIZZONTI.index(30)]), 0.0, places=6)

    def test_la_protezione_scatta_solo_negli_orizzonti_che_la_vedono(self):
        B = self.piatta()
        g = 5 * A.BARRE + 10
        B.l[0, g + 4] = 15.0                                                     # un crollo 20 minuti dopo l'entrata
        sig = np.full((1, 1), 0.01)
        R, LK, FE, OK = A.esiti(B, np.array([g]), sig, costo=0.0)
        self.assertFalse(FE[0, 0, A.ORIZZONTI.index(15)])                        # 15 minuti: finisce prima
        self.assertTrue(FE[0, 0, A.ORIZZONTI.index(30)])
        stop = 20.0 * (1 - rete.K_STOP * 0.01 * np.sqrt(30 / 60))
        self.assertAlmostEqual(float(R[0, 0, A.ORIZZONTI.index(30)]), stop * (1 - A.SLIP) / 20.0 - 1, places=5)
        self.assertEqual(float(LK[0, 0, A.ORIZZONTI.index(30)]), 5 * A.BARRA)

    def test_il_futuro_che_manca_si_segnala(self):
        B = barre_finte(sedute=7, titoli=1, ultima=40)
        G = A.decisioni_possibili(B, solo_complete=False)
        g = int(G[-1])                                                           # l'ultima barra: niente esito oltre
        R, LK, FE, OK = A.esiti(B, np.array([g - 10]), np.full((1, 1), 0.01))
        self.assertTrue(OK[0, 0, A.ORIZZONTI.index(5)])
        self.assertFalse(OK[0, 0, A.ORIZZONTI.index(60)])
        self.assertFalse(OK[0, 0, A.ORIZZONTI.index(510)])

    def test_dati_per_l_addestramento(self):
        D = A.DatiAzioni(barre_finte(sedute=8, titoli=2))
        self.assertEqual(D.R.shape, (2, len(D.G), H))
        self.assertEqual(D.X.shape[:2], (2, len(D.G)))
        self.assertEqual((D.passo, D.orizzonti), (A.BARRA, A.ORIZZONTI))
        self.assertTrue(np.all(np.diff(D.K) > 0))


class RigiocaAzioni(unittest.TestCase):
    def test_operazioni_chiuse_entro_la_seduta_e_una_alla_volta(self):
        B = barre_finte(sedute=8, titoli=3)
        m = modello_che_compra(A.ORIZZONTI.index(60) + 1)
        chiuse, aperte, vant = A.rigioca(m, B, margine=0.001, sedute=3, costo=0.001)
        self.assertGreater(len(chiuse), 20)
        self.assertEqual(aperte, [])                                             # tutte le sedute sono finite
        self.assertEqual(set(vant), set(B.simboli))
        per_titolo = {}
        for o in chiuse:
            entra, esce = ora_roma(o["t"]), ora_roma(o["t_uscita"])
            self.assertEqual(entra.date(), esce.date())                          # niente posizioni di notte
            self.assertLessEqual((esce.hour, esce.minute), (17, 30))
            self.assertGreaterEqual((entra.hour, entra.minute), (9, 10))
            self.assertIn(o["motivo"], ("scadenza", "chiusura", "protezione"))
            self.assertAlmostEqual(o["r"], (1 - 0.001) ** 2 * o["prezzo_uscita"] / o["prezzo"] - 1, places=5)
            if o["motivo"] == "scadenza":
                self.assertEqual((esce - entra).total_seconds(), 3600)
            per_titolo.setdefault(o["sym"], []).append(o)
        for ops in per_titolo.values():                                         # una posizione alla volta per titolo
            for a, b in zip(ops, ops[1:]):
                self.assertGreaterEqual(b["t"], a["t_uscita"])
        sedute = {ora_roma(o["t"]).date() for o in chiuse}
        self.assertEqual(len(sedute), 3)                                        # solo le ultime 3 sedute

    def test_fino_alla_chiusura(self):
        B = barre_finte(sedute=7, titoli=2)
        chiuse, aperte, _ = A.rigioca(modello_che_compra(H), B, margine=0.001, sedute=2, costo=0.0)
        self.assertTrue(chiuse)
        for o in chiuse:
            if o["motivo"] == "chiusura":
                esce = ora_roma(o["t_uscita"])
                self.assertEqual((esce.hour, esce.minute), (17, 30))
                g = int(np.flatnonzero(B.T == datetime.datetime.strptime(o["t"], "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=datetime.timezone.utc).timestamp())[0])
                c = B.simboli.index(o["sym"])
                self.assertAlmostEqual(o["prezzo_uscita"], B.c[c, (g // A.BARRE) * A.BARRE + A.BARRE - 1], places=5)

    def test_nella_seduta_in_corso_restano_aperte(self):
        B = barre_finte(sedute=7, titoli=3, ultima=60)
        chiuse, aperte, _ = A.rigioca(modello_che_compra(H), B, margine=0.001, sedute=2, costo=0.001)
        self.assertLessEqual(len(aperte), 3)
        self.assertGreater(len(aperte), 0)
        oggi = datetime.datetime.fromtimestamp(B.T[B.ultima], ROMA).date()
        for o in aperte:
            self.assertNotIn("t_uscita", o)
            self.assertEqual(ora_roma(o["t"]).date(), oggi)
            self.assertEqual(ora_roma(o["scade"]).date(), oggi)                 # chiude al più tardi in chiusura
            self.assertLess(o["protezione"], o["prezzo"])
        self.assertEqual(len({o["sym"] for o in aperte}), len(aperte))

    def test_se_aspettare_vale_di_piu_non_compra(self):
        B = barre_finte(sedute=7, titoli=2)
        chiuse, aperte, vant = A.rigioca(modello_che_compra(2, valore=0.05), B, margine=0.001, sedute=2)
        self.assertEqual((chiuse, aperte), ([], []))                             # 0,05 % in più non batte il margine di 0,1 %
        self.assertTrue(all(abs(v - 0.0005) < 1e-6 for v in vant.values()))

    def test_robot_per_l_app(self):
        B = barre_finte(sedute=7, titoli=2, ultima=50)
        m = modello_che_compra(A.ORIZZONTI.index(30) + 1)
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "m.json")
            blocco = {"rete": m["rete"].a_dizionario(), "media": [0.0] * A.N_FEATURE, "dev": [1.0] * A.N_FEATURE,
                      "margine": None, "fuori": True, "iterazione": 3}
            with open(p, "w") as fh:
                json.dump({"modelli": {"0.001": blocco, "0.0005": blocco}}, fh)
            with mock.patch.object(A, "MODELLO", p), mock.patch.object(A, "carica", lambda **k: B):
                r = A.robot(log=lambda m: None)
        self.assertEqual(r["costo"], 0.001)                                     # il costo più alto
        self.assertEqual(r["margine"], A.MARGINE_ROBOT)
        self.assertTrue(r["modello"]["fuori"])
        self.assertGreater(len(r["operazioni"]), 0)
        self.assertEqual(set(r["prezzi"]), set(B.simboli))
        self.assertAlmostEqual(r["prezzi"]["T0.MI"], B.c[0, B.ultima], places=5)
        json.dumps(r)                                                            # va nell'app così com'è

    def test_per_app_senza_pesi(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "m.json")
            with open(p, "w") as fh:
                json.dump({"costi": {}, "modelli": {"0.001": {"fuori": True, "rete": {"W": [[1]]}, "media": [0], "dev": [1]}}}, fh)
            with mock.patch.object(A, "MODELLO", p):
                self.assertEqual(A.per_app()["modelli"]["0.001"], {"fuori": True})
            with mock.patch.object(A, "MODELLO", os.path.join(t, "manca.json")):
                self.assertIsNone(A.per_app())


def modello_probabile_azioni(azione, p_alta=0.7, p_bassa=0.3, soglia=0.6):
    net = rete.Rete([A.N_FEATURE, 4, H], 0)
    net.W = [np.zeros_like(w) for w in net.W]
    logit = lambda p: float(np.log(p / (1 - p)))
    net.b[-1] = np.full(H, logit(p_bassa), np.float32)
    net.b[-1][azione - 1] = logit(p_alta)
    return {"rete": net.a_dizionario(), "media": [0.0] * A.N_FEATURE, "dev": [1.0] * A.N_FEATURE, "tipo": "probabilita",
            "soglia": soglia, "quota": 0.01, "fuori": True, "iterazione": 2, "addestrato": "2030-01-15"}


class Archivio(unittest.TestCase):
    def test_tiene_le_barre_vecchie_e_aggiorna_quelle_nuove(self):
        with tempfile.TemporaryDirectory() as t:
            prima = [(100, 1.0, 1.1, 0.9, 1.05, 10.0), (400, 1.05, 1.2, 1.0, 1.1, 5.0)]
            self.assertEqual(A.archivia("X.MI", prima, cartella=t), prima)
            dopo = [(400, 1.05, 1.3, 1.0, 1.25, 9.0), (700, 1.25, 1.3, 1.2, 1.2, 3.0)]        # Yahoo non ha più la barra 100
            tutte = A.archivia("X.MI", dopo, cartella=t)
            self.assertEqual([r[0] for r in tutte], [100, 400, 700])
            self.assertEqual(tutte[1], (400, 1.05, 1.3, 1.0, 1.25, 9.0))       # la barra nuova vince (era ancora in corso)
            with open(os.path.join(t, "X.MI.npz"), "wb") as fh:                  # archivio rovinato: si riparte dalle barre nuove
                fh.write(b"rotto")
            self.assertEqual([r[0] for r in A.archivia("X.MI", dopo, cartella=t)], [400, 700])


class RegoleDaiLibri(unittest.TestCase):
    def test_ogni_regola_decide_solo_nel_suo_momento(self):
        D = A.DatiAzioni(barre_finte(sedute=8, titoli=3))
        R = A.regole(D)
        for nome in ("orb_in_play", "momento_intraday", "buy_on_gap", "vwap_ritorno", "stagione", "apertura_chiusura"):
            self.assertIn(nome, R)
            az = R[nome](D, 0, D.N)
            self.assertEqual(az.shape, (D.C, D.N))
        j = np.broadcast_to(D.G % A.BARRE, (D.C, D.N))
        self.assertTrue(np.all(j[R["momento_intraday"](D, 0, D.N) > 0] == 96))          # alle 17:00
        self.assertTrue(np.all(j[R["buy_on_gap"](D, 0, D.N) > 0] == A.PRIMA))           # alle 9:10
        orb = R["orb_in_play"](D, 0, D.N)
        self.assertTrue(np.all((j[orb > 0] >= A.BARRE_OR) & (j[orb > 0] <= 6)))
        self.assertTrue(np.all(orb[orb > 0] == 1 + A.ORIZZONTI.index(510)))              # fino alla chiusura


class RobotConProbabilita(unittest.TestCase):
    def robot(self, json_modelli, B):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "m.json")
            with open(p, "w") as fh:
                json.dump(json_modelli, fh)
            with mock.patch.object(A, "MODELLO", p), mock.patch.object(A, "carica", lambda **k: B):
                return A.robot(log=lambda m: None)

    def test_sceglie_dalla_soglia_imparata(self):
        B = barre_finte(sedute=7, titoli=2, ultima=50)
        j = A.ORIZZONTI.index(60) + 1
        q = modello_che_compra(2)
        q_json = {"rete": q["rete"].a_dizionario(), "media": [0.0] * A.N_FEATURE, "dev": [1.0] * A.N_FEATURE, "margine": None, "fuori": True}
        r = self.robot({"modelli": {"0.001": q_json}, "probabilita": {"0.001": modello_probabile_azioni(j)}}, B)
        self.assertEqual((r["tipo"], r["soglia"], r["quota"], r["margine"]), ("probabilita", 0.6, 0.01, None))
        self.assertEqual(r["modello"]["addestrato"], "2030-01-15")
        self.assertGreater(len(r["operazioni"]), 5)
        for o in r["operazioni"] + r["aperte"]:
            self.assertAlmostEqual(o["probabilita"], 0.7, places=4)
            self.assertLessEqual(o["minuti"], 60)
        r = self.robot({"modelli": {"0.001": q_json}, "probabilita": {"0.001": modello_probabile_azioni(j, soglia=0.8)}}, B)
        self.assertTrue(r["operazioni"])                                          # sotto la soglia prende il meglio di ogni ora
        self.assertTrue(all(abs(o["probabilita"] - 0.7) < 1e-4 for o in r["operazioni"]))

    def test_senza_probabilita_il_q_learning_con_il_margine(self):
        B = barre_finte(sedute=7, titoli=2, ultima=50)
        q = modello_che_compra(A.ORIZZONTI.index(30) + 1)
        r = self.robot({"modelli": {"0.001": {"rete": q["rete"].a_dizionario(), "media": [0.0] * A.N_FEATURE, "dev": [1.0] * A.N_FEATURE,
                                              "margine": None, "fuori": True}}}, B)
        self.assertEqual((r["tipo"], r["margine"], r["soglia"]), ("q", A.MARGINE_ROBOT, None))
        self.assertTrue(all("vantaggio" in o for o in r["operazioni"]))

    def test_per_app_toglie_i_pesi_anche_alla_probabilita(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "m.json")
            with open(p, "w") as fh:
                json.dump({"modelli": {}, "probabilita": {"0.001": modello_probabile_azioni(3)}}, fh)
            with mock.patch.object(A, "MODELLO", p):
                m = A.per_app()["probabilita"]["0.001"]
        self.assertNotIn("rete", m)
        self.assertNotIn("media", m)
        self.assertEqual(m["soglia"], 0.6)


class SoglieOgniOra(unittest.TestCase):
    def test_ogni_ora_della_seduta_ha_le_sue_occasioni(self):
        B = A.BARRE
        G = np.arange(2 * B)                                                    # due sedute intere
        ora = (G % B) * A.BARRA // 60
        prob = np.tile(np.where(ora == 0, 0.9, 0.5 + 0.001 * (G % B)), (5, 1))     # all'apertura molto più alte
        S = A.soglie_per_ora(G, prob, 0.8, quota=0.05)
        self.assertTrue(np.all(S <= 0.8))
        scelte = prob >= S[None, :]
        for s in range(2):
            for h in range(9):
                m = (G // B == s) & (ora == h)
                self.assertTrue(scelte[:, m].any(), (s, h))                     # ogni ora di ogni seduta compra qualcosa
        self.assertEqual(S[0], 0.8)                                             # dove la soglia imparata basta, resta quella


if __name__ == "__main__":
    unittest.main()
