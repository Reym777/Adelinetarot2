/* Ping /api/health en arriere-plan des l'arrivee du visiteur pour reveiller le backend Render avant tout clic. */
(function () {
  "use strict";
  try {
    var meta = document.querySelector('meta[name="adeline-api-base"]');
    var base = (meta && meta.content ? meta.content.trim() : "").replace(/\/+$/, "") || "https://adelinetarot2.onrender.com";
    fetch(base + "/api/health", { mode: "no-cors", cache: "no-store", keepalive: true }).catch(function () {});
  } catch (e) {}
})();
