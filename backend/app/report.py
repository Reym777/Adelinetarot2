"""Detailed report generator (the "IA" that writes AdelineTarot's brief).

Given a computed natal chart and tarot spread, it composes a structured,
personalised report in Spanish. The text is assembled deterministically from a
rich set of astrological correspondences so the same birth data always yields
the same brief — ready for AdelineTarot to read before the live video session.

To plug a real LLM later, replace :func:`build_report` with an API call; the
chart payload it receives is already model-ready.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from .astrology import SIGNS

# Element-level guidance used to colour the synthesis.
_ELEMENT_VOICE = {
    "Fuego": "necesita movimiento, propósito y una causa que encienda su entusiasmo",
    "Tierra": "busca seguridad, resultados tangibles y un ritmo sostenible",
    "Aire": "se nutre de ideas, conversación y libertad mental",
    "Agua": "se guía por la emoción, los vínculos profundos y la intuición",
}

_MODALITY_VOICE = {
    "Cardinal": "inicia, abre caminos y prefiere tomar la delantera",
    "Fijo": "consolida, persevera y sostiene lo que construye",
    "Mutable": "se adapta, conecta puntas y fluye con el cambio",
}

_MOON_NEED = {
    "Aries": "independencia emocional y respuestas rápidas",
    "Tauro": "calma, contacto físico y estabilidad",
    "Géminis": "estímulo mental y conversación",
    "Cáncer": "pertenencia, hogar y cuidado mutuo",
    "Leo": "reconocimiento sincero y calidez",
    "Virgo": "orden, utilidad y sentirse de ayuda",
    "Libra": "armonía, belleza y compañía",
    "Escorpio": "intimidad verdadera y confianza absoluta",
    "Sagitario": "espacio, sentido y horizontes amplios",
    "Capricornio": "logro, respeto y un propósito claro",
    "Acuario": "libertad, amistad y autenticidad",
    "Piscis": "ternura, arte y silencio compartido",
}


def _sign_idx(name: str) -> int:
    for i, s in enumerate(SIGNS):
        if s["name"] == name:
            return i
    return 0


def _luminary_line(sun: Dict[str, object]) -> str:
    return (
        f"Con el Sol en {sun['sign']} {sun['symbol']}, la esencia de esta "
        f"persona vibra con {sun['trait']}. Es un signo de {str(sun['element']).lower()} "
        f"y modalidad {str(sun['modality']).lower()}: {_MODALITY_VOICE[str(sun['modality'])]}. "
        f"Su regente, {sun['ruler']}, marca el tono profundo de su voluntad."
    )


def _moon_line(moon: Dict[str, object]) -> str:
    need = _MOON_NEED.get(str(moon["sign"]), "equilibrio y autenticidad")
    return (
        f"La Luna en {moon['sign']} {moon['symbol']} (≈{moon['degree']}°) describe su "
        f"mundo emocional: para sentirse en paz necesita {need}. Aquí viven sus "
        f"reacciones instintivas y aquello que la reconforta."
    )


def _ascendant_line(asc: Optional[Dict[str, object]], time_known: bool) -> str:
    if not asc or not time_known:
        return (
            "El Ascendente no se pudo precisar porque falta la hora exacta de "
            "nacimiento; al confirmarla en la sesión, la lectura del estilo "
            "personal y la primera impresión se afinará por completo."
        )
    return (
        f"El Ascendente en {asc['sign']} {asc['symbol']} pinta su carta de "
        f"presentación: la forma en que aborda la vida y cómo lo percibe el mundo "
        f"a primera vista. Es la puerta de entrada a toda la carta."
    )


def _element_balance(chart: Dict[str, object]) -> str:
    counts = {"Fuego": 0, "Tierra": 0, "Aire": 0, "Agua": 0}
    signs_in_play: List[str] = [str(chart["sun"]["sign"]), str(chart["moon"]["sign"])]
    if chart.get("ascendant"):
        signs_in_play.append(str(chart["ascendant"]["sign"]))
    for p in chart["planets"].values():  # type: ignore[union-attr]
        signs_in_play.append(str(p["sign"]))
    for name in signs_in_play:
        counts[SIGNS[_sign_idx(name)]["element"]] += 1
    dominant = max(counts, key=counts.get)
    return (
        f"El elemento dominante en su carta es {dominant}: en el día a día "
        f"{_ELEMENT_VOICE[dominant]}. Tenerlo presente ayuda a hablarle en su "
        f"propio idioma emocional durante la consulta."
    )


def _tarot_block(tarot: List[Dict[str, object]]) -> List[str]:
    lines = []
    for c in tarot:
        lines.append(
            f"• {c['position']} — {c['name']} ({c['orientation']}): {c['meaning']}."
        )
    return lines


def _tarot_synthesis(tarot: List[Dict[str, object]]) -> str:
    keys = ", ".join(str(c["keyword"]) for c in tarot)
    closing = tarot[-1]
    return (
        f"El hilo de la tirada ({keys}) apunta a un camino de corto plazo donde "
        f"lo más importante es {closing['meaning']}. Es la imagen que conviene "
        f"devolverle con cariño y claridad al cierre de la sesión."
    )


def build_report(consultant_name: str, birth: date, chart: Dict[str, object]) -> str:
    """Assemble the full Spanish brief for AdelineTarot."""
    sun = chart["sun"]  # type: ignore[index]
    moon = chart["moon"]  # type: ignore[index]
    asc = chart.get("ascendant")  # type: ignore[union-attr]

    parts: List[str] = []
    parts.append(f"INFORME ASTROLÓGICO Y DE TAROT — {consultant_name}")
    parts.append(
        f"Nacimiento: {birth.strftime('%d/%m/%Y')} · Lugar: {chart['birth_place']}."
    )
    parts.append("")
    parts.append("1) RETRATO ASTRAL")
    parts.append(_luminary_line(sun))  # type: ignore[arg-type]
    parts.append(_moon_line(moon))  # type: ignore[arg-type]
    parts.append(_ascendant_line(asc, bool(chart["birth_time_known"])))  # type: ignore[arg-type]
    parts.append(_element_balance(chart))
    parts.append("")
    parts.append("2) POSICIONES PLANETARIAS (aprox.)")
    for name, pos in chart["planets"].items():  # type: ignore[union-attr]
        if name == "Luna":
            continue
        parts.append(f"• {name} en {pos['sign']} {pos['symbol']} (≈{pos['degree']}°)")
    parts.append("")
    parts.append("3) LECTURA DE TAROT — VISIÓN A CORTO PLAZO")
    parts.extend(_tarot_block(chart["tarot"]))  # type: ignore[arg-type]
    parts.append("")
    parts.append(_tarot_synthesis(chart["tarot"]))  # type: ignore[arg-type]
    parts.append("")
    parts.append("4) GUÍA PARA LA SESIÓN")
    parts.append(
        "Comienza validando su mundo emocional (Luna), conecta su propósito "
        "(Sol) con la pregunta que traiga, y usa la tirada para ofrecer un "
        "paso concreto y esperanzador para las próximas semanas."
    )
    parts.append(
        "Nota: las posiciones son aproximaciones simbólicas pensadas para la "
        "consulta; la hora exacta de nacimiento permite afinar Ascendente y casas."
    )
    return "\n".join(parts)
