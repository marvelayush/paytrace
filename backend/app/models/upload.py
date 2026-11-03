from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, one_of, utc_now
from app.models.enums import UPLOAD_STATUSES


class Upload(Base):
    __tablename__ = "uploads"
    __table_args__ = (one_of("status", UPLOAD_STATUSES),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    mapping_id: Mapped[int | None] = mapped_column(ForeignKey("column_mappings.id"))
    filename: Mapped[str] = mapped_column(String(255))
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    rows_ok: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class UploadRowError(Base):
    """A rejected row. Kept and shown to the user, never silently dropped."""

    __tablename__ = "upload_row_errors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
