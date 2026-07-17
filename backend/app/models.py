"""ORM model for persisted consultations (bookings).

Only the data needed to deliver the consultation is stored. No card/payment
secrets are ever persisted â€” PayPal handles the transaction out of band and we
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
    appointment_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    appointment_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)

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
    # When the client declared the payment (claim) vs. when Adelinemagica validated
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


class PageVisit(Base):
    __tablename__ = "page_visits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    path: Mapped[str] = mapped_column(String(120), index=True)
    hits: Mapped[int] = mapped_column(Integer, default=0)


class DirectPaymentIntake(Base):
    __tablename__ = "direct_payment_intakes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    service: Mapped[str] = mapped_column(String(32), index=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(254), index=True)
    appointment_date: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    appointment_time: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    stripe_session_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    stripe_payment_link_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    appointment_start_at: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    appointment_end_at: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    video_room: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    google_event_id: Mapped[Optional[str]] = mapped_column(String(220), nullable=True)
    google_event_status: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    google_event_html_link: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    google_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    google_last_error: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(180))
    subtitle: Mapped[Optional[str]] = mapped_column(String(260), nullable=True)
    hero_image: Mapped[Optional[str]] = mapped_column(String(600), nullable=True)
    excerpt: Mapped[Optional[str]] = mapped_column(String(360), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    author_name: Mapped[str] = mapped_column(String(120), default="Adeline")
    is_published: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

