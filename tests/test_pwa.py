"""Test offline di pwa.py: manifest con le icone che esistono, service worker che non tocca le richieste che non
sono GET, collegamenti aggiunti alla pagina una volta sola e dopo la meta charset. Niente rete.

    python3 -m unittest discover -s tests
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pwa  # noqa: E402


class Manifest(unittest.TestCase):
    def test_icone_presenti_nella_cartella(self):
        with open(os.path.join(pwa.CARTELLA, "manifest.webmanifest"), encoding="utf-8") as fh:
            m = json.load(fh)
        self.assertEqual(m["display"], "standalone")
        self.assertEqual(m["lang"], "it")
        lati = set()
        for i in m["icons"]:
            self.assertTrue(os.path.exists(os.path.join(pwa.CARTELLA, i["src"])), i["src"])
            lati.add(i["sizes"])
        self.assertTrue({"192x192", "512x512"} <= lati)                 # le due misure che Chrome chiede per installare
        self.assertTrue(any(i.get("purpose") == "maskable" for i in m["icons"]))

    def test_service_worker_uguale_al_codice(self):
        with open(os.path.join(pwa.CARTELLA, "sw.js"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), pwa.SERVICE_WORKER)              # la cartella pwa/ è aggiornata (python3 pwa.py)
        self.assertIn("r.method !== 'GET'", pwa.SERVICE_WORKER)
        for f in ("./index.html", "./manifest.webmanifest", "./icona-192.png"):
            self.assertIn(f, pwa.SERVICE_WORKER)


class Installa(unittest.TestCase):
    def test_dopo_la_charset_e_una_volta_sola(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "index.html")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write('<meta charset="utf-8">\n<title>Finanza</title>\n<p>ciao</p>')
            pwa.installa(p)
            pwa.installa(p)
            with open(p, encoding="utf-8") as fh:
                html = fh.read()
        self.assertTrue(html.startswith('<meta charset="utf-8">' + pwa.TAG))   # la charset resta la prima cosa
        self.assertEqual(html.count('rel="manifest"'), 1)
        self.assertEqual(html.count('name="viewport"'), 1)

    def test_con_head(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "index.html")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("<!doctype html><html><head><title>x</title></head><body></body></html>")
            pwa.installa(p)
            with open(p, encoding="utf-8") as fh:
                html = fh.read()
        self.assertIn("<head>" + pwa.TAG + "<title>", html)


if __name__ == "__main__":
    unittest.main()
