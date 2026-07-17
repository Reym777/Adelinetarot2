"""Admin endpoints (Adelinemagica).

Every route is guarded by a constant-time admin-token check (sent in the
``X-Admin-Token`` header). Adelinemagica reviews each booking, validates that she
received the payment, and triggers delivery of the private video link by email
(the link is never shown to the client on the website).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..delivery import ensure_deliverables
from ..google_calendar import upsert_direct_event
from ..mailer import send_video_link
from ..models import Booking, DirectPaymentIntake, PageVisit
from ..schemas import (
    AdminBookingDetail,
    AdminBookingSummary,
    AdminDashboardResponse,
)
from ..security import read_rate_limit, require_admin, write_rate_limit

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


def _direct_intake_start_at(row: DirectPaymentIntake) -> Optional[datetime]:
    """Best-effort start datetime for direct paid intakes."""
    raw = (row.appointment_start_at or "").strip()
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except Exception:
            pass

    d = (row.appointment_date or "").strip()
    t = (row.appointment_time or "").strip()
    if "T" in d:
        left, right = d.split("T", 1)
        d = left.strip()
        if not t and right:
            t = right.strip()
    if not d:
        return None
    if not t:
        t = "09:00"
    try:
        return datetime.fromisoformat(f"{d[:10]}T{t[:5]}")
    except Exception:
        return None


def _intake_to_calendar_payload(row: DirectPaymentIntake) -> tuple[dict, dict]:
    intake_data = {
        "token": row.token,
        "service": row.service,
        "first_name": row.first_name,
        "last_name": row.last_name,
        "email": row.email,
        "notes": row.notes or "",
        "appointment_start_at": row.appointment_start_at or "",
        "appointment_end_at": row.appointment_end_at or "",
        "video_url": row.video_url or "",
    }
    appointment_data = {
        "start_at": row.appointment_start_at or "",
        "end_at": row.appointment_end_at or "",
        "video_room": row.video_room or "",
        "video_url": row.video_url or "",
    }
    return intake_data, appointment_data


def _to_detail(b: Booking) -> AdminBookingDetail:
    chart = json.loads(b.chart_json) if b.chart_json else None
    return AdminBookingDetail(
        id=b.id, reference=b.reference, full_name=b.full_name, email=b.email,
        birth_date=b.birth_date, birth_time=b.birth_time, birth_place=b.birth_place,
        status=b.status, plan=b.plan, currency=b.currency, amount=b.amount,
        charge_currency=b.charge_currency, charge_amount=b.charge_amount,
        payment_method=b.payment_method, paypal_order_id=b.paypal_order_id,
        stripe_session_id=b.stripe_session_id,
        payment_claimed_at=b.payment_claimed_at, link_emailed_at=b.link_emailed_at,
        email_status=b.email_status,
        created_at=b.created_at, paid_at=b.paid_at,
        video_url=b.video_url, video_room=b.video_room,
        chart=chart, report_text=b.report_text,
    )


@router.get("/me")
def verify_token() -> dict:
    """Lightweight endpoint the dashboard calls to validate the token."""
    return {"ok": True}


@router.get("/bookings", response_model=List[AdminBookingSummary])
def list_bookings(
    _: None = Depends(read_rate_limit),
    db: Session = Depends(get_db),
) -> List[AdminBookingSummary]:
    rows = db.query(Booking).order_by(Booking.created_at.desc()).limit(500).all()
    return [
        AdminBookingSummary(
            id=b.id, reference=b.reference, full_name=b.full_name, email=b.email,
            birth_date=b.birth_date, birth_place=b.birth_place, status=b.status,
            plan=b.plan, currency=b.currency, amount=b.amount,
            created_at=b.created_at, paid_at=b.paid_at,
        )
        for b in rows
    ]


@router.get("/dashboard", response_model=AdminDashboardResponse)
def dashboard(
    _: None = Depends(read_rate_limit),
    db: Session = Depends(get_db),
) -> AdminDashboardResponse:
    today = datetime.now(timezone.utc).date()
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)
    yesterday = today - timedelta(days=1)

    upcoming_rows = (
        db.query(Booking)
        .filter(Booking.appointment_date.isnot(None))
        .filter(Booking.appointment_date >= today)
        .order_by(Booking.appointment_date.asc(), Booking.appointment_time.asc())
        .limit(40)
        .all()
    )
    upcoming = [
        {
            "id": b.id,
            "reference": b.reference,
            "name": b.full_name,
            "email": b.email,
            "date": b.appointment_date.isoformat() if b.appointment_date else None,
            "time": b.appointment_time.strftime("%H:%M") if b.appointment_time else None,
            "status": b.status,
        }
        for b in upcoming_rows
    ]

    payment_rows = (
        db.query(Booking)
        .filter((Booking.payment_claimed_at.isnot(None)) | (Booking.paid_at.isnot(None)))
        .order_by(Booking.payment_claimed_at.desc(), Booking.paid_at.desc(), Booking.created_at.desc())
        .limit(50)
        .all()
    )
    recent_payments = [
        {
            "id": b.id,
            "reference": b.reference,
            "name": b.full_name,
            "email": b.email,
            "method": b.payment_method,
            "status": b.status,
            "amount": b.amount,
            "currency": b.currency,
            "claimed_at": b.payment_claimed_at.isoformat() if b.payment_claimed_at else None,
            "paid_at": b.paid_at.isoformat() if b.paid_at else None,
        }
        for b in payment_rows
    ]

    month_paid = (
        db.query(Booking)
        .filter(Booking.status == "paid")
        .filter(Booking.paid_at.isnot(None))
        .filter(Booking.paid_at >= datetime.combine(month_start, datetime.min.time(), tzinfo=timezone.utc))
        .all()
    )
    year_paid = (
        db.query(Booking)
        .filter(Booking.status == "paid")
        .filter(Booking.paid_at.isnot(None))
        .filter(Booking.paid_at >= datetime.combine(year_start, datetime.min.time(), tzinfo=timezone.utc))
        .all()
    )

    def _sum_by_currency(rows: list[Booking]) -> dict:
        out: dict = {}
        for r in rows:
            c = r.currency or "UNK"
            out[c] = round(float(out.get(c, 0.0)) + float(r.amount or 0.0), 2)
        return out

    visits_yesterday = (
        db.query(PageVisit)
        .filter(PageVisit.day == yesterday)
        .with_entities(PageVisit.hits)
        .all()
    )
    visits_total = sum(int(v[0]) for v in visits_yesterday)

    recent_emails = (
        db.query(Booking.email)
        .order_by(Booking.created_at.desc())
        .limit(60)
        .all()
    )
    email_unique: list[str] = []
    seen = set()
    for row in recent_emails:
        mail = str(row[0] or "").strip().lower()
        if mail and mail not in seen:
            seen.add(mail)
            email_unique.append(mail)

    return AdminDashboardResponse(
        upcoming_citas=upcoming,
        recent_payments=recent_payments,
        totals={
            "month": _sum_by_currency(month_paid),
            "year": _sum_by_currency(year_paid),
        },
        visits_yesterday=visits_total,
        recent_client_emails=email_unique,
    )


@router.get("/calendar-events")
def calendar_events(
    days: int = 180,
    _: None = Depends(read_rate_limit),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Complete admin calendar feed (bookings + direct paid intakes)."""
    safe_days = max(7, min(int(days or 180), 365))
    now = datetime.now(timezone.utc)
    until = now + timedelta(days=safe_days)

    rows = (
        db.query(Booking)
        .filter(Booking.appointment_date.isnot(None))
        .filter(Booking.appointment_date >= now.date())
        .filter(Booking.appointment_date <= until.date())
        .order_by(Booking.appointment_date.asc(), Booking.appointment_time.asc())
        .all()
    )

    events: list[dict] = []
    for b in rows:
        if not b.appointment_date:
            continue
        hhmm = b.appointment_time.strftime("%H:%M") if b.appointment_time else "09:00"
        start_iso = f"{b.appointment_date.isoformat()}T{hhmm}:00"
        end_iso = f"{b.appointment_date.isoformat()}T{hhmm}:00"
        events.append(
            {
                "id": f"booking-{b.id}",
                "title": f"{b.full_name} · {b.status}",
                "start": start_iso,
                "end": end_iso,
                "allDay": False,
                "extendedProps": {
                    "source": "booking",
                    "reference": b.reference,
                    "status": b.status,
                    "email": b.email,
                },
            }
        )

    direct_rows = (
        db.query(DirectPaymentIntake)
        .filter(DirectPaymentIntake.consumed_at.isnot(None))
        .order_by(DirectPaymentIntake.created_at.desc())
        .limit(1500)
        .all()
    )
    for row in direct_rows:
        start_dt = _direct_intake_start_at(row)
        if start_dt is None:
            continue
        if start_dt < now or start_dt > until:
            continue
        events.append(
            {
                "id": f"direct-{row.id}",
                "title": f"{row.service} · {row.first_name} {row.last_name}",
                "start": start_dt.isoformat(),
                "end": (datetime.fromisoformat(row.appointment_end_at) if row.appointment_end_at else start_dt).isoformat(),
                "allDay": False,
                "extendedProps": {
                    "source": "direct",
                    "service": row.service,
                    "email": row.email,
                    "video_url": row.video_url,
                    "notes": row.notes,
                    "google_event_status": row.google_event_status,
                    "google_event_id": row.google_event_id,
                    "google_event_html_link": row.google_event_html_link,
                    "google_last_error": row.google_last_error,
                },
            }
        )

    return events


@router.post("/direct-intakes/{intake_id}/google-status")
def update_direct_google_status(
    intake_id: int,
    status: str,
    _: None = Depends(write_rate_limit),
    db: Session = Depends(get_db),
) -> dict:
    target = str(status or "").strip().lower()
    if target not in {"tentative", "confirmed", "cancelled"}:
        raise HTTPException(status_code=422, detail="Estado Google invalido")

    row: Optional[DirectPaymentIntake] = db.get(DirectPaymentIntake, intake_id)
    if not row:
        raise HTTPException(status_code=404, detail="No encontrado")
    if row.consumed_at is None:
        raise HTTPException(status_code=400, detail="Pago directo aun no consumido")
    if not row.appointment_start_at:
        raise HTTPException(status_code=400, detail="Sin horario de cita para sincronizar")

    intake_data, appointment_data = _intake_to_calendar_payload(row)
    ok, payload = upsert_direct_event(
        intake_data=intake_data,
        appointment_data=appointment_data,
        existing_event_id=row.google_event_id or "",
        status=target,
    )

    row.google_synced_at = datetime.now(timezone.utc)
    if ok:
        row.google_event_id = (payload.get("event_id") or row.google_event_id or "")[:220]
        row.google_event_status = (payload.get("event_status") or target)[:24]
        row.google_event_html_link = (payload.get("html_link") or row.google_event_html_link or "")[:500]
        row.google_last_error = None
        db.commit()
        return {
            "ok": True,
            "google_event_id": row.google_event_id,
            "google_event_status": row.google_event_status,
            "google_event_html_link": row.google_event_html_link,
        }

    row.google_last_error = str(payload.get("error") or "google_sync_failed")[:300]
    db.commit()
    raise HTTPException(status_code=502, detail=row.google_last_error)


@router.get("/bookings/{booking_id}", response_model=AdminBookingDetail)
def booking_detail(
    booking_id: int,
    _: None = Depends(read_rate_limit),
    db: Session = Depends(get_db),
) -> AdminBookingDetail:
    b: Optional[Booking] = db.get(Booking, booking_id)
    if not b:
        raise HTTPException(status_code=404, detail="No encontrado")
    return _to_detail(b)


@router.post("/bookings/{booking_id}/validate", response_model=AdminBookingDetail)
def validate_payment(
    booking_id: int,
    _: None = Depends(write_rate_limit),
    db: Session = Depends(get_db),
) -> AdminBookingDetail:
    """Confirm receipt of the payment, generate the deliverables and email the
    private video link to the client."""
    b: Optional[Booking] = db.get(Booking, booking_id)
    if not b:
        raise HTTPException(status_code=404, detail="No encontrado")

    ensure_deliverables(b)
    if b.status != "paid":
        b.status = "paid"
        b.paid_at = b.paid_at or datetime.now(timezone.utc)

    ok, detail = send_video_link(b)
    if ok:
        b.link_emailed_at = datetime.now(timezone.utc)
    b.email_status = detail
    db.commit()
    return _to_detail(b)


@router.post("/bookings/{booking_id}/resend", response_model=AdminBookingDetail)
def resend_link(
    booking_id: int,
    _: None = Depends(write_rate_limit),
    db: Session = Depends(get_db),
) -> AdminBookingDetail:
    """Re-send the video link email for an already validated booking."""
    b: Optional[Booking] = db.get(Booking, booking_id)
    if not b:
        raise HTTPException(status_code=404, detail="No encontrado")
    if b.status != "paid" or not b.video_url:
        raise HTTPException(status_code=400, detail="La consulta aun no esta validada.")

    ok, detail = send_video_link(b)
    if ok:
        b.link_emailed_at = datetime.now(timezone.utc)
    b.email_status = detail
    db.commit()
    return _to_detail(b)

