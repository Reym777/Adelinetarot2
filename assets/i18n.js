(function () {
  'use strict';

  var STORAGE_KEY = 'adelinemagica_lang';
  var SUPPORTED = { es: true, en: true };
  var DEFAULT_LANG = 'es';
  var TITLE_ES = 'Lectura de tarot y carta astral online | Adeline M\u00e1gica';
  var TITLE_EN = 'Online Tarot and Birth Chart Readings | Adeline Magica';

  var textOriginals = new WeakMap();
  var attrOriginals = new WeakMap();

  var COMMON = {
    'Home': 'Home',
    'Inicio': 'Home',
    'Volver': 'Back',
    'Contact': 'Contact',
    'Contacto': 'Contact',
    'Conexi\u00f3n / inscripci\u00f3n': 'Connection / Sign-up',
    'Solicita tu oraci\u00f3n hoy mismo': 'Request your prayer today',
    'Meditaciones via videollamada': 'Video call meditations',
    'Meditaciones v\u00eda videollamada': 'Video call meditations',
    'Tarot terap\u00e9utico': 'Therapeutic tarot',
    'Mundo astrologico': 'Astrology world',
    'Mundo astrol\u00f3gico': 'Astrology world',
    'Lectura de carta natal': 'Birth chart reading',
    'Sinastr\u00eda': 'Synastry',
    'Paquete M\u00c1GICA': 'MAGICA Package',
    'Adquiere': 'Get',
    'Paquete': 'Package',
    'Pagar': 'Pay',
    'Reservar': 'Book',
    'MAGICA': 'MAGICA',
    'Cerrar men\u00fa': 'Close menu',
    'Abrir men\u00fa': 'Open menu',
    'Men\u00fa': 'Menu',
    'Ver sitio': 'View site',
    'Cerrar sesi\u00f3n': 'Log out'
  };

  var ES_MAP = {
    'Home': 'Inicio',
    'Contact': 'Contacto',
    'Connection / Sign-up': 'Conexi\u00f3n / inscripci\u00f3n',
    'Dashboard admin': 'Panel admin',
    'Site public': 'Sitio p\u00fablico',
    'Panel cl\u00e1sico': 'Panel cl\u00e1sico',
    'Connexion administrateur': 'Conexi\u00f3n de administrador',
    'Token admin': 'Token admin',
    'Coller le token admin': 'Pega el token admin',
    'Entrer': 'Entrar',
    'Vue op\u00e9rationnelle': 'Vista operativa',
    'P\u00e9riode': 'Periodo',
    'Tout': 'Todo',
    'Aujourd\'hui': 'Hoy',
    'Rechercher client, ref, email': 'Buscar cliente, ref, email',
    'Actualiser': 'Actualizar',
    'Copier emails': 'Copiar emails',
    'D\u00e9connexion': 'Cerrar sesi\u00f3n',
    'RDV \u00e0 venir': 'Pr\u00f3ximas citas',
    'Paiements r\u00e9cents': 'Pagos recientes',
    'Total mois': 'Total mes',
    'Total ann\u00e9e': 'Total a\u00f1o',
    'Visites hier': 'Visitas ayer',
    'Planning prochaines citations': 'Pr\u00f3ximas citas',
    'Derniers paiements': '\u00daltimos pagos',
    'Emails clients r\u00e9cents': 'Emails recientes de clientes',
    'Ref': 'Ref',
    'Client': 'Cliente',
    'Date': 'Fecha',
    'Heure': 'Hora',
    '\u00c9tat': 'Estado',
    'Actions': 'Acciones',
    'Montant': 'Monto',
    'M\u00e9thode': 'M\u00e9todo',
    'Contact \u00b7 Adeline': 'Contacto \u00b7 Adeline'
  };

  var MAP = {
    'ADELINEMAGICA ? Dashboard admin': 'ADELINEMAGICA ? Admin dashboard',
    'Site public': 'Public site',
    'Panel cl?sico': 'Classic panel',
    'Connexion administrateur': 'Administrator login',
    'Token admin': 'Admin token',
    'Coller le token admin': 'Paste admin token',
    'Entrer': 'Sign in',
    'Vue op?rationnelle': 'Operations view',
    'P?riode': 'Period',
    'Tout': 'All',
    'Aujourd\'hui': 'Today',
    'Rechercher client, ref, email': 'Search client, ref, email',
    'Actualiser': 'Refresh',
    'Copier emails': 'Copy emails',
    'D?connexion': 'Log out',
    'RDV ? venir': 'Upcoming appointments',
    'Paiements r?cents': 'Recent payments',
    'Total mois': 'Monthly total',
    'Total ann?e': 'Yearly total',
    'Visites hier': 'Visits yesterday',
    'Planning prochaines citations': 'Upcoming bookings',
    'Derniers paiements': 'Latest payments',
    'Emails clients r?cents': 'Recent client emails',
    '?tat': 'Status',
    'Montant': 'Amount',
    'M?thode': 'Method',

    'Oraciones \u00b7 Tarot terap\u00e9utico \u00b7 Meditaciones': 'Prayers \u00b7 Therapeutic tarot \u00b7 Meditations',
    'Elevo tu oraci\u00f3n': 'I lift your prayer',
    'al creador': 'to the Creator',
    'y el cielo responde': 'and heaven responds',
    '\u00a1Perm\u00edteme sumar!': 'Allow me to support you!',
    'Solicitar oraci\u00f3n / rezo': 'Request prayer',
    'Paquete M\u00e1gica': 'Magica Package',
    '3 meditaciones de 33 min + 1 lectura de tarot terap\u00e9utico de 30 min + PDF con recomendaciones para apertura de caminos y autosanaci\u00f3n por 144 USD.': '3 meditations of 33 min + 1 therapeutic tarot reading of 30 min + PDF with recommendations for opening paths and self-healing for 144 USD.',
    '3 meditaciones': '3 meditations',
    'Sesiones de 33 minutos via videollamada con foco en sanaci\u00f3n interior.': '33-minute video call sessions focused on inner healing.',
    'Una lectura de 30 minutos que abrir\u00e1 paso a tu claridad mental y equilibrio emocional.': 'A 30-minute reading that opens the way to mental clarity and emotional balance.',
    'PDF de apoyo': 'Support PDF',
    'Con un modelo de 7 p\u00e1ginas para digerir en tu tiempo libre. Permite que desarrolles autosanaci\u00f3n, apertura de caminos y enfoque.': 'A 7-page guide you can absorb at your own pace. It supports self-healing, opening new paths, and deeper focus.',
    'Adquiere hoy': 'Get it today',
    'Oraciones de sanaci\u00f3n y de purificaci\u00f3n': 'Healing and purification prayers',
    'Completa la informaci\u00f3n para elevar el rezo.': 'Fill in your details to submit your prayer.',
    'Nota: una vez realizado el pago, deber\u00e1s colocar un vaso de cristal con agua en un espacio de paz dentro de tu hogar.': 'Note: once payment is made, place a glass of water in a peaceful space in your home.',
    'Nombre (opcional)': 'First name (optional)',
    'Apellido (opcional)': 'Last name (optional)',
    'Email': 'Email',
    'Cual es la situacion que se espera mejorar (salud, fortaleza, paz, bienestar, toma de decisiones, entre otros)': 'Which situation do you want to improve (health, strength, peace, well-being, decision making, among others)',
    'Describe la situacion a mejorar': 'Describe the situation to improve',
    'Describe lo m\u00e1s claro posible tu petici\u00f3n': 'Describe your request as clearly as possible',
    'Escribe tu intenci\u00f3n': 'Write your intention',
    'Informaci\u00f3n complementaria (persona, situaci\u00f3n, mascota, ciudad, nombre del proceso...)': 'Additional information (person, situation, pet, city, process name...)',
    'Detalles adicionales': 'Additional details',
    'Oraciones por 3 d\u00edas = 60 USD': 'Prayers for 3 days = 60 USD',
    'Pagar con Tarjeta': 'Pay with card',

    'Meditaciones via videollamada': 'Video call meditations',
    '33 USD por 33 min.': '33 USD for 33 min.',
    'Nombre o alias': 'Name or alias',
    'Motivo o raz\u00f3n': 'Reason',
    'Motivo': 'Reason',
    'Correo electr\u00f3nico': 'Email',
    'Qu\u00e9 te gustar\u00eda sanar a trav\u00e9s de la meditaci\u00f3n': 'What would you like to heal through meditation',
    'Selecciona el dia y horario': 'Select day and time',
    'Horarios disponibles': 'Available times',
    'Meditaci\u00f3n pregrabada personalizada enviada por correo (60 USD, solo en espa\u00f1ol)': 'Personalized pre-recorded meditation sent by email (60 USD, Spanish only)',
    'Las sesiones se agendan con cupo limitado y confirmaci\u00f3n manual.': 'Sessions are scheduled with limited spots and manual confirmation.',
    'PAGAR LAS MEDITACIONES': 'PAY FOR MEDITATIONS',
    'Meditaciones via videollamada \u00b7 acompa\u00f1amiento espiritual': 'Video call meditations \u00b7 spiritual support',

    'Escr\u00edbenos para recibir precisiones sobre los productos propuestos. Te responderemos por correo.': 'Write to us to receive details about our services. We will reply by email.',
    'Nombre': 'First name',
    'Apellido': 'Last name',
    'Tu mensaje': 'Your message',
    'Ind\u00edcanos sobre qu\u00e9 producto deseas m\u00e1s informaci\u00f3n.': 'Tell us which service you want more information about.',
    'Enviar solicitud': 'Send request',
    'Campos obligatorios: nombre, apellido y correo electr\u00f3nico.': 'Required fields: first name, last name, and email.',

    'Paquete Magica': 'Magica Package',
    'Completa tus datos y fija las fechas de tus sesiones antes del pago.': 'Fill in your details and set your session dates before payment.',
    'Tu nombre': 'Your first name',
    'Tu apellido': 'Your last name',
    'Selecciona fecha y hora de inicio del paquete': 'Select package start date and time',
    'Preferencias para las otras 3 sesiones (opcional)': 'Preferences for the other 3 sessions (optional)',
    'Ejemplo: prefiero martes/jueves por la tarde': 'Example: I prefer Tuesday/Thursday afternoons',
    'pagar el paquete magica': 'pay for the magica package',
    'Despues del pago te contactaremos para confirmar las siguientes sesiones en hora local de Peru.': 'After payment, we will contact you to confirm the next sessions in Peru local time.',
    'Paquete Magica \u00b7 tarot y acompanamiento espiritual': 'Magica Package \u00b7 tarot and spiritual guidance',

    'Predicci\u00f3n astral gratuita': 'Free astral prediction',
    'Ingresa tu fecha de nacimiento y recibe una lectura inmediata. Elige entre visi\u00f3n a corto plazo (tarot - pr\u00f3ximas semanas) o largo plazo (astrolog\u00eda - pr\u00f3ximos 5 a\u00f1os).': 'Enter your birth date and get an instant reading. Choose between short-term vision (tarot - next weeks) or long-term vision (astrology - next 5 years).',
    'CP Corto plazo': 'ST Short term',
    'LP Largo plazo': 'LT Long term',
    'Tu nombre': 'Your name',
    'Fecha de nacimiento': 'Birth date',
    'Tema principal': 'Main topic',
    'General': 'General',
    'Amor y relaciones': 'Love and relationships',
    'Trabajo y dinero': 'Work and money',
    'Salud y bienestar': 'Health and wellness',
    'Familia': 'Family',
    'Ver mi lectura de tarot': 'See my tarot reading',
    'Continuar la lectura completa': 'Continue full reading',
    'Los 3 primeros p\u00e1rrafos son visibles. Para desbloquear toda la predicci\u00f3n, env\u00eda tu email.': 'The first 3 paragraphs are visible. To unlock the full prediction, enter your email.',
    'Tu email': 'Your email',
    'Desbloquear': 'Unlock',
    'Hora de nacimiento': 'Birth time',
    '(opcional)': '(optional)',
    'Ver mi prediccion 5 anos': 'See my 5-year prediction',
    'Prediccion 5 anos bloqueada': '5-year prediction locked',
    'Acceso completo por 5 USD. Es la misma tarifa especial de la visio con Adeline.': 'Full access for 5 USD. This is the same special rate as Adeline vision.',
    'Pagar 5 USD': 'Pay 5 USD',
    'Ya pagu\u00e9, desbloquear': 'I already paid, unlock',
    'Acompa\u00f1amiento espiritual de alto valor y en tiempo real - Consultas previa agenda': 'High-value spiritual guidance in real time - Consultations by appointment only',
    'Acompa\u00f1amiento espiritual de alto valor y en tiempo real - Consultas con agenda previa': 'High-value spiritual guidance in real time - Consultations by appointment only',

    'Lectura de carta natal': 'Birth chart reading',
    'Completa tus datos para generar una interpretaci\u00f3n amplia en espa\u00f1ol con planetas, casas, signos y aspectos.': 'Fill in your details to generate a full interpretation in English with planets, houses, signs, and aspects.',
    'Pa\u00eds de nacimiento': 'Country of birth',
    'Ciudad de nacimiento': 'City of birth',
    'Ej: Francia': 'e.g.: France',
    'Ej: Par\u00eds': 'e.g.: Paris',
    '\u00bfHora de verano?': 'Daylight saving time?',
    'No': 'No',
    'S\u00ed': 'Yes',
    'Generar mi carta natal completa': 'Generate my full birth chart',

    'Introduce los datos de dos personas para analizar su compatibilidad con aspectos, signos y planetas cruzados.': 'Enter the data of two people to analyze compatibility through aspects, signs, and cross-planet dynamics.',
    'Nombre de la persona A': 'Person A name',
    'Pa\u00eds de nacimiento A': 'Person A country of birth',
    'Ciudad de nacimiento A': 'Person A city of birth',
    '\u00bfHora de verano A?': 'DST for person A?',
    'Nombre de la persona B': 'Person B name',
    'Pa\u00eds de nacimiento B': 'Person B country of birth',
    'Ciudad de nacimiento B': 'Person B city of birth',
    '\u00bfHora de verano B?': 'DST for person B?',
    'Ej: M\u00e9xico': 'e.g.: Mexico',
    'Ej: Ciudad de M\u00e9xico': 'e.g.: Mexico City',
    'Generar sinastr\u00eda completa': 'Generate full synastry',

    'Panel de Adeline': 'Adeline panel',
    'Introduce tu clave de administraci\u00f3n para ver las consultas.': 'Enter your admin key to view consultations.',
    'Clave de administraci\u00f3n': 'Administration key',
    'Entrar': 'Sign in',
    'Consultas': 'Consultations',
    'Cargando\u2026': 'Loading...',
    'Completa un email v\u00e1lido y tu petici\u00f3n.': 'Complete a valid email and your request.',
    'Datos listos para el pago seguro.': 'Data ready for secure payment.',
    'Redirection vers paiement securise...': 'Redirecting to secure payment...',
    'Erreur de configuration du paiement Stripe. Verifie le lien de paiement.': 'Stripe payment configuration error. Check the payment link.',
    'Completa nombre, apellido, correo y mensaje.': 'Complete first name, last name, email, and message.',
    'Enviando solicitud...': 'Sending request...',
    'Solicitud enviada. Te responderemos por correo pronto.': 'Request sent. We will reply by email soon.',
    'No se pudo enviar tu solicitud.': 'Your request could not be sent.',
    'Completa todos los campos antes de pagar.': 'Complete all fields before paying.',
    'Completa nombre, fecha y email v\u00e1lido.': 'Complete name, date, and a valid email.',
    'Completa los dos perfiles y un email v\u00e1lido.': 'Complete both profiles and a valid email.',
    'Completa todos los campos con email v\u00e1lido.': 'Complete all fields with a valid email.',
    'Por favor, ingresa tu nombre y fecha de nacimiento.': 'Please enter your name and birth date.',
    'Ingresa un email v\u00e1lido para desbloquear.': 'Enter a valid email to unlock.',
    'Gracias. Contenido desbloqueado.': 'Thank you. Content unlocked.',
    'Resultado expr\u00e9s': 'Quick result',
    'Tu solicitud est\u00e1 lista para la lectura completa.': 'Your request is ready for the full reading.',
    'Compatibilidad r\u00e1pida': 'Quick compatibility',
    'Puntaje estimado:': 'Estimated score:',
    'La sesi\u00f3n en vivo permitir\u00e1 afinar con preguntas espec\u00edficas.': 'A live session will let us refine this with your specific questions.',
    'Proyecci\u00f3n 1 a\u00f1o': '1-year projection',
    'Visi\u00f3n 5 a\u00f1os': '5-year vision',
    'Ventanas fuertes: a\u00f1o 1.5, 3 y 4.5 con decisiones estructurantes.': 'Key windows: years 1.5, 3, and 4.5 for major structural decisions.',
    'Oraci\u00f3n recomendada': 'Recommended prayer',
    'Tu perfil astral de bienestar': 'Your astral wellness profile',
    'Por que te favorece:': 'Why it supports you:',
    'Las cartas se est\u00e1n revelando para ti\u2026': 'The cards are being revealed for you?',
    'S\u00edntesis de las pr\u00f3ximas semanas': 'Summary for the coming weeks',
    '\u00bfQuieres profundizar en esta lectura con una interpretaci\u00f3n personal en vivo?': 'Would you like to go deeper with a personal live interpretation?',
    'Reservar mi consulta': 'Book my consultation',
    'Contenido bloqueado': 'Locked content',
    'Has llegado al l\u00edmite gratuito de 3 p\u00e1rrafos. Ingresa tu email para desbloquear el resto.': 'You have reached the free limit of 3 paragraphs. Enter your email to unlock the rest.',
    'Acceso desbloqueado. Ya puedes ver la predicci\u00f3n de 5 a\u00f1os.': 'Access unlocked. You can now view your 5-year prediction.',
    'Calculando tu tema natal completo\u2026': 'Calculating your full natal theme?',
    'Carrera & Finanzas': 'Career & Finances',
    'Amor & Relaciones': 'Love & Relationships',
    'Familia & Hogar': 'Family & Home',
    'Bienestar & Salud': 'Well-being & Health',
    'Amigos & Vida social': 'Friends & Social Life',
    'Visi\u00f3n a 10 a\u00f1os & Plan personal': '10-year vision & personal plan',
    'Predicci\u00f3n 5 a\u00f1os bloqueada': '5-year prediction locked',
    'No se pudo determinar la zona horaria de nacimiento. Verifica pa\u00eds y ciudad.': 'Could not determine the birth timezone. Please verify country and city.',
    'No se pudo determinar la zona horaria autom\u00e1tica. Verifica pa\u00eds y ciudad de ambas personas.': 'Could not determine timezone automatically. Please verify country and city for both people.',
    'Calculando zona horaria seg\u00fan pa\u00eds y ciudad...': 'Calculating timezone from country and city...',
    'Calculando zonas horarias seg\u00fan pa\u00eds y ciudad...': 'Calculating timezones from country and city...',
    'Completa nombre, pa\u00eds, ciudad y fecha de nacimiento.': 'Complete name, country, city, and birth date.',
    'Completa nombre, pa\u00eds, ciudad y fecha de nacimiento de ambas personas.': 'Complete name, country, city, and birth date for both people.'
  };

  function pageName() {
    var p = String(location.pathname || '').split('/').pop() || 'index';
    p = p.replace(/\.html$/i, '');
    return p || 'index';
  }

  function isLocalizedFolderPath() {
    var p = String((location && location.pathname) || '').toLowerCase();
    return /\/(en|es|fr)(\/|$)/.test(p);
  }

  function getPathLang() {
    var p = String((location && location.pathname) || '').toLowerCase();
    var match = p.match(/\/(en|es|fr)(?:\/|$)/);
    return match ? match[1] : '';
  }

  function getLang() {
    var fromPath = getPathLang();
    if (SUPPORTED[fromPath]) {
      return fromPath;
    }
    var saved = (localStorage.getItem(STORAGE_KEY) || '').toLowerCase();
    if (SUPPORTED[saved]) {
      return saved;
    }
    return DEFAULT_LANG;
  }

  function setLang(lang) {
    var normalized = SUPPORTED[lang] ? lang : DEFAULT_LANG;
    localStorage.setItem(STORAGE_KEY, normalized);
    applyLanguage(normalized);
  }

  function injectStyles() {
    if (document.getElementById('adeline-lang-style')) {
      return;
    }
    var style = document.createElement('style');
    style.id = 'adeline-lang-style';
    style.textContent = '.lang-switch{display:inline-flex;gap:6px;align-items:center}.lang-switch button{border:1px solid rgba(232,198,107,.35);background:rgba(12,10,29,.65);color:#e8c66b;border-radius:999px;padding:4px 10px;font:600 12px/1 Cinzel,serif;letter-spacing:.04em;cursor:pointer}.lang-switch button.active{background:#e8c66b;color:#0c0a1d;border-color:#e8c66b}.side-menu-head>.lang-switch{margin-left:auto}';
    document.head.appendChild(style);
  }

  function maybeRepairMojibake(value) {
    if (typeof value !== 'string' || !/[????]/.test(value)) {
      return value;
    }
    var fixed = value;
    for (var i = 0; i < 2; i += 1) {
      try {
        var next = decodeURIComponent(escape(fixed));
        if (!next || next === fixed) {
          break;
        }
        fixed = next;
      } catch (_err) {
        break;
      }
    }
    return fixed.replace(/\uFFFD/g, '');
  }

  function makeSwitch() {
    var host = document.createElement('div');
    host.className = 'lang-switch';
    host.setAttribute('role', 'group');
    host.setAttribute('aria-label', 'Language selector');

    ['es', 'en'].forEach(function (lang) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.dataset.lang = lang;
      btn.textContent = lang.toUpperCase();
      btn.addEventListener('click', function () { setLang(lang); });
      host.appendChild(btn);
    });

    return host;
  }

  function injectSwitches() {
    var sideHead = document.querySelector('#sideMenu .side-menu-head');
    if (sideHead && sideHead.querySelector('.side-menu-lang-top')) {
      return;
    }
    if (sideHead && !sideHead.querySelector('.lang-switch')) {
      sideHead.appendChild(makeSwitch());
    }
  }

  function getTextOriginal(node) {
    if (!textOriginals.has(node)) {
      textOriginals.set(node, node.nodeValue);
    }
    return textOriginals.get(node);
  }

  function getAttrOriginal(el, attr) {
    var store = attrOriginals.get(el);
    if (!store) {
      store = {};
      attrOriginals.set(el, store);
    }
    if (!Object.prototype.hasOwnProperty.call(store, attr)) {
      store[attr] = el.getAttribute(attr);
    }
    return store[attr];
  }

  function translateText(value, lang) {
    if (typeof value !== 'string') {
      return value;
    }
    var match = value.match(/^(\s*)([\s\S]*?)(\s*)$/);
    if (!match) {
      return value;
    }
    var left = match[1];
    var core = maybeRepairMojibake(match[2]);
    var right = match[3];
    var translated;
    if (lang === 'es') {
      translated = ES_MAP[core] || core;
    } else {
      translated = MAP[core] || COMMON[core] || ES_MAP[core] || core;
    }
    return left + translated + right;
  }

  function shouldSkipTextNode(node) {
    if (!node || !node.parentElement) {
      return true;
    }
    var tag = node.parentElement.tagName;
    return tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT' || tag === 'TEXTAREA';
  }

  function applyOnRoot(root, lang) {
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    var current;
    while ((current = walker.nextNode())) {
      if (shouldSkipTextNode(current)) {
        continue;
      }
      var originalText = maybeRepairMojibake(getTextOriginal(current));
      current.nodeValue = translateText(originalText, lang);
    }

    var attrTargets = root.querySelectorAll ? root.querySelectorAll('[placeholder],[aria-label],[title],input[type="button"],input[type="submit"]') : [];
    for (var i = 0; i < attrTargets.length; i += 1) {
      var el = attrTargets[i];
      ['placeholder', 'aria-label', 'title', 'value'].forEach(function (attr) {
        if (!el.hasAttribute(attr)) {
          return;
        }
        var originalValue = getAttrOriginal(el, attr);
        if (originalValue == null) {
          return;
        }
        el.setAttribute(attr, translateText(maybeRepairMojibake(originalValue), lang));
      });
    }
  }

  function syncButtons(lang) {
    var buttons = document.querySelectorAll('.lang-switch button[data-lang]');
    buttons.forEach(function (btn) {
      btn.classList.toggle('active', btn.dataset.lang === lang);
    });
  }

  function applyLanguage(lang) {
    var effective = SUPPORTED[lang] ? lang : DEFAULT_LANG;
    document.documentElement.lang = effective;
    document.title = effective === 'en' ? TITLE_EN : TITLE_ES;
    applyOnRoot(document.body, effective);
    syncButtons(effective);
  }

  function observeDynamic() {
    var observer = new MutationObserver(function (mutations) {
      var lang = getLang();
      for (var i = 0; i < mutations.length; i += 1) {
        var m = mutations[i];
        if (m.type === 'characterData') {
          var changed = m.target;
          if (!shouldSkipTextNode(changed)) {
            var translated = translateText(maybeRepairMojibake(changed.nodeValue || ''), lang);
            if (changed.nodeValue !== translated) {
              changed.nodeValue = translated;
            }
          }
          continue;
        }
        if (m.type === 'childList') {
          m.addedNodes.forEach(function (node) {
            if (node.nodeType === Node.TEXT_NODE) {
              if (shouldSkipTextNode(node)) {
                return;
              }
              var original = maybeRepairMojibake(getTextOriginal(node));
              node.nodeValue = translateText(original, lang);
              return;
            }
            if (node.nodeType === Node.ELEMENT_NODE) {
              applyOnRoot(node, lang);
            }
          });
        }
      }
    });
    observer.observe(document.body, { childList: true, characterData: true, subtree: true });
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (isLocalizedFolderPath()) {
      applyLanguage(getLang());
      observeDynamic();
      return;
    }
    injectStyles();
    injectSwitches();
    applyLanguage(getLang());
    observeDynamic();
  });
})();

