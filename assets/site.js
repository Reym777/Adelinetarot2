(function () {
  'use strict';

  var knownPages = new Set([
    'index',
    'admin',
    'confirmation',
    'tarot-terapeutico',
    'prediccion-astral',
    'lectura-de-carta-natal',
    'sinastria',
    'oraciones',
    'meditaciones',
    'conexion-inscripcion',
    'articulos',
    'articles',
    'contact',
  ]);

  function splitHref(href) {
    var hashIndex = href.indexOf('#');
    if (hashIndex === -1) {
      return { path: href, hash: '' };
    }
    return { path: href.slice(0, hashIndex), hash: href.slice(hashIndex) };
  }

  function isHomePage() {
    var path = String((location && location.pathname) || '').toLowerCase();
    return path === '/' || path.endsWith('/index') || path.endsWith('/index.html');
  }

  function isLowEndDevice() {
    var cores = Number(navigator && navigator.hardwareConcurrency);
    var lowCores = Number.isFinite(cores) && cores > 0 && cores <= 4;
    var mem = Number(navigator && navigator.deviceMemory);
    var lowMem = Number.isFinite(mem) && mem > 0 && mem <= 4;
    return lowCores || lowMem;
  }

  function isSlowConnection() {
    var connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    if (!connection) {
      return false;
    }
    if (connection.saveData) {
      return true;
    }
    var type = String(connection.effectiveType || '').toLowerCase();
    return type === 'slow-2g' || type === '2g';
  }

  function appendHeadLink(rel, href, asValue) {
    if (!href || !document.head) {
      return;
    }
    var selector = 'link[rel="' + rel + '"][href="' + href + '"]';
    if (document.head.querySelector(selector)) {
      return;
    }
    var link = document.createElement('link');
    link.rel = rel;
    link.href = href;
    if (asValue) {
      link.as = asValue;
    }
    document.head.appendChild(link);
  }

  function appendNetworkHint(rel, href, useCrossOrigin) {
    if (!href || !document.head) {
      return;
    }
    var selector = 'link[rel="' + rel + '"][href="' + href + '"]';
    if (document.head.querySelector(selector)) {
      return;
    }

    var link = document.createElement('link');
    link.rel = rel;
    link.href = href;

    if (useCrossOrigin) {
      link.crossOrigin = 'anonymous';
    }

    document.head.appendChild(link);
  }

  function collectExternalOrigins() {
    var origins = new Set();

    var hasPayPal = !!document.querySelector(
      'script[src*="paypal.com"], iframe[src*="paypal.com"], [data-paypal-button]'
    );
    if (hasPayPal) {
      origins.add('https://www.paypal.com');
      origins.add('https://www.paypalobjects.com');
    }

    var hasStripe = !!document.querySelector(
      'script[src*="js.stripe.com"], iframe[src*="stripe.com"], [data-stripe-button]'
    );
    if (hasStripe) {
      origins.add('https://js.stripe.com');
      origins.add('https://api.stripe.com');
    }

    var hasJsDelivr = !!document.querySelector('script[src*="cdn.jsdelivr.net"]');
    if (hasJsDelivr) {
      origins.add('https://cdn.jsdelivr.net');
    }

    return origins;
  }

  function primeNetworkHints() {
    var origins = collectExternalOrigins();
    if (!origins.size) {
      return;
    }

    var priority = [
      'https://cdn.jsdelivr.net',
      'https://www.paypal.com',
      'https://www.paypalobjects.com',
      'https://js.stripe.com',
      'https://api.stripe.com'
    ];

    var ordered = [];
    priority.forEach(function (origin) {
      if (origins.has(origin)) {
        ordered.push(origin);
        origins.delete(origin);
      }
    });

    origins.forEach(function (origin) {
      ordered.push(origin);
    });

    var maxPreconnect = isSlowConnection() ? 1 : 3;
    ordered.forEach(function (origin, idx) {
      if (idx < maxPreconnect) {
        appendNetworkHint('preconnect', origin, false);
      }
      appendNetworkHint('dns-prefetch', origin, false);
    });
  }

  function preloadCriticalImages() {
    var critical = [
      'assets/images/bandeau10_upscaled_1280.webp'
    ];

    critical.forEach(function (src) {
      appendHeadLink('preload', src, 'image');
    });
  }

  function warmupSecondaryImages() {
    if (isSlowConnection() || isLowEndDevice() || !isHomePage()) {
      return;
    }

    var secondary = [
      'assets/images/carte amour.webp',
      'assets/images/carte astrologue.webp',
      'assets/images/carte histoire.webp',
      'assets/images/carte histoire2.webp',
      'assets/images/carte oracion.webp',
      'assets/images/carte tirage.webp'
    ];

    var run = function () {
      secondary.forEach(function (src) {
        var img = new Image();
        img.decoding = 'async';
        img.src = src;
      });
    };

    if (window.requestIdleCallback) {
      window.requestIdleCallback(run, { timeout: 1800 });
    } else {
      window.setTimeout(run, 600);
    }
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

    var host = String((location && location.hostname) || '').toLowerCase();
    var forceHtml = forLocalFile || host.endsWith('.github.io');
    return forceHtml ? path + '.html' + parts.hash : path + parts.hash;
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

  function initLanguageLinks() {
    var links = document.querySelectorAll('.side-menu-lang-top a[aria-label]');
    if (!links.length) {
      return;
    }

    var onLocalFile = location.protocol === 'file:';
    var path = String(location.pathname || '').toLowerCase();
    var inLangFolder = /\/(en|es|fr)\//.test(path);

    links.forEach(function (link) {
      var label = String(link.getAttribute('aria-label') || '').toLowerCase();
      var lang = 'es';
      if (label.indexOf('english') !== -1) {
        lang = 'en';
      } else if (label.indexOf('fran') !== -1) {
        lang = 'fr';
      }

      if (onLocalFile) {
        link.setAttribute('href', inLangFolder ? ('../' + lang + '/index.html') : (lang + '/index.html'));
      }

      link.style.display = 'inline-flex';
      link.style.alignItems = 'center';
      link.style.justifyContent = 'center';
      link.style.width = '34px';
      link.style.height = '34px';
      link.style.borderRadius = '999px';
      link.style.border = '1px solid rgba(232,198,107,.55)';
      link.style.background = 'rgba(12,10,29,.72)';
      link.style.fontWeight = '700';
      link.style.letterSpacing = '.03em';
      link.style.textDecoration = 'none';
      link.style.color = 'var(--gold)';
      link.style.fontSize = '.78rem';
      link.style.lineHeight = '1';
      link.style.padding = '0';
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

    var bolts = window.innerWidth < 640 ? 6 : 10;
    for (var i = 0; i < bolts; i += 1) {
      var bolt = document.createElement('span');
      bolt.className = 'lightning-bolt';
      bolt.style.setProperty('--rot', (i * (360 / bolts)) + 'deg');
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
    if (!isHomePage() || isLowEndDevice() || !isEnhancedFxEnabled()) {
      return;
    }

    var lastBurstTs = 0;
    document.addEventListener('click', function (event) {
      var now = Date.now();
      if (now - lastBurstTs < 120) {
        return;
      }

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

      if (trigger.dataset && trigger.dataset.noFx === 'true') {
        return;
      }

      var rect = trigger.getBoundingClientRect();
      var x = event.clientX;
      var y = event.clientY;

      if (!x && !y) {
        x = rect.left + rect.width / 2;
        y = rect.top + rect.height / 2;
      }

      lastBurstTs = now;
      spawnLightningBurst(x, y);
    }, true);
  }

  function injectFallingCards() {
    if (!isHomePage() || isLowEndDevice() || !isEnhancedFxEnabled()) {
      return;
    }

    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      return;
    }
    var host = document.querySelector('.falling-cards');
    if (!host) {
      host = document.createElement('div');
      host.className = 'falling-cards';
      host.setAttribute('aria-hidden', 'true');

      var ambient = document.querySelector('.ambient-decor');
      if (ambient && ambient.parentNode) {
        ambient.parentNode.insertBefore(host, ambient.nextSibling);
      } else {
        document.body.insertBefore(host, document.body.firstChild);
      }
    }

    host.innerHTML = '';

    var defs = [
      'card-amour',
      'card-astrologue',
      'card-histoire',
      'card-histoire2',
      'card-oracion',
      'card-tirage'
    ];
    var lowEnd = isLowEndDevice();
    var count = window.innerWidth < 820 ? (lowEnd ? 3 : 5) : (lowEnd ? 5 : 8);

    for (var i = 0; i < count; i += 1) {
      var cls = defs[Math.floor(Math.random() * defs.length)];
      var x = (4 + Math.random() * 88).toFixed(2) + 'vw';
      var delay = (Math.random() * 12).toFixed(2) + 's';
      var duration = (12.5 + Math.random() * 6.5).toFixed(2) + 's';
      var driftA = (-3.8 + Math.random() * 7.6).toFixed(2) + 'vw';
      var driftB = (-4.8 + Math.random() * 9.6).toFixed(2) + 'vw';
      var driftC = (-3.2 + Math.random() * 6.4).toFixed(2) + 'vw';
      var driftBNeg = (-parseFloat(driftB)).toFixed(2) + 'vw';
      var rotA = (-14 + Math.random() * 12).toFixed(2) + 'deg';
      var rotB = (-7 + Math.random() * 14).toFixed(2) + 'deg';
      var rotC = (-11 + Math.random() * 22).toFixed(2) + 'deg';
      var rotBNeg = (-parseFloat(rotB)).toFixed(2) + 'deg';
      var scaleA = (0.9 + Math.random() * 0.08).toFixed(3);
      var scaleB = (0.98 + Math.random() * 0.08).toFixed(3);
      var scaleC = (0.99 + Math.random() * 0.07).toFixed(3);
      var maxOpacity = (0.42 + Math.random() * 0.18).toFixed(2);

      var item = document.createElement('span');
      item.className = 'falling-card ' + cls;
      item.style.setProperty('--x', x);
      item.style.setProperty('--delay', delay);
      item.style.setProperty('--duration', duration);
      item.style.setProperty('--drift-a', driftA);
      item.style.setProperty('--drift-b', driftB);
      item.style.setProperty('--drift-b-neg', driftBNeg);
      item.style.setProperty('--drift-c', driftC);
      item.style.setProperty('--rot-a', rotA);
      item.style.setProperty('--rot-b', rotB);
      item.style.setProperty('--rot-b-neg', rotBNeg);
      item.style.setProperty('--rot-c', rotC);
      item.style.setProperty('--scale-a', scaleA);
      item.style.setProperty('--scale-b', scaleB);
      item.style.setProperty('--scale-c', scaleC);
      item.style.setProperty('--card-opacity', maxOpacity);
      host.appendChild(item);
    }
  }

  function goToSitePath(pathWithOptionalHash) {
    var target = normalizeInternalHref(pathWithOptionalHash, location.protocol === 'file:');
    if (target) {
      window.location.href = target;
    }
  }

  function initHeaderHomeRedirect() {
    var header = document.querySelector('.site-header');
    if (!header) {
      return;
    }

    header.addEventListener('click', function (event) {
      if (!event || !event.target || !event.target.closest) {
        return;
      }

      var interactive = event.target.closest('a, button, input, select, textarea, label');
      if (interactive) {
        return;
      }

      goToSitePath('index');
    });
  }

  function setMenuInteractivity(menu, enabled) {
    var interactive = menu.querySelectorAll('a, button, input, select, textarea, [tabindex]');
    interactive.forEach(function (node) {
      if (enabled) {
        if (node.hasAttribute('data-prev-tabindex')) {
          var prev = node.getAttribute('data-prev-tabindex');
          if (prev === '') {
            node.removeAttribute('tabindex');
          } else {
            node.setAttribute('tabindex', prev);
          }
          node.removeAttribute('data-prev-tabindex');
        } else if (node.getAttribute('tabindex') === '-1') {
          node.removeAttribute('tabindex');
        }
      } else {
        if (!node.hasAttribute('data-prev-tabindex')) {
          node.setAttribute('data-prev-tabindex', node.getAttribute('tabindex') || '');
        }
        node.setAttribute('tabindex', '-1');
      }
    });
  }

  function toggleMenu(open) {
    var menu = document.getElementById('sideMenu');
    var backdrop = document.getElementById('menuBackdrop');
    if (!menu || !backdrop) {
      return;
    }
    var shouldOpen = !!open;
    menu.classList.toggle('open', shouldOpen);
    menu.setAttribute('aria-hidden', shouldOpen ? 'false' : 'true');
    menu.inert = !shouldOpen;
    menu.style.visibility = shouldOpen ? 'visible' : 'hidden';
    menu.style.pointerEvents = shouldOpen ? 'auto' : 'none';
    setMenuInteractivity(menu, shouldOpen);
    backdrop.classList.toggle('hidden', !shouldOpen);
    backdrop.style.display = shouldOpen ? 'block' : 'none';
    backdrop.style.pointerEvents = shouldOpen ? 'auto' : 'none';

    if (shouldOpen) {
      var firstFocusable = menu.querySelector('button, a, input, select, textarea');
      if (firstFocusable && typeof firstFocusable.focus === 'function') {
        firstFocusable.focus();
      }
    }
  }

  function initMenuControls() {
    var openButtons = document.querySelectorAll('.menu-toggle');
    openButtons.forEach(function (button) {
      button.addEventListener('click', function (event) {
        if (event) {
          event.preventDefault();
        }
        toggleMenu(true);
      });
    });

    var closeButtons = document.querySelectorAll('.menu-close');
    closeButtons.forEach(function (button) {
      button.addEventListener('click', function (event) {
        if (event) {
          event.preventDefault();
        }
        toggleMenu(false);
      });
    });

    var backdrop = document.getElementById('menuBackdrop');
    if (backdrop) {
      backdrop.addEventListener('click', function (event) {
        if (event) {
          event.preventDefault();
        }
        toggleMenu(false);
      });
    }
  }

  function initSideMenuLinks() {
    var links = document.querySelectorAll('.side-menu-links a[href]');
    if (!links.length) {
      return;
    }

    links.forEach(function (link) {
      link.addEventListener('click', function (event) {
        if (!event) {
          return;
        }
        event.stopPropagation();
        if (event.defaultPrevented || event.button !== 0) {
          return;
        }
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
          return;
        }

        var rawHref = link.getAttribute('href') || '';
        if (!rawHref || rawHref[0] === '#') {
          toggleMenu(false);
          return;
        }
        if (/^(mailto:|tel:|javascript:)/i.test(rawHref)) {
          return;
        }

        event.preventDefault();
        event.stopPropagation();
        toggleMenu(false);

        var target = normalizeInternalHref(rawHref, location.protocol === 'file:');
        if (!target) {
          return;
        }

        // Resolve relative links consistently from any page depth/language folder.
        var resolved = new URL(target, location.href).toString();
        window.location.assign(resolved);
      });
    });
  }

  function redirectToConfirmation(kind, status, extraParams) {
    var params = new URLSearchParams();
    params.set('kind', kind || 'generic');
    params.set('status', status || 'success');
    if (extraParams) {
      Object.keys(extraParams).forEach(function (key) {
        var val = extraParams[key];
        if (val != null && String(val).trim() !== '') {
          params.set(key, String(val));
        }
      });
    }
    goToSitePath('confirmation?' + params.toString());
  }

  function handleStripeReturnRedirect() {
    var params = new URLSearchParams(location.search || '');
    var paid = (params.get('paid') || '').toLowerCase();
    var canceled = (params.get('canceled') || '').toLowerCase();

    if (paid === 'stripe') {
      redirectToConfirmation('payment', 'success', {
        source: 'stripe',
        session_id: params.get('session_id') || '',
        service: params.get('service') || ''
      });
      return true;
    }

    if (canceled === 'stripe') {
      redirectToConfirmation('payment', 'cancel', { source: 'stripe' });
      return true;
    }

    return false;
  }

  function optimizeImages() {
    var images = document.querySelectorAll('img');
    images.forEach(function (img, index) {
      if (!img.hasAttribute('decoding')) {
        img.setAttribute('decoding', 'async');
      }

      if (!img.hasAttribute('loading')) {
        var isHero = index < 2 || img.closest('.site-header') || img.classList.contains('brand-banner-img');
        img.setAttribute('loading', isHero ? 'eager' : 'lazy');
      }

      if (!img.hasAttribute('fetchpriority')) {
        var isCritical = index < 2 || img.closest('.site-header') || img.classList.contains('brand-banner-img');
        img.setAttribute('fetchpriority', isCritical ? 'high' : 'low');
      }
    });
  }

  function isEnhancedFxEnabled() {
    var body = document.body;
    return !!(body && body.dataset && body.dataset.enhancedFx === 'on');
  }

  window.goToSitePath = goToSitePath;
  window.toggleMenu = toggleMenu;
  preloadCriticalImages();
  primeNetworkHints();

  window.addEventListener('load', function () {
    warmupSecondaryImages();
  }, { once: true });

  document.addEventListener('DOMContentLoaded', function () {
    if (handleStripeReturnRedirect()) {
      return;
    }
    rewriteLocalLinks();
    initLanguageLinks();
    initHeaderHomeRedirect();
    initMenuControls();
    initSideMenuLinks();
    optimizeImages();
    toggleMenu(false);
    injectFallingCards();
    initButtonLightning();
  });
})();

