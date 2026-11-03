from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, one_of, utc_now
from app.models.enums import RECON_STATUSES


class ReconRun(Base):
    __tablename__ = "recon_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    started_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    as_of: Mapped[date] = mapped_column(Date)  # "today" used for due dates and ages
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    order_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    # Per-stage timings and status counts, shown in the UI and the benchmark.
    stats_json: Mapped[dict | None] = mapped_column(JSONB)


class ReconResult(Base):
    """One row per order per run. Written in bulk with Postgres COPY."""

    __tablename__ = "recon_results"
    __table_args__ = (one_of("status", RECON_STATUSES),)

    run_id: Mapped[int] = mapped_column(ForeignKey("recon_runs.id", ondelete="CASCADE"), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(40), primary_key=True, index=True)
    partner_id: Mapped[int] = mapped_column(ForeignKey("partners.id"), index=True)
    expected_paise: Mapped[int] = mapped_column(BigInteger)
    received_paise: Mapped[int] = mapped_column(BigInteger)
    diff_paise: Mapped[int] = mapped_column(BigInteger)
    # What we would claim for this order (0 when settled or pending). For lost returns this is the goods value.
    at_risk_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    expected_freight_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    charged_freight_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    # Taxes are kept apart from the difference: tax is not leakage (A6).
    tcs_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    tds_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    expected_breakdown_json: Mapped[dict] = mapped_column(JSONB)
    evidence_json: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(30), index=True)
    overpaid: Mapped[bool] = mapped_column(Boolean, default=False)  # A12
    due_date: Mapped[date | None] = mapped_column(Date)
    age_days: Mapped[int | None] = mapped_column(Integer)
