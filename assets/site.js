(function () {
  'use strict';

  var knownPages = new Set([
    'index',
    'admin',
    'reserva-tu-lectura',
    'prediccion-astral',
    'lectura-de-carta-natal',
    'oraciones',
  ]);

  function splitHref(href) {
    var hashIndex = href.indexOf('#');
    if (hashIndex === -1) {
      return { path: href, hash: '' };
    }
    return { path: href.slice(0, hashIndex), hash: href.slice(hashIndex) };
  }

  function normalizeInternalHref(href, forLocalFile) {
    if (!href || href[0] === '#' || /^(https?:|mailto:|tel:|javascript:)/i.test(href)) {
      return href;
    }

    var parts = splitHref(href);
    var path = parts.path.replace(/^\.\//, '').replace(/^\//, '');

    if (!path) {
      return href;
    }

    if (path.endsWith('.html')) {
      path = path.slice(0, -5);
    }

    if (!knownPages.has(path)) {
      return href;
    }

    return forLocalFile ? path + '.html' + parts.hash : path + parts.hash;
  }

  function rewriteLocalLinks() {
    if (location.protocol !== 'file:') {
      return;
    }

    document.querySelectorAll('a[href]').forEach(function (link) {
      var href = link.getAttribute('href');
      var normalized = normalizeInternalHref(href, true);
      if (normalized && normalized !== href) {
        link.setAttribute('href', normalized);
      }
    });
  }

  function goToSitePath(pathWithOptionalHash) {
    var target = normalizeInternalHref(pathWithOptionalHash, location.protocol === 'file:');
    if (target) {
      window.location.href = target;
    }
  }

  window.goToSitePath = goToSitePath;
  document.addEventListener('DOMContentLoaded', rewriteLocalLinks);
})();
