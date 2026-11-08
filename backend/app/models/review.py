"""Partner lines that arrived without an order ID, and returns confirmed by hand.

Both are low-volume and edited by people, so unlike the bulk ledger tables they keep their foreign keys.
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, one_of, utc_now
from app.models.enums import QUEUE_LINE_KINDS, QUEUE_STATUSES, RANKING_ENGINES


class UnmatchedLine(Base):
    """A settlement or COD remittance line with no order ID (and no usable AWB).

    It waits in the review queue with suggested orders. It is only ever linked to an order when a finance
    executive accepts a suggestion: nothing here is closed automatically.
    """

    __tablename__ = "unmatched_lines"
    __table_args__ = (
        one_of("kind", QUEUE_LINE_KINDS),
        one_of("status", QUEUE_STATUSES),
        one_of("engine", RANKING_ENGINES),
        # The same line uploaded twice waits in the queue once.
        UniqueConstraint("partner_id", "kind", "line_hash", name="uq_unmatched_lines_partner_kind_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id"), index=True)
    partner_id: Mapped[int] = mapped_column(ForeignKey("partners.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # settlement | cod_remittance
    row_number: Mapped[int] = mapped_column(Integer)
    line_date: Mapped[date | None] = mapped_column(Date)
    # Settlement amounts (zero for COD lines); `amount_paise` is the money the line pays: net or remitted.
    gross_paise: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    commission_paise: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    fees_paise: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    tcs_paise: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    tds_paise: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    awb: Mapped[str | None] = mapped_column(String(40))
    reference: Mapped[str | None] = mapped_column(String(120))  # partner's line reference or bank UTR
    line_hash: Mapped[str] = mapped_column(String(32))

    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open", index=True)
    # Rule shortlist, best first: [{order_id, rule_score, signals}]
    candidates_json: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    suggested_order_id: Mapped[str | None] = mapped_column(String(40))
    confidence: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text)
    engine: Mapped[str] = mapped_column(String(10), default="rules", server_default="rules")
    # Why the AI did not rank this line (no key, error, invalid answer); null when it did.
    ai_note: Mapped[str | None] = mapped_column(String(120))

    resolved_order_id: Mapped[str | None] = mapped_column(String(40))
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    # Server default too: lines are written in bulk with COPY, which skips ORM defaults.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, server_default=text("now()"))


class ManualReturnReceipt(Base):
    """A return a finance executive confirmed as received without a warehouse scan, with the reason why."""

    __tablename__ = "manual_return_receipts"

    order_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    received_on: Mapped[date] = mapped_column(Date)
    note: Mapped[str] = mapped_column(Text)
    marked_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    marked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
