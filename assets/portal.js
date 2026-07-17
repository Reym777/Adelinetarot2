(function () {
  'use strict';

  function $(id) { return document.getElementById(id); }
  function esc(v) {
    return String(v == null ? '' : v)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function resolveApiBase() {
    var meta = document.querySelector('meta[name="adeline-api-base"]');
    var configured = meta && meta.content ? meta.content.trim() : '';
    if (configured) return configured.replace(/\/+$/, '');
    if (location.protocol === 'file:') return 'http://127.0.0.1:8000';
    return '';
  }

  var API_BASE = resolveApiBase();
  var TOKEN_KEY = 'adeline_admin_token';
  var token = sessionStorage.getItem(TOKEN_KEY) || '';
  var cachedEmails = [];
  var cachedUpcoming = [];
  var cachedPayments = [];
  var currentRange = 'all';
  var currentSearch = '';
  var refreshTimer = null;

  function setMsg(id, text, isError) {
    var el = $(id);
    if (!el) return;
    el.textContent = text || '';
    el.style.color = isError ? '#fca5a5' : '#c4b5fd';
  }

  function setKpi(id, value) {
    var el = $(id);
    if (!el) return;
    el.textContent = String(value == null ? 0 : value);
  }

  function apiAdmin(path, method, body) {
    return fetch(API_BASE + path, {
      method: method || 'GET',
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'X-Admin-Token': token,
      },
      body: body ? JSON.stringify(body) : undefined,
    }).then(function (res) {
      if (res.status === 401) throw new Error('401');
      return res.json().then(function (data) {
        if (!res.ok) throw new Error((data && data.detail) || ('Error ' + res.status));
        return data;
      });
    });
  }

  function showDash(ok) {
    $('dashView').classList.toggle('hidden', !ok);
    $('loginView').classList.toggle('hidden', ok);
  }

  function moneyMapText(map) {
    var keys = Object.keys(map || {});
    if (!keys.length) return '0';
    return keys.map(function (k) { return k + ': ' + map[k]; }).join(' · ');
  }

  function renderRows(id, rows, cols) {
    var body = $(id);
    if (!body) return;
    if (!rows || !rows.length) {
      body.innerHTML = '<tr><td colspan="' + cols + '" class="muted">Sin datos.</td></tr>';
      return;
    }
    body.innerHTML = rows.join('');
  }

  function parseIsoDate(value) {
    if (!value) return null;
    var d = new Date(value);
    return isNaN(d.getTime()) ? null : d;
  }

  function isInRange(isoDateOrDate) {
    if (currentRange === 'all') return true;
    var d = parseIsoDate(isoDateOrDate);
    if (!d) return false;
    var now = new Date();
    var start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    if (currentRange === 'today') {
      var end = new Date(start);
      end.setDate(end.getDate() + 1);
      return d >= start && d < end;
    }
    if (currentRange === '7d') {
      var d7 = new Date(start);
      d7.setDate(d7.getDate() - 7);
      return d >= d7;
    }
    if (currentRange === '30d') {
      var d30 = new Date(start);
      d30.setDate(d30.getDate() - 30);
      return d >= d30;
    }
    return true;
  }

  function matchesSearch(row) {
    if (!currentSearch) return true;
    var haystack = [row.reference, row.name, row.email, row.method, row.status, row.date, row.time]
      .map(function (x) { return String(x || '').toLowerCase(); })
      .join(' ');
    return haystack.indexOf(currentSearch) !== -1;
  }

  function renderTablesFromCache() {
    var upcomingFiltered = cachedUpcoming.filter(function (r) {
      return isInRange(r.date) && matchesSearch(r);
    });
    var paymentsFiltered = cachedPayments.filter(function (r) {
      return isInRange(r.paid_at || r.claimed_at) && matchesSearch(r);
    });

    setKpi('kpiUpcoming', upcomingFiltered.length);
    setKpi('kpiPayments', paymentsFiltered.length);

    renderRows('upcomingBody', upcomingFiltered.map(function (r) {
      var mail = esc(r.email || '');
      return '<tr>' +
        '<td>' + esc(r.reference) + '</td>' +
        '<td>' + esc(r.name) + '</td>' +
        '<td>' + esc(r.date || '—') + '</td>' +
        '<td>' + esc(r.time || '—') + '</td>' +
        '<td>' + esc(r.status) + '</td>' +
        '<td><button data-copy="' + mail + '">Copier mail</button></td>' +
        '</tr>';
    }), 6);

    renderRows('paymentsBody', paymentsFiltered.map(function (r) {
      var mail = esc(r.email || '');
      return '<tr>' +
        '<td>' + esc(r.reference) + '</td>' +
        '<td>' + esc(r.name) + '</td>' +
        '<td>' + esc(r.amount) + ' ' + esc(r.currency) + '</td>' +
        '<td>' + esc(r.method || '—') + '</td>' +
        '<td>' + esc(r.paid_at || r.claimed_at || '—') + '</td>' +
        '<td><button data-copy="' + mail + '">Copier mail</button></td>' +
        '</tr>';
    }), 6);

    Array.prototype.forEach.call(document.querySelectorAll('button[data-copy]'), function (btn) {
      btn.addEventListener('click', function () {
        var v = btn.getAttribute('data-copy') || '';
        if (!v) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(v).then(function () {
            setMsg('dashMsg', 'Email copié: ' + v);
          }).catch(function () {
            setMsg('dashMsg', 'Copie impossible.', true);
          });
        }
      });
    });
  }

  function loadDashboard() {
    apiAdmin('/api/admin/dashboard').then(function (d) {
      cachedUpcoming = d.upcoming_citas || [];
      cachedPayments = d.recent_payments || [];

      $('monthTotals').textContent = moneyMapText((d.totals || {}).month || {});
      $('yearTotals').textContent = moneyMapText((d.totals || {}).year || {});
      $('visitsYesterday').textContent = String(d.visits_yesterday || 0);
      renderTablesFromCache();

      cachedEmails = d.recent_client_emails || [];
      $('emailsList').innerHTML = cachedEmails.length
        ? cachedEmails.map(function (m) { return '<span class="chip">' + esc(m) + '</span>'; }).join('')
        : '<span class="muted">Sin correos recientes.</span>';

      setMsg('dashMsg', 'Mis à jour réussie.');
    }).catch(function (err) {
      if (err.message === '401') {
        logout();
        return;
      }
      setMsg('dashMsg', err.message || 'Erreur chargement dashboard', true);
    });
  }


  function copyEmails() {
    if (!cachedEmails.length) {
      setMsg('dashMsg', 'Aucun email à copier.', true);
      return;
    }
    var value = cachedEmails.join('; ');
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(value).then(function () {
        setMsg('dashMsg', 'Emails copiés dans le presse-papiers.');
      }).catch(function () {
        setMsg('dashMsg', 'Copie impossible.', true);
      });
      return;
    }
    setMsg('dashMsg', 'Copie non supportée sur ce navigateur.', true);
  }

  function login() {
    token = ($('adminToken').value || '').trim();
    if (!token) {
      setMsg('loginMsg', 'Introduce la clave admin.', true);
      return;
    }
    apiAdmin('/api/admin/me').then(function () {
      sessionStorage.setItem(TOKEN_KEY, token);
      showDash(true);
      loadDashboard();
      if (!refreshTimer) {
        refreshTimer = setInterval(function () {
          loadDashboard();
        }, 60000);
      }
    }).catch(function () {
      token = '';
      sessionStorage.removeItem(TOKEN_KEY);
      setMsg('loginMsg', 'Token invalide.', true);
    });
  }

  function logout() {
    token = '';
    sessionStorage.removeItem(TOKEN_KEY);
    if (refreshTimer) {
      clearInterval(refreshTimer);
      refreshTimer = null;
    }
    showDash(false);
  }

  document.addEventListener('DOMContentLoaded', function () {
    $('loginBtn').addEventListener('click', login);
    $('refreshDash').addEventListener('click', function () { loadDashboard(); });
    $('logoutBtn').addEventListener('click', logout);
    $('copyEmails').addEventListener('click', copyEmails);
    $('rangeFilter').addEventListener('change', function () {
      currentRange = $('rangeFilter').value || 'all';
      renderTablesFromCache();
    });
    $('quickSearch').addEventListener('input', function () {
      currentSearch = String($('quickSearch').value || '').trim().toLowerCase();
      renderTablesFromCache();
    });

    if (token) {
      showDash(true);
      loadDashboard();
      refreshTimer = setInterval(function () {
        loadDashboard();
      }, 60000);
    } else {
      showDash(false);
    }
  });
})();
