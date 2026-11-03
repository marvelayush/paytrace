"""Claims: flagged orders grouped by the partner who owes the money, with evidence.

After every reconciliation run `refresh_claims` keeps each partner's single *open* claim in step with the
results: newly flagged orders are added, orders since paid are removed, amounts follow the latest run.
Claims already filed, recovered or rejected are frozen, and an order is claimed at most once (A37).
Filing with the partner happens outside PayTrace; users record it by changing the status (A7).
"""

from datetime import datetime, timezone

from sqlalchemy import bindparam, select, text
from sqlalchemy.orm import Session

from app.models import Claim, ClaimItem, Order, Partner, ReconResult, Upload, User
from app.services.audit import record_audit
from app.services.matching import FLAGGED_STATUSES

# open -> filed -> recovered / rejected (A7).
ALLOWED_TRANSITIONS = {"open": {"filed"}, "filed": {"recovered", "rejected"}, "recovered": set(), "rejected": set()}

SNAPSHOT = """jsonb_build_object(
    'expected_paise', r.expected_paise, 'received_paise', r.received_paise, 'diff_paise', r.diff_paise,
    'tcs_paise', r.tcs_paise, 'tds_paise', r.tds_paise, 'due_date', r.due_date, 'age_days', r.age_days,
    'breakdown', r.expected_breakdown_json, 'evidence', r.evidence_json, 'run_id', r.run_id)"""


class ClaimTransitionError(ValueError):
    pass


def refresh_claims(db: Session) -> dict[str, int]:
    """Bring open claims in line with the latest results. Set-based SQL: no loop per order."""
    flagged = {"flagged": list(FLAGGED_STATUSES)}
    statements = [
        # Paid since, or now owed by someone else: drop from the open claim.
        ("removed", """
            DELETE FROM claim_items ci USING claims c
            WHERE ci.claim_id = c.id AND c.status = 'open'
              AND NOT EXISTS (SELECT 1 FROM recon_results r
                              WHERE r.order_id = ci.order_id AND r.status = ANY(:flagged) AND r.partner_id = c.partner_id)"""),
        # Still flagged: follow the latest amount, reason and evidence.
        ("updated", f"""
            UPDATE claim_items ci SET amount_paise = r.at_risk_paise, reason_status = r.status, evidence_json = {SNAPSHOT}
            FROM claims c, recon_results r
            WHERE ci.claim_id = c.id AND c.status = 'open' AND r.order_id = ci.order_id"""),
        # A partner with newly flagged orders and no open claim gets one.
        ("claims_opened", """
            INSERT INTO claims (partner_id, status, total_paise, created_at)
            SELECT DISTINCT r.partner_id, 'open', 0, now() FROM recon_results r
            WHERE r.status = ANY(:flagged)
              AND NOT EXISTS (SELECT 1 FROM claim_items ci WHERE ci.order_id = r.order_id)
              AND NOT EXISTS (SELECT 1 FROM claims c WHERE c.partner_id = r.partner_id AND c.status = 'open')"""),
        ("added", f"""
            INSERT INTO claim_items (claim_id, order_id, reason_status, amount_paise, evidence_json)
            SELECT c.id, r.order_id, r.status, r.at_risk_paise, {SNAPSHOT}
            FROM recon_results r JOIN claims c ON c.partner_id = r.partner_id AND c.status = 'open'
            WHERE r.status = ANY(:flagged) AND NOT EXISTS (SELECT 1 FROM claim_items ci WHERE ci.order_id = r.order_id)"""),
        ("totals", """
            UPDATE claims c SET total_paise = COALESCE((SELECT SUM(amount_paise) FROM claim_items WHERE claim_id = c.id), 0)
            WHERE c.status = 'open'"""),
        ("empty_closed", "DELETE FROM claims c WHERE c.status = 'open' AND NOT EXISTS (SELECT 1 FROM claim_items WHERE claim_id = c.id)"),
    ]
    counts: dict[str, int] = {}
    for name, sql in statements:
        params = flagged if ":flagged" in sql else {}
        counts[name] = db.execute(text(sql), params).rowcount
    return counts


def change_status(db: Session, claim: Claim, new_status: str, user: User, reference: str | None) -> Claim:
    if new_status not in ALLOWED_TRANSITIONS[claim.status]:
        allowed = ", ".join(sorted(ALLOWED_TRANSITIONS[claim.status])) or "none (this claim is closed)"
        raise ClaimTransitionError(f"A {claim.status} claim can move to: {allowed}.")
    before = {"status": claim.status, "reference": claim.reference, "total_paise": claim.total_paise}
    claim.status = new_status
    if reference is not None and reference.strip():
        claim.reference = reference.strip()[:80]
    claim.updated_at = datetime.now(timezone.utc)
    claim.updated_by = user.id
    db.flush()
    record_audit(db, user, f"claim.{new_status}", "claim", claim.id, before=before,
                 after={"status": claim.status, "reference": claim.reference, "total_paise": claim.total_paise})
    return claim


# ---------- reading ----------

def claim_summary(claim: Claim, partner_name: str, item_count: int, reasons: dict[str, dict], oldest_age: int | None) -> dict:
    return {
        "id": claim.id,
        "partner_id": claim.partner_id,
        "partner_name": partner_name,
        "status": claim.status,
        "total_paise": claim.total_paise,
        "reference": claim.reference,
        "created_at": claim.created_at,
        "updated_at": claim.updated_at,
        "item_count": item_count,
        "by_reason": reasons,
        "oldest_age_days": oldest_age,
    }


def list_claims(db: Session, status: str | None = None) -> list[dict]:
    query = select(Claim, Partner.name).join(Partner, Partner.id == Claim.partner_id)
    if status:
        query = query.where(Claim.status == status)
    claims = db.execute(query.order_by(Claim.total_paise.desc(), Claim.id)).all()
    if not claims:
        return []
    stats = db.execute(
        text("""
            SELECT claim_id, reason_status, COUNT(*), SUM(amount_paise), MAX((evidence_json->>'age_days')::int)
            FROM claim_items WHERE claim_id = ANY(:ids) GROUP BY claim_id, reason_status"""),
        {"ids": [claim.id for claim, _ in claims]},
    ).all()
    by_claim: dict[int, dict] = {}
    for claim_id, reason, count, amount, oldest in stats:
        entry = by_claim.setdefault(claim_id, {"count": 0, "reasons": {}, "oldest": None})
        entry["count"] += count
        entry["reasons"][reason] = {"count": count, "amount_paise": int(amount)}
        if oldest is not None:
            entry["oldest"] = max(entry["oldest"] or 0, oldest)
    return [
        claim_summary(claim, name, by_claim.get(claim.id, {}).get("count", 0), by_claim.get(claim.id, {}).get("reasons", {}),
                      by_claim.get(claim.id, {}).get("oldest"))
        for claim, name in claims
    ]


def claim_items(db: Session, claim_id: int) -> list[dict]:
    rows = db.execute(
        select(ClaimItem, Order.channel_partner_id, Order.order_date, Order.value_paise, ReconResult.status)
        .join(Order, Order.order_id == ClaimItem.order_id)
        .outerjoin(ReconResult, ReconResult.order_id == ClaimItem.order_id)
        .where(ClaimItem.claim_id == claim_id)
        .order_by(ClaimItem.amount_paise.desc(), ClaimItem.order_id)
    ).all()
    channel_names = dict(db.execute(select(Partner.id, Partner.name)).all())
    return [
        {
            "order_id": item.order_id,
            "channel": channel_names.get(channel_id),
            "order_date": order_date,
            "value_paise": value,
            "reason_status": item.reason_status,
            "amount_paise": item.amount_paise,
            "expected_paise": item.evidence_json.get("expected_paise"),
            "received_paise": item.evidence_json.get("received_paise"),
            "diff_paise": item.evidence_json.get("diff_paise"),
            "due_date": item.evidence_json.get("due_date"),
            "age_days": item.evidence_json.get("age_days"),
            "current_status": current,  # may differ once a filed claim is paid
        }
        for item, channel_id, order_date, value, current in rows
    ]


def evidence_sources(db: Session, order_ids: list[str]) -> dict[str, list[str]]:
    """For each order: the uploaded files and row numbers of every line that counted, e.g. 'payouts.csv row 12'."""
    if not order_ids:
        return {}
    sql = text("""
        SELECT order_id, upload_id, row_number FROM settlement_lines WHERE order_id IN :ids
        UNION ALL
        SELECT COALESCE(l.order_id, o.order_id), l.upload_id, l.row_number
          FROM cod_remittances l LEFT JOIN orders o ON l.order_id IS NULL AND o.awb = l.awb
         WHERE COALESCE(l.order_id, o.order_id) IN :ids
        UNION ALL
        SELECT COALESCE(l.order_id, o.order_id), l.upload_id, l.row_number
          FROM freight_lines l LEFT JOIN orders o ON l.order_id IS NULL AND o.awb = l.awb
         WHERE COALESCE(l.order_id, o.order_id) IN :ids
        UNION ALL
        SELECT order_id, upload_id, row_number FROM warehouse_receipts WHERE order_id IN :ids
        ORDER BY 1, 2, 3""").bindparams(bindparam("ids", expanding=True))
    rows = db.execute(sql, {"ids": order_ids}).all()
    names = dict(db.execute(select(Upload.id, Upload.filename).where(Upload.id.in_({row[1] for row in rows}))).all()) if rows else {}
    sources: dict[str, list[str]] = {}
    for order_id, upload_id, row_number in rows:
        sources.setdefault(order_id, []).append(f"{names.get(upload_id, 'unknown file')} row {row_number}")
    return sources
