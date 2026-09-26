(function () {
  const majorArcana = [
    ["El Loco", "Anímate a dar un paso nuevo, confiando en tu capacidad de aprender durante el camino."],
    ["El Mago", "Reconoce los recursos que ya tienes y úsalos con intención."],
    ["La Sacerdotisa", "Haz espacio al silencio; tu intuición puede mostrarte algo importante."],
    ["La Emperatriz", "Cuida lo que está creciendo en ti y permite que florezca a su ritmo."],
    ["El Emperador", "Un límite claro o una estructura estable puede darte seguridad."],
    ["El Hierofante", "Busca una guía o un valor que te ayude a encontrar sentido."],
    ["Los Enamorados", "Elige desde la coherencia con tus valores y necesidades reales."],
    ["El Carro", "Avanza con dirección; reúne tus fuerzas antes de tomar impulso."],
    ["La Fuerza", "La paciencia y la amabilidad contigo también son formas de valentía."],
    ["El Ermitaño", "Tómate un momento a solas para escuchar lo que de verdad necesitas."],
    ["La Rueda de la Fortuna", "Un cambio de ciclo te invita a adaptarte sin perder tu centro."],
    ["La Justicia", "Mira la situación con honestidad y busca un equilibrio justo."],
    ["El Colgado", "Cambiar de perspectiva puede abrir una posibilidad que no veías."],
    ["La Muerte", "Soltar una etapa permite hacer sitio a una transformación necesaria."],
    ["La Templanza", "Integra los extremos con calma y avanza paso a paso."],
    ["El Diablo", "Observa qué hábito o apego limita tu libertad, sin juzgarte."],
    ["La Torre", "Una verdad que sale a la luz puede ayudarte a reconstruir sobre bases firmes."],
    ["La Estrella", "Recupera la esperanza y atiende con ternura aquello que necesita sanar."],
    ["La Luna", "Si hay incertidumbre, avanza despacio y distingue intuición de temor."],
    ["El Sol", "Permítete disfrutar de la claridad, la vitalidad y los vínculos sinceros."],
    ["El Juicio", "Escucha el llamado a cerrar asuntos pendientes y responder con conciencia."],
    ["El Mundo", "Reconoce lo que has completado y celebra tu crecimiento."]
  ];
  const suits = [
    ["Bastos", "tu creatividad y energía"],
    ["Copas", "tus emociones y vínculos"],
    ["Espadas", "tus ideas y conversaciones"],
    ["Oros", "tu bienestar y vida práctica"]
  ];
  const ranks = [
    ["As", "un comienzo"], ["Dos", "una elección o alianza"], ["Tres", "un crecimiento compartido"],
    ["Cuatro", "una base estable"], ["Cinco", "un cambio que pide adaptación"], ["Seis", "un paso hacia la armonía"],
    ["Siete", "la perseverancia ante las dudas"], ["Ocho", "el avance mediante la constancia"], ["Nueve", "la madurez y autonomía"],
    ["Diez", "el cierre de un ciclo"], ["Sota", "la curiosidad y el aprendizaje"], ["Caballero", "la iniciativa y el movimiento"],
    ["Reina", "la sensibilidad y la confianza interior"], ["Rey", "el liderazgo y la responsabilidad"]
  ];
  const positions = ["Tu momento presente", "Lo que pide atención", "Un recurso interior", "Un paso posible", "Para integrar"];
  const deck = majorArcana.map(([name, meaning], spriteIndex) => ({ name, meaning, spriteIndex }));
  const suitSpriteStarts = { Copas: 22, Bastos: 36, Espadas: 50, Oros: 64 };

  suits.forEach(([suit, theme]) => {
    ranks.forEach(([rank, lesson], rankIndex) => {
      deck.push({
        name: `${rank} de ${suit}`,
        spriteIndex: suitSpriteStarts[suit] + rankIndex,
        meaning: `Esta carta señala ${lesson} en ${theme}. Pregúntate cómo puedes acompañar ese proceso con intención.`
      });
    });
  });

  function randomIndex(max) {
    if (!window.crypto || !window.crypto.getRandomValues) return Math.floor(Math.random() * max);
    const range = 0x100000000;
    const limit = range - (range % max);
    const value = new Uint32Array(1);
    do {
      window.crypto.getRandomValues(value);
    } while (value[0] >= limit);
    return value[0] % max;
  }

  function drawCards() {
    const shuffled = deck.slice();
    for (let index = shuffled.length - 1; index > 0; index -= 1) {
      const swapIndex = randomIndex(index + 1);
      [shuffled[index], shuffled[swapIndex]] = [shuffled[swapIndex], shuffled[index]];
    }
    return shuffled.slice(0, 5);
  }

  function renderReading() {
    const results = document.getElementById("online-tarot-results");
    if (!results) return;
    const fragment = document.createDocumentFragment();

    drawCards().forEach((card, index) => {
      const article = document.createElement("article");
      article.className = "online-tarot-card";
      const position = document.createElement("span");
      position.className = "online-tarot-position";
      position.textContent = `${index + 1}. ${positions[index]}`;
      const image = document.createElement("div");
      image.className = "online-tarot-image";
      image.setAttribute("role", "img");
      image.setAttribute("aria-label", `Ilustración de ${card.name}`);
      image.dataset.spriteIndex = card.spriteIndex;
      const title = document.createElement("h3");
      title.className = "online-tarot-name";
      title.textContent = card.name;
      const meaning = document.createElement("p");
      meaning.className = "online-tarot-meaning";
      meaning.textContent = card.meaning;
      article.append(position, image, title, meaning);
      fragment.appendChild(article);
    });

    results.replaceChildren(fragment);
    alignSpriteImages();
  }

  function revealDailyReading() {
    const drawButton = document.getElementById("online-tarot-draw");
    const progress = document.getElementById("online-tarot-progress");
    const progressTrack = progress && progress.querySelector('[role="progressbar"]');
    const progressValue = document.getElementById("online-tarot-progress-value");
    const progressFill = document.getElementById("online-tarot-progress-fill");
    const results = document.getElementById("online-tarot-results");
    if (!drawButton || !progress || !progressTrack || !progressValue || !progressFill || drawButton.disabled) return;

    drawButton.disabled = true;
    progress.hidden = false;
    if (results) results.replaceChildren();
    let value = 0;
    progressValue.textContent = "0%";
    progressTrack.setAttribute("aria-valuenow", "0");
    progressFill.style.width = "0%";

    const timer = window.setInterval(() => {
      value = Math.min(value + 4, 100);
      progressValue.textContent = `${value}%`;
      progressTrack.setAttribute("aria-valuenow", String(value));
      progressFill.style.width = `${value}%`;
      if (value < 100) return;

      window.clearInterval(timer);
      renderReading();
      drawButton.hidden = true;
      window.setTimeout(() => {
        progress.hidden = true;
      }, 450);
    }, 50);
  }

  function alignSpriteImages() {
    document.querySelectorAll(".online-tarot-image").forEach((image) => {
      const spriteIndex = Number(image.dataset.spriteIndex);
      const column = spriteIndex % 13;
      const row = Math.floor(spriteIndex / 13);
      const scale = image.getBoundingClientRect().width / 112;
      const left = 6 + column * 121.6;
      const top = 311 + row * 214;
      image.style.backgroundImage = 'url("arcanes.webp")';
      image.style.backgroundSize = `${1588 * scale}px ${1588 * scale}px`;
      image.style.backgroundPosition = `${-left * scale}px ${-top * scale}px`;
    });
  }

  const drawButton = document.getElementById("online-tarot-draw");
  if (drawButton) drawButton.addEventListener("click", revealDailyReading);
  window.addEventListener("resize", alignSpriteImages);
})();