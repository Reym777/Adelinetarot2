"""ORM model for persisted consultations (bookings).

Only the data needed to deliver the consultation is stored. No card/payment
secrets are ever persisted — PayPal handles the transaction out of band and we
keep just the resulting order id for reconciliation. The natal chart and report
are stored as computed by the server.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Optional

from sqlalchemy import Date, DateTime, Float, Integer, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    public_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Consultant (birth data)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), index=True)
    birth_date: Mapped[date] = mapped_column(Date)
    birth_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    birth_place: Mapped[str] = mapped_column(String(160))

    # Payment (authoritative, server-computed)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    plan: Mapped[str] = mapped_column(String(8))               # mxn | pen
    currency: Mapped[str] = mapped_column(String(3))           # MXN | PEN
    amount: Mapped[float] = mapped_column(Float)
    charge_currency: Mapped[str] = mapped_column(String(3), default="MXN")
    charge_amount: Mapped[float] = mapped_column(Float, default=0.0)
    paypal_order_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    stripe_session_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    payment_method: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # When the client declared the payment (claim) vs. when AdelineTarot validated
    # it (paid_at). The video link is only created/sent at validation time.
    payment_claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    link_emailed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    email_status: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)

    # Deliverables (generated on payment)
    video_room: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    chart_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    report_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Light audit trail
    client_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
