"""Google Analytics Measurement Protocol client.

The API secret is read from the backend environment only. The frontend can send
validated events to the local API, and this module relays them to Google without
ever exposing ``api_secret`` in HTML or JavaScript.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .config import settings

_TIMEOUT = 10
_API_BASE = "https://www.google-analytics.com"


class AnalyticsError(Exception):
    """Raised when a Measurement Protocol request cannot be completed."""


def _endpoint() -> str:
    path = "/debug/mp/collect" if settings.ga_measurement_protocol_debug else "/mp/collect"
    query = urllib.parse.urlencode(
        {
            "measurement_id": settings.ga_measurement_id.strip(),
            "api_secret": settings.ga_api_secret.strip(),
        }
    )
    return f"{_API_BASE}{path}?{query}"


def collect_events(
    *,
    client_id: str,
    events: List[Dict[str, Any]],
    user_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """Send validated events to Google Analytics Measurement Protocol."""
    if not settings.ga_measurement_protocol_enabled:
        raise AnalyticsError("Measurement Protocol no configurado")

    payload: Dict[str, Any] = {
        "client_id": client_id,
        "non_personalized_ads": False,
        "events": events[:25],
    }
    if user_id:
        payload["user_id"] = user_id

    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        _endpoint(),
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Adelinemagica/analytics",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8", "replace")
            if settings.ga_measurement_protocol_debug and raw:
                parsed = json.loads(raw)
                messages = parsed.get("validationMessages") or []
                if messages:
                    return False, "Google Analytics rechazó el evento"
            return 200 <= resp.status < 300, "Evento enviado."
    except urllib.error.HTTPError as exc:
        return False, f"Google Analytics HTTP {exc.code}"
    except urllib.error.URLError as exc:
        raise AnalyticsError(f"Google Analytics no accesible: {exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise AnalyticsError(f"Google Analytics sin respuesta: {exc}") from exc
