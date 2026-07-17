/* Adelinemagica - logica del cliente (reserva + pago PayPal + enlace de videollamada) */
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
  var STRIPE_FIXED_PAYMENT_URL = "https://buy.stripe.com/cNi7sL9LAgYoeHz4Ud6J204";

  // Aviso para el desarrollador: GitHub Pages (estático) no ejecuta el backend.
  if (!API_BASE && !/^(localhost|127\.0\.0\.1|\[?::1\]?)$/.test(location.hostname)) {
    var warnMsg = "[Adelinemagica] Sin backend configurado o backend estático detectado. Define <meta name=\"adeline-api-base\" content=\"https://tu-backend\"> o asegúrate de desplegar como Web Service (ej: en Render).";
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
    { n: "Aries", s: "\u2648" }, { n: "Tauro", s: "\u2649" }, { n: "Geminis", s: "\u264A" },
    { n: "Cancer", s: "\u264B" }, { n: "Leo", s: "\u264C" }, { n: "Virgo", s: "\u264D" },
    { n: "Libra", s: "\u264E" }, { n: "Escorpio", s: "\u264F" }, { n: "Sagitario", s: "\u2650" },
    { n: "Capricornio", s: "\u2651" }, { n: "Acuario", s: "\u2652" }, { n: "Piscis", s: "\u2653" },
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
    var appointmentDateVal = $("appointment_date") ? $("appointment_date").value : "";
    var appointmentTimeVal = $("appointment_time") ? $("appointment_time").value : "";
    if (appointmentDateVal) payload.appointment_date = appointmentDateVal;
    if (appointmentTimeVal) payload.appointment_time = appointmentTimeVal;

    if (!payload.full_name || !payload.email || !payload.birth_date || !payload.birth_place) {
      alertBox(alertC, "Por favor completa todos los campos obligatorios.");
      return;
    }

    var btn = $("submitBtn");
    btn.disabled = true;
    btn.textContent = "Preparando tu carta...";

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
    if (stripeBox) {
      stripeBox.classList.remove("hidden");
    }
    var stripeBtn = $("stripeBtn");
    if (stripeBtn) { stripeBtn.disabled = false; stripeBtn.textContent = "Pagar con Tarjeta (Stripe)"; }

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

    if (state.paypalClientId) {
      renderPayPalButtons();
    } else {
      alertBox(
        note,
        "Pulsa <strong>Pagar ahora</strong> para completar el pago y luego <strong>He realizado el pago</strong>.",
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
                        description: "Adelinemagica · Carta astral + Tarot",
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
      })
      .catch(function (err) {
        alertBox($("paypalNote"), err.message + " Usa 'Pagar ahora' y 'He realizado el pago'.");
      });
  }

  function claimPayment(method, orderId) {
    if (state.paid) { return; }
    var alertC = $("payAlert");
    clearAlert(alertC);
    var btn = $("confirmPaidBtn");
    btn.disabled = true;
    btn.textContent = "Registrando...";

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
    var btn = e ? e.currentTarget : $("stripeBtn");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Redirigiendo a Stripe...";
    }
    window.location.href = STRIPE_FIXED_PAYMENT_URL;
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
    var form = $("bookingForm");
    if (!form) {
      var yOnly = $("year");
      if (yOnly) yOnly.textContent = new Date().getFullYear();
      return;
    }

    form.addEventListener("submit", handleSubmit);
    var confirmBtn = $("confirmPaidBtn");
    if (confirmBtn) {
      confirmBtn.addEventListener("click", function () {
        claimPayment("paypalme", null);
      });
    }
    var stripeBtn = $("stripeBtn");
    if (stripeBtn) { stripeBtn.addEventListener("click", startStripeCheckout); }
    var backToForm = $("backToForm");
    if (backToForm) {
      backToForm.addEventListener("click", function (e) {
        e.preventDefault();
        $("stepPay").classList.add("hidden");
        $("stepForm").classList.remove("hidden");
        $("stepForm").scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
    var y = $("year");
    if (y) y.textContent = new Date().getFullYear();
  }

  function applyAppointmentFromQuery() {
    var params = new URLSearchParams(location.search);
    var apptDate = params.get("appointment_date") || "";
    var apptTime = params.get("appointment_time") || "";
    var dateInput = $("appointment_date");
    var timeInput = $("appointment_time");
    var wrap = $("appointment_summary_wrap");
    var summary = $("appointment_summary");

    if (!dateInput || !timeInput || !wrap || !summary) {
      return;
    }
    if (!apptDate || !apptTime) {
      return;
    }

    dateInput.value = apptDate;
    timeInput.value = apptTime;

    var parts = apptDate.split("-");
    var prettyDate = apptDate;
    if (parts.length === 3) {
      prettyDate = parts[2] + "/" + parts[1] + "/" + parts[0];
    }
    summary.textContent = prettyDate + " a las " + apptTime + " (Peru)";
    wrap.style.display = "block";
  }

  document.addEventListener("DOMContentLoaded", function () {
    applyAppointmentFromQuery();
    wireControls();
    wirePlans();
    loadConfig();
    handleStripeReturn();
  });
})();

