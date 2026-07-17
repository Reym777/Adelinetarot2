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
    appointment_date: Optional[date] = None
    appointment_time: Optional[time] = None
    plan: Literal["mxn", "pen"]
    # Honeypot â€” must stay empty. Bounded (not 0) so the router can trap bots.
    website: Annotated[str, Field(max_length=200)] = ""

    @field_validator("full_name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        v = _clean(v)
        if not _NAME_RE.match(v):
            raise ValueError("nombre no vÃ¡lido")
        return v

    @field_validator("birth_place")
    @classmethod
    def _valid_place(cls, v: str) -> str:
        v = _clean(v)
        if not _PLACE_RE.match(v):
            raise ValueError("lugar no vÃ¡lido")
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
            raise ValueError("identificador de pago no vÃ¡lido")
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
            raise ValueError("identificador de orden no vÃ¡lido")
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
            raise ValueError("identificador de sesiÃ³n no vÃ¡lido")
        return v


class StripeServiceCheckoutRequest(StrictModel):
    service: Literal["meditaciones", "oraciones", "tarot"]
    first_name: Annotated[str, Field(min_length=2, max_length=80)]
    last_name: Annotated[str, Field(min_length=2, max_length=80)]
    email: EmailStr
    appointment_date: Optional[Annotated[str, Field(max_length=20)]] = None
    appointment_time: Optional[Annotated[str, Field(max_length=10)]] = None
    notes: Optional[Annotated[str, Field(max_length=600)]] = None
    tarot_duration: Optional[int] = None
    recorded: bool = False
    embedded: bool = True
    website: Annotated[str, Field(max_length=200)] = ""

    @field_validator("first_name", "last_name")
    @classmethod
    def _valid_service_name(cls, v: str) -> str:
        v = _clean(v)
        if not _NAME_RE.match(v):
            raise ValueError("nombre no vÃ¡lido")
        return v

    @field_validator("appointment_date", "appointment_time", "notes")
    @classmethod
    def _clean_optional_text(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = _clean(v)
        return cleaned or None


class StripeInvoiceCreateRequest(StrictModel):
    email: EmailStr
    customer_name: Annotated[str, Field(min_length=2, max_length=120)]
    description: Annotated[str, Field(min_length=3, max_length=200)]
    amount: float
    currency: Annotated[str, Field(min_length=3, max_length=3)] = "USD"
    due_days: int = 7
    website: Annotated[str, Field(max_length=200)] = ""

    @field_validator("customer_name", "description")
    @classmethod
    def _clean_invoice_text(cls, v: str) -> str:
        v = _clean(v)
        if len(v) < 2:
            raise ValueError("valor no vÃ¡lido")
        return v

    @field_validator("currency")
    @classmethod
    def _clean_currency(cls, v: str) -> str:
        c = _clean(v).upper()
        if not re.match(r"^[A-Z]{3}$", c):
            raise ValueError("divisa no vÃ¡lida")
        return c

    @field_validator("amount")
    @classmethod
    def _valid_amount(cls, v: float) -> float:
        if float(v) <= 0:
            raise ValueError("importe no vÃ¡lido")
        return float(v)

    @field_validator("due_days")
    @classmethod
    def _valid_due_days(cls, v: int) -> int:
        safe = int(v)
        if safe < 1 or safe > 60:
            raise ValueError("due_days fuera de rango")
        return safe


class StripeInvoiceCreateResponse(BaseModel):
    id: str
    hosted_invoice_url: Optional[str] = None


class StripeServiceCheckoutResponse(BaseModel):
    id: str
    url: Optional[str] = None
    client_secret: Optional[str] = None


class StripeDirectIntakeRequest(StrictModel):
    service: Literal["meditaciones", "oraciones", "paquete-magica", "tarot-terapeutico"]
    first_name: Annotated[str, Field(min_length=2, max_length=80)]
    last_name: Annotated[str, Field(min_length=2, max_length=80)]
    email: EmailStr
    appointment_date: Optional[Annotated[str, Field(max_length=40)]] = None
    appointment_time: Optional[Annotated[str, Field(max_length=20)]] = None
    notes: Optional[Annotated[str, Field(max_length=1200)]] = None
    tarot_duration: Optional[int] = None
    meditation_sessions: Optional[Annotated[int, Field(ge=1, le=12)]] = 1
    recorded: bool = False
    website: Annotated[str, Field(max_length=200)] = ""

    @field_validator("first_name", "last_name")
    @classmethod
    def _valid_direct_name(cls, v: str) -> str:
        v = _clean(v)
        if not _NAME_RE.match(v):
            raise ValueError("nombre no vÃ¡lido")
        return v

    @field_validator("appointment_date", "appointment_time", "notes")
    @classmethod
    def _clean_direct_optional(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = _clean(v)
        return cleaned or None


class StripeDirectIntakeResponse(BaseModel):
    ok: bool
    payment_url: str


# --------------------------------------------------------------------------- #
# Contact requests
# --------------------------------------------------------------------------- #
class ContactRequest(StrictModel):
    first_name: Annotated[str, Field(min_length=2, max_length=80)]
    last_name: Annotated[str, Field(min_length=2, max_length=80)]
    email: EmailStr
    message: Annotated[str, Field(min_length=10, max_length=2000)]
    website: Annotated[str, Field(max_length=200)] = ""

    @field_validator("first_name", "last_name")
    @classmethod
    def _valid_contact_name(cls, v: str) -> str:
        v = _clean(v)
        if not _NAME_RE.match(v):
            raise ValueError("nombre no vÃ¡lido")
        return v

    @field_validator("message")
    @classmethod
    def _valid_message(cls, v: str) -> str:
        v = _clean(v)
        if len(v) < 10:
            raise ValueError("mensaje demasiado corto")
        return v


class ContactResponse(BaseModel):
    ok: bool
    message: str


# --------------------------------------------------------------------------- #
# Articles
# --------------------------------------------------------------------------- #
class ArticleCreate(StrictModel):
    title: Annotated[str, Field(min_length=3, max_length=180)]
    subtitle: Optional[Annotated[str, Field(max_length=260)]] = None
    hero_image: Optional[Annotated[str, Field(max_length=600)]] = None
    excerpt: Optional[Annotated[str, Field(max_length=360)]] = None
    content: Annotated[str, Field(min_length=80, max_length=1200000)]

    @field_validator("title", "subtitle", "excerpt", "content")
    @classmethod
    def _clean_article_text(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = _clean(v)
        return cleaned or None

    @field_validator("hero_image")
    @classmethod
    def _valid_hero_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = _clean(v)
        if not cleaned:
            return None
        if not re.match(r"^https?://[^\s]+$", cleaned):
            raise ValueError("url de imagen no válida")
        return cleaned


class ArticleSummary(BaseModel):
    slug: str
    title: str
    subtitle: Optional[str] = None
    excerpt: Optional[str] = None
    hero_image: Optional[str] = None
    author_name: str
    created_at: datetime


class ArticleDetail(ArticleSummary):
    content: str


class ArticleImport(ArticleCreate):
    slug: Optional[Annotated[str, Field(max_length=220)]] = None
    author_name: Optional[Annotated[str, Field(max_length=120)]] = None
    is_published: Optional[int] = 1
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ArticleDraftSave(StrictModel):
    slug: Optional[Annotated[str, Field(max_length=220)]] = None
    title: Annotated[str, Field(min_length=1, max_length=180)]
    content: Annotated[str, Field(min_length=1, max_length=1200000)]


class ArticleEmailRequest(StrictModel):
    slug: Optional[Annotated[str, Field(max_length=220)]] = None
    title: Annotated[str, Field(min_length=1, max_length=180)]
    content: Annotated[str, Field(min_length=1, max_length=1200000)]



# --------------------------------------------------------------------------- #
# Client-facing status
#
# Deliberately omits the video link: it is delivered to the client ONLY by
# email, and only after Adelinemagica validates the payment. The client API
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


class TarotAvailabilitySlot(BaseModel):
    time: str
    available: bool


class TarotAvailabilityDay(BaseModel):
    date: str
    label: str
    slots: List[TarotAvailabilitySlot]


class TarotAvailabilityResponse(BaseModel):
    timezone: str
    days: List[TarotAvailabilityDay]


# --------------------------------------------------------------------------- #
# Admin views (Adelinemagica)
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


class AdminDashboardTotals(BaseModel):
    month: dict
    year: dict


class AdminDashboardResponse(BaseModel):
    upcoming_citas: List[dict]
    recent_payments: List[dict]
    totals: AdminDashboardTotals
    visits_yesterday: int
    recent_client_emails: List[str]

