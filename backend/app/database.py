"""Database setup (SQLAlchemy 2.x).

Parameterized ORM queries are used everywhere, which structurally prevents SQL
injection. SQLite is the default; switch ``ADELINE_DATABASE_URL`` to Postgres
for production without code changes.
"""
from __future__ import annotations

from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

_connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables if they do not yet exist."""
    from . import models  # noqa: F401  (register models on the metadata)

    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns()


def _ensure_sqlite_columns() -> None:
    """Lightweight forward migration for SQLite.

    ``create_all`` never alters existing tables, so a database created by an
    earlier version is missing the newer payment-workflow columns. Add any that
    are absent (no-op when already present, or when not using SQLite).
    """
    if not settings.database_url.startswith("sqlite"):
        return

    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "bookings" not in inspector.get_table_names():
        return

    existing = {col["name"] for col in inspector.get_columns("bookings")}
    needed = {
        "payment_claimed_at": "DATETIME",
        "link_emailed_at": "DATETIME",
        "email_status": "VARCHAR(160)",
        "stripe_session_id": "VARCHAR(80)",
    }
    with engine.begin() as conn:
        for name, ddl in needed.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE bookings ADD COLUMN {name} {ddl}"))
