"""Pydantic request/response schemas with strict input validation.

Defense in depth at the system boundary:
* ``extra="forbid"`` rejects unexpected fields (mass-assignment protection).
* Length / pattern constraints bound every string (anti-DoS, anti-injection).
* ``EmailStr`` enforces RFC-valid emails.
* A honeypot field silently traps naive spam bots.
* Free text is stripped of control characters and only ever returned as JSON
  (never rendered as server-side HTML), which avoids stored XSS.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timezone
from typing import Annotated, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_NAME_RE = re.compile(r"^[^\d<>@]{2,120}$")        # no digits, brackets or @
_PLACE_RE = re.compile(r"^[^<>]{2,160}$")


def _clean(value: str) -> str:
    return _CONTROL_RE.sub("", value).strip()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --------------------------------------------------------------------------- #
# Booking creation
# --------------------------------------------------------------------------- #
class BookingCreate(StrictModel):
    full_name: Annotated[str, Field(min_length=2, max_length=120)]
    email: EmailStr
    birth_date: date
    birth_time: Optional[time] = None
    birth_place: Annotated[str, Field(min_length=2, max_length=160)]
    plan: Literal["mxn", "pen"]
    # Honeypot — must stay empty. Bounded (not 0) so the router can trap bots.
    website: Annotated[str, Field(max_length=200)] = ""

    @field_validator("full_name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        v = _clean(v)
        if not _NAME_RE.match(v):
            raise ValueError("nombre no válido")
        return v

    @field_validator("birth_place")
    @classmethod
    def _valid_place(cls, v: str) -> str:
        v = _clean(v)
        if not _PLACE_RE.match(v):
            raise ValueError("lugar no válido")
        return v

    @field_validator("birth_date")
    @classmethod
    def _valid_birth(cls, v: date) -> date:
        today = datetime.now(timezone.utc).date()
        if v > today:
            raise ValueError("la fecha de nacimiento no puede estar en el futuro")
        if v.year < 1900:
            raise ValueError("fecha de nacimiento fuera de rango")
        return v


class BookingCreateResponse(BaseModel):
    reference: str
    public_token: str
    status: str
    plan: str
    currency: str
    amount: float
    charge_currency: str
    charge_amount: float
    paypal_client_id: str
    paypal_me_url: str
    payment_url: str
    payment_note: str
    message: str


# --------------------------------------------------------------------------- #
# Payment confirmation
# --------------------------------------------------------------------------- #
class PaymentConfirm(StrictModel):
    method: Literal["paypal", "paypalme"]
    paypal_order_id: Optional[Annotated[str, Field(max_length=64)]] = None
    website: Annotated[str, Field(max_length=200)] = ""

    @field_validator("paypal_order_id")
    @classmethod
    def _clean_order(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = _clean(v)
        if v and not re.match(r"^[A-Za-z0-9\-]{4,64}$", v):
            raise ValueError("identificador de pago no válido")
        return v or None


# --------------------------------------------------------------------------- #
# PayPal advanced (server-side order + capture)
# --------------------------------------------------------------------------- #
class PayPalOrderResponse(BaseModel):
    id: str


class PayPalCaptureRequest(StrictModel):
    order_id: Annotated[str, Field(min_length=6, max_length=40)]
    website: Annotated[str, Field(max_length=200)] = ""

    @field_validator("order_id")
    @classmethod
    def _valid_order(cls, v: str) -> str:
        v = _clean(v)
        if not re.match(r"^[A-Z0-9]{6,40}$", v):
            raise ValueError("identificador de orden no válido")
        return v


# --------------------------------------------------------------------------- #
# Stripe (hosted Checkout)
# --------------------------------------------------------------------------- #
class StripeCheckoutRequest(StrictModel):
    public_token: Annotated[str, Field(min_length=10, max_length=64)]
    website: Annotated[str, Field(max_length=200)] = ""


class StripeCheckoutResponse(BaseModel):
    id: str
    url: str


class StripeConfirmRequest(StrictModel):
    session_id: Annotated[str, Field(min_length=8, max_length=120)]

    @field_validator("session_id")
    @classmethod
    def _valid_session(cls, v: str) -> str:
        v = _clean(v)
        if not re.match(r"^cs_[A-Za-z0-9_]+$", v):
            raise ValueError("identificador de sesión no válido")
        return v



# --------------------------------------------------------------------------- #
# Client-facing status
#
# Deliberately omits the video link: it is delivered to the client ONLY by
# email, and only after AdelineTarot validates the payment. The client API
# never exposes the room URL.
# --------------------------------------------------------------------------- #
class BookingStatus(BaseModel):
    reference: str
    full_name: str
    status: str
    plan: str
    currency: str
    amount: float
    message: str


# --------------------------------------------------------------------------- #
# Admin views (AdelineTarot)
# --------------------------------------------------------------------------- #
class AdminBookingSummary(BaseModel):
    id: int
    reference: str
    full_name: str
    email: EmailStr
    birth_date: date
    birth_place: str
    status: str
    plan: str
    currency: str
    amount: float
    created_at: datetime
    paid_at: Optional[datetime] = None


class AdminBookingDetail(AdminBookingSummary):
    birth_time: Optional[time] = None
    charge_currency: str
    charge_amount: float
    payment_method: Optional[str] = None
    paypal_order_id: Optional[str] = None
    stripe_session_id: Optional[str] = None
    payment_claimed_at: Optional[datetime] = None
    link_emailed_at: Optional[datetime] = None
    email_status: Optional[str] = None
    video_url: Optional[str] = None
    video_room: Optional[str] = None
    chart: Optional[dict] = None
    report_text: Optional[str] = None
