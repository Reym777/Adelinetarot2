"""Stripe payment endpoints: start a hosted Checkout, confirm it on return and
receive signed webhooks.

The video link is never returned here. A verified Stripe payment only moves the
booking to ``awaiting_validation`` (or, when ``stripe_auto_validate`` is set,
delivers the link by email) â€” Adelinemagica still confirms from the admin panel,
where the payment shows as Stripe-verified.
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import stripe_client
from ..config import settings
from ..database import get_db
from ..delivery import ensure_deliverables
from ..direct_appointments import create_direct_appointment
from ..google_calendar import upsert_direct_event
from ..mailer import (
    send_business_notice,
    send_direct_stripe_appointment_details,
    send_direct_stripe_customer_confirmation,
    send_direct_stripe_payment_notice,
    send_payment_received_confirmation,
    send_stripe_invoice_notice,
    send_video_link,
)
from ..models import Booking, DirectPaymentIntake
from ..schemas import (
    BookingStatus,
    StripeCheckoutRequest,
    StripeCheckoutResponse,
    StripeConfirmRequest,
    StripeDirectIntakeRequest,
    StripeDirectIntakeResponse,
    StripeInvoiceCreateRequest,
    StripeInvoiceCreateResponse,
    StripeServiceCheckoutRequest,
    StripeServiceCheckoutResponse,
)
from ..security import write_rate_limit

router = APIRouter(prefix="/api/stripe", tags=["stripe"])
logger = logging.getLogger("adelinemagica.payments")

_DIRECT_PAYMENT_LINKS = {
    "oraciones": "https://buy.stripe.com/3cI4gy7dZ9Gf48M9FTbjW02",
    "meditaciones": {
        False: "https://buy.stripe.com/4gMaEWfKvf0z7kY5pDbjW03",
        True: "https://buy.stripe.com/7sYbJ09m7bOn7kYf0dbjW04",
    },
    "tarot-terapeutico": {
        30: "https://buy.stripe.com/fZueVc69V7y7dJm3hvbjW05",
        45: "https://buy.stripe.com/28EeVceGrdWv0WA7xLbjW06",
        90: "https://buy.stripe.com/fZu28qeGraKj8p2bO1bjW08",
    },
    "paquete-magica": "https://buy.stripe.com/cNieVc2XJ19JcFicS5bjW07",
}


def _normalize_slot(date_raw: str, time_raw: str) -> tuple[str, str]:
    date_text = (date_raw or "").strip()
    time_text = (time_raw or "").strip()
    if "T" in date_text:
        left, right = date_text.split("T", 1)
        date_text = left.strip()
        if not time_text and right:
            time_text = right.strip()
    if not date_text or not time_text:
        return "", ""
    try:
        d_iso = datetime.strptime(date_text[:10], "%Y-%m-%d").date().isoformat()
        hh, mm = time_text[:5].split(":", 1)
        h_iso = datetime.strptime(f"{int(hh):02d}:{int(mm):02d}", "%H:%M").strftime("%H:%M")
        return d_iso, h_iso
    except Exception:
        return "", ""


def _slot_taken(db: Session, service: str, date_iso: str, hhmm: str) -> bool:
    if not date_iso or not hhmm:
        return False

    paid_rows = (
        db.query(DirectPaymentIntake)
        .filter(DirectPaymentIntake.service == service)
        .filter(DirectPaymentIntake.consumed_at.isnot(None))
        .all()
    )
    for row in paid_rows:
        d2, h2 = _normalize_slot(row.appointment_date or "", row.appointment_time or "")
        if d2 == date_iso and h2 == hhmm:
            return True

    # Legacy tarot bookings are also considered occupied.
    if service == "tarot-terapeutico":
        try:
            day = datetime.strptime(date_iso, "%Y-%m-%d").date()
            at = datetime.strptime(hhmm, "%H:%M").time()
        except Exception:
            return True
        existing = (
            db.query(Booking)
            .filter(Booking.appointment_date == day)
            .filter(Booking.appointment_time == at)
            .filter(Booking.status.in_(["pending", "awaiting_validation", "paid"]))
            .first()
        )
        if existing is not None:
            return True

    return False


def _base_url(request: Request) -> str:
    """Public origin used to build Stripe success/cancel return URLs."""
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
    if host:
        return f"https://{host}"
    return str(request.base_url).rstrip("/")


def _resolve_direct_payment_link(payload: StripeDirectIntakeRequest) -> str:
    if payload.service == "oraciones":
        return _DIRECT_PAYMENT_LINKS["oraciones"]
    if payload.service == "paquete-magica":
        return _DIRECT_PAYMENT_LINKS["paquete-magica"]
    if payload.service == "meditaciones":
        return _DIRECT_PAYMENT_LINKS["meditaciones"][bool(payload.recorded)]
    if payload.service == "tarot-terapeutico":
        duration = int(payload.tarot_duration or 0)
        url = _DIRECT_PAYMENT_LINKS["tarot-terapeutico"].get(duration)
        if not url:
            raise HTTPException(status_code=422, detail="Duracion de tarot no valida.")
        return url
    raise HTTPException(status_code=422, detail="Servicio no valido.")


def _build_direct_payment_url(payload: StripeDirectIntakeRequest, token: str) -> str:
    params = {
        "prefilled_email": str(payload.email),
        "client_reference_id": token,
        "locale": "es",
    }
    return f"{_resolve_direct_payment_link(payload)}?{urlencode(params)}"


def _resolve_meditation_sessions(payload: StripeDirectIntakeRequest) -> int:
    if payload.service != "meditaciones" or payload.recorded:
        return 1
    raw = int(payload.meditation_sessions or 1)
    if raw < 1 or raw > 12:
        raise HTTPException(status_code=422, detail="Cantidad de meditaciones no valida.")
    return raw


def _status_message(booking: Booking) -> str:
    if booking.status == "paid":
        return (
            "Pago validado. Te hemos enviado el enlace de la videollamada a tu "
            "correo."
        )
    if booking.status == "awaiting_validation":
        return (
            "Hemos recibido tu pago. En cuanto Adelinemagica lo confirme, recibiras "
            "el enlace de la videollamada en tu correo."
        )
    return "Pendiente de pago."


def _service_checkout_pricing(payload: StripeServiceCheckoutRequest) -> tuple[float, str, str]:
    """Return authoritative (amount, currency, description) for direct service checkout."""
    if payload.service == "meditaciones":
        amount = 60.0 if payload.recorded else 33.0
        desc = "Meditaciones guiadas"
        if payload.recorded:
            desc = "Meditacion pregrabada personalizada"
        return amount, "USD", desc
    if payload.service == "oraciones":
        return 60.0, "USD", "Oraciones personalizadas (3 dias)"

    duration = int(payload.tarot_duration or 0)
    if duration not in (30, 45, 90):
        raise HTTPException(status_code=422, detail="DuraciÃ³n de tarot no vÃ¡lida")
    return float(duration), "USD", f"Tarot terapÃ©utico {duration} min"


def _apply_stripe_paid(db: Session, booking: Booking) -> None:
    """Idempotently advance a booking after a verified Stripe payment."""
    if booking.status == "paid":
        return
    now = datetime.now(timezone.utc)
    booking.payment_method = "stripe"
    booking.payment_claimed_at = booking.payment_claimed_at or now
    booking.status = "awaiting_validation"
    # Optional immediate delivery; otherwise Adelinemagica validates manually.
    if settings.stripe_auto_validate:
        ensure_deliverables(booking)
        booking.status = "paid"
        booking.paid_at = booking.paid_at or now
        ok, detail = send_video_link(booking)
        if ok:
            booking.link_emailed_at = now
        booking.email_status = detail
    db.commit()
    send_business_notice(
        booking,
        "Pago Stripe verificado",
        "Checkout Stripe confirmado y validado por backend.",
    )
    send_payment_received_confirmation(booking)


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
    success_url = (
        f"{base}/confirmation?kind=payment&status=success"
        f"&source=stripe&session_id={{CHECKOUT_SESSION_ID}}"
    )
    cancel_url = f"{base}/confirmation?kind=payment&status=cancel&source=stripe"
    try:
        session = stripe_client.create_checkout_session(
            amount=booking.amount,
            currency=booking.currency,
            reference=booking.reference,
            email=booking.email,
            description="Adelinemagica - Carta astral + Tarot",
            success_url=success_url,
            cancel_url=cancel_url,
            booking_token=booking.public_token,
        )
    except stripe_client.StripeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    booking.stripe_session_id = session["id"]
    db.commit()
    return StripeCheckoutResponse(id=session["id"], url=session["url"])


@router.post("/service-checkout", response_model=StripeServiceCheckoutResponse)
def create_service_checkout(
    payload: StripeServiceCheckoutRequest,
    request: Request,
    _: None = Depends(write_rate_limit),
) -> StripeCheckoutResponse:
    """Create Stripe Checkout Session for direct service pages with rich metadata."""
    if payload.website:
        raise HTTPException(status_code=404, detail="No encontrado")
    if not settings.stripe_enabled:
        logger.error(
            "Stripe service-checkout refused: stripe secret key missing (stripe_enabled=false)."
        )
        raise HTTPException(status_code=503, detail="Pago con tarjeta no disponible.")
    if payload.embedded and not settings.stripe_publishable_key:
        logger.error(
            "Stripe embedded checkout refused: publishable key missing while embedded=true."
        )
        raise HTTPException(status_code=503, detail="Stripe publishable key no configurada.")

    amount, currency, description = _service_checkout_pricing(payload)
    base = _base_url(request)
    success_url = (
        f"{base}/confirmation?kind=payment&status=success"
        f"&source=stripe&session_id={{CHECKOUT_SESSION_ID}}"
    )
    cancel_url = f"{base}/confirmation?kind=payment&status=cancel&source=stripe"
    reference = f"ADM-{int(datetime.now(timezone.utc).timestamp())}"
    metadata = {
        "service": payload.service,
        "first_name": payload.first_name,
        "last_name": payload.last_name,
        "email": str(payload.email),
        "appointment_date": payload.appointment_date or "",
        "appointment_time": payload.appointment_time or "",
        "notes": payload.notes or "",
        "tarot_duration": str(payload.tarot_duration or ""),
        "recorded": "true" if payload.recorded else "false",
    }

    try:
        session = stripe_client.create_checkout_session(
            amount=amount,
            currency=currency,
            reference=reference,
            email=str(payload.email),
            description=description,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=metadata,
            embedded=payload.embedded,
        )
    except stripe_client.StripeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return StripeServiceCheckoutResponse(
        id=session["id"],
        url=session.get("url"),
        client_secret=session.get("client_secret"),
    )


@router.post("/direct-intake", response_model=StripeDirectIntakeResponse)
def create_direct_intake(
    payload: StripeDirectIntakeRequest,
    request: Request,
    _: None = Depends(write_rate_limit),
    db: Session = Depends(get_db),
) -> StripeDirectIntakeResponse:
    """Store direct payment form data and return a Stripe payment-link URL."""
    if payload.website:
        raise HTTPException(status_code=404, detail="No encontrado")
    if not settings.stripe_enabled:
        logger.error("Stripe direct-intake refused: stripe secret key missing.")
        raise HTTPException(status_code=503, detail="Pago con tarjeta no disponible.")
    date_iso, hhmm = _normalize_slot(payload.appointment_date or "", payload.appointment_time or "")
    if date_iso and hhmm and _slot_taken(db, payload.service, date_iso, hhmm):
        raise HTTPException(status_code=409, detail="Este horario ya no esta disponible.")

    token = f"dpi_{secrets.token_urlsafe(18)}"
    intake = DirectPaymentIntake(
        token=token,
        service=payload.service,
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=str(payload.email),
        appointment_date=date_iso or payload.appointment_date,
        appointment_time=hhmm or payload.appointment_time,
        notes=payload.notes,
    )
    db.add(intake)
    db.commit()

    payment_url = _build_direct_payment_url(payload, token)

    meditation_sessions = _resolve_meditation_sessions(payload)
    if payload.service == "meditaciones" and not payload.recorded and meditation_sessions > 1:
        base = _base_url(request)
        success_url = (
            f"{base}/confirmation?kind=payment&status=success"
            f"&source=stripe&session_id={{CHECKOUT_SESSION_ID}}"
        )
        cancel_url = f"{base}/confirmation?kind=payment&status=cancel&source=stripe"
        try:
            session = stripe_client.create_checkout_session(
                amount=33.0 * float(meditation_sessions),
                currency="USD",
                reference=token,
                email=str(payload.email),
                description=f"Meditaciones guiadas x{meditation_sessions}",
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "service": payload.service,
                    "first_name": payload.first_name,
                    "last_name": payload.last_name,
                    "email": str(payload.email),
                    "appointment_date": payload.appointment_date or "",
                    "appointment_time": payload.appointment_time or "",
                    "notes": payload.notes or "",
                    "meditation_sessions": str(meditation_sessions),
                    "recorded": "false",
                },
            )
            payment_url = session.get("url") or payment_url
        except stripe_client.StripeError as exc:
            raise HTTPException(status_code=502, detail=str(exc))

    return StripeDirectIntakeResponse(ok=True, payment_url=payment_url)


@router.post("/invoices", response_model=StripeInvoiceCreateResponse)
def create_invoice(
    payload: StripeInvoiceCreateRequest,
    _: None = Depends(write_rate_limit),
) -> StripeInvoiceCreateResponse:
    """Create and send a Stripe invoice (Invoicing integration)."""
    if payload.website:
        raise HTTPException(status_code=404, detail="No encontrado")
    if not settings.stripe_enabled:
        raise HTTPException(status_code=503, detail="Stripe no disponible")

    metadata = {
        "source": "adelinemagica",
        "notify_to": settings.notify_recipient,
    }
    try:
        invoice = stripe_client.create_and_send_invoice(
            customer_email=str(payload.email),
            customer_name=payload.customer_name,
            description=payload.description,
            amount=payload.amount,
            currency=payload.currency,
            due_days=payload.due_days,
            metadata=metadata,
        )
    except stripe_client.StripeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return StripeInvoiceCreateResponse(
        id=str(invoice.get("id") or ""),
        hosted_invoice_url=invoice.get("hosted_invoice_url"),
    )


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
        logger.error("Stripe webhook verification failed: invalid signature or webhook secret mismatch.")
        raise HTTPException(status_code=400, detail="Firma no vÃ¡lida")

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
            elif event_type == "checkout.session.completed":
                # Direct Stripe Payment Link flow: no Booking exists in DB, but
                # business still needs a payment notification email.
                intake_data = _intake_for_session(db, session)
                customer = session.get("customer_details") or {}
                payer_email = str(
                    customer.get("email")
                    or session.get("customer_email")
                    or ""
                ).strip()
                if payer_email:
                    intake_data["payer_email"] = payer_email
                ok, detail = send_direct_stripe_payment_notice(session, intake_data)
                if not ok:
                    logger.error(
                        "Stripe direct payment notification failed: %s | notify_to=%s | resend_enabled=%s | smtp_enabled=%s",
                        detail,
                        settings.notify_recipient,
                        settings.resend_enabled,
                        settings.mail_enabled,
                    )
                ok_user, detail_user = send_direct_stripe_customer_confirmation(session, intake_data)
                if not ok_user:
                    logger.error(
                        "Stripe direct customer confirmation failed: %s | customer_email=%s",
                        detail_user,
                        (session.get("customer_details") or {}).get("email") or intake_data.get("email") or "N/A",
                    )

                service = (intake_data.get("service") or "").strip()
                if service in {"meditaciones", "tarot-terapeutico", "paquete-magica"}:
                    previous_video_url = (intake_data.get("video_url") or "").strip()
                    previous_was_meet = "meet.google.com" in previous_video_url.lower()
                    appointment_data: dict
                    if intake_data.get("appointment_start_at"):
                        appointment_data = {
                            "start_at": intake_data.get("appointment_start_at") or "",
                            "end_at": intake_data.get("appointment_end_at") or "",
                            "video_room": intake_data.get("video_room") or "",
                            "video_url": intake_data.get("video_url") or "",
                            "tentative": "false",
                            "reason": "",
                        }
                    else:
                        appointment_data = create_direct_appointment(intake_data)
                        _save_intake_appointment_data(
                            db,
                            token=intake_data.get("token") or "",
                            appointment_data=appointment_data,
                        )

                    intake_row = _get_intake_by_token(db, intake_data.get("token") or "")
                    if intake_row is not None:
                        ok_google, google_data = upsert_direct_event(
                            intake_data=intake_data,
                            appointment_data=appointment_data,
                            existing_event_id=intake_row.google_event_id or "",
                            status=settings.google_calendar_default_status,
                        )
                        _save_intake_google_data(
                            db,
                            intake=intake_row,
                            ok=ok_google,
                            payload=google_data,
                        )

                        if ok_google:
                            meet_url = (google_data.get("meet_url") or "").strip()
                            calendar_url = (google_data.get("html_link") or "").strip()
                            if google_data.get("warning") == "attendees_forbidden_for_service_account":
                                logger.warning(
                                    "Google Calendar event created without attendees (service-account restriction). token=%s",
                                    intake_data.get("token") or "N/A",
                                )
                            if meet_url:
                                appointment_data["video_url"] = meet_url
                            if calendar_url:
                                appointment_data["google_calendar_url"] = calendar_url
                            _save_intake_appointment_data(
                                db,
                                token=intake_data.get("token") or "",
                                appointment_data=appointment_data,
                            )

                            should_send_appointment_email = (
                                bool(meet_url)
                                and ((not previous_was_meet) or (previous_video_url.strip() != meet_url))
                            )
                            if should_send_appointment_email:
                                ok_appt_email, appt_email_detail = send_direct_stripe_appointment_details(
                                    session,
                                    intake_data,
                                    appointment_data,
                                )
                                if not ok_appt_email:
                                    logger.error(
                                        "Direct appointment email failed: %s | token=%s",
                                        appt_email_detail,
                                        intake_data.get("token") or "N/A",
                                    )
                        else:
                            logger.error(
                                "Google Calendar sync failed for direct appointment token=%s error=%s",
                                intake_data.get("token") or "N/A",
                                google_data.get("error") or "N/A",
                            )
    elif event_type in ("invoice.paid", "invoice.payment_failed", "invoice.sent"):
        invoice = event.get("data", {}).get("object", {})
        if invoice:
            send_stripe_invoice_notice(invoice, event_type)
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


def _intake_for_session(db: Session, session: dict) -> dict:
    """Find direct-intake payload captured before redirecting to payment link."""
    token = (session.get("client_reference_id") or "").strip()
    intake: Optional[DirectPaymentIntake] = None

    if token:
        intake = (
            db.query(DirectPaymentIntake)
            .filter(DirectPaymentIntake.token == token)
            .first()
        )

    # Payment Links may occasionally arrive without client_reference_id in the
    # webhook payload; fallback to the closest pending intake by email/time.
    if intake is None:
        customer = session.get("customer_details") or {}
        customer_email = str(
            customer.get("email")
            or session.get("customer_email")
            or ""
        ).strip().lower()

        created_ts = session.get("created")
        session_created_at: Optional[datetime] = None
        if isinstance(created_ts, int):
            session_created_at = datetime.fromtimestamp(created_ts, tz=timezone.utc)

        candidates = (
            db.query(DirectPaymentIntake)
            .filter(DirectPaymentIntake.consumed_at.is_(None))
            .order_by(DirectPaymentIntake.created_at.desc())
            .limit(80)
            .all()
        )
        if not candidates:
            return {}

        email_matches = [
            row
            for row in candidates
            if customer_email and str(row.email or "").strip().lower() == customer_email
        ]
        pool = email_matches or candidates

        if session_created_at is not None:
            pool = sorted(
                pool,
                key=lambda row: abs((row.created_at - session_created_at).total_seconds()),
            )

        picked = pool[0] if pool else None
        if picked is None:
            return {}

        # Safety window to avoid linking very old pending intakes.
        if session_created_at is not None:
            delta = abs((picked.created_at - session_created_at).total_seconds())
            if delta > int(timedelta(hours=36).total_seconds()):
                return {}
        intake = picked

    now = datetime.now(timezone.utc)
    if intake.consumed_at is None:
        intake.consumed_at = now
    intake.stripe_session_id = session.get("id") or intake.stripe_session_id
    intake.stripe_payment_link_id = session.get("payment_link") or intake.stripe_payment_link_id
    db.commit()

    return {
        "token": intake.token,
        "service": intake.service,
        "first_name": intake.first_name,
        "last_name": intake.last_name,
        "email": intake.email,
        "appointment_date": intake.appointment_date or "",
        "appointment_time": intake.appointment_time or "",
        "notes": intake.notes or "",
        "appointment_start_at": intake.appointment_start_at or "",
        "appointment_end_at": intake.appointment_end_at or "",
        "video_room": intake.video_room or "",
        "video_url": intake.video_url or "",
    }


def _save_intake_appointment_data(db: Session, token: str, appointment_data: dict) -> None:
    """Persist direct appointment and video details for idempotency."""
    if not token:
        return
    intake = (
        db.query(DirectPaymentIntake)
        .filter(DirectPaymentIntake.token == token)
        .first()
    )
    if intake is None:
        return
    changed = False
    if appointment_data.get("start_at") and intake.appointment_start_at != appointment_data.get("start_at"):
        intake.appointment_start_at = appointment_data.get("start_at")
        changed = True
    if appointment_data.get("end_at") and intake.appointment_end_at != appointment_data.get("end_at"):
        intake.appointment_end_at = appointment_data.get("end_at")
        changed = True
    if appointment_data.get("video_room") and intake.video_room != appointment_data.get("video_room"):
        intake.video_room = appointment_data.get("video_room")
        changed = True
    if appointment_data.get("video_url") and intake.video_url != appointment_data.get("video_url"):
        intake.video_url = appointment_data.get("video_url")
        changed = True
    if changed:
        db.commit()


def _get_intake_by_token(db: Session, token: str) -> Optional[DirectPaymentIntake]:
    if not token:
        return None
    return (
        db.query(DirectPaymentIntake)
        .filter(DirectPaymentIntake.token == token)
        .first()
    )


def _save_intake_google_data(db: Session, intake: DirectPaymentIntake, ok: bool, payload: dict) -> None:
    changed = False
    now = datetime.now(timezone.utc)
    if ok:
        event_id = (payload.get("event_id") or "").strip()
        status = (payload.get("event_status") or "").strip()
        html_link = (payload.get("html_link") or "").strip()
        if event_id and intake.google_event_id != event_id:
            intake.google_event_id = event_id
            changed = True
        if status and intake.google_event_status != status:
            intake.google_event_status = status
            changed = True
        if html_link and intake.google_event_html_link != html_link:
            intake.google_event_html_link = html_link
            changed = True
        intake.google_last_error = None
        intake.google_synced_at = now
        changed = True
    else:
        error = str(payload.get("error") or "google_sync_failed")[:300]
        if intake.google_last_error != error:
            intake.google_last_error = error
            changed = True
        intake.google_synced_at = now
        changed = True
    if changed:
        db.commit()

