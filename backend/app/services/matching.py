"""Reconciliation engine: per order, what was expected, what was received, and what is wrong.

Everything is vectorised with Polars (hash joins and column expressions, no Python loop per row), so
1 lakh orders and their lines reconcile in seconds. Data is loaded from Postgres with COPY TO STDOUT and
results are written back with COPY, inside one transaction.

Expected amount: the same rules as `expected.py` (which is the readable reference; a test checks the two
agree), with the rate card in force on the order date (as-of join) and the courier's weight slab for the
chargeable weight (forward as-of join).

Received (A18) = settlement net + TCS + TDS withheld + COD remitted − courier charges invoiced.
Lines are matched to orders by order ID, or by AWB when a courier reports only the AWB (A24).

Status rules, first match wins:
  1. return_not_received  returned/RTO, no warehouse receipt, and the receipt window (A8/A23) has passed
  2. freight_overcharged   courier freight charged − expected freight > ₹10
  3. unpaid_past_due       delivered, nothing received, and the due date has passed
  4. pending               in transit, or nothing received yet but not yet due, or a return still within
                           its receipt window (A11: not money at risk)
  5. short_paid            received < expected − ₹10
  6. settled               otherwise (|difference| ≤ ₹10, or overpaid: flagged, A12)
"""

import io
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import polars as pl
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import ReconRun
from app.services.ingest import copy_frame

GAP_THRESHOLD_PAISE = 1_000  # ₹10 (brief, A5)
FLAGGED_STATUSES = ("return_not_received", "freight_overcharged", "unpaid_past_due", "short_paid")
INDIA = ZoneInfo("Asia/Kolkata")


def today_in_india() -> date:
    return datetime.now(INDIA).date()


# ---------- loading ----------

def _driver(db: Session):
    return db.connection().connection.driver_connection


def load_frame(db: Session, query: str, schema: dict[str, pl.DataType]) -> pl.DataFrame:
    """Run a query with COPY ... TO STDOUT and read the CSV straight into Polars."""
    buffer = io.BytesIO()
    with _driver(db).cursor() as cursor:
        with cursor.copy(f"COPY ({query}) TO STDOUT WITH (FORMAT csv, HEADER true)") as copy:
            for chunk in copy:
                buffer.write(chunk)
    buffer.seek(0)
    if buffer.getbuffer().nbytes == 0:
        return pl.DataFrame(schema=schema)
    return pl.read_csv(buffer, schema=schema)


@dataclass
class Inputs:
    orders: pl.DataFrame
    partners: pl.DataFrame
    rate_cards: pl.DataFrame
    slabs: pl.DataFrame
    settlements: pl.DataFrame
    cod: pl.DataFrame
    freight: pl.DataFrame
    receipts: pl.DataFrame


def load_inputs(db: Session) -> Inputs:
    i64, s, d = pl.Int64, pl.String, pl.Date
    return Inputs(
        orders=load_frame(db, "SELECT order_id, channel_partner_id, courier_partner_id, awb, order_date, delivered_date, returned_date, value_paise, payment_mode, delivery_status, dead_weight_g, volumetric_weight_g FROM orders", {
            "order_id": s, "channel_partner_id": i64, "courier_partner_id": i64, "awb": s, "order_date": d, "delivered_date": d,
            "returned_date": d, "value_paise": i64, "payment_mode": s, "delivery_status": s, "dead_weight_g": i64, "volumetric_weight_g": i64}),
        partners=load_frame(db, "SELECT id, kind, settlement_days FROM partners", {"id": i64, "kind": s, "settlement_days": i64}),
        rate_cards=load_frame(db, "SELECT id, partner_id, effective_from, commission_pct_bp, fixed_fee_paise, cod_fee_paise, cod_fee_pct_bp, gateway_pct_bp, tcs_pct_bp, tds_pct_bp FROM rate_cards", {
            "id": i64, "partner_id": i64, "effective_from": d, "commission_pct_bp": i64, "fixed_fee_paise": i64, "cod_fee_paise": i64,
            "cod_fee_pct_bp": i64, "gateway_pct_bp": i64, "tcs_pct_bp": i64, "tds_pct_bp": i64}),
        slabs=load_frame(db, "SELECT rate_card_id, leg, up_to_g, price_paise FROM weight_slabs", {"rate_card_id": i64, "leg": s, "up_to_g": i64, "price_paise": i64}),
        settlements=load_frame(db, "SELECT order_id, net_paise, tcs_paise, tds_paise FROM settlement_lines", {"order_id": s, "net_paise": i64, "tcs_paise": i64, "tds_paise": i64}),
        cod=load_frame(db, "SELECT order_id, awb, amount_paise FROM cod_remittances", {"order_id": s, "awb": s, "amount_paise": i64}),
        freight=load_frame(db, "SELECT order_id, awb, leg, freight_paise, cod_fee_paise FROM freight_lines", {
            "order_id": s, "awb": s, "leg": s, "freight_paise": i64, "cod_fee_paise": i64}),
        receipts=load_frame(db, "SELECT order_id, (received_at AT TIME ZONE 'Asia/Kolkata')::date AS received_on FROM warehouse_receipts", {"order_id": s, "received_on": d}),
    )


# ---------- expected amounts (vectorised mirror of expected.py) ----------

def percent_of(amount: pl.Expr, rate_bp: pl.Expr) -> pl.Expr:
    """Basis points of an amount, rounded half up to the paisa (symmetric for negatives), in integers."""
    rounded = (amount.abs() * rate_bp + 5_000) // 10_000
    return pl.when(amount < 0).then(-rounded).otherwise(rounded)


CARD_TERMS = ("commission_pct_bp", "fixed_fee_paise", "cod_fee_paise", "cod_fee_pct_bp", "gateway_pct_bp", "tcs_pct_bp", "tds_pct_bp")


def _card_in_force(orders: pl.DataFrame, cards: pl.DataFrame, partner_column: str, prefix: str) -> pl.DataFrame:
    """Attach the partner's rate card effective on the order date (the earliest card if the order is older)."""
    renamed = cards.select(
        pl.col("id").alias(f"{prefix}card_id"),
        pl.col("partner_id").alias(partner_column),
        pl.col("effective_from").alias(f"{prefix}effective_from"),
        *[pl.col(term).alias(f"{prefix}{term}") for term in CARD_TERMS],
    ).sort(f"{prefix}effective_from")
    joined = orders.sort("order_date").join_asof(
        renamed, left_on="order_date", right_on=f"{prefix}effective_from", by=partner_column, strategy="backward", check_sortedness=False
    )
    earliest = renamed.group_by(partner_column).agg(pl.all().sort_by(f"{prefix}effective_from").first())
    fallback_columns = [name for name in renamed.columns if name != partner_column]
    joined = joined.join(earliest, on=partner_column, how="left", suffix="_earliest")
    return joined.with_columns(
        pl.coalesce(pl.col(name), pl.col(f"{name}_earliest")).alias(name) for name in fallback_columns
    ).drop([f"{name}_earliest" for name in fallback_columns])


def _slab_price(orders: pl.DataFrame, slabs: pl.DataFrame, leg: str, alias: str) -> pl.DataFrame:
    """Price of the first slab covering the chargeable weight; heavier than the top slab -> top slab (A16)."""
    leg_slabs = slabs.filter(pl.col("leg") == leg).select(
        pl.col("rate_card_id").alias("cr_card_id"), pl.col("up_to_g"), pl.col("price_paise").alias(alias)
    ).sort("up_to_g")
    top = leg_slabs.sort("up_to_g").group_by("cr_card_id").agg(pl.col(alias).last().alias(f"{alias}_top"))
    priced = orders.sort("chargeable_weight_g").join_asof(
        leg_slabs, left_on="chargeable_weight_g", right_on="up_to_g", by="cr_card_id", strategy="forward", check_sortedness=False
    ).drop("up_to_g")
    priced = priced.join(top, on="cr_card_id", how="left")
    return priced.with_columns(pl.coalesce(alias, f"{alias}_top").fill_null(0).alias(alias)).drop(f"{alias}_top")


def expected_amounts(orders: pl.DataFrame, rate_cards: pl.DataFrame, slabs: pl.DataFrame) -> pl.DataFrame:
    """Add the itemised expected breakdown columns to the orders frame."""
    frame = _card_in_force(orders, rate_cards, "channel_partner_id", "ch_")
    # Courier card: null for orders the channel ships itself, so they carry no freight or COD fee.
    frame = _card_in_force(frame, rate_cards, "courier_partner_id", "cr_")
    frame = frame.with_columns(
        pl.max_horizontal(pl.col("dead_weight_g").fill_null(0), pl.col("volumetric_weight_g").fill_null(0)).alias("chargeable_weight_g")
    )
    frame = _slab_price(frame, slabs, "forward", "slab_forward")
    frame = _slab_price(frame, slabs, "return", "slab_return")

    status = pl.col("delivery_status")
    returned = status.is_in(["returned", "rto"])
    cancelled = status == "cancelled"
    normal = ~returned & ~cancelled
    value = pl.col("value_paise")
    has_courier = pl.col("cr_card_id").is_not_null()
    term = lambda name: pl.col(name).fill_null(0)  # noqa: E731 - short local helper for readability

    return frame.with_columns(
        pl.when(normal).then(value).otherwise(0).alias("exp_value"),
        pl.when(normal).then(percent_of(value, term("ch_commission_pct_bp"))).otherwise(0).alias("exp_commission"),
        pl.when(normal).then(term("ch_fixed_fee_paise")).otherwise(0).alias("exp_fixed_fee"),
        pl.when(normal & (pl.col("payment_mode") == "prepaid")).then(percent_of(value, term("ch_gateway_pct_bp"))).otherwise(0).alias("exp_gateway_fee"),
        pl.when(normal & (pl.col("payment_mode") == "cod") & has_courier)
        .then(term("cr_cod_fee_paise") + percent_of(value, term("cr_cod_fee_pct_bp"))).otherwise(0).alias("exp_cod_fee"),
        pl.when(cancelled | ~has_courier).then(0).otherwise(pl.col("slab_forward")).alias("exp_forward_freight"),
        pl.when(returned & has_courier).then(pl.col("slab_return")).otherwise(0).alias("exp_return_freight"),
        pl.when(normal).then(percent_of(value, term("ch_tcs_pct_bp"))).otherwise(0).alias("exp_tcs"),
        pl.when(normal).then(percent_of(value, term("ch_tds_pct_bp"))).otherwise(0).alias("exp_tds"),
    ).with_columns(
        (pl.col("exp_value") - pl.col("exp_commission") - pl.col("exp_fixed_fee") - pl.col("exp_gateway_fee")
         - pl.col("exp_cod_fee") - pl.col("exp_forward_freight") - pl.col("exp_return_freight")).alias("expected_paise"),
        (pl.col("exp_forward_freight") + pl.col("exp_return_freight")).alias("expected_freight_paise"),
    )


# ---------- received amounts ----------

def _resolve_order_ids(lines: pl.DataFrame, awb_to_order: pl.DataFrame) -> pl.DataFrame:
    """Lines that carry only an AWB get the order ID of the order with that AWB."""
    resolved = lines.join(awb_to_order, on="awb", how="left")
    return resolved.with_columns(pl.coalesce("order_id", "awb_order_id").alias("order_id")).drop("awb_order_id")


def received_amounts(inputs: Inputs) -> tuple[pl.DataFrame, dict[str, int]]:
    """One row per order with summed partner lines, plus counts of lines that matched no order."""
    awb_to_order = inputs.orders.filter(pl.col("awb").is_not_null()).select("awb", pl.col("order_id").alias("awb_order_id")).unique("awb")
    known = inputs.orders.select("order_id")

    settlement = inputs.settlements.group_by("order_id").agg(
        pl.col("net_paise").sum().alias("settled_net"),
        pl.col("tcs_paise").sum().alias("tcs_paise"),
        pl.col("tds_paise").sum().alias("tds_paise"),
        pl.len().alias("settlement_lines"),
    )
    cod = _resolve_order_ids(inputs.cod, awb_to_order).group_by("order_id").agg(
        pl.col("amount_paise").sum().alias("cod_remitted"), pl.len().alias("cod_lines")
    )
    freight = _resolve_order_ids(inputs.freight, awb_to_order).group_by("order_id").agg(
        pl.col("freight_paise").sum().alias("charged_freight_paise"),
        pl.col("cod_fee_paise").sum().alias("charged_cod_fee"),
        pl.len().alias("freight_lines"),
    )
    receipts = (
        inputs.receipts.join(awb_to_order.rename({"awb": "order_id", "awb_order_id": "resolved"}), on="order_id", how="left")
        .with_columns(pl.coalesce("resolved", "order_id").alias("order_id"))
        .group_by("order_id").agg(pl.col("received_on").min().alias("receipt_date"))
    )

    unmatched = {
        "settlement": settlement.join(known, on="order_id", how="anti")["settlement_lines"].sum() or 0,
        "cod": cod.join(known, on="order_id", how="anti")["cod_lines"].sum() or 0,
        "freight": freight.join(known, on="order_id", how="anti")["freight_lines"].sum() or 0,
    }

    combined = (
        known.join(settlement, on="order_id", how="left")
        .join(cod, on="order_id", how="left")
        .join(freight, on="order_id", how="left")
        .join(receipts, on="order_id", how="left")
        .with_columns(pl.col(pl.Int64).fill_null(0), pl.col(pl.UInt32).fill_null(0))
    )
    return combined, unmatched


# ---------- statuses ----------

def classify(frame: pl.DataFrame, partners: pl.DataFrame, as_of: date, return_window_days: int) -> pl.DataFrame:
    days = partners.select(pl.col("id"), pl.col("settlement_days"))
    frame = (
        frame.join(days.rename({"id": "channel_partner_id", "settlement_days": "channel_days"}), on="channel_partner_id", how="left")
        .join(days.rename({"id": "courier_partner_id", "settlement_days": "courier_days"}), on="courier_partner_id", how="left")
    )
    status = pl.col("delivery_status")
    returned = status.is_in(["returned", "rto"])
    delivered = status == "delivered"
    as_of_lit = pl.lit(as_of)

    # Who owes the money: the courier for COD it collected, otherwise the sales channel.
    paid_by_courier = (pl.col("payment_mode") == "cod") & pl.col("courier_partner_id").is_not_null()
    paying_partner = pl.when(paid_by_courier).then(pl.col("courier_partner_id")).otherwise(pl.col("channel_partner_id"))
    paying_days = pl.when(paid_by_courier).then(pl.col("courier_days")).otherwise(pl.col("channel_days")).fill_null(7)
    payment_due = pl.col("delivered_date") + pl.duration(days=paying_days)

    window_end = pl.col("returned_date") + pl.duration(days=return_window_days)
    no_receipt = pl.col("receipt_date").is_null()
    return_lost = returned & no_receipt & (as_of_lit > window_end)
    return_waiting = returned & no_receipt & (as_of_lit <= window_end)
    freight_excess = pl.col("charged_freight_paise") - pl.col("expected_freight_paise")
    overcharged = (pl.col("freight_lines") > 0) & (freight_excess > GAP_THRESHOLD_PAISE)
    nothing_received = (pl.col("settlement_lines") + pl.col("cod_lines")) == 0
    unpaid_past_due = delivered & nothing_received & (pl.col("expected_paise") > 0) & (as_of_lit > payment_due)
    not_yet_due = delivered & nothing_received & (as_of_lit <= payment_due)
    pending = (status == "in_transit") | not_yet_due | return_waiting
    difference = pl.col("diff_paise")

    frame = frame.with_columns(
        (pl.col("settled_net") + pl.col("tcs_paise") + pl.col("tds_paise") + pl.col("cod_remitted")
         - pl.col("charged_freight_paise") - pl.col("charged_cod_fee")).alias("received_paise"),
    ).with_columns((pl.col("received_paise") - pl.col("expected_paise")).alias("diff_paise"))

    frame = frame.with_columns(
        pl.when(return_lost).then(pl.lit("return_not_received"))
        .when(overcharged).then(pl.lit("freight_overcharged"))
        .when(unpaid_past_due).then(pl.lit("unpaid_past_due"))
        .when(pending).then(pl.lit("pending"))
        .when(difference < -GAP_THRESHOLD_PAISE).then(pl.lit("short_paid"))
        .otherwise(pl.lit("settled"))
        .alias("status"),
    )
    shortfall = pl.max_horizontal(-difference, pl.lit(0))
    freight_due = pl.coalesce("returned_date", "delivered_date", "order_date") + pl.duration(days=pl.col("courier_days").fill_null(10))
    frame = frame.with_columns(
        (pl.col("status").eq("settled") & (difference > GAP_THRESHOLD_PAISE)).alias("overpaid"),
        pl.when(pl.col("status") == "return_not_received").then(pl.col("value_paise") + shortfall)
        .when(pl.col("status").is_in(["freight_overcharged", "unpaid_past_due", "short_paid"])).then(shortfall)
        .otherwise(0).alias("at_risk_paise"),
        pl.when(pl.col("status") == "return_not_received").then(window_end)
        .when(pl.col("status") == "freight_overcharged").then(freight_due)
        .otherwise(payment_due).alias("due_date"),
        pl.when(pl.col("status") == "return_not_received")
        .then(pl.coalesce("courier_partner_id", "channel_partner_id"))
        .when(pl.col("status") == "freight_overcharged").then(pl.col("courier_partner_id"))
        .otherwise(paying_partner).alias("partner_id"),
    )
    return frame.with_columns(
        pl.when(pl.col("due_date").is_null()).then(None)
        .otherwise(pl.max_horizontal((as_of_lit - pl.col("due_date")).dt.total_days(), pl.lit(0)))
        .cast(pl.Int32).alias("age_days")
    )


# ---------- the whole run ----------

BREAKDOWN_FIELDS = {
    "value": "exp_value", "commission": "exp_commission", "fixed_fee": "exp_fixed_fee", "gateway_fee": "exp_gateway_fee",
    "cod_fee": "exp_cod_fee", "forward_freight": "exp_forward_freight", "return_freight": "exp_return_freight",
    "tcs": "exp_tcs", "tds": "exp_tds", "chargeable_weight_g": "chargeable_weight_g",
    "rate_card_id": "ch_card_id", "courier_rate_card_id": "cr_card_id",
}
EVIDENCE_FIELDS = {
    "settlement_lines": "settlement_lines", "cod_lines": "cod_lines", "freight_lines": "freight_lines",
    "settled_net": "settled_net", "cod_remitted": "cod_remitted", "charged_cod_fee": "charged_cod_fee",
    "receipt_date": "receipt_date",
}
RESULT_COLUMNS = [
    "run_id", "order_id", "partner_id", "expected_paise", "received_paise", "diff_paise", "at_risk_paise",
    "expected_freight_paise", "charged_freight_paise", "tcs_paise", "tds_paise", "expected_breakdown_json",
    "evidence_json", "status", "overpaid", "due_date", "age_days",
]


def reconcile(inputs: Inputs, as_of: date, return_window_days: int) -> tuple[pl.DataFrame, dict[str, int]]:
    """Pure function: inputs -> one result row per order. No database access (used by tests and the benchmark)."""
    expected = expected_amounts(inputs.orders, inputs.rate_cards, inputs.slabs)
    received, unmatched = received_amounts(inputs)
    combined = expected.join(received, on="order_id", how="left")
    results = classify(combined, inputs.partners, as_of, return_window_days)
    return results, unmatched


def _results_for_copy(results: pl.DataFrame, run_id: int) -> pl.DataFrame:
    return results.select(
        pl.lit(run_id).alias("run_id"),
        "order_id",
        "partner_id",
        "expected_paise",
        "received_paise",
        "diff_paise",
        "at_risk_paise",
        "expected_freight_paise",
        "charged_freight_paise",
        "tcs_paise",
        "tds_paise",
        pl.struct([pl.col(column).alias(name) for name, column in BREAKDOWN_FIELDS.items()]).struct.json_encode().alias("expected_breakdown_json"),
        pl.struct([pl.col(column).alias(name) for name, column in EVIDENCE_FIELDS.items()]).struct.json_encode().alias("evidence_json"),
        "status",
        "overpaid",
        "due_date",
        "age_days",
    )


@dataclass
class RunSummary:
    run_id: int
    as_of: date
    order_count: int
    duration_ms: int
    stage_ms: dict[str, int] = field(default_factory=dict)
    status_counts: dict[str, int] = field(default_factory=dict)
    money_at_risk_paise: int = 0
    auto_matched_pct: float = 0.0
    unmatched_lines: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id, "as_of": self.as_of.isoformat(), "order_count": self.order_count,
            "duration_ms": self.duration_ms, "stage_ms": self.stage_ms, "status_counts": self.status_counts,
            "money_at_risk_paise": self.money_at_risk_paise, "auto_matched_pct": self.auto_matched_pct,
            "unmatched_lines": self.unmatched_lines,
        }


def auto_match_rate(results: pl.DataFrame) -> float:
    """Share of orders where money should have moved that were linked to at least one partner line automatically."""
    eligible = results.filter(pl.col("delivery_status").is_in(["delivered", "returned", "rto"]) & (pl.col("status") != "pending"))
    if eligible.is_empty():
        return 0.0
    matched = eligible.filter((pl.col("settlement_lines") + pl.col("cod_lines") + pl.col("freight_lines")) > 0).height
    return round(100 * matched / eligible.height, 2)


def run_reconciliation(db: Session, started_by: int | None, as_of: date | None = None, return_window_days: int = 7) -> RunSummary:
    """Load -> match -> write in one transaction. Only the latest run's results are kept (older runs keep their stats)."""
    as_of = as_of or today_in_india()
    started = time.perf_counter()
    stage_ms: dict[str, int] = {}

    def lap(name: str, since: float) -> float:
        now = time.perf_counter()
        stage_ms[name] = int((now - since) * 1000)
        return now

    # One run at a time (a second request waits for the first to finish).
    db.execute(text("SELECT pg_advisory_xact_lock(4242)"))
    run = ReconRun(started_by=started_by, as_of=as_of, started_at=datetime.now(timezone.utc))
    db.add(run)
    db.flush()

    mark = time.perf_counter()
    inputs = load_inputs(db)
    mark = lap("load", mark)
    results, unmatched = reconcile(inputs, as_of, return_window_days)
    mark = lap("match", mark)
    db.execute(text("DELETE FROM recon_results"))
    copy_frame(db, "recon_results", _results_for_copy(results, run.id))
    mark = lap("write", mark)

    counts = dict(zip(*results["status"].value_counts().sort("status").to_dict(as_series=False).values()))
    summary = RunSummary(
        run_id=run.id,
        as_of=as_of,
        order_count=results.height,
        duration_ms=int((time.perf_counter() - started) * 1000),
        stage_ms=stage_ms,
        status_counts={status: int(count) for status, count in counts.items()},
        money_at_risk_paise=int(results.filter(pl.col("status").is_in(FLAGGED_STATUSES))["at_risk_paise"].sum() or 0),
        auto_matched_pct=auto_match_rate(results),
        unmatched_lines={kind: int(count) for kind, count in unmatched.items()},
    )
    run.finished_at = datetime.now(timezone.utc)
    run.order_count = summary.order_count
    run.duration_ms = summary.duration_ms
    run.stats_json = summary.as_dict()
    db.flush()
    return summary
