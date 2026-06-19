"""Admin endpoints (AdelineTarot).

Every route is guarded by a constant-time admin-token check (sent in the
``X-Admin-Token`` header). AdelineTarot reviews each booking, validates that she
received the payment, and triggers delivery of the private video link by email
(the link is never shown to the client on the website).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..delivery import ensure_deliverables
from ..mailer import send_video_link
from ..models import Booking
from ..schemas import AdminBookingDetail, AdminBookingSummary
from ..security import read_rate_limit, require_admin, write_rate_limit

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


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
