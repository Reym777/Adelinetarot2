"""Minimal, dependency-free PayPal REST (Orders v2) client.

Uses only the Python standard library (``urllib``) so no extra package has to
be installed on the host. It powers the *advanced* checkout: the order is
created and captured server-side, so the amount is authoritative and never
trusted from the browser (this also backs the Apple Pay / Google Pay buttons,
which require a server-confirmed order).

Security notes:
* Credentials come from the environment only (``ADELINE_PAYPAL_CLIENT_ID`` /
  ``ADELINE_PAYPAL_SECRET``); the secret is never sent to the client.
* The OAuth token is cached in memory until shortly before it expires.
* Order ids are validated against a strict pattern before being interpolated
  into a request URL (defence against request/URL injection).
* Every network error is converted into :class:`PayPalError`; callers turn that
  into a clean HTTP response instead of leaking internals.
"""
from __future__ import annotations

import base64
import json
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

from .config import settings

# PayPal order ids are short upper-case alphanumeric tokens.
ORDER_ID_RE = re.compile(r"^[A-Z0-9]{6,40}$")

_TIMEOUT = 20
_token_lock = threading.Lock()
_token_cache: Dict[str, float] = {"expires": 0.0}
_token_value: Dict[str, str] = {"value": ""}


class PayPalError(Exception):
    """Raised when a PayPal API call cannot be completed successfully."""


def _request(
    method: str,
    url: str,
    headers: Dict[str, str],
    data: Optional[bytes] = None,
) -> Tuple[int, Dict[str, Any]]:
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
            body = json.loads(raw) if raw else {}
            return resp.status, body
    except urllib.error.HTTPError as exc:  # 4xx/5xx with a body
        raw = exc.read().decode("utf-8", "replace")
        try:
            body = json.loads(raw)
        except ValueError:
            body = {"raw": raw[:500]}
        return exc.code, body
    except urllib.error.URLError as exc:
        raise PayPalError(f"PayPal no accesible: {exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise PayPalError(f"PayPal sin respuesta: {exc}") from exc


def get_access_token() -> str:
    """Return a cached OAuth2 access token, fetching a new one when needed."""
    if not settings.paypal_server_enabled:
        raise PayPalError("PayPal no configurado (faltan client id o secret)")

    now = time.time()
    with _token_lock:
        if _token_value["value"] and _token_cache["expires"] - 60 > now:
            return _token_value["value"]

    creds = f"{settings.paypal_client_id}:{settings.paypal_secret}".encode("utf-8")
    auth = base64.b64encode(creds).decode("ascii")
    status, body = _request(
        "POST",
        f"{settings.paypal_api_base}/v1/oauth2/token",
        {
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        b"grant_type=client_credentials",
    )
    token = body.get("access_token")
    if status != 200 or not token:
        raise PayPalError("Autenticación con PayPal fallida")

    with _token_lock:
        _token_value["value"] = token
        _token_cache["expires"] = now + float(body.get("expires_in", 3000))
    return token


def create_order(
    amount: float,
    currency: str,
    reference: str,
    description: str,
) -> Dict[str, Any]:
    """Create a CAPTURE-intent order with a server-authoritative amount."""
    token = get_access_token()
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "reference_id": reference[:127],
                "description": description[:127],
                "amount": {"currency_code": currency, "value": f"{float(amount):.2f}"},
            }
        ],
        "application_context": {
            "brand_name": settings.business_name[:127],
            "shipping_preference": "NO_SHIPPING",
            "user_action": "PAY_NOW",
        },
    }
    status, body = _request(
        "POST",
        f"{settings.paypal_api_base}/v2/checkout/orders",
        {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json.dumps(payload).encode("utf-8"),
    )
    if status not in (200, 201) or not body.get("id"):
        raise PayPalError("No se pudo crear la orden de PayPal")
    return body


def capture_order(order_id: str) -> Dict[str, Any]:
    """Capture a previously created order. ``order_id`` is validated first."""
    if not ORDER_ID_RE.match(order_id or ""):
        raise PayPalError("Identificador de orden no válido")
    token = get_access_token()
    status, body = _request(
        "POST",
        f"{settings.paypal_api_base}/v2/checkout/orders/{order_id}/capture",
        {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        b"{}",
    )
    if status not in (200, 201):
        raise PayPalError("No se pudo capturar el pago de PayPal")
    return body


def extract_capture(body: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[float]]:
    """Return (status, currency, amount) from a capture response, defensively."""
    overall = str(body.get("status", ""))
    try:
        cap = body["purchase_units"][0]["payments"]["captures"][0]
        amount = cap.get("amount", {})
        return (
            str(cap.get("status", overall)),
            amount.get("currency_code"),
            float(amount["value"]) if amount.get("value") is not None else None,
        )
    except (KeyError, IndexError, TypeError, ValueError):
        return overall, None, None
