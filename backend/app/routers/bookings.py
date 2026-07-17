"""Public booking endpoints: create a consultation, confirm the PayPal payment
and poll the resulting status / video link.

Pricing is authoritative (recomputed server-side from the chosen plan), the
honeypot traps bots, every write is rate-limited and the natal chart + report
are generated only after payment is confirmed.
"""
from __future__ import annotations

import secrets
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import paypal
from ..config import settings
from ..database import get_db
from ..delivery import ensure_deliverables
from ..mailer import (
    send_business_notice,
    send_payment_received_confirmation,
    send_video_link,
)
from ..models import Booking, DirectPaymentIntake
from ..schemas import (
    BookingCreate,
    BookingCreateResponse,
    BookingStatus,
    PaymentConfirm,
    PayPalCaptureRequest,
    PayPalOrderResponse,
    TarotAvailabilityDay,
    TarotAvailabilityResponse,
    TarotAvailabilitySlot,
)
from ..security import client_ip, write_rate_limit
from ..security import read_rate_limit

router = APIRouter(prefix="/api/bookings", tags=["bookings"])

_TAROT_SLOT_TIMES = (time(7, 0), time(11, 0), time(15, 20))
_MEDITATION_SLOT_TIMES = (time(6, 0), time(20, 0))
_PACKAGE_SLOT_TIMES = (time(8, 0), time(11, 0), time(15, 0), time(19, 0))


def _service_slot_times(service: str) -> Tuple[time, ...]:
    if service == "meditaciones":
        return _MEDITATION_SLOT_TIMES
    if service == "paquete-magica":
        return _PACKAGE_SLOT_TIMES
    return _TAROT_SLOT_TIMES


def _normalize_slot(date_raw: Optional[str], time_raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    date_text = (date_raw or "").strip()
    time_text = (time_raw or "").strip()
    if not date_text and not time_text:
        return None, None

    # Supports yyyy-mm-dd or yyyy-mm-ddThh:mm payloads.
    if "T" in date_text:
        left, right = date_text.split("T", 1)
        date_text = left.strip()
        if not time_text and right:
            time_text = right.strip()

    if date_text:
        try:
            date_text = datetime.strptime(date_text[:10], "%Y-%m-%d").date().isoformat()
        except Exception:
            return None, None

    if time_text:
        try:
            hh, mm = time_text[:5].split(":", 1)
            time_text = time(hour=int(hh), minute=int(mm)).strftime("%H:%M")
        except Exception:
            return None, None

    if not date_text or not time_text:
        return None, None
    return date_text, time_text


def _booked_paid_direct_slots(
    db: Session,
    service: str,
    today: date,
    end_day: date,
) -> Set[Tuple[str, str]]:
    rows = (
        db.query(DirectPaymentIntake)
        .filter(DirectPaymentIntake.service == service)
        .filter(DirectPaymentIntake.consumed_at.isnot(None))
        .all()
    )
    out: Set[Tuple[str, str]] = set()
    for row in rows:
        d_iso, hhmm = _normalize_slot(row.appointment_date, row.appointment_time)
        if not d_iso or not hhmm:
            continue
        try:
            day = datetime.strptime(d_iso, "%Y-%m-%d").date()
        except Exception:
            continue
        if day < today or day > end_day:
            continue
        out.add((d_iso, hhmm))
    return out


def _booked_booking_slots(db: Session, today: date, end_day: date) -> Set[Tuple[str, str]]:
    rows = (
        db.query(Booking)
        .filter(Booking.appointment_date.isnot(None))
        .filter(Booking.appointment_time.isnot(None))
        .filter(Booking.appointment_date >= today)
        .filter(Booking.appointment_date <= end_day)
        .filter(Booking.status.in_(["pending", "awaiting_validation", "paid"]))
        .all()
    )
    out: Set[Tuple[str, str]] = set()
    for row in rows:
        if row.appointment_date and row.appointment_time:
            out.add((row.appointment_date.isoformat(), row.appointment_time.strftime("%H:%M")))
    return out


def _service_availability_payload(
    db: Session,
    service: str,
    days: int,
) -> TarotAvailabilityResponse:
    safe_days = max(1, min(int(days or 7), 60))
    today = datetime.now(timezone.utc).date()
    end_day = today + timedelta(days=safe_days - 1)
    slot_times = _service_slot_times(service)

    booked = _booked_paid_direct_slots(db, service, today, end_day)
    if service == "tarot-terapeutico":
        booked |= _booked_booking_slots(db, today, end_day)

    out_days: List[TarotAvailabilityDay] = []
    for offset in range(safe_days):
        d = today + timedelta(days=offset)
        d_iso = d.isoformat()
        slots: List[TarotAvailabilitySlot] = []
        for slot_time in slot_times:
            hhmm = slot_time.strftime("%H:%M")
            slots.append(TarotAvailabilitySlot(time=hhmm, available=(d_iso, hhmm) not in booked))
        out_days.append(TarotAvailabilityDay(date=d_iso, label=_format_day_label(d), slots=slots))
    return TarotAvailabilityResponse(timezone="America/Lima", days=out_days)


def _format_day_label(d: date) -> str:
    return d.strftime("%d/%m/%Y")


@router.get("/tarot/availability", response_model=TarotAvailabilityResponse)
def tarot_availability(
    days: int = 7,
    _: None = Depends(read_rate_limit),
    db: Session = Depends(get_db),
) -> TarotAvailabilityResponse:
    return _service_availability_payload(db, "tarot-terapeutico", days)


@router.get("/direct-availability", response_model=TarotAvailabilityResponse)
def direct_availability(
    service: str,
    days: int = 30,
    _: None = Depends(read_rate_limit),
    db: Session = Depends(get_db),
) -> TarotAvailabilityResponse:
    service_key = (service or "").strip().lower()
    if service_key not in {"meditaciones", "tarot-terapeutico", "paquete-magica"}:
        raise HTTPException(status_code=422, detail="Servicio no valido")
    return _service_availability_payload(db, service_key, days)


def _plan_pricing(plan: str) -> Dict[str, object]:
    """Authoritative amounts. PayPal cannot settle PEN, so the sol plan is
    charged as its configured USD equivalent."""
    if plan == "mxn":
        return {
            "currency": "MXN", "amount": float(settings.price_mxn),
            "charge_currency": "MXN", "charge_amount": float(settings.price_mxn),
        }
    return {
        "currency": "PEN", "amount": float(settings.price_pen),
        "charge_currency": "USD", "charge_amount": float(settings.price_pen_as_usd),
    }


def _paypal_me_url(charge_currency: str, charge_amount: float) -> str:
    amount = f"{charge_amount:.2f}".rstrip("0").rstrip(".")
    return f"https://paypal.me/{settings.paypal_me_handle}/{amount}{charge_currency}"


def _payment_url(charge_currency: str, charge_amount: float) -> str:
    """Real destination for the "Pay" button: an explicit configured link
    (e.g. a Stripe Payment Link) when provided, otherwise a PayPal.Me URL."""
    if settings.payment_link:
        return settings.payment_link
    return _paypal_me_url(charge_currency, charge_amount)


def _make_reference() -> str:
    stamp = datetime.now(timezone.utc).strftime("%y%m%d")
    return f"ADT-{stamp}-{secrets.token_hex(3).upper()}"


@router.post("", response_model=BookingCreateResponse, status_code=201)
def create_booking(
    payload: BookingCreate,
    request: Request,
    _: None = Depends(write_rate_limit),
    db: Session = Depends(get_db),
) -> BookingCreateResponse:
    # Honeypot: a filled "website" means a bot â€” fake success, store nothing.
    if payload.website:
        return BookingCreateResponse(
            reference="ADT-IGNORED", public_token="", status="pending",
            plan=payload.plan, currency="MXN", amount=0.0,
            charge_currency="MXN", charge_amount=0.0,
            paypal_client_id="", paypal_me_url="", payment_url="", payment_note="",
            message="Recibido.",
        )

    pricing = _plan_pricing(payload.plan)
    booking = Booking(
        reference=_make_reference(),
        public_token=secrets.token_urlsafe(24),
        full_name=payload.full_name,
        email=str(payload.email),
        birth_date=payload.birth_date,
        birth_time=payload.birth_time,
        birth_place=payload.birth_place,
        appointment_date=payload.appointment_date,
        appointment_time=payload.appointment_time,
        status="pending",
        plan=payload.plan,
        currency=str(pricing["currency"]),
        amount=float(pricing["amount"]),
        charge_currency=str(pricing["charge_currency"]),
        charge_amount=float(pricing["charge_amount"]),
        client_ip=client_ip(request),
    )
    db.add(booking)
    db.commit()

    send_business_notice(
        booking,
        "Nueva cita",
        "Se creo una nueva reserva desde el sitio.",
    )

    return BookingCreateResponse(
        reference=booking.reference,
        public_token=booking.public_token,
        status=booking.status,
        plan=booking.plan,
        currency=booking.currency,
        amount=booking.amount,
        charge_currency=booking.charge_currency,
        charge_amount=booking.charge_amount,
        paypal_client_id=settings.paypal_client_id,
        paypal_me_url=_paypal_me_url(booking.charge_currency, booking.charge_amount),
        payment_url=_payment_url(booking.charge_currency, booking.charge_amount),
        payment_note=settings.payment_note,
        message="Datos recibidos. Completa el pago para confirmar tu consulta.",
    )


def _status_message(booking: Booking) -> str:
    if booking.status == "paid":
        return (
            "Pago validado. Te hemos enviado el enlace de la videollamada a tu "
            "correo."
        )
    if booking.status == "awaiting_validation":
        return (
            "Hemos registrado tu pago. En cuanto Adelinemagica confirme la "
            "recepcion, recibiras el enlace de la videollamada en tu correo."
        )
    return "Pendiente de pago."


@router.post("/{public_token}/pay", response_model=BookingStatus)
def confirm_payment(
    public_token: str,
    payload: PaymentConfirm,
    request: Request,
    _: None = Depends(write_rate_limit),
    db: Session = Depends(get_db),
) -> BookingStatus:
    """Register a *payment claim* from the client.

    Crucially, this does NOT generate or reveal the video link. The link is
    created and emailed only when Adelinemagica validates the payment from the
    admin panel. Here we just move the booking to ``awaiting_validation`` and
    record how the client says they paid.
    """
    if payload.website:  # honeypot
        raise HTTPException(status_code=404, detail="No encontrado")

    booking = (
        db.query(Booking).filter(Booking.public_token == public_token).first()
    )
    if not booking:
        raise HTTPException(status_code=404, detail="No encontrado")

    # Already validated: nothing to do, never echo the link back to the client.
    if booking.status != "paid":
        should_notify = booking.status == "pending"
        booking.status = "awaiting_validation"
        booking.payment_method = payload.method
        booking.paypal_order_id = payload.paypal_order_id
        booking.payment_claimed_at = datetime.now(timezone.utc)
        db.commit()
        if should_notify:
            send_business_notice(
                booking,
                "Pago declarado",
                f"El cliente declaro pago por metodo: {payload.method}.",
            )
            send_payment_received_confirmation(booking)

    return BookingStatus(
        reference=booking.reference, full_name=booking.full_name,
        status=booking.status, plan=booking.plan, currency=booking.currency,
        amount=booking.amount, message=_status_message(booking),
    )


@router.post("/{public_token}/paypal/order", response_model=PayPalOrderResponse)
def create_paypal_order(
    public_token: str,
    request: Request,
    _: None = Depends(write_rate_limit),
    db: Session = Depends(get_db),
) -> PayPalOrderResponse:
    """Create a server-side PayPal order with an authoritative amount.

    The amount is recomputed from the stored booking, never taken from the
    client, so it cannot be tampered with. Backs the PayPal, Apple Pay and
    Google Pay buttons.
    """
    if not settings.paypal_server_enabled:
        raise HTTPException(status_code=503, detail="Pago en linea no disponible.")

    booking = (
        db.query(Booking).filter(Booking.public_token == public_token).first()
    )
    if not booking:
        raise HTTPException(status_code=404, detail="No encontrado")
    if booking.status == "paid":
        raise HTTPException(status_code=409, detail="Esta consulta ya esta pagada.")

    try:
        order = paypal.create_order(
            booking.charge_amount,
            booking.charge_currency,
            booking.reference,
            "Adelinemagica - Carta astral + Tarot",
        )
    except paypal.PayPalError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    booking.paypal_order_id = order["id"]
    db.commit()
    return PayPalOrderResponse(id=order["id"])


@router.post("/{public_token}/paypal/capture", response_model=BookingStatus)
def capture_paypal_order(
    public_token: str,
    payload: PayPalCaptureRequest,
    request: Request,
    _: None = Depends(write_rate_limit),
    db: Session = Depends(get_db),
) -> BookingStatus:
    """Capture a PayPal order server-side and verify the amount before trusting
    it. The video link is still never returned here."""
    if payload.website:  # honeypot
        raise HTTPException(status_code=404, detail="No encontrado")
    if not settings.paypal_server_enabled:
        raise HTTPException(status_code=503, detail="Pago en linea no disponible.")

    booking = (
        db.query(Booking).filter(Booking.public_token == public_token).first()
    )
    if not booking:
        raise HTTPException(status_code=404, detail="No encontrado")
    # A client may only capture the order that belongs to their own booking.
    if not booking.paypal_order_id or payload.order_id != booking.paypal_order_id:
        raise HTTPException(status_code=409, detail="La orden no coincide.")
    if booking.status == "paid":
        return BookingStatus(
            reference=booking.reference, full_name=booking.full_name,
            status=booking.status, plan=booking.plan, currency=booking.currency,
            amount=booking.amount, message=_status_message(booking),
        )

    try:
        result = paypal.capture_order(payload.order_id)
    except paypal.PayPalError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    cap_status, cap_currency, cap_amount = paypal.extract_capture(result)
    if cap_status.upper() != "COMPLETED":
        raise HTTPException(status_code=402, detail="El pago no se completo.")
    # Defence in depth: the captured money must match the server-side price.
    if cap_currency and cap_currency != booking.charge_currency:
        raise HTTPException(status_code=400, detail="Divisa del pago no valida.")
    if cap_amount is not None and abs(cap_amount - float(booking.charge_amount)) > 0.01:
        raise HTTPException(status_code=400, detail="Importe del pago no valido.")

    now = datetime.now(timezone.utc)
    booking.payment_method = "paypal"
    booking.payment_claimed_at = now
    booking.status = "awaiting_validation"

    # Optionally deliver immediately on a verified capture (otherwise Adeline
    # validates from the admin panel, where the payment shows as PayPal-verified).
    if settings.paypal_auto_validate:
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
        "Pago PayPal verificado",
        "Capture PayPal completado y validado por backend.",
    )
    send_payment_received_confirmation(booking)
    return BookingStatus(
        reference=booking.reference, full_name=booking.full_name,
        status=booking.status, plan=booking.plan, currency=booking.currency,
        amount=booking.amount, message=_status_message(booking),
    )


@router.get("/{public_token}", response_model=BookingStatus)
def get_status(
    public_token: str,
    _: None = Depends(read_rate_limit),
    db: Session = Depends(get_db),
) -> BookingStatus:
    booking = (
        db.query(Booking).filter(Booking.public_token == public_token).first()
    )
    if not booking:
        raise HTTPException(status_code=404, detail="No encontrado")
    # The video link is never exposed here â€” it is emailed after validation.
    return BookingStatus(
        reference=booking.reference, full_name=booking.full_name,
        status=booking.status, plan=booking.plan, currency=booking.currency,
        amount=booking.amount, message=_status_message(booking),
    )

