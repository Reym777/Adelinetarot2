"""Astrology + tarot engine.

Pure, deterministic, dependency-free computations:

* Natal chart — Sun sign (tropical calendar zodiac), Moon longitude (full
  Meeus Ch.47 lunar series) and the planets from Keplerian heliocentric →
  geocentric positions, plus an approximate rising sign (Ascendant) derived
  from the birth time. No birth coordinates are collected, so the Ascendant
  stays approximate and is labelled as such in the generated report.
* Tarot — a reproducible three-card draw (past / present / near future) of the
  22 Major Arcana, seeded by the consultant's name and birth date so the same
  person always receives the same spread.

No third-party ephemeris is required, which keeps the backend lightweight and
fully offline.
"""
from __future__ import annotations

import hashlib
import math
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
# Accurate ephemeris — Meeus Ch.47 Moon + Keplerian planets (deterministic)
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


# Keplerian orbital elements (J2000): L0/dL mean longitude, a semi-major axis,
# e0/de eccentricity, om longitude of perihelion. T = Julian centuries / J2000.
_EL_EARTH = {"L0": 100.4664825, "dL": 36000.7698, "a": 1.0,
             "e0": 0.01671, "de": -0.00004, "om": 102.9373}
_EL_PLANETS: Dict[str, Dict[str, float]] = {
    "Mercurio": {"L0": 252.2507519, "dL": 149472.6742, "a": 0.38710,
                 "e0": 0.20563, "de": 0.000020, "om": 77.4561},
    "Venus":    {"L0": 181.9798085, "dL": 58517.8153, "a": 0.72333,
                 "e0": 0.00677, "de": -0.000050, "om": 131.5637},
    "Marte":    {"L0": 355.4332750, "dL": 19140.2993, "a": 1.52366,
                 "e0": 0.09341, "de": 0.000090, "om": 336.0602},
    "Júpiter":  {"L0": 34.3514816, "dL": 3034.9057, "a": 5.20336,
                 "e0": 0.04839, "de": -0.000130, "om": 14.3320},
    "Saturno":  {"L0": 50.0774443, "dL": 1221.5515, "a": 9.53707,
                 "e0": 0.05415, "de": -0.000500, "om": 93.0572},
}

# Meeus Ch.47 periodic terms: (D, Msun, M', F, coefficient in 1e-6 deg).
_MOON_LON_TERMS = [
    (0, 0, 1, 0, 6288774), (2, 0, -1, 0, 1274027), (2, 0, 0, 0, 658314),
    (0, 0, 2, 0, 213618), (0, 1, 0, 0, -185116), (0, 0, 0, 2, -114332),
    (2, 0, -2, 0, 58793), (2, -1, -1, 0, 57066), (2, 0, 1, 0, 53322),
    (2, -1, 0, 0, 45758), (0, 1, -1, 0, -40923), (1, 0, 0, 0, -34720),
    (0, 1, 1, 0, -30383), (2, 0, 0, -2, 15327), (0, 0, 1, 2, -12528),
    (0, 0, 1, -2, 10980), (4, 0, -1, 0, 10675), (0, 0, 3, 0, 10034),
    (4, 0, -2, 0, 8548), (2, 1, -1, 0, -7888), (2, 1, 0, 0, -6766),
    (1, 0, -1, 0, -5163), (1, 1, 0, 0, 4987), (2, -1, 1, 0, 4036),
    (2, 0, 2, 0, 3994), (4, 0, 0, 0, 3861), (2, 0, -3, 0, 3665),
    (0, 1, -2, 0, -2689), (2, 0, -1, 2, -2602), (2, -1, -2, 0, 2390),
    (1, 0, 1, 0, -2348), (2, -2, 0, 0, 2236), (0, 1, 2, 0, -2120),
    (0, 2, 0, 0, -2069), (2, -2, -1, 0, 2048), (2, 0, 1, -2, -1773),
    (2, 0, 0, 2, -1595), (4, -1, -1, 0, 1215), (0, 0, 2, 2, -1110),
    (3, 0, -1, 0, -892), (2, 1, 1, 0, -810), (4, -1, -2, 0, 759),
    (0, 2, -1, 0, -713), (2, 2, -1, 0, -700), (2, 1, -2, 0, 691),
    (2, -1, 0, -2, 596), (4, 0, 1, 0, 549), (0, 0, 4, 0, 537),
    (4, -1, 0, 0, 520), (1, 0, -2, 0, -487), (2, 1, 0, -2, -399),
    (0, 0, 2, -2, -381), (1, 1, 1, 0, 351), (3, 0, -2, 0, -340),
    (4, 0, -3, 0, 330), (2, -1, 2, 0, 327), (0, 2, 1, 0, -323),
    (1, 1, -1, 0, 299), (2, 0, 3, 0, 294),
]


def _rev_deg(x: float) -> float:
    return x % 360.0


def _helio_xy(el: Dict[str, float], julian_century: float) -> tuple:
    """Heliocentric ecliptic (x, y) of a body from its Keplerian elements."""
    t = julian_century
    longitude = _rev_deg(el["L0"] + el["dL"] * t)
    e = el["e0"] + el["de"] * t
    om = el["om"]
    mean_anom = _rev_deg(longitude - om)
    mr = math.radians(mean_anom)
    center = (
        (2 * e - 0.25 * e ** 3) * math.sin(mr)
        + 1.25 * e * e * math.sin(2 * mr)
        + (13.0 / 12.0) * e ** 3 * math.sin(3 * mr)
    )
    true_lon = _rev_deg(mean_anom + math.degrees(center) + om)
    radius = el["a"] * (1 - e * e) / (
        1 + e * math.cos(math.radians(_rev_deg(mean_anom + math.degrees(center))))
    )
    return (radius * math.cos(math.radians(true_lon)),
            radius * math.sin(math.radians(true_lon)))


def _moon_longitude(julian_century: float) -> float:
    """Geocentric ecliptic longitude of the Moon (Meeus Ch.47, ~0.01°)."""
    t = julian_century
    lp = _rev_deg(218.3164477 + 481267.88123421 * t - 0.0015786 * t * t
                  + t ** 3 / 538841 - t ** 4 / 65194000)
    d = _rev_deg(297.8501921 + 445267.1114034 * t - 0.0018819 * t * t
                 + t ** 3 / 545868 - t ** 4 / 113065000)
    m_sun = _rev_deg(357.5291092 + 35999.0502909 * t - 0.0001536 * t * t
                     + t ** 3 / 24490000)
    mp = _rev_deg(134.9633964 + 477198.8675055 * t + 0.0087414 * t * t
                  + t ** 3 / 69699 - t ** 4 / 14712000)
    f = _rev_deg(93.2720950 + 483202.0175233 * t - 0.0036539 * t * t
                 - t ** 3 / 3526000 + t ** 4 / 863310000)
    ecc = 1 - 0.002516 * t - 0.0000074 * t * t
    a1 = _rev_deg(119.75 + 131.849 * t)
    a2 = _rev_deg(53.09 + 479264.290 * t)
    total = 0.0
    for cd, cm, cmp, cf, coef in _MOON_LON_TERMS:
        amp = float(coef)
        eccentric = abs(cm)
        if eccentric == 1:
            amp *= ecc
        elif eccentric == 2:
            amp *= ecc * ecc
        total += amp * math.sin(math.radians(cd * d + cm * m_sun + cmp * mp + cf * f))
    total += (3958 * math.sin(math.radians(a1))
              + 1962 * math.sin(math.radians(lp - f))
              + 318 * math.sin(math.radians(a2)))
    return _rev_deg(lp + total / 1000000.0)


def _planet_longitude(name: str, julian_century: float) -> float:
    """Geocentric ecliptic longitude of a planet (heliocentric → geocentric)."""
    ex, ey = _helio_xy(_EL_EARTH, julian_century)
    px, py = _helio_xy(_EL_PLANETS[name], julian_century)
    return _rev_deg(math.degrees(math.atan2(py - ey, px - ex)))


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
    julian_century = (_julian_day(birth_date, clock) - 2451545.0) / 36525.0

    planets: Dict[str, Dict[str, object]] = {
        "Luna": _sign_from_longitude(_moon_longitude(julian_century))
    }
    for name in ("Mercurio", "Venus", "Marte", "Júpiter", "Saturno"):
        planets[name] = _sign_from_longitude(_planet_longitude(name, julian_century))

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
