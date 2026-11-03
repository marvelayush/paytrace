"""Normalised partner data: orders, and every line that pays for or charges against them."""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, one_of
from app.models.enums import DELIVERY_STATUSES, FREIGHT_LEGS, PAYMENT_MODES


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (one_of("payment_mode", PAYMENT_MODES), one_of("delivery_status", DELIVERY_STATUSES))

    order_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    channel_partner_id: Mapped[int] = mapped_column(ForeignKey("partners.id"), index=True)
    courier_partner_id: Mapped[int | None] = mapped_column(ForeignKey("partners.id"), index=True)
    # Courier tracking number; COD remittances and freight lines may reference it instead of order_id.
    awb: Mapped[str | None] = mapped_column(String(40), index=True)
    order_date: Mapped[date] = mapped_column(Date)
    delivered_date: Mapped[date | None] = mapped_column(Date)
    # Date the courier marked the order returned / RTO; starts the A8 warehouse-receipt window.
    returned_date: Mapped[date | None] = mapped_column(Date)
    value_paise: Mapped[int] = mapped_column(BigInteger)
    payment_mode: Mapped[str] = mapped_column(String(10))
    delivery_status: Mapped[str] = mapped_column(String(20))
    dead_weight_g: Mapped[int | None] = mapped_column(Integer)
    volumetric_weight_g: Mapped[int | None] = mapped_column(Integer)
    # PII is masked at ingestion; raw values are never stored (DPDP Act 2023).
    customer_name_masked: Mapped[str | None] = mapped_column(String(80))
    customer_phone_masked: Mapped[str | None] = mapped_column(String(20))
    pincode: Mapped[str | None] = mapped_column(String(10))


class SettlementLine(Base):
    __tablename__ = "settlement_lines"
    __table_args__ = (UniqueConstraint("partner_id", "line_hash", name="uq_settlement_lines_partner_hash"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), index=True)
    partner_id: Mapped[int] = mapped_column(ForeignKey("partners.id"), index=True)
    order_id: Mapped[str] = mapped_column(String(40), index=True)
    settlement_date: Mapped[date | None] = mapped_column(Date)
    gross_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    commission_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    fees_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    tcs_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    tds_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    net_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    raw_ref: Mapped[str | None] = mapped_column(String(120))  # partner's own line reference, if any
    # Hash of the canonical values: the same line uploaded twice is stored once.
    line_hash: Mapped[str] = mapped_column(String(32))
    row_number: Mapped[int] = mapped_column(Integer)  # 1-based data row in the uploaded file (evidence)


class CodRemittance(Base):
    __tablename__ = "cod_remittances"
    __table_args__ = (UniqueConstraint("courier_partner_id", "line_hash", name="uq_cod_remittances_partner_hash"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), index=True)
    courier_partner_id: Mapped[int] = mapped_column(ForeignKey("partners.id"), index=True)
    order_id: Mapped[str | None] = mapped_column(String(40), index=True)
    awb: Mapped[str | None] = mapped_column(String(40), index=True)
    remittance_date: Mapped[date | None] = mapped_column(Date)
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    utr: Mapped[str | None] = mapped_column(String(40))
    # Hash of the canonical values: the same line uploaded twice is stored once.
    line_hash: Mapped[str] = mapped_column(String(32))
    row_number: Mapped[int] = mapped_column(Integer)  # 1-based data row in the uploaded file (evidence)


class FreightLine(Base):
    __tablename__ = "freight_lines"
    __table_args__ = (
        one_of("leg", FREIGHT_LEGS),
        UniqueConstraint("courier_partner_id", "line_hash", name="uq_freight_lines_partner_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), index=True)
    courier_partner_id: Mapped[int] = mapped_column(ForeignKey("partners.id"), index=True)
    order_id: Mapped[str | None] = mapped_column(String(40), index=True)
    awb: Mapped[str | None] = mapped_column(String(40), index=True)
    charged_weight_g: Mapped[int | None] = mapped_column(Integer)
    leg: Mapped[str] = mapped_column(String(10))
    freight_paise: Mapped[int] = mapped_column(BigInteger)
    # COD handling fee billed on the same invoice line (0 for prepaid).
    cod_fee_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    invoice_no: Mapped[str | None] = mapped_column(String(40))
    # Hash of the canonical values: the same line uploaded twice is stored once.
    line_hash: Mapped[str] = mapped_column(String(32))
    row_number: Mapped[int] = mapped_column(Integer)  # 1-based data row in the uploaded file (evidence)


class WarehouseReceipt(Base):
    __tablename__ = "warehouse_receipts"
    __table_args__ = (UniqueConstraint("line_hash", name="uq_warehouse_receipts_hash"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), index=True)
    order_id: Mapped[str] = mapped_column(String(40), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Hash of the canonical values: the same line uploaded twice is stored once.
    line_hash: Mapped[str] = mapped_column(String(32))
    row_number: Mapped[int] = mapped_column(Integer)  # 1-based data row in the uploaded file (evidence)
