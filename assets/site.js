(function () {
  'use strict';

  var knownPages = new Set([
    'index',
    'admin',
    'reserva-tu-lectura',
    'prediccion-astral',
    'lectura-de-carta-natal',
    'synastria',
    'oraciones',
    'tarot-terapeutico',
    'meditaciones',
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

  function spawnLightningBurst(x, y) {
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      return;
    }

    var burst = document.createElement('span');
    burst.className = 'lightning-burst';
    burst.style.setProperty('--x', x + 'px');
    burst.style.setProperty('--y', y + 'px');

    for (var i = 0; i < 10; i += 1) {
      var bolt = document.createElement('span');
      bolt.className = 'lightning-bolt';
      bolt.style.setProperty('--rot', (i * 36) + 'deg');
      bolt.style.animationDelay = (i % 2 === 0 ? 0 : 0.04) + 's';
      burst.appendChild(bolt);
    }

    document.body.appendChild(burst);
    window.setTimeout(function () {
      if (burst.parentNode) {
        burst.parentNode.removeChild(burst);
      }
    }, 650);
  }

  function initButtonLightning() {
    document.addEventListener('click', function (event) {
      var target = event.target;
      if (!target || !target.closest) {
        return;
      }

      var trigger = target.closest('.btn, button');
      if (!trigger) {
        return;
      }
      if (trigger.disabled || trigger.getAttribute('aria-disabled') === 'true') {
        return;
      }

      var rect = trigger.getBoundingClientRect();
      var x = event.clientX;
      var y = event.clientY;

      if (!x && !y) {
        x = rect.left + rect.width / 2;
        y = rect.top + rect.height / 2;
      }

      spawnLightningBurst(x, y);
    }, true);
  }

  function goToSitePath(pathWithOptionalHash) {
    var target = normalizeInternalHref(pathWithOptionalHash, location.protocol === 'file:');
    if (target) {
      window.location.href = target;
    }
  }

  window.goToSitePath = goToSitePath;
  document.addEventListener('DOMContentLoaded', function () {
    rewriteLocalLinks();
    initButtonLightning();
  });
})();
