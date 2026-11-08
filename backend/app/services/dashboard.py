"""Money-at-risk dashboard: headline numbers, partner x age matrix, and why money is at risk."""

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Claim, Partner, ReconRun
from app.services.matching import FLAGGED_STATUSES
from app.services.results import AGE_BUCKETS
from app.services.returns import returns_summary
from app.services.review_queue import queue_counts


def dashboard(db: Session) -> dict:
    run = db.scalar(select(ReconRun).where(ReconRun.finished_at.is_not(None)).order_by(ReconRun.id.desc()).limit(1))
    if run is None:
        return {"run": None}

    flagged = {"flagged": list(FLAGGED_STATUSES)}
    matrix_rows = db.execute(text("""
        SELECT partner_id,
               CASE WHEN age_days IS NULL OR age_days <= 15 THEN '0-15'
                    WHEN age_days <= 30 THEN '16-30'
                    WHEN age_days <= 60 THEN '31-60'
                    ELSE '60+' END AS bucket,
               COUNT(*), SUM(at_risk_paise)
        FROM recon_results WHERE status = ANY(:flagged)
        GROUP BY 1, 2"""), flagged).all()
    names = dict(db.execute(select(Partner.id, Partner.name)).all())
    kinds = dict(db.execute(select(Partner.id, Partner.kind)).all())

    partners: dict[int, dict] = {}
    for partner_id, bucket, count, amount in matrix_rows:
        row = partners.setdefault(partner_id, {
            "partner_id": partner_id, "partner_name": names.get(partner_id), "partner_kind": kinds.get(partner_id),
            "buckets": {name: {"orders": 0, "at_risk_paise": 0} for name in AGE_BUCKETS}, "orders": 0, "at_risk_paise": 0,
        })
        row["buckets"][bucket] = {"orders": count, "at_risk_paise": int(amount)}
        row["orders"] += count
        row["at_risk_paise"] += int(amount)
    matrix = sorted(partners.values(), key=lambda row: -row["at_risk_paise"])
    bucket_totals = {
        bucket: {
            "orders": sum(row["buckets"][bucket]["orders"] for row in matrix),
            "at_risk_paise": sum(row["buckets"][bucket]["at_risk_paise"] for row in matrix),
        }
        for bucket in AGE_BUCKETS
    }

    by_status = [
        {"status": status, "orders": count, "at_risk_paise": int(amount or 0), "diff_paise": int(diff or 0)}
        for status, count, amount, diff in db.execute(text(
            "SELECT status, COUNT(*), SUM(at_risk_paise), SUM(diff_paise) FROM recon_results GROUP BY status ORDER BY 3 DESC NULLS LAST"
        )).all()
    ]
    tcs, tds, orders = db.execute(text("SELECT COALESCE(SUM(tcs_paise),0), COALESCE(SUM(tds_paise),0), COUNT(*) FROM recon_results")).one()
    tax_by_partner = [
        {"partner_name": names.get(partner_id), "tcs_paise": int(partner_tcs), "tds_paise": int(partner_tds)}
        for partner_id, partner_tcs, partner_tds in db.execute(text(
            "SELECT partner_id, SUM(tcs_paise), SUM(tds_paise) FROM recon_results GROUP BY partner_id "
            "HAVING SUM(tcs_paise) + SUM(tds_paise) > 0 ORDER BY 2 DESC"
        )).all()
    ]
    claims = {
        status: {"claims": count, "total_paise": int(total or 0)}
        for status, count, total in db.execute(select(Claim.status, func.count(), func.sum(Claim.total_paise)).group_by(Claim.status)).all()
    }
    stats = run.stats_json or {}
    return {
        "run": {
            "run_id": run.id,
            "as_of": run.as_of,
            "finished_at": run.finished_at,
            "duration_ms": run.duration_ms,
            "order_count": run.order_count,
            "auto_matched_pct": stats.get("auto_matched_pct"),
            "unmatched_lines": stats.get("unmatched_lines", {}),
        },
        "kpis": {
            "money_at_risk_paise": sum(row["at_risk_paise"] for row in matrix),
            "orders_at_risk": sum(row["orders"] for row in matrix),
            "orders": orders,
            "auto_matched_pct": stats.get("auto_matched_pct"),
            "open_claims": claims.get("open", {"claims": 0, "total_paise": 0}),
            "filed_claims": claims.get("filed", {"claims": 0, "total_paise": 0}),
            "recovered_claims": claims.get("recovered", {"claims": 0, "total_paise": 0}),
            "tcs_paise": int(tcs),
            "tds_paise": int(tds),
        },
        "matrix": matrix,
        "bucket_totals": bucket_totals,
        "by_status": by_status,
        "tax_by_partner": tax_by_partner,
        "returns": returns_summary(db, get_settings().return_receipt_days),
        "review_queue": queue_counts(db),
    }
