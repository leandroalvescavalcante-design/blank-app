/* Service worker: o app abre sem rede (arquivos em cache); a API nunca vem do cache. */
const VERSAO = "coleta-v2";
const ARQUIVOS = ["./", "index.html", "app.js", "estilo.css", "manifest.webmanifest", "icone-192.png", "icone-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSAO).then((c) => c.addAll(ARQUIVOS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== VERSAO).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  // rede primeiro (pega versão nova quando há Wi-Fi), cache se offline
  // limite de 4 s: em rede sem rota até o computador, abre do cache em vez de ficar carregando
  const rede = Promise.race([fetch(e.request), new Promise((_, nao) => setTimeout(() => nao(new Error("tempo")), 4000))]);
  e.respondWith(
    rede.then((r) => {
      if (r.ok) { const copia = r.clone(); caches.open(VERSAO).then((c) => c.put(e.request, copia)); }
      return r;
    }).catch(() => caches.match(e.request, { ignoreSearch: true })
      .then((r) => r || (e.request.mode === "navigate" ? caches.match("index.html") : Response.error())))
  );
});
