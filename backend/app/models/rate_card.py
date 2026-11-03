from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, one_of
from app.models.enums import FREIGHT_LEGS


class RateCard(Base):
    """Fees a partner charges, effective from a date. Percentages are basis points (1% = 100 bp)."""

    __tablename__ = "rate_cards"
    __table_args__ = (UniqueConstraint("partner_id", "effective_from", name="uq_rate_cards_partner_effective"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    partner_id: Mapped[int] = mapped_column(ForeignKey("partners.id"), index=True)
    effective_from: Mapped[date] = mapped_column(Date)
    commission_pct_bp: Mapped[int] = mapped_column(Integer, default=0)
    fixed_fee_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    cod_fee_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    cod_fee_pct_bp: Mapped[int] = mapped_column(Integer, default=0)
    gateway_pct_bp: Mapped[int] = mapped_column(Integer, default=0)
    tcs_pct_bp: Mapped[int] = mapped_column(Integer, default=0)
    tds_pct_bp: Mapped[int] = mapped_column(Integer, default=0)


class WeightSlab(Base):
    """Courier freight price for parcels up to `up_to_g` grams on one leg (A9)."""

    __tablename__ = "weight_slabs"
    __table_args__ = (
        one_of("leg", FREIGHT_LEGS),
        UniqueConstraint("rate_card_id", "leg", "up_to_g", name="uq_weight_slabs_card_leg_weight"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rate_card_id: Mapped[int] = mapped_column(ForeignKey("rate_cards.id", ondelete="CASCADE"), index=True)
    leg: Mapped[str] = mapped_column(String(10))
    up_to_g: Mapped[int] = mapped_column(Integer)
    price_paise: Mapped[int] = mapped_column(BigInteger)
