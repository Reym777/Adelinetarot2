"""Detailed report generator (the "IA" that writes Adelinemagica's brief).

Given a computed natal chart and tarot spread, it composes a structured,
personalised report in Spanish. The text is assembled deterministically from a
rich set of astrological correspondences so the same birth data always yields
the same brief â€” ready for Adelinemagica to read before the live video session.

To plug a real LLM later, replace :func:`build_report` with an API call; the
chart payload it receives is already model-ready.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from .astrology import SIGNS

# Element-level guidance used to colour the synthesis.
_ELEMENT_VOICE = {
    "Fuego": "necesita movimiento, propÃ³sito y una causa que encienda su entusiasmo",
    "Tierra": "busca seguridad, resultados tangibles y un ritmo sostenible",
    "Aire": "se nutre de ideas, conversaciÃ³n y libertad mental",
    "Agua": "se guÃ­a por la emociÃ³n, los vÃ­nculos profundos y la intuiciÃ³n",
}

_MODALITY_VOICE = {
    "Cardinal": "inicia, abre caminos y prefiere tomar la delantera",
    "Fijo": "consolida, persevera y sostiene lo que construye",
    "Mutable": "se adapta, conecta puntas y fluye con el cambio",
}

_MOON_NEED = {
    "Aries": "independencia emocional y respuestas rÃ¡pidas",
    "Tauro": "calma, contacto fÃ­sico y estabilidad",
    "GÃ©minis": "estÃ­mulo mental y conversaciÃ³n",
    "CÃ¡ncer": "pertenencia, hogar y cuidado mutuo",
    "Leo": "reconocimiento sincero y calidez",
    "Virgo": "orden, utilidad y sentirse de ayuda",
    "Libra": "armonÃ­a, belleza y compaÃ±Ã­a",
    "Escorpio": "intimidad verdadera y confianza absoluta",
    "Sagitario": "espacio, sentido y horizontes amplios",
    "Capricornio": "logro, respeto y un propÃ³sito claro",
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
        f"La Luna en {moon['sign']} {moon['symbol']} (â‰ˆ{moon['degree']}Â°) describe su "
        f"mundo emocional: para sentirse en paz necesita {need}. AquÃ­ viven sus "
        f"reacciones instintivas y aquello que la reconforta."
    )


def _ascendant_line(asc: Optional[Dict[str, object]], time_known: bool) -> str:
    if not asc or not time_known:
        return (
            "El Ascendente no se pudo precisar porque falta la hora exacta de "
            "nacimiento; al confirmarla en la sesiÃ³n, la lectura del estilo "
            "personal y la primera impresiÃ³n se afinarÃ¡ por completo."
        )
    return (
        f"El Ascendente en {asc['sign']} {asc['symbol']} pinta su carta de "
        f"presentaciÃ³n: la forma en que aborda la vida y cÃ³mo lo percibe el mundo "
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
        f"El elemento dominante en su carta es {dominant}: en el dÃ­a a dÃ­a "
        f"{_ELEMENT_VOICE[dominant]}. Tenerlo presente ayuda a hablarle en su "
        f"propio idioma emocional durante la consulta."
    )


def _tarot_block(tarot: List[Dict[str, object]]) -> List[str]:
    lines = []
    for c in tarot:
        lines.append(
            f"â€¢ {c['position']} â€” {c['name']} ({c['orientation']}): {c['meaning']}."
        )
    return lines


def _tarot_synthesis(tarot: List[Dict[str, object]]) -> str:
    keys = ", ".join(str(c["keyword"]) for c in tarot)
    closing = tarot[-1]
    return (
        f"El hilo de la tirada ({keys}) apunta a un camino de corto plazo donde "
        f"lo mÃ¡s importante es {closing['meaning']}. Es la imagen que conviene "
        f"devolverle con cariÃ±o y claridad al cierre de la sesiÃ³n."
    )


def build_report(consultant_name: str, birth: date, chart: Dict[str, object]) -> str:
    """Assemble the full Spanish brief for Adelinemagica."""
    sun = chart["sun"]  # type: ignore[index]
    moon = chart["moon"]  # type: ignore[index]
    asc = chart.get("ascendant")  # type: ignore[union-attr]

    parts: List[str] = []
    parts.append(f"INFORME ASTROLÃ“GICO Y DE TAROT â€” {consultant_name}")
    parts.append(
        f"Nacimiento: {birth.strftime('%d/%m/%Y')} Â· Lugar: {chart['birth_place']}."
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
        parts.append(f"â€¢ {name} en {pos['sign']} {pos['symbol']} (â‰ˆ{pos['degree']}Â°)")
    parts.append("")
    parts.append("3) LECTURA DE TAROT â€” VISIÃ“N A CORTO PLAZO")
    parts.extend(_tarot_block(chart["tarot"]))  # type: ignore[arg-type]
    parts.append("")
    parts.append(_tarot_synthesis(chart["tarot"]))  # type: ignore[arg-type]
    parts.append("")
    parts.append("4) GUÃA PARA LA SESIÃ“N")
    parts.append(
        "Comienza validando su mundo emocional (Luna), conecta su propÃ³sito "
        "(Sol) con la pregunta que traiga, y usa la tirada para ofrecer un "
        "paso concreto y esperanzador para las prÃ³ximas semanas."
    )
    parts.append(
        "Nota: las posiciones son aproximaciones simbÃ³licas pensadas para la "
        "consulta; la hora exacta de nacimiento permite afinar Ascendente y casas."
    )
    return "\n".join(parts)

