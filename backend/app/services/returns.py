"""Returns tracker: every order the courier marked returned or RTO, checked against warehouse receipt scans.

A return is
- received  when the warehouse scanned it in (or a finance executive confirmed it by hand, A44);
- waiting   when there is no scan yet but the receipt window (A8, default 7 days) is still open;
- overdue   when there is no scan and the window has passed. Matching flags these `return_not_received`
            and they are claimed from the courier (or the channel, for returns it shipped itself).

Ages use the latest reconciliation run's date, so this screen always agrees with the orders and claims.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import ManualReturnReceipt, Order, User
from app.models.enums import RETURNED_STATUSES
from app.services.audit import record_audit
from app.services.matching import today_in_india

SCAN_STATUSES = ("overdue", "waiting", "received")
# Days since the courier marked the return.
RETURN_AGE_BUCKETS = ("0-7", "8-15", "16-30", "30+")
OWN_LOGISTICS = "channel"  # courier filter key for returns the sales channel shipped itself


def scan_status(returned_on: date, received_on: date | None, as_of: date, window_days: int) -> str:
    """The rule in one place: received, still waiting inside the window, or overdue."""
    if received_on is not None:
        return "received"
    if (as_of - returned_on).days <= window_days:
        return "waiting"
    return "overdue"


def age_bucket(days: int) -> str:
    if days <= 7:
        return "0-7"
    if days <= 15:
        return "8-15"
    if days <= 30:
        return "16-30"
    return "30+"


def tracker_date(db: Session) -> date:
    as_of = db.scalar(text("SELECT as_of FROM recon_runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"))
    return as_of or today_in_india()


RETURNS_QUERY = """
WITH scans AS (
    -- Scans that carry only an AWB belong to the order with that AWB (as in matching).
    SELECT COALESCE(by_awb.order_id, w.order_id) AS order_id,
           MIN((w.received_at AT TIME ZONE 'Asia/Kolkata')::date) AS scanned_on
    FROM warehouse_receipts w
    LEFT JOIN orders by_awb ON by_awb.awb = w.order_id
    GROUP BY 1
)
SELECT o.order_id, o.delivery_status, o.returned_date, o.value_paise, o.awb,
       channel.name AS partner_name, o.courier_partner_id, courier.name AS courier_name,
       s.scanned_on, m.received_on AS manual_on, m.note AS manual_note, u.name AS marked_by, m.marked_at,
       ci.claim_id
FROM orders o
JOIN partners channel ON channel.id = o.channel_partner_id
LEFT JOIN partners courier ON courier.id = o.courier_partner_id
LEFT JOIN scans s ON s.order_id = o.order_id
LEFT JOIN manual_return_receipts m ON m.order_id = o.order_id
LEFT JOIN users u ON u.id = m.marked_by
LEFT JOIN claim_items ci ON ci.order_id = o.order_id
WHERE o.delivery_status IN ('returned', 'rto') AND o.returned_date IS NOT NULL
"""


def _row(record, as_of: date, window_days: int) -> dict:
    received_on = record.scanned_on or record.manual_on
    status = scan_status(record.returned_date, received_on, as_of, window_days)
    days = max((as_of - record.returned_date).days, 0)
    return {
        "order_id": record.order_id,
        "delivery_status": record.delivery_status,
        "partner_name": record.partner_name,
        "courier_key": str(record.courier_partner_id) if record.courier_partner_id else OWN_LOGISTICS,
        "courier_name": record.courier_name,
        "awb": record.awb,
        "returned_date": record.returned_date,
        "due_date": record.returned_date + timedelta(days=window_days),
        "days_since_return": days,
        "age_bucket": age_bucket(days),
        "status": status,
        "received_on": received_on,
        "received_how": "scan" if record.scanned_on else ("manual" if record.manual_on else None),
        "manual_note": record.manual_note,
        "marked_by": record.marked_by,
        "marked_at": record.marked_at,
        "value_paise": record.value_paise,
        # Only an overdue return is money at risk; a waiting one may still arrive (A11).
        "at_risk_paise": record.value_paise if status == "overdue" else 0,
        "claim_id": record.claim_id,
    }


@dataclass
class ReturnFilters:
    status: str | None = None
    courier: str | None = None
    age: str | None = None
    search: str | None = None


def _keep(row: dict, filters: ReturnFilters, skip: str | None = None) -> bool:
    if filters.status and skip != "status" and row["status"] != filters.status:
        return False
    if filters.courier and skip != "courier" and row["courier_key"] != filters.courier:
        return False
    if filters.age and skip != "age" and row["age_bucket"] != filters.age:
        return False
    if filters.search:
        needle = filters.search.strip().upper()
        if needle not in row["order_id"].upper() and needle not in (row["awb"] or "").upper():
            return False
    return True


STATUS_ORDER = {"overdue": 0, "waiting": 1, "received": 2}


def returns_tracker(db: Session, filters: ReturnFilters, window_days: int, limit: int = 200, offset: int = 0) -> dict:
    as_of = tracker_date(db)
    all_rows = [_row(record, as_of, window_days) for record in db.execute(text(RETURNS_QUERY)).all()]

    # Chip counts: each group is counted with the *other* filters applied, so a chip shows what clicking it gives.
    def counts(key: str, values: list[str]) -> dict[str, int]:
        tally = {value: 0 for value in values}
        for row in all_rows:
            if _keep(row, filters, skip=key) and row[key] in tally:
                tally[row[key]] += 1
        return tally

    couriers: dict[str, str] = {}
    for row in all_rows:
        couriers.setdefault(row["courier_key"], row["courier_name"] or "Channel's own logistics")

    rows = [row for row in all_rows if _keep(row, filters)]
    rows.sort(key=lambda row: (STATUS_ORDER[row["status"]], -row["days_since_return"] if row["status"] != "received" else 0, row["order_id"]))
    summary = {status: {"orders": 0, "value_paise": 0} for status in SCAN_STATUSES}
    for row in all_rows:
        summary[row["status"]]["orders"] += 1
        summary[row["status"]]["value_paise"] += row["value_paise"]

    return {
        "as_of": as_of,
        "window_days": window_days,
        "summary": summary,
        "couriers": [{"key": key, "name": name} for key, name in sorted(couriers.items(), key=lambda item: item[1])],
        "counts": {
            "status": counts("status", list(SCAN_STATUSES)),
            "courier": counts("courier_key", list(couriers)),
            "age": counts("age_bucket", list(RETURN_AGE_BUCKETS)),
        },
        "total": len(rows),
        "at_risk_paise": sum(row["at_risk_paise"] for row in rows),
        "rows": rows[offset: offset + limit],
    }


def returns_summary(db: Session, window_days: int) -> dict:
    """The dashboard card: how many returns are received, waiting and overdue, and the overdue value."""
    data = returns_tracker(db, ReturnFilters(), window_days, limit=0)
    return {"as_of": data["as_of"], "window_days": window_days, **data["summary"]}


class ReturnNotEligible(ValueError):
    pass


def mark_received_manually(db: Session, order_id: str, user: User, note: str, received_on: date | None, window_days: int) -> dict:
    """Record a return as received without a warehouse scan (audited). The caller re-matches the order."""
    order = db.get(Order, order_id)
    if order is None:
        raise LookupError("Order not found.")
    if order.delivery_status not in RETURNED_STATUSES or order.returned_date is None:
        raise ReturnNotEligible("This order was not returned.")
    record = next((row for row in db.execute(text(RETURNS_QUERY + " AND o.order_id = :order_id"), {"order_id": order_id}).all()), None)
    if record is not None and (record.scanned_on or record.manual_on):
        raise ReturnNotEligible("This return is already marked received.")
    as_of = tracker_date(db)
    received_on = received_on or as_of
    if received_on < order.returned_date:
        raise ReturnNotEligible("The receipt date cannot be before the return date.")
    if received_on > max(as_of, today_in_india()):
        raise ReturnNotEligible("The receipt date cannot be in the future.")

    db.add(ManualReturnReceipt(order_id=order_id, received_on=received_on, note=note.strip(), marked_by=user.id,
                               marked_at=datetime.now(timezone.utc)))
    record_audit(db, user, "return_marked_received", "order", order_id,
                 before={"scan_status": scan_status(order.returned_date, None, as_of, window_days)},
                 after={"scan_status": "received", "received_on": received_on.isoformat(), "how": "manual", "note": note.strip()})
    db.flush()
    return {"order_id": order_id, "received_on": received_on}
