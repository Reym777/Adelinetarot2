"""Application configuration, loaded from environment / .env file.

Every security-relevant knob (CORS, allowed hosts, rate limits, body size,
admin secret, PayPal config) is configurable so the same code runs safely in
development and production by changing the environment only.
"""
from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Annotated, List, Union

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Directory that contains this backend package (…/AdelineTarot/backend).
BACKEND_DIR = Path(__file__).resolve().parent.parent


def _split_csv(value: Union[str, List[str]]) -> List[str]:
    """Parse a comma-separated string into a clean list of items."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    """Strongly-typed application settings."""

    model_config = SettingsConfigDict(
        env_prefix="ADELINE_",
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AdelineTarot API"
    debug: bool = False

    database_url: str = "sqlite:///./adelinetarot.db"

    # NoDecode lets these be provided as a comma-separated string in the
    # environment; the validator below splits them (otherwise pydantic-settings
    # would try to JSON-decode the value first and fail on plain CSV).
    cors_origins: Annotated[List[str], NoDecode] = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    allowed_hosts: Annotated[List[str], NoDecode] = ["localhost", "127.0.0.1"]

    serve_frontend: bool = True
    frontend_dir: str = ".."

    # Abuse protection
    max_request_bytes: int = 256 * 1024
    write_ratelimit_max: int = 12
    write_ratelimit_window: int = 60
    read_ratelimit_max: int = 90
    read_ratelimit_window: int = 60
    trust_proxy: bool = False

    # Admin (AdelineTarot) access. Override ADELINE_ADMIN_TOKEN in production.
    # When left empty a random token is generated at startup and logged once.
    admin_token: str = ""

    # Video calls — a unique Jitsi Meet room is built per booking. No API key
    # needed; the same URL is shared by the client and the admin.
    video_base_url: str = "https://meet.jit.si"
    video_room_prefix: str = "AdelineTarot"

    # Payment — PayPal. Drop your live/sandbox client id here to enable the
    # in-page PayPal buttons. The PayPal.Me handle powers the manual fallback.
    paypal_client_id: str = ""
    paypal_me_handle: str = "adelinetarot"
    # Advanced (server-side) PayPal. Adding the REST secret unlocks real, verified
    # captures done from the backend (the amount is never trusted from the client)
    # plus the Apple Pay and Google Pay buttons. ``paypal_env`` MUST match the
    # credentials ("live" for a live client id, "sandbox" for a sandbox one).
    paypal_secret: str = ""
    paypal_env: str = "live"
    # When True, a verified PayPal capture immediately delivers the video link by
    # email. Left False to honour the manual-validation workflow (AdelineTarot
    # still confirms from the admin panel, but sees the payment is PayPal-verified).
    paypal_auto_validate: bool = False
    # Apple Pay domain verification file contents (provided by PayPal). Served at
    # /.well-known/apple-developer-merchantid-domain-association when set.
    apple_pay_domain_association: str = ""
    # Optional override: a ready-made payment destination (e.g. a Stripe Payment
    # Link or a custom PayPal.Me). When set it is used as-is for the "Pay" button
    # instead of building a PayPal.Me URL from the handle.
    payment_link: str = ""
    # Extra instructions shown on the payment step (bank transfer, Yape/Plin…).
    payment_note: str = ""
    # Authoritative plan catalogue (currency -> amount). Never trust the client.
    price_mxn: float = 100.0
    price_pen: float = 20.0
    # PayPal cannot settle in PEN; the sol plan is charged as this USD value.
    price_pen_as_usd: float = 6.0

    # Payment — Stripe (hosted Checkout). Adding the secret key enables a
    # "Pay by card / Apple Pay / Google Pay" button: the customer is redirected
    # to Stripe's hosted page (which natively offers Apple Pay and Google Pay on
    # eligible devices) and sent back here. The amount is authoritative
    # (recomputed server-side) and Stripe handles all card data (PCI-compliant).
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    # When True a verified Stripe payment immediately delivers the link by email;
    # left False to honour the manual-validation workflow.
    stripe_auto_validate: bool = False
    # Public base URL used to build Stripe return URLs. When empty it is derived
    # from RENDER_EXTERNAL_HOSTNAME or the incoming request.
    public_base_url: str = ""

    # Email (SMTP) — the private video link is delivered ONLY by email, and only
    # after AdelineTarot validates the payment. Credentials come from the
    # environment exclusively (never hardcoded). Leave smtp_host empty to disable
    # sending (the admin panel then shows that mail is not configured).
    business_name: str = "AdelineTarot"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""            # defaults to smtp_user when empty
    smtp_use_tls: bool = True      # STARTTLS (port 587)
    smtp_use_ssl: bool = False     # implicit TLS (port 465)
    smtp_timeout: int = 20
    mail_reply_to: str = ""

    @field_validator("cors_origins", "allowed_hosts", mode="before")
    @classmethod
    def _parse_csv(cls, value: object) -> List[str]:
        if isinstance(value, str):
            return _split_csv(value)
        return value  # type: ignore[return-value]

    @property
    def frontend_path(self) -> Path:
        """Resolved absolute path to the folder holding index.html."""
        p = Path(self.frontend_dir)
        if not p.is_absolute():
            p = (BACKEND_DIR / p).resolve()
        return p

    @property
    def trusted_hosts(self) -> List[str]:
        """allowed_hosts augmented with the PaaS external hostname.

        Render (and similar hosts) expose the public hostname via an env var.
        Trusting it automatically means a deploy works out of the box without
        hardcoding the domain, while the configured default stays restrictive.
        """
        hosts = list(self.allowed_hosts)
        if "*" in hosts:
            return hosts
        for var in ("RENDER_EXTERNAL_HOSTNAME", "WEBSITE_HOSTNAME"):
            external = os.environ.get(var, "").strip()
            if external and external not in hosts:
                hosts.append(external)
        return hosts

    @property
    def resolved_admin_token(self) -> str:
        """Return the configured admin token, generating one if unset."""
        if not self.admin_token:
            object.__setattr__(self, "admin_token", secrets.token_urlsafe(24))
        return self.admin_token

    @property
    def effective_sender(self) -> str:
        """From address used for outgoing email (falls back to the SMTP user)."""
        return (self.smtp_from or self.smtp_user).strip()

    @property
    def mail_enabled(self) -> bool:
        """True when SMTP is configured enough to attempt sending."""
        return bool(self.smtp_host and self.effective_sender)

    @property
    def paypal_api_base(self) -> str:
        """REST API root, matching the configured environment."""
        if self.paypal_env.strip().lower() == "live":
            return "https://api-m.paypal.com"
        return "https://api-m.sandbox.paypal.com"

    @property
    def paypal_server_enabled(self) -> bool:
        """True when server-side capture (and Apple/Google Pay) can be used."""
        return bool(self.paypal_client_id and self.paypal_secret)

    @property
    def paypal_components(self) -> str:
        """JS SDK components to load (Apple/Google Pay need the secret)."""
        comps = ["buttons"]
        if self.paypal_server_enabled:
            comps.extend(["applepay", "googlepay"])
        return ",".join(comps)

    @property
    def stripe_enabled(self) -> bool:
        """True when Stripe hosted Checkout (card + Apple/Google Pay) is usable."""
        return bool(self.stripe_secret_key)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()


settings = get_settings()
