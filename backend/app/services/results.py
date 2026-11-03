"""Reading reconciliation results: filtered order lists and the full evidence for one order."""

from dataclasses import dataclass

from sqlalchemy import and_, case, func, literal, or_, select
from sqlalchemy.orm import Session, aliased

from app.models import (
    CodRemittance,
    FreightLine,
    Order,
    Partner,
    ReconResult,
    SettlementLine,
    Upload,
    WarehouseReceipt,
)
from app.services.matching import FLAGGED_STATUSES

# Money-at-risk age buckets (A4): days since the amount became due.
AGE_BUCKETS = ("0-15", "16-30", "31-60", "60+")
SORTS = {
    "at_risk": (ReconResult.at_risk_paise.desc(), ReconResult.order_id),
    "difference": (ReconResult.diff_paise.asc(), ReconResult.order_id),
    "age": (ReconResult.age_days.desc().nulls_last(), ReconResult.order_id),
    "order_date": (Order.order_date.desc(), ReconResult.order_id),
    "order_id": (ReconResult.order_id,),
}


def age_bucket_expr():
    age = ReconResult.age_days
    return case(
        (age.is_(None), literal(None)),
        (age <= 15, literal("0-15")),
        (age <= 30, literal("16-30")),
        (age <= 60, literal("31-60")),
        else_=literal("60+"),
    )


def _bucket_condition(bucket: str):
    age = ReconResult.age_days
    return {
        "0-15": age <= 15,
        "16-30": and_(age > 15, age <= 30),
        "31-60": and_(age > 30, age <= 60),
        "60+": age > 60,
    }[bucket]


@dataclass
class OrderFilters:
    partner_id: int | None = None
    statuses: list[str] | None = None  # "flagged" expands to every flagged status
    age_bucket: str | None = None
    search: str | None = None


def _conditions(filters: OrderFilters) -> list:
    conditions = []
    if filters.partner_id is not None:
        conditions.append(ReconResult.partner_id == filters.partner_id)
    if filters.statuses:
        statuses = set()
        for status in filters.statuses:
            statuses.update(FLAGGED_STATUSES if status == "flagged" else [status])
        conditions.append(ReconResult.status.in_(sorted(statuses)))
    if filters.age_bucket:
        conditions.append(_bucket_condition(filters.age_bucket))
        conditions.append(ReconResult.status.in_(FLAGGED_STATUSES))  # ageing is about money at risk
    if filters.search:
        term = f"%{filters.search.strip()}%"
        conditions.append(or_(ReconResult.order_id.ilike(term), Order.awb.ilike(term)))
    return conditions


def list_orders(db: Session, filters: OrderFilters, sort: str, offset: int, limit: int) -> dict:
    channel = aliased(Partner)
    responsible = aliased(Partner)
    base = (
        select(ReconResult, Order, channel.name.label("channel_name"), responsible.name.label("partner_name"))
        .join(Order, Order.order_id == ReconResult.order_id)
        .join(channel, channel.id == Order.channel_partner_id)
        .join(responsible, responsible.id == ReconResult.partner_id)
        .where(*_conditions(filters))
    )
    rows = db.execute(base.order_by(*SORTS.get(sort, SORTS["at_risk"])).offset(offset).limit(limit)).all()

    totals_query = (
        select(
            func.count(),
            func.coalesce(func.sum(ReconResult.expected_paise), 0),
            func.coalesce(func.sum(ReconResult.received_paise), 0),
            func.coalesce(func.sum(ReconResult.diff_paise), 0),
            func.coalesce(func.sum(ReconResult.at_risk_paise), 0),
        )
        .select_from(ReconResult)
        .join(Order, Order.order_id == ReconResult.order_id)
        .where(*_conditions(filters))
    )
    count, expected, received, difference, at_risk = db.execute(totals_query).one()
    return {
        "items": [_list_item(result, order, channel_name, partner_name) for result, order, channel_name, partner_name in rows],
        "total": count,
        # SUM of BIGINT comes back as numeric: convert so the JSON carries plain integers (paise).
        "totals": {"expected_paise": int(expected), "received_paise": int(received), "diff_paise": int(difference), "at_risk_paise": int(at_risk)},
        "offset": offset,
        "limit": limit,
    }


def bucket_of(age_days: int | None) -> str | None:
    if age_days is None:
        return None
    if age_days <= 15:
        return "0-15"
    if age_days <= 30:
        return "16-30"
    if age_days <= 60:
        return "31-60"
    return "60+"


def _list_item(result: ReconResult, order: Order, channel_name: str, partner_name: str) -> dict:
    return {
        "order_id": result.order_id,
        "channel": channel_name,
        "partner_id": result.partner_id,
        "partner_name": partner_name,
        "order_date": order.order_date,
        "value_paise": order.value_paise,
        "payment_mode": order.payment_mode,
        "delivery_status": order.delivery_status,
        "expected_paise": result.expected_paise,
        "received_paise": result.received_paise,
        "diff_paise": result.diff_paise,
        "at_risk_paise": result.at_risk_paise,
        "status": result.status,
        "overpaid": result.overpaid,
        "age_days": result.age_days if result.status in FLAGGED_STATUSES else None,
        "age_bucket": bucket_of(result.age_days) if result.status in FLAGGED_STATUSES else None,
    }


# ---------- one order, with evidence ----------

def _upload_names(db: Session, upload_ids: set[int]) -> dict[int, str]:
    if not upload_ids:
        return {}
    return dict(db.execute(select(Upload.id, Upload.filename).where(Upload.id.in_(upload_ids))).all())


def order_evidence(db: Session, order: Order) -> dict:
    """Every partner line that counted towards this order, with the file and row it came from."""
    by_order_or_awb = lambda model: or_(  # noqa: E731 - same rule for both courier tables
        model.order_id == order.order_id,
        and_(model.order_id.is_(None), model.awb == order.awb) if order.awb else literal(False),
    )
    settlements = db.scalars(select(SettlementLine).where(SettlementLine.order_id == order.order_id).order_by(SettlementLine.settlement_date)).all()
    remittances = db.scalars(select(CodRemittance).where(by_order_or_awb(CodRemittance)).order_by(CodRemittance.remittance_date)).all()
    freight = db.scalars(select(FreightLine).where(by_order_or_awb(FreightLine)).order_by(FreightLine.leg)).all()
    receipts = db.scalars(
        select(WarehouseReceipt).where(or_(WarehouseReceipt.order_id == order.order_id, WarehouseReceipt.order_id == (order.awb or "")))
    ).all()
    names = _upload_names(db, {line.upload_id for line in [*settlements, *remittances, *freight, *receipts]})
    partner_names = dict(db.execute(select(Partner.id, Partner.name)).all())

    def source(line) -> dict:
        return {"file": names.get(line.upload_id, "unknown file"), "row": line.row_number}

    return {
        "settlement_lines": [
            {**source(line), "partner": partner_names.get(line.partner_id), "date": line.settlement_date, "gross_paise": line.gross_paise,
             "commission_paise": line.commission_paise, "fees_paise": line.fees_paise, "tcs_paise": line.tcs_paise,
             "tds_paise": line.tds_paise, "net_paise": line.net_paise, "reference": line.raw_ref}
            for line in settlements
        ],
        "cod_remittances": [
            {**source(line), "partner": partner_names.get(line.courier_partner_id), "date": line.remittance_date,
             "amount_paise": line.amount_paise, "utr": line.utr, "matched_by": "order ID" if line.order_id else "AWB"}
            for line in remittances
        ],
        "freight_lines": [
            {**source(line), "partner": partner_names.get(line.courier_partner_id), "leg": line.leg, "invoice_no": line.invoice_no,
             "charged_weight_g": line.charged_weight_g, "freight_paise": line.freight_paise, "cod_fee_paise": line.cod_fee_paise,
             "matched_by": "order ID" if line.order_id else "AWB"}
            for line in freight
        ],
        "warehouse_receipts": [{**source(line), "received_at": line.received_at} for line in receipts],
    }


def order_detail(db: Session, order_id: str) -> dict | None:
    row = db.execute(select(ReconResult, Order).join(Order, Order.order_id == ReconResult.order_id).where(ReconResult.order_id == order_id)).first()
    if row is None:
        return None
    result, order = row
    partner_names = dict(db.execute(select(Partner.id, Partner.name)).all())
    return {
        "order": {
            "order_id": order.order_id,
            "channel": partner_names.get(order.channel_partner_id),
            "courier": partner_names.get(order.courier_partner_id) if order.courier_partner_id else None,
            "awb": order.awb,
            "order_date": order.order_date,
            "delivered_date": order.delivered_date,
            "returned_date": order.returned_date,
            "value_paise": order.value_paise,
            "payment_mode": order.payment_mode,
            "delivery_status": order.delivery_status,
            "dead_weight_g": order.dead_weight_g,
            "volumetric_weight_g": order.volumetric_weight_g,
            # Already masked at ingestion; raw personal data is never stored.
            "customer_name": order.customer_name_masked,
            "customer_phone": order.customer_phone_masked,
            "pincode": order.pincode,
        },
        "result": {
            "status": result.status,
            "overpaid": result.overpaid,
            "partner_id": result.partner_id,
            "partner_name": partner_names.get(result.partner_id),
            "expected_paise": result.expected_paise,
            "received_paise": result.received_paise,
            "diff_paise": result.diff_paise,
            "at_risk_paise": result.at_risk_paise,
            "expected_freight_paise": result.expected_freight_paise,
            "charged_freight_paise": result.charged_freight_paise,
            "tcs_paise": result.tcs_paise,
            "tds_paise": result.tds_paise,
            "breakdown": result.expected_breakdown_json,
            "evidence_summary": result.evidence_json,
            "due_date": result.due_date,
            "age_days": result.age_days if result.status in FLAGGED_STATUSES else None,
            "run_id": result.run_id,
        },
        "evidence": order_evidence(db, order),
    }
