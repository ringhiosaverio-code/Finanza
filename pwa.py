#!/usr/bin/env python3
"""L'app installabile sul telefono (PWA) per il sito GitHub Pages: icone, manifest e service worker.

    python3 pwa.py                         # rifà la cartella pwa/ (icone disegnate qui, manifest, service worker)
    python3 pwa.py --installa site/index.html    # aggiunge alla pagina i collegamenti a manifest e icone (lo fa il workflow)

Con il service worker l'app si apre anche senza rete: mostra l'ultima copia salvata (e l'ultimo stato del robot letto),
e quando la rete c'è prende sempre la versione nuova. Si attiva solo sul sito GitHub, mai nel motore del cloud.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
CARTELLA = os.path.join(ROOT, "pwa")
COLORE = (36, 83, 201)                 # il blu dell'app (--accent)
SFONDO = "#f3f5f8"

MANIFEST = {
    "name": "Finanza", "short_name": "Finanza", "lang": "it", "start_url": "./", "scope": "./", "display": "standalone",
    "background_color": SFONDO, "theme_color": "#2453c9",
    "description": "Consigli, piano e robot con la rete neurale: azioni, ETF, obbligazioni e crypto.",
    "icons": [{"src": "icona-192.png", "sizes": "192x192", "type": "image/png"},
              {"src": "icona-512.png", "sizes": "512x512", "type": "image/png"},
              {"src": "icona-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}],
}

SERVICE_WORKER = r"""// Finanza: la copia dell'app sul telefono. Prima la rete (così arriva sempre la versione nuova), se manca la copia.
const CACHE = 'finanza-v1';
const BASE = ['./', './index.html', './manifest.webmanifest', './icona-192.png', './icona-512.png', './icona-180.png'];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(BASE)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(k => Promise.all(k.filter(x => x !== CACHE).map(x => caches.delete(x)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const r = e.request;
  if (r.method !== 'GET') return;
  const url = new URL(r.url);
  const vivo = r.mode === 'navigate' || url.hostname === 'raw.githubusercontent.com' || url.hostname === 'api.github.com';
  if (vivo) {                                       // la pagina e lo stato del robot: prima la rete, poi la copia
    e.respondWith(fetch(r).then(res => {
      if (res && res.ok) { const copia = res.clone(); caches.open(CACHE).then(c => c.put(url.origin + url.pathname, copia)); }
      return res;
    }).catch(() => caches.match(url.origin + url.pathname).then(m => m || (r.mode === 'navigate' ? caches.match('./index.html') : undefined))
      .then(m => m || new Response('', {status: 504}))));
    return;
  }
  if (url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com') {   // i caratteri: la copia, se c'è
    e.respondWith(caches.match(r).then(m => m || fetch(r).then(res => {
      if (res && (res.ok || res.type === 'opaque')) { const copia = res.clone(); caches.open(CACHE).then(c => c.put(r, copia)); }
      return res;
    })));
    return;
  }
  if (url.origin === location.origin) e.respondWith(caches.match(r).then(m => m || fetch(r)));
});
"""

# la larghezza del telefono (su claude.ai la mette la cornice dell'artefatto; sul sito GitHub serve qui, se no il telefono
# mostra la pagina larga 980 pixel e rimpicciolita), il manifest e le icone
TAG = ('<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
       '<link rel="manifest" href="manifest.webmanifest"><meta name="theme-color" content="#2453c9">'
       '<link rel="apple-touch-icon" href="icona-180.png"><meta name="apple-mobile-web-app-capable" content="yes">'
       '<meta name="apple-mobile-web-app-title" content="Finanza">')


def icona(lato, percorso):
    """L'icona: il blu dell'app con una linea bianca che sale, come un grafico."""
    from PIL import Image, ImageDraw
    s = 4                                                     # disegnata più grande e poi ridotta: bordi morbidi
    im = Image.new("RGB", (lato * s, lato * s), COLORE)
    d = ImageDraw.Draw(im)
    L = lato * s
    punti = [(0.18, 0.70), (0.38, 0.52), (0.52, 0.62), (0.80, 0.30)]
    xy = [(x * L, y * L) for x, y in punti]
    d.line(xy, fill=(255, 255, 255), width=int(0.075 * L), joint="curve")
    r = 0.045 * L
    for x, y in (xy[0], xy[-1]):
        d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255))
    im.resize((lato, lato), Image.LANCZOS).save(percorso, optimize=True)


def genera():
    os.makedirs(CARTELLA, exist_ok=True)
    for lato in (180, 192, 512):
        icona(lato, os.path.join(CARTELLA, "icona-%d.png" % lato))
    with open(os.path.join(CARTELLA, "manifest.webmanifest"), "w", encoding="utf-8") as fh:
        json.dump(MANIFEST, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(CARTELLA, "sw.js"), "w", encoding="utf-8") as fh:
        fh.write(SERVICE_WORKER)
    print("[pwa] scritta la cartella pwa/")


def installa(pagina):
    """Aggiunge alla pagina i collegamenti a manifest e icone (una volta sola)."""
    with open(pagina, encoding="utf-8") as fh:
        html = fh.read()
    if 'rel="manifest"' not in html:
        for dopo in ("<head>", '<meta charset="utf-8">'):              # la pagina dell'app comincia con la meta charset
            if dopo in html:
                html = html.replace(dopo, dopo + TAG, 1)
                break
        else:
            html = TAG + html
        with open(pagina, "w", encoding="utf-8") as fh:
            fh.write(html)
    print("[pwa] collegamenti aggiunti a %s" % pagina)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--installa"]:
        for p in argv[1:]:
            installa(p)
        return 0
    genera()
    return 0


if __name__ == "__main__":
    sys.exit(main())
