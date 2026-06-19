"""Astrology + tarot engine.

Pure, deterministic, dependency-free computations:

* Natal chart — Sun sign (tropical calendar zodiac), Moon sign and the inner
  planets from mean ecliptic longitudes, plus an approximate rising sign
  (Ascendant) from the birth time. These are *approximations* suitable for a
  consultation product; they are labelled as such in the generated report.
* Tarot — a reproducible three-card draw (past / present / near future) of the
  22 Major Arcana, seeded by the consultant's name and birth date so the same
  person always receives the same spread.

No third-party ephemeris is required, which keeps the backend lightweight and
fully offline.
"""
from __future__ import annotations

import hashlib
import random
from datetime import date, time
from typing import Dict, List, Optional

# --------------------------------------------------------------------------- #
# Zodiac data (Spanish)
# --------------------------------------------------------------------------- #
SIGNS: List[Dict[str, str]] = [
    {"name": "Aries", "symbol": "♈", "element": "Fuego", "modality": "Cardinal",
     "ruler": "Marte", "trait": "iniciativa, coraje y empuje pionero"},
    {"name": "Tauro", "symbol": "♉", "element": "Tierra", "modality": "Fijo",
     "ruler": "Venus", "trait": "constancia, sensualidad y arraigo"},
    {"name": "Géminis", "symbol": "♊", "element": "Aire", "modality": "Mutable",
     "ruler": "Mercurio", "trait": "curiosidad, palabra y versatilidad"},
    {"name": "Cáncer", "symbol": "♋", "element": "Agua", "modality": "Cardinal",
     "ruler": "la Luna", "trait": "sensibilidad, memoria y protección"},
    {"name": "Leo", "symbol": "♌", "element": "Fuego", "modality": "Fijo",
     "ruler": "el Sol", "trait": "creatividad, generosidad y presencia"},
    {"name": "Virgo", "symbol": "♍", "element": "Tierra", "modality": "Mutable",
     "ruler": "Mercurio", "trait": "análisis, servicio y precisión"},
    {"name": "Libra", "symbol": "♎", "element": "Aire", "modality": "Cardinal",
     "ruler": "Venus", "trait": "equilibrio, vínculo y estética"},
    {"name": "Escorpio", "symbol": "♏", "element": "Agua", "modality": "Fijo",
     "ruler": "Plutón", "trait": "intensidad, transformación y verdad"},
    {"name": "Sagitario", "symbol": "♐", "element": "Fuego", "modality": "Mutable",
     "ruler": "Júpiter", "trait": "expansión, sentido y aventura"},
    {"name": "Capricornio", "symbol": "♑", "element": "Tierra", "modality": "Cardinal",
     "ruler": "Saturno", "trait": "ambición, estructura y madurez"},
    {"name": "Acuario", "symbol": "♒", "element": "Aire", "modality": "Fijo",
     "ruler": "Urano", "trait": "originalidad, visión y comunidad"},
    {"name": "Piscis", "symbol": "♓", "element": "Agua", "modality": "Mutable",
     "ruler": "Neptuno", "trait": "compasión, intuición y arte"},
]

# Inclusive (month, day) start of each sign, tropical calendar zodiac.
_SUN_RANGES = [
    (3, 21, 0), (4, 20, 1), (5, 21, 2), (6, 21, 3), (7, 23, 4), (8, 23, 5),
    (9, 23, 6), (10, 23, 7), (11, 22, 8), (12, 22, 9), (1, 20, 10), (2, 19, 11),
]


def sun_sign_index(d: date) -> int:
    """Accurate tropical Sun sign index (0=Aries … 11=Piscis)."""
    md = (d.month, d.day)
    boundaries = sorted(
        (((m, dd), i) for (m, dd, i) in _SUN_RANGES), key=lambda x: x[0]
    )
    chosen = 9  # Capricornio default for early-January / late-December
    for (m, dd), i in boundaries:
        if md >= (m, dd):
            chosen = i
    return chosen


# --------------------------------------------------------------------------- #
# Mean-longitude ephemeris (approximate, deterministic)
# --------------------------------------------------------------------------- #
def _julian_day(d: date, t: time) -> float:
    """Julian Day for a civil date/time (treated as the birth local clock)."""
    year, month, day = d.year, d.month, d.day
    if month <= 2:
        year -= 1
        month += 12
    a = year // 100
    b = 2 - a + a // 4
    jd = (
        int(365.25 * (year + 4716))
        + int(30.6001 * (month + 1))
        + day + b - 1524.5
    )
    jd += (t.hour + t.minute / 60.0 + t.second / 3600.0) / 24.0
    return jd


# longitude(deg) = base + rate * d, with d = days since J2000.0
_MEAN_ELEMENTS = {
    "Luna": (218.316, 13.176396),
    "Mercurio": (252.251, 4.092317),
    "Venus": (181.979, 1.602136),
    "Marte": (355.433, 0.524039),
    "Júpiter": (34.351, 0.083091),
    "Saturno": (50.078, 0.033494),
}


def _mean_longitude(base: float, rate: float, days_since_j2000: float) -> float:
    return (base + rate * days_since_j2000) % 360.0


def _sign_from_longitude(longitude: float) -> Dict[str, object]:
    idx = int(longitude // 30) % 12
    deg = longitude % 30
    return {
        "sign": SIGNS[idx]["name"],
        "symbol": SIGNS[idx]["symbol"],
        "index": idx,
        "degree": round(deg, 1),
    }


def ascendant_index(sun_idx: int, t: Optional[time]) -> Optional[int]:
    """Approximate rising sign: the Sun's sign rises near 6:00 and a new sign
    rises roughly every two hours. Returns ``None`` if the birth time is
    unknown."""
    if t is None:
        return None
    minutes = t.hour * 60 + t.minute
    offset = ((minutes - 360) // 120) % 12  # 360 min = 06:00
    return (sun_idx + int(offset)) % 12


# --------------------------------------------------------------------------- #
# Tarot — 22 Major Arcana (Spanish)
# --------------------------------------------------------------------------- #
MAJOR_ARCANA: List[Dict[str, object]] = [
    {"n": 0, "name": "El Loco", "key": "comienzos",
     "up": "un salto de fe, libertad y nuevos comienzos llenos de potencial",
     "rev": "imprudencia o miedo a lanzarse; conviene mirar antes de saltar"},
    {"n": 1, "name": "El Mago", "key": "manifestación",
     "up": "tienes las herramientas para crear tu realidad; voluntad y talento",
     "rev": "energía dispersa o promesas vacías; recupera el foco"},
    {"n": 2, "name": "La Sacerdotisa", "key": "intuición",
     "up": "escucha tu voz interior; saber oculto que pronto se revela",
     "rev": "desconexión de la intuición; secretos que pesan"},
    {"n": 3, "name": "La Emperatriz", "key": "abundancia",
     "up": "fertilidad, cuidado y abundancia creativa que florece",
     "rev": "bloqueo creativo o exceso de control; vuelve a nutrirte"},
    {"n": 4, "name": "El Emperador", "key": "estructura",
     "up": "orden, autoridad y bases sólidas para construir",
     "rev": "rigidez o falta de límites; revisa tu estructura"},
    {"n": 5, "name": "El Hierofante", "key": "guía",
     "up": "tradición, aprendizaje y un mentor que ilumina el camino",
     "rev": "rebeldía necesaria; cuestionar dogmas heredados"},
    {"n": 6, "name": "Los Enamorados", "key": "elección",
     "up": "una unión significativa y una decisión del corazón alineada",
     "rev": "desequilibrio o duda en un vínculo; clarifica valores"},
    {"n": 7, "name": "El Carro", "key": "voluntad",
     "up": "avance decidido; vences obstáculos con determinación",
     "rev": "fuerzas en conflicto; falta de rumbo claro"},
    {"n": 8, "name": "La Fuerza", "key": "coraje",
     "up": "dominio sereno; el coraje suave que doma toda dificultad",
     "rev": "dudas internas; recupera la confianza con paciencia"},
    {"n": 9, "name": "El Ermitaño", "key": "introspección",
     "up": "un tiempo de retiro y sabiduría que alumbra tu verdad",
     "rev": "aislamiento excesivo; es momento de volver al mundo"},
    {"n": 10, "name": "La Rueda de la Fortuna", "key": "ciclos",
     "up": "un giro favorable del destino; el ciclo cambia a tu favor",
     "rev": "resistencia al cambio; suelta lo que ya cumplió su ciclo"},
    {"n": 11, "name": "La Justicia", "key": "equilibrio",
     "up": "verdad, equilibrio y consecuencias justas de tus actos",
     "rev": "desequilibrio o cuentas pendientes por saldar"},
    {"n": 12, "name": "El Colgado", "key": "pausa",
     "up": "una pausa fértil; ver el mundo desde otra perspectiva",
     "rev": "estancamiento o sacrificio inútil; suelta para avanzar"},
    {"n": 13, "name": "La Muerte", "key": "transformación",
     "up": "un final necesario que abre una transformación profunda",
     "rev": "resistencia a un cierre inevitable; el miedo a soltar"},
    {"n": 14, "name": "La Templanza", "key": "armonía",
     "up": "equilibrio, paciencia y la alquimia de los opuestos",
     "rev": "excesos o impaciencia; busca el punto medio"},
    {"n": 15, "name": "El Diablo", "key": "ataduras",
     "up": "reconocer apegos y deseos que encadenan para liberarte",
     "rev": "rompes una cadena; recuperas tu poder personal"},
    {"n": 16, "name": "La Torre", "key": "revelación",
     "up": "una sacudida que derrumba lo falso para revelar la verdad",
     "rev": "evitar un cambio inevitable prolonga la tensión"},
    {"n": 17, "name": "La Estrella", "key": "esperanza",
     "up": "esperanza, inspiración y sanación; el cielo te guía",
     "rev": "desánimo pasajero; reconecta con tu fe"},
    {"n": 18, "name": "La Luna", "key": "misterio",
     "up": "intuición profunda; navega la incertidumbre con tu instinto",
     "rev": "se disipa una confusión; la verdad emerge"},
    {"n": 19, "name": "El Sol", "key": "plenitud",
     "up": "éxito, vitalidad y claridad radiante; un sí del universo",
     "rev": "una alegría que tarda un poco; el brillo regresa"},
    {"n": 20, "name": "El Juicio", "key": "renacer",
     "up": "un despertar, un llamado y la oportunidad de renacer",
     "rev": "autocrítica o miedo al cambio; perdónate y avanza"},
    {"n": 21, "name": "El Mundo", "key": "realización",
     "up": "culminación, plenitud y un ciclo que se completa con éxito",
     "rev": "un cierre casi logrado; falta un último paso"},
]

_SPREAD_POSITIONS = ["Pasado", "Presente", "Futuro próximo"]


def _seed(full_name: str, birth: date) -> str:
    raw = f"{full_name.strip().lower()}|{birth.isoformat()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def draw_tarot(full_name: str, birth: date) -> List[Dict[str, object]]:
    """Reproducible three-card spread seeded by the consultant's identity."""
    rng = random.Random(_seed(full_name, birth))
    cards = rng.sample(MAJOR_ARCANA, 3)
    spread: List[Dict[str, object]] = []
    for position, card in zip(_SPREAD_POSITIONS, cards):
        upright = rng.random() > 0.32
        spread.append({
            "position": position,
            "number": card["n"],
            "name": card["name"],
            "keyword": card["key"],
            "orientation": "Al derecho" if upright else "Invertida",
            "meaning": card["up"] if upright else card["rev"],
        })
    return spread


# --------------------------------------------------------------------------- #
# Natal chart assembly
# --------------------------------------------------------------------------- #
def compute_chart(
    full_name: str,
    birth_date: date,
    birth_time: Optional[time],
    birth_place: str,
) -> Dict[str, object]:
    """Build the full natal-chart + tarot payload for a consultant."""
    sun_idx = sun_sign_index(birth_date)
    sun = SIGNS[sun_idx]

    clock = birth_time or time(12, 0)
    days = _julian_day(birth_date, clock) - 2451545.0

    planets: Dict[str, Dict[str, object]] = {}
    for name, (base, rate) in _MEAN_ELEMENTS.items():
        planets[name] = _sign_from_longitude(_mean_longitude(base, rate, days))

    asc_idx = ascendant_index(sun_idx, birth_time)
    ascendant = (
        {
            "sign": SIGNS[asc_idx]["name"],
            "symbol": SIGNS[asc_idx]["symbol"],
            "index": asc_idx,
        }
        if asc_idx is not None
        else None
    )

    return {
        "sun": {
            "sign": sun["name"], "symbol": sun["symbol"], "index": sun_idx,
            "element": sun["element"], "modality": sun["modality"],
            "ruler": sun["ruler"], "trait": sun["trait"],
        },
        "moon": planets["Luna"],
        "ascendant": ascendant,
        "planets": planets,
        "birth_place": birth_place,
        "birth_time_known": birth_time is not None,
        "tarot": draw_tarot(full_name, birth_date),
    }
