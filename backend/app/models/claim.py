from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, one_of, utc_now
from app.models.enums import CLAIM_STATUSES, RECON_STATUSES


class Claim(Base):
    """A claim against one partner. Status changes are manual (A7)."""

    __tablename__ = "claims"
    __table_args__ = (one_of("status", CLAIM_STATUSES),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    partner_id: Mapped[int] = mapped_column(ForeignKey("partners.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    total_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class ClaimItem(Base):
    __tablename__ = "claim_items"
    __table_args__ = (one_of("reason_status", RECON_STATUSES),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    order_id: Mapped[str] = mapped_column(String(40), index=True)
    reason_status: Mapped[str] = mapped_column(String(30))
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    evidence_json: Mapped[dict] = mapped_column(JSONB)
