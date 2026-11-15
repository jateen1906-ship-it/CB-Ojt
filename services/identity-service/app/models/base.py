"""SQLAlchemy declarative base and shared UTC timestamp helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import DeclarativeBase


def utc_now() -> datetime:
    """Return current UTC datetime for SQLAlchemy column defaults."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base for all Identity Service ORM models."""

