"""Minimal, dependency-free Stripe client (hosted Checkout).

Uses only the Python standard library (``urllib`` / ``hmac`` / ``hashlib``) so
no extra package has to be installed on the host. It powers the Stripe
"Pay by card / Apple Pay / Google Pay" button: a Checkout Session is created
server-side with an authoritative amount, the customer is redirected to
Stripe's hosted page, and the payment is verified server-side (on return and/or
via a signed webhook) before the booking advances.

Security notes:
* The secret key comes from the environment only and is never sent to the client.
* Amounts are always recomputed server-side (never trusted from the browser).
* Webhook payloads are verified with an HMAC-SHA256 signature (constant-time
  compare) and a 5-minute replay window.
* Session ids are validated by the request schema before use.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .config import settings

_API_BASE = "https://api.stripe.com"
_TIMEOUT = 20


class StripeError(Exception):
    """Raised when a Stripe API call or signature check cannot be completed."""


def _request(
    method: str,
    path: str,
    data: Optional[Dict[str, str]] = None,
) -> Tuple[int, Dict[str, Any]]:
    headers = {
        "Authorization": f"Bearer {settings.stripe_secret_key}",
        "Accept": "application/json",
    }
    body: Optional[bytes] = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(
        _API_BASE + path, data=body, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:  # 4xx/5xx with a JSON error body
        raw = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = {"error": {"message": raw[:300]}}
        return exc.code, parsed
    except urllib.error.URLError as exc:
        raise StripeError(f"Stripe no accesible: {exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise StripeError(f"Stripe sin respuesta: {exc}") from exc


def create_checkout_session(
    *,
    amount: float,
    currency: str,
    reference: str,
    email: str,
    description: str,
    success_url: str,
    cancel_url: str,
    booking_token: str = "",
    metadata: Optional[Dict[str, str]] = None,
    embedded: bool = False,
) -> Dict[str, Any]:
    """Create a hosted Checkout Session with a server-authoritative amount.

    Card payments enable Apple Pay and Google Pay automatically on Stripe's
    hosted page (Stripe also handles Apple Pay domain registration for Checkout).
    """
    if not settings.stripe_enabled:
        raise StripeError("Stripe no configurado")
    minor = int(round(float(amount) * 100))
    if minor <= 0:
        raise StripeError("Importe no válido")
    data = {
        "mode": "payment",
        "client_reference_id": reference[:200],
        "customer_email": email,
        "locale": "es",
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": currency.lower(),
        "line_items[0][price_data][unit_amount]": str(minor),
        "line_items[0][price_data][product_data][name]": description[:127],
    }
    if embedded:
        data["ui_mode"] = "embedded"
        data["return_url"] = success_url
    else:
        data["success_url"] = success_url
        data["cancel_url"] = cancel_url
    if booking_token:
        data["metadata[booking_token]"] = booking_token
    data["metadata[reference]"] = reference[:200]
    if metadata:
        for key, value in metadata.items():
            clean_key = str(key).strip()[:40]
            clean_val = str(value).strip()[:500]
            if clean_key and clean_val:
                data[f"metadata[{clean_key}]"] = clean_val
    status, body = _request("POST", "/v1/checkout/sessions", data)
    if status not in (200, 201) or not body.get("id"):
        message = (body.get("error") or {}).get(
            "message", "No se pudo iniciar el pago de Stripe"
        )
        raise StripeError(message)
    if not embedded and not body.get("url"):
        raise StripeError("Checkout URL no disponible")
    if embedded and not body.get("client_secret"):
        raise StripeError("Checkout embebido no disponible")
    return body


def retrieve_session(session_id: str) -> Dict[str, Any]:
    """Fetch a Checkout Session to verify its payment status server-side."""
    if not settings.stripe_enabled:
        raise StripeError("Stripe no configurado")
    safe = urllib.parse.quote(session_id, safe="")
    status, body = _request("GET", f"/v1/checkout/sessions/{safe}")
    if status != 200 or not body.get("id"):
        raise StripeError("No se pudo verificar la sesión de Stripe")
    return body


def _first_customer_by_email(email: str) -> Optional[Dict[str, Any]]:
    q = urllib.parse.urlencode({"email": email, "limit": "1"})
    status, body = _request("GET", f"/v1/customers?{q}")
    if status != 200:
        return None
    data = body.get("data") or []
    if data:
        return data[0]
    return None


def ensure_customer(*, email: str, name: str) -> str:
    """Return existing customer id by email, or create a new one."""
    existing = _first_customer_by_email(email)
    if existing and existing.get("id"):
        return str(existing["id"])

    payload = {
        "email": email,
        "name": name[:120],
    }
    status, body = _request("POST", "/v1/customers", payload)
    if status not in (200, 201) or not body.get("id"):
        message = (body.get("error") or {}).get("message", "No se pudo crear cliente")
        raise StripeError(message)
    return str(body["id"])


def create_and_send_invoice(
    *,
    customer_email: str,
    customer_name: str,
    description: str,
    amount: float,
    currency: str,
    due_days: int,
    metadata: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create an invoice item, invoice, finalize and send it to customer."""
    if not settings.stripe_enabled:
        raise StripeError("Stripe no configurado")
    minor = int(round(float(amount) * 100))
    if minor <= 0:
        raise StripeError("Importe no válido")

    customer_id = ensure_customer(email=customer_email, name=customer_name)
    item_data = {
        "customer": customer_id,
        "currency": currency.lower(),
        "amount": str(minor),
        "description": description[:200],
    }
    status_item, body_item = _request("POST", "/v1/invoiceitems", item_data)
    if status_item not in (200, 201) or not body_item.get("id"):
        message = (body_item.get("error") or {}).get("message", "No se pudo crear invoice item")
        raise StripeError(message)

    invoice_data = {
        "customer": customer_id,
        "collection_method": "send_invoice",
        "days_until_due": str(max(1, min(int(due_days), 60))),
        "description": description[:200],
    }
    if metadata:
        for key, value in metadata.items():
            clean_key = str(key).strip()[:40]
            clean_val = str(value).strip()[:500]
            if clean_key and clean_val:
                invoice_data[f"metadata[{clean_key}]"] = clean_val

    status_inv, body_inv = _request("POST", "/v1/invoices", invoice_data)
    if status_inv not in (200, 201) or not body_inv.get("id"):
        message = (body_inv.get("error") or {}).get("message", "No se pudo crear factura")
        raise StripeError(message)

    invoice_id = str(body_inv["id"])
    status_fin, body_fin = _request("POST", f"/v1/invoices/{urllib.parse.quote(invoice_id, safe='')}/finalize")
    if status_fin not in (200, 201) or not body_fin.get("id"):
        message = (body_fin.get("error") or {}).get("message", "No se pudo finalizar factura")
        raise StripeError(message)

    status_send, body_send = _request("POST", f"/v1/invoices/{urllib.parse.quote(invoice_id, safe='')}/send")
    if status_send not in (200, 201) or not body_send.get("id"):
        message = (body_send.get("error") or {}).get("message", "No se pudo enviar factura")
        raise StripeError(message)
    return body_send


def extract_session_payment(
    session: Dict[str, Any],
) -> Tuple[str, Optional[str], Optional[float]]:
    """Return (payment_status, currency_upper, amount) from a session, safely."""
    pay_status = str(session.get("payment_status", ""))
    currency = session.get("currency")
    total = session.get("amount_total")
    amount = float(total) / 100.0 if total is not None else None
    return pay_status, (currency.upper() if currency else None), amount


def verify_webhook(payload: bytes, sig_header: str) -> Dict[str, Any]:
    """Verify a Stripe webhook signature and return the decoded event.

    Implements Stripe's scheme: ``t=<ts>,v1=<sig>[,v1=<sig>...]`` where the
    signature is ``HMAC_SHA256(secret, f"{ts}.{payload}")``. Rejects payloads
    older than 5 minutes (replay protection) and uses a constant-time compare.
    """
    secret = settings.stripe_webhook_secret
    if not secret:
        raise StripeError("Webhook de Stripe no configurado")
    if not sig_header:
        raise StripeError("Firma ausente")

    timestamp = ""
    signatures: List[str] = []
    for part in sig_header.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        if key == "t":
            timestamp = value.strip()
        elif key == "v1":
            signatures.append(value.strip())
    if not timestamp or not signatures:
        raise StripeError("Firma incompleta")

    try:
        if abs(time.time() - int(timestamp)) > 300:
            raise StripeError("Firma expirada")
    except ValueError as exc:
        raise StripeError("Marca de tiempo no válida") from exc

    signed = timestamp.encode("utf-8") + b"." + payload
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, sig) for sig in signatures):
        raise StripeError("Firma no válida")

    try:
        return json.loads(payload.decode("utf-8"))
    except ValueError as exc:
        raise StripeError("Cuerpo del webhook no válido") from exc
