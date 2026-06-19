/* AdelineTarot — lógica del cliente (reserva + pago PayPal + enlace de videollamada) */
(function () {
  "use strict";

  // El backend (FastAPI) no puede ejecutarse en GitHub Pages (hosting estatico).
  // Resolucion: <meta name="adeline-api-base"> > file:// local > mismo origen.
  function resolveApiBase() {
    var meta = document.querySelector('meta[name="adeline-api-base"]');
    var configured = meta && meta.content ? meta.content.trim() : "";
    if (configured) { return configured.replace(/\/+$/, ""); }
    if (location.protocol === "file:") { return "http://127.0.0.1:8000"; }
    return "";
  }
  var API_BASE = resolveApiBase();

  // Aviso para el desarrollador: GitHub Pages (estático) no ejecuta el backend.
  if (!API_BASE && !/^(localhost|127\.0\.0\.1|\[?::1\]?)$/.test(location.hostname)) {
    var warnMsg = "[AdelineTarot] Sin backend configurado o backend estático detectado. Define <meta name=\"adeline-api-base\" content=\"https://tu-backend\"> o asegúrate de desplegar como Web Service (ej: en Render).";
    console.warn(warnMsg);
    // document.addEventListener no ha saltado aùn aquí, pero DOM puede estar parcial, lo metemos en un timeout o lo dejamos
    setTimeout(function() { logDebug("WARNING: " + warnMsg); }, 500); 
  }

  var state = {
    publicToken: "",
    reference: "",
    fullName: "",
    email: "",
    birthDate: "",
    plan: "mxn",
    currency: "MXN",
    amount: 100,
    chargeCurrency: "MXN",
    chargeAmount: 100,
    paypalClientId: "",
    paypalMeUrl: "",
    paymentUrl: "",
    paymentNote: "",
    paypalAdvanced: false,
    paypalEnv: "live",
    paypalComponents: "buttons",
    stripeEnabled: false,
    paid: false,
  };

  var paypalScriptLoaded = "";

  // -------------------- utilidades --------------------
  function $(id) { return document.getElementById(id); }

  function alertBox(container, message, kind) {
    container.innerHTML =
      '<div class="alert alert-' + (kind || "error") + '">' + message + "</div>";
  }
  function clearAlert(container) { container.innerHTML = ""; }

  function logDebug(msg) {
    var box = $("debugLogBox");
    if (!box) return;
    box.classList.remove("hidden");
    var div = document.createElement("div");
    div.style.borderBottom = "1px solid #333";
    div.style.padding = "4px 0";
    div.textContent = "> " + (typeof msg === "string" ? msg : JSON.stringify(msg));
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
  }

  function api(path, options) {
    options = options || {};
    options.headers = Object.assign(
      { "Content-Type": "application/json", Accept: "application/json" },
      options.headers || {}
    );
    return fetch(API_BASE + path, options).then(function (res) {
      // Si el servidor responde con HTML en lugar de JSON (e.g. hosting estático mal configurado)
      var cType = res.headers.get("content-type") || "";
      if (res.ok && cType.indexOf("application/json") === -1) {
        logDebug("ERROR: La API " + path + " devolvió " + (cType || "texto plano") + " en lugar de JSON. Probablemente el servidor estático atrapó la petición y el backend no se está ejecutando.");
        throw new Error("No se pudo conectar con el motor de reservas. Verifique la consola inferior.");
      }
      return res
        .json()
        .catch(function () { return {}; })
        .then(function (body) {
          if (!res.ok) {
            logDebug("API " + path + " (" + res.status + "): " + JSON.stringify(body));
            var msg = body && body.detail ? body.detail : "Ocurrió un error (" + res.status + ").";
            if (body && body.errors && body.errors.length) {
              msg = body.errors.map(function (e) { return e.msg; }).join(" · ");
            }
            throw new Error(typeof msg === "string" ? msg : "Error de validación.");
          }
          return body;
        });
    }).catch(function(err) {
      if (err instanceof TypeError && err.message.indexOf("Failed to fetch") !== -1 || err.message.indexOf("NetworkError") !== -1) {
        logDebug("ERROR de Red: El backend en " + API_BASE + " no responde o hay un problema de CORS.");
      } else {
        logDebug("ERROR: " + err.message);
      }
      throw err;
    });
  }

  // signo solar (sólo para el detalle de cortesía al confirmar)
  var SIGNS = [
    { n: "Aries", s: "♈" }, { n: "Tauro", s: "♉" }, { n: "Géminis", s: "♊" },
    { n: "Cáncer", s: "♋" }, { n: "Leo", s: "♌" }, { n: "Virgo", s: "♍" },
    { n: "Libra", s: "♎" }, { n: "Escorpio", s: "♏" }, { n: "Sagitario", s: "♐" },
    { n: "Capricornio", s: "♑" }, { n: "Acuario", s: "♒" }, { n: "Piscis", s: "♓" },
  ];
  function sunSign(iso) {
    var p = iso.split("-");
    var m = parseInt(p[1], 10), d = parseInt(p[2], 10);
    var ranges = [
      [3, 21, 0], [4, 20, 1], [5, 21, 2], [6, 21, 3], [7, 23, 4], [8, 23, 5],
      [9, 23, 6], [10, 23, 7], [11, 22, 8], [12, 22, 9], [1, 20, 10], [2, 19, 11],
    ];
    var chosen = 9;
    ranges
      .slice()
      .sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; })
      .forEach(function (r) {
        if (m > r[0] || (m === r[0] && d >= r[1])) chosen = r[2];
      });
    return SIGNS[chosen];
  }

  // -------------------- config inicial --------------------
  function loadConfig() {
    api("/api/config", { method: "GET" })
      .then(function (cfg) {
        if (cfg.prices) {
          $("amtMxn").textContent = String(cfg.prices.mxn);
          $("amtPen").textContent = String(cfg.prices.pen);
        }
        state.paypalAdvanced = !!cfg.paypal_advanced;
        state.paypalEnv = cfg.paypal_env || "live";
        state.paypalComponents = cfg.paypal_components || "buttons";
        state.stripeEnabled = !!cfg.stripe_enabled;
      })
      .catch(function () { /* valores por defecto del HTML */ });
  }

  // -------------------- selección de plan --------------------
  function wirePlans() {
    var plans = document.querySelectorAll("#plans .plan");
    plans.forEach(function (p) {
      p.addEventListener("click", function () {
        plans.forEach(function (x) { x.classList.remove("selected"); });
        p.classList.add("selected");
        p.querySelector("input").checked = true;
        state.plan = p.getAttribute("data-plan");
      });
    });
  }

  // -------------------- envío del formulario --------------------
  function handleSubmit(e) {
    e.preventDefault();
    var alertC = $("formAlert");
    clearAlert(alertC);

    var payload = {
      full_name: $("full_name").value.trim(),
      email: $("email").value.trim(),
      birth_date: $("birth_date").value,
      birth_place: $("birth_place").value.trim(),
      plan: state.plan,
      website: $("website").value,
    };
    var timeVal = $("birth_time").value;
    if (timeVal) payload.birth_time = timeVal;

    if (!payload.full_name || !payload.email || !payload.birth_date || !payload.birth_place) {
      alertBox(alertC, "Por favor completa todos los campos obligatorios.");
      return;
    }

    var btn = $("submitBtn");
    btn.disabled = true;
    btn.textContent = "Preparando tu carta…";

    api("/api/bookings", { method: "POST", body: JSON.stringify(payload) })
      .then(function (res) {
        state.publicToken = res.public_token;
        state.reference = res.reference;
        state.fullName = payload.full_name;
        state.email = payload.email;
        state.birthDate = payload.birth_date;
        state.currency = res.currency;
        state.amount = res.amount;
        state.chargeCurrency = res.charge_currency;
        state.chargeAmount = res.charge_amount;
        state.paypalClientId = res.paypal_client_id;
        state.paypalMeUrl = res.paypal_me_url;
        state.paymentUrl = res.payment_url || res.paypal_me_url || "";
        state.paymentNote = res.payment_note || "";
        goToPayment();
      })
      .catch(function (err) {
        alertBox(alertC, err.message || "No se pudo registrar la reserva.");
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = "Continuar al pago";
      });
  }

  // -------------------- paso de pago --------------------
  function goToPayment() {
    $("stepForm").classList.add("hidden");
    $("stepDone").classList.add("hidden");
    $("stepPay").classList.remove("hidden");

    $("payAmount").textContent = state.amount + " " + state.currency;
    $("payName").textContent = state.fullName;
    $("payRef").textContent = state.reference;

    var stripeBox = $("stripeBox");
    // Prioridad a la API Stripe nativa (que genera las sesiones y gestiona el retorno automático)
    if (stripeBox) { 
      stripeBox.classList.toggle("hidden", !state.stripeEnabled); 
    }
    var stripeBtn = $("stripeBtn");
    if (stripeBtn) { stripeBtn.disabled = false; stripeBtn.textContent = "💳 Pagar con Tarjeta (Stripe)"; }
    var stripeAppleBtn = $("stripeAppleBtn");
    if (stripeAppleBtn) { stripeAppleBtn.disabled = false; stripeAppleBtn.textContent = " Apple Pay"; }
    var stripeGoogleBtn = $("stripeGoogleBtn");
    if (stripeGoogleBtn) { stripeGoogleBtn.disabled = false; stripeGoogleBtn.innerHTML = '<svg style="width:16px;height:16px;vertical-align:text-bottom;margin-right:6px;" viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.7 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6C44.43 38.02 46.98 31.85 46.98 24.55z"/><path fill="#FBBC05" d="M10.54 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.98-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg> Google Pay'; }

    var link = $("paypalMeLink");
    var payUrl = state.paymentUrl || state.paypalMeUrl || "";
    // Solo mostramos el enlace estático si Stripe nativo NO está activado
    if (payUrl && !state.stripeEnabled) {
      link.href = payUrl;
      link.classList.remove("hidden");
    } else {
      link.classList.add("hidden");
    }

    var note = $("paypalNote");
    note.innerHTML = "";

    resetWallets();

    if (state.paypalClientId) {
      renderPayPalButtons();
    } else {
      alertBox(
        note,
        "Pulsa <strong>Pagar ahora</strong> para completar el pago y luego “He realizado el pago”.",
        "ok"
      );
    }
    $("stepPay").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function loadPayPalSDK(clientId, currency) {
    var components = state.paypalComponents || "buttons";
    var key = currency + "|" + components;
    return new Promise(function (resolve, reject) {
      if (paypalScriptLoaded === key && window.paypal) { resolve(); return; }
      // Si ya había un SDK con otra divisa/componentes, lo quitamos para recargar.
      var old = document.getElementById("paypal-sdk");
      if (old) { old.remove(); try { delete window.paypal; } catch (e) { window.paypal = undefined; } }
      var s = document.createElement("script");
      s.id = "paypal-sdk";
      s.src =
        "https://www.paypal.com/sdk/js?client-id=" +
        encodeURIComponent(clientId) +
        "&currency=" + encodeURIComponent(currency) +
        "&intent=capture&components=" + encodeURIComponent(components) +
        "&enable-funding=card";
      s.onload = function () { paypalScriptLoaded = key; resolve(); };
      s.onerror = function () { reject(new Error("No se pudo cargar PayPal.")); };
      document.head.appendChild(s);
    });
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      if (document.querySelector('script[src="' + src + '"]')) { resolve(); return; }
      var s = document.createElement("script");
      s.src = src;
      s.onload = function () { resolve(); };
      s.onerror = function () { reject(new Error("No se pudo cargar " + src)); };
      document.head.appendChild(s);
    });
  }

  // -------------------- PayPal avanzado (orden + captura en servidor) --------------------
  function paypalOrderRequest() {
    return api(
      "/api/bookings/" + encodeURIComponent(state.publicToken) + "/paypal/order",
      { method: "POST", body: "{}" }
    ).then(function (o) { return o.id; });
  }

  function paypalCaptureRequest(orderId) {
    return api(
      "/api/bookings/" + encodeURIComponent(state.publicToken) + "/paypal/capture",
      { method: "POST", body: JSON.stringify({ order_id: orderId, website: "" }) }
    );
  }

  function finishPaid(res) {
    state.paid = true;
    showPending(res);
  }

  function renderPayPalButtons() {
    var container = $("paypal-buttons");
    container.innerHTML = "";
    var advanced = state.paypalAdvanced;
    loadPayPalSDK(state.paypalClientId, state.chargeCurrency)
      .then(function () {
        window.paypal
          .Buttons({
            style: { color: "gold", shape: "pill", label: "paypal" },
            createOrder: advanced
              ? function () { return paypalOrderRequest(); }
              : function (data, actions) {
                  return actions.order.create({
                    purchase_units: [
                      {
                        description: "AdelineTarot · Carta astral + Tarot",
                        amount: {
                          value: Number(state.chargeAmount).toFixed(2),
                          currency_code: state.chargeCurrency,
                        },
                      },
                    ],
                  });
                },
            onApprove: advanced
              ? function (data) {
                  return paypalCaptureRequest(data.orderID).then(finishPaid);
                }
              : function (data, actions) {
                  return actions.order.capture().then(function (details) {
                    claimPayment("paypal", (details && details.id) || data.orderID);
                  });
                },
            onError: function () {
              alertBox($("payAlert"), "PayPal devolvió un error. Intenta con otro método.");
            },
          })
          .render("#paypal-buttons");
        if (advanced) { setupWallets(); }
      })
      .catch(function (err) {
        alertBox($("paypalNote"), err.message + " Usa “Pagar ahora” y “He realizado el pago”.");
      });
  }

  // -------------------- Apple Pay / Google Pay (vía PayPal) --------------------
  function resetWallets() {
    ["applepay-button", "googlepay-button"].forEach(function (id) {
      var el = $(id);
      if (el) { el.innerHTML = ""; el.classList.add("hidden"); }
    });
    var w = $("walletButtons");
    if (w) { w.classList.add("hidden"); }
  }

  function showWallets() {
    var w = $("walletButtons");
    if (w) { w.classList.remove("hidden"); }
  }

  function setupWallets() {
    try { setupApplePay(); } catch (e) { /* sin Apple Pay */ }
    try { setupGooglePay(); } catch (e) { /* sin Google Pay */ }
  }

  function setupApplePay() {
    if (!window.paypal || !window.paypal.Applepay) { return; }
    if (typeof window.ApplePaySession === "undefined" || !window.ApplePaySession) { return; }
    try { if (!window.ApplePaySession.canMakePayments()) { return; } } catch (e) { return; }

    var applepay = window.paypal.Applepay();
    applepay.config()
      .then(function (cfg) {
        if (!cfg || !cfg.isEligible) { return; }
        var box = $("applepay-button");
        box.innerHTML = '<apple-pay-button buttonstyle="black" type="buy" locale="es-ES"></apple-pay-button>';
        box.classList.remove("hidden");
        showWallets();
        box.querySelector("apple-pay-button").addEventListener("click", function () {
          onApplePayClicked(applepay, cfg);
        });
      })
      .catch(function () { /* sin Apple Pay */ });
  }

  function onApplePayClicked(applepay, cfg) {
    var session;
    try {
      session = new window.ApplePaySession(4, {
        countryCode: cfg.countryCode,
        currencyCode: state.chargeCurrency,
        merchantCapabilities: cfg.merchantCapabilities,
        supportedNetworks: cfg.supportedNetworks,
        requiredBillingContactFields: ["postalAddress", "name"],
        total: { label: "AdelineTarot", amount: Number(state.chargeAmount).toFixed(2) },
      });
    } catch (e) {
      alertBox($("payAlert"), "Apple Pay no está disponible en este dispositivo.");
      return;
    }

    session.onvalidatemerchant = function (event) {
      applepay.validateMerchant({ validationUrl: event.validationURL })
        .then(function (payload) { session.completeMerchantValidation(payload.merchantSession); })
        .catch(function () { session.abort(); });
    };
    session.onpaymentauthorized = function (event) {
      paypalOrderRequest()
        .then(function (orderId) {
          return applepay.confirmOrder({
            orderId: orderId,
            token: event.payment.token,
            billingContact: event.payment.billingContact,
          }).then(function () { return paypalCaptureRequest(orderId); });
        })
        .then(function (res) {
          session.completePayment(window.ApplePaySession.STATUS_SUCCESS);
          finishPaid(res);
        })
        .catch(function (err) {
          session.completePayment(window.ApplePaySession.STATUS_FAILURE);
          alertBox($("payAlert"), "Apple Pay: " + (err.message || "no se pudo completar."));
        });
    };
    session.oncancel = function () { /* cancelado por el usuario */ };
    session.begin();
  }

  function setupGooglePay() {
    if (!window.paypal || !window.paypal.Googlepay) { return; }
    loadScript("https://pay.google.com/gp/p/js/pay.js")
      .then(function () {
        var googlepay = window.paypal.Googlepay();
        return googlepay.config().then(function (cfg) {
          if (!cfg || !cfg.isEligible || !window.google || !google.payments) { return; }
          var env = state.paypalEnv === "live" ? "PRODUCTION" : "TEST";
          var client = new google.payments.api.PaymentsClient({ environment: env });
          return client.isReadyToPay({
            apiVersion: cfg.apiVersion,
            apiVersionMinor: cfg.apiVersionMinor,
            allowedPaymentMethods: cfg.allowedPaymentMethods,
          }).then(function (ready) {
            if (!ready || !ready.result) { return; }
            var btn = client.createButton({
              onClick: function () { onGooglePayClicked(googlepay, cfg, client); },
              buttonType: "pay",
              buttonSizeMode: "fill",
            });
            var box = $("googlepay-button");
            box.innerHTML = "";
            box.appendChild(btn);
            box.classList.remove("hidden");
            showWallets();
          });
        });
      })
      .catch(function () { /* sin Google Pay */ });
  }

  function onGooglePayClicked(googlepay, cfg, client) {
    client.loadPaymentData({
      apiVersion: cfg.apiVersion,
      apiVersionMinor: cfg.apiVersionMinor,
      allowedPaymentMethods: cfg.allowedPaymentMethods,
      merchantInfo: cfg.merchantInfo,
      transactionInfo: {
        countryCode: cfg.countryCode,
        currencyCode: state.chargeCurrency,
        totalPriceStatus: "FINAL",
        totalPrice: Number(state.chargeAmount).toFixed(2),
      },
    })
      .then(function (paymentData) {
        return paypalOrderRequest().then(function (orderId) {
          return googlepay.confirmOrder({
            orderId: orderId,
            paymentMethodData: paymentData.paymentMethodData,
          }).then(function (conf) {
            if (conf.status === "APPROVED" || conf.status === "PAYER_ACTION_REQUIRED") {
              return paypalCaptureRequest(orderId);
            }
            throw new Error("pago no aprobado");
          });
        });
      })
      .then(finishPaid)
      .catch(function (err) {
        if (err && err.statusCode === "CANCELED") { return; }
        alertBox($("payAlert"), "Google Pay: " + (err.message || "no se pudo completar."));
      });
  }

  function claimPayment(method, orderId) {
    if (state.paid) { return; }
    var alertC = $("payAlert");
    clearAlert(alertC);
    var btn = $("confirmPaidBtn");
    btn.disabled = true;
    btn.textContent = "Registrando…";

    api("/api/bookings/" + encodeURIComponent(state.publicToken) + "/pay", {
      method: "POST",
      body: JSON.stringify({ method: method, paypal_order_id: orderId || null, website: "" }),
    })
      .then(function (res) {
        state.paid = true;
        showPending(res);
      })
      .catch(function (err) {
        alertBox(alertC, err.message || "No se pudo registrar el pago.");
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = "He realizado el pago";
      });
  }

  // -------------------- confirmación (pendiente de validación) --------------------
  function showPending(res) {
    $("stepForm").classList.add("hidden");
    $("stepPay").classList.add("hidden");
    $("stepDone").classList.remove("hidden");

    var nameEl = $("doneName");
    if (nameEl) { nameEl.textContent = state.fullName || ""; }
    var emailEl = $("doneEmail");
    if (emailEl) { emailEl.textContent = state.email || "tu correo"; }
    var refEl = $("doneRef");
    if (refEl) { refEl.textContent = (res && res.reference) || state.reference || ""; }

    if (state.birthDate) {
      var sign = sunSign(state.birthDate);
      $("teaserBox").innerHTML =
        '<div class="teaser">' + sign.s + " Tu signo solar: <strong>&nbsp;" +
        sign.n + "</strong></div>";
    }
    $("stepDone").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // -------------------- pago con Stripe (tarjeta / Apple Pay / Google Pay) --------------------
  function startStripeCheckout(e) {
    if (state.paid) { return; }
    var alertC = $("payAlert");
    clearAlert(alertC);
    
    // Si la configuracion dice que abramos un Custom Link (en lugar de sesión via backend)
    var payUrl = state.paymentUrl;
    if (payUrl && !state.stripeEnabled) {
      window.open(payUrl, "_blank");
      return;
    }

    var btn = e ? e.currentTarget : $("stripeBtn");
    var originalText = btn.innerHTML;
    btn.disabled = true;
    btn.textContent = "Redirigiendo a pago seguro…";
    api("/api/stripe/checkout", {
      method: "POST",
      body: JSON.stringify({ public_token: state.publicToken, website: "" }),
    })
      .then(function (res) {
        if (res && res.url) {
          window.location.href = res.url;
        } else {
          throw new Error("No se pudo iniciar el pago.");
        }
      })
      .catch(function (err) {
        btn.disabled = false;
        btn.innerHTML = originalText;
        alertBox(alertC, err.message || "No se pudo iniciar el pago con tarjeta.");
      });
  }

  // Al volver de Stripe (?paid=stripe&session_id=...) confirmamos el pago en el
  // servidor; el enlace nunca se muestra aquí (llega por correo tras validar).
  function handleStripeReturn() {
    var params = new URLSearchParams(location.search);
    if (params.get("paid") !== "stripe") { return; }
    var sid = params.get("session_id");
    if (window.history && history.replaceState) {
      history.replaceState({}, document.title, location.pathname);
    }
    if (!sid) { return; }
    api("/api/stripe/confirm", {
      method: "POST",
      body: JSON.stringify({ session_id: sid }),
    })
      .then(function (res) {
        state.paid = true;
        state.reference = res.reference || "";
        state.fullName = res.full_name || "";
        showPending(res);
      })
      .catch(function () {
        $("stepForm").classList.add("hidden");
        $("stepPay").classList.add("hidden");
        $("stepDone").classList.remove("hidden");
        $("stepDone").scrollIntoView({ behavior: "smooth", block: "start" });
      });
  }

  // -------------------- enlaces / arranque --------------------
  function wireControls() {
    $("bookingForm").addEventListener("submit", handleSubmit);
    $("confirmPaidBtn").addEventListener("click", function () {
      claimPayment("paypalme", null);
    });
    var stripeBtn = $("stripeBtn");
    if (stripeBtn) { stripeBtn.addEventListener("click", startStripeCheckout); }      var stripeAppleBtn = $("stripeAppleBtn");
      if (stripeAppleBtn) { stripeAppleBtn.addEventListener("click", startStripeCheckout); }
      var stripeGoogleBtn = $("stripeGoogleBtn");
      if (stripeGoogleBtn) { stripeGoogleBtn.addEventListener("click", startStripeCheckout); }
          $("backToForm").addEventListener("click", function (e) {
      e.preventDefault();
      $("stepPay").classList.add("hidden");
      $("stepForm").classList.remove("hidden");
      $("stepForm").scrollIntoView({ behavior: "smooth", block: "start" });
    });
    var y = $("year");
    if (y) y.textContent = new Date().getFullYear();
  }

  document.addEventListener("DOMContentLoaded", function () {
    wireControls();
    wirePlans();
    loadConfig();
    handleStripeReturn();
  });
})();
