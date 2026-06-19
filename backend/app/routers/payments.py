"""Stripe payment endpoints: start a hosted Checkout, confirm it on return and
receive signed webhooks.

The video link is never returned here. A verified Stripe payment only moves the
booking to ``awaiting_validation`` (or, when ``stripe_auto_validate`` is set,
delivers the link by email) — AdelineTarot still confirms from the admin panel,
where the payment shows as Stripe-verified.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import stripe_client
from ..config import settings
from ..database import get_db
from ..delivery import ensure_deliverables
from ..mailer import send_video_link
from ..models import Booking
from ..schemas import (
    BookingStatus,
    StripeCheckoutRequest,
    StripeCheckoutResponse,
    StripeConfirmRequest,
)
from ..security import write_rate_limit

router = APIRouter(prefix="/api/stripe", tags=["stripe"])


def _base_url(request: Request) -> str:
    """Public origin used to build Stripe success/cancel return URLs."""
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
    if host:
        return f"https://{host}"
    return str(request.base_url).rstrip("/")


def _status_message(booking: Booking) -> str:
    if booking.status == "paid":
        return (
            "Pago validado. Te hemos enviado el enlace de la videollamada a tu "
            "correo."
        )
    if booking.status == "awaiting_validation":
        return (
            "Hemos recibido tu pago. En cuanto AdelineTarot lo confirme, recibiras "
            "el enlace de la videollamada en tu correo."
        )
    return "Pendiente de pago."


def _apply_stripe_paid(db: Session, booking: Booking) -> None:
    """Idempotently advance a booking after a verified Stripe payment."""
    if booking.status == "paid":
        return
    now = datetime.now(timezone.utc)
    booking.payment_method = "stripe"
    booking.payment_claimed_at = booking.payment_claimed_at or now
    booking.status = "awaiting_validation"
    # Optional immediate delivery; otherwise AdelineTarot validates manually.
    if settings.stripe_auto_validate:
        ensure_deliverables(booking)
        booking.status = "paid"
        booking.paid_at = booking.paid_at or now
        ok, detail = send_video_link(booking)
        if ok:
            booking.link_emailed_at = now
        booking.email_status = detail
    db.commit()


@router.post("/checkout", response_model=StripeCheckoutResponse)
def create_checkout(
    payload: StripeCheckoutRequest,
    request: Request,
    _: None = Depends(write_rate_limit),
    db: Session = Depends(get_db),
) -> StripeCheckoutResponse:
    """Create a hosted Checkout Session for a booking and return its URL.

    The amount is recomputed from the stored booking (never trusted from the
    client) and charged in the consultation's own currency (MXN or PEN).
    """
    if payload.website:  # honeypot
        raise HTTPException(status_code=404, detail="No encontrado")
    if not settings.stripe_enabled:
        raise HTTPException(status_code=503, detail="Pago con tarjeta no disponible.")

    booking = (
        db.query(Booking).filter(Booking.public_token == payload.public_token).first()
    )
    if not booking:
        raise HTTPException(status_code=404, detail="No encontrado")
    if booking.status == "paid":
        raise HTTPException(status_code=409, detail="Esta consulta ya esta pagada.")

    base = _base_url(request)
    success_url = f"{base}/?paid=stripe&session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{base}/?canceled=stripe"
    try:
        session = stripe_client.create_checkout_session(
            amount=booking.amount,
            currency=booking.currency,
            reference=booking.reference,
            email=booking.email,
            description="AdelineTarot - Carta astral + Tarot",
            success_url=success_url,
            cancel_url=cancel_url,
            booking_token=booking.public_token,
        )
    except stripe_client.StripeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    booking.stripe_session_id = session["id"]
    db.commit()
    return StripeCheckoutResponse(id=session["id"], url=session["url"])


@router.post("/confirm", response_model=BookingStatus)
def confirm_checkout(
    payload: StripeConfirmRequest,
    _: None = Depends(write_rate_limit),
    db: Session = Depends(get_db),
) -> BookingStatus:
    """Verify a Checkout Session server-side when the client returns from Stripe.

    Only a session that Stripe reports as ``paid`` (with the expected amount and
    currency) advances the booking. The video link is never returned here.
    """
    booking = (
        db.query(Booking)
        .filter(Booking.stripe_session_id == payload.session_id)
        .first()
    )
    if not booking:
        raise HTTPException(status_code=404, detail="No encontrado")

    if booking.status != "paid":
        try:
            session = stripe_client.retrieve_session(payload.session_id)
        except stripe_client.StripeError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        pay_status, currency, amount = stripe_client.extract_session_payment(session)
        if pay_status != "paid":
            raise HTTPException(status_code=402, detail="El pago aun no se ha completado.")
        if currency and currency != booking.currency:
            raise HTTPException(status_code=400, detail="Divisa del pago no valida.")
        if amount is not None and abs(amount - float(booking.amount)) > 0.01:
            raise HTTPException(status_code=400, detail="Importe del pago no valido.")
        _apply_stripe_paid(db, booking)

    return BookingStatus(
        reference=booking.reference, full_name=booking.full_name,
        status=booking.status, plan=booking.plan, currency=booking.currency,
        amount=booking.amount, message=_status_message(booking),
    )


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    """Receive and verify Stripe webhook events (authoritative confirmation)."""
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = stripe_client.verify_webhook(payload, signature)
    except stripe_client.StripeError:
        raise HTTPException(status_code=400, detail="Firma no válida")

    event_type = event.get("type", "")
    if event_type in (
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
    ):
        session = event.get("data", {}).get("object", {})
        if session.get("payment_status") == "paid":
            booking = _booking_for_session(db, session)
            if booking is not None:
                _, currency, amount = stripe_client.extract_session_payment(session)
                amount_ok = amount is None or abs(amount - float(booking.amount)) <= 0.01
                currency_ok = not currency or currency == booking.currency
                if amount_ok and currency_ok:
                    _apply_stripe_paid(db, booking)
    return {"received": True}


def _booking_for_session(db: Session, session: dict):
    """Locate the booking a Stripe session belongs to (by id, then token)."""
    session_id = session.get("id")
    if session_id:
        booking = (
            db.query(Booking)
            .filter(Booking.stripe_session_id == session_id)
            .first()
        )
        if booking is not None:
            return booking
    token = (session.get("metadata") or {}).get("booking_token")
    if token:
        return db.query(Booking).filter(Booking.public_token == token).first()
    return None
