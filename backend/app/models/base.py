from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, MetaData
from sqlalchemy.orm import DeclarativeBase

# Stable constraint names so Alembic migrations are deterministic.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def one_of(column: str, values: tuple[str, ...]) -> CheckConstraint:
    """CHECK constraint limiting a text column to a fixed set (used instead of native ENUM types)."""
    allowed = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=f"{column}_allowed")
