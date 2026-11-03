from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, one_of, utc_now
from app.models.enums import FILE_KINDS, PARTNER_KINDS


class Partner(Base):
    __tablename__ = "partners"
    __table_args__ = (one_of("kind", PARTNER_KINDS),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    kind: Mapped[str] = mapped_column(String(20))
    # Days after delivery by which the money is due (A3).
    settlement_days: Mapped[int] = mapped_column(Integer, default=7)


class Source(Base):
    """One kind of file a partner sends us, such as the Marketplace 1 settlement report."""

    __tablename__ = "sources"
    __table_args__ = (
        one_of("file_kind", FILE_KINDS),
        UniqueConstraint("partner_id", "file_kind", name="uq_sources_partner_kind"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    partner_id: Mapped[int] = mapped_column(ForeignKey("partners.id"), index=True)
    file_kind: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(120))


class ColumnMapping(Base):
    """A versioned mapping from a source's columns to canonical fields. Old versions are kept for rollback."""

    __tablename__ = "column_mappings"
    __table_args__ = (UniqueConstraint("source_id", "version", name="uq_column_mappings_source_version"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    mapping_json: Mapped[dict] = mapped_column(JSONB)
    header_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_suggested_json: Mapped[dict | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)
