// Finanza: la copia dell'app sul telefono. Prima la rete (così arriva sempre la versione nuova), se manca la copia.
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
