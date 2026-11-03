"""Reconciliation runs."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user, require_finance_exec
from app.config import get_settings
from app.db import get_db
from app.models import ReconRun, User
from app.models.enums import RECON_STATUSES
from app.services.claims import refresh_claims
from app.services.matching import run_reconciliation
from app.services.results import OrderFilters, list_orders, order_detail

router = APIRouter(prefix="/recon", tags=["reconciliation"], dependencies=[Depends(current_user)])


def reconcile_now(db: Session, user_id: int | None) -> dict:
    """Run reconciliation, bring claims up to date, commit. Shared by the manual trigger and every processed upload."""
    summary = run_reconciliation(db, started_by=user_id, return_window_days=get_settings().return_receipt_days)
    claim_changes = refresh_claims(db)
    db.commit()
    return {**summary.as_dict(), "claims": claim_changes}


@router.post("/runs", status_code=status.HTTP_201_CREATED)
def start_run(db: Session = Depends(get_db), user: User = Depends(require_finance_exec)) -> dict:
    return reconcile_now(db, user.id)


@router.get("/runs/latest")
def latest_run(db: Session = Depends(get_db)) -> dict | None:
    run = db.scalar(select(ReconRun).where(ReconRun.finished_at.is_not(None)).order_by(ReconRun.id.desc()).limit(1))
    if run is None:
        return None
    return {**(run.stats_json or {}), "finished_at": run.finished_at.isoformat() if run.finished_at else None}


STATUS_VALUES = (*RECON_STATUSES, "flagged")


@router.get("/orders")
def orders(
    partner_id: int | None = None,
    status_filter: str | None = Query(default=None, alias="status", description="Comma-separated statuses, or 'flagged'"),
    age_bucket: str | None = Query(default=None, pattern=r"^(0-15|16-30|31-60|60\+)$"),
    q: str | None = Query(default=None, max_length=60),
    sort: str = Query(default="at_risk", pattern="^(at_risk|difference|age|order_date|order_id)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    statuses = [value.strip() for value in status_filter.split(",") if value.strip()] if status_filter else None
    if statuses and any(value not in STATUS_VALUES for value in statuses):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown status filter.")
    filters = OrderFilters(partner_id=partner_id, statuses=statuses, age_bucket=age_bucket, search=q)
    return list_orders(db, filters, sort, offset, limit)


@router.get("/orders/{order_id}")
def order(order_id: str, db: Session = Depends(get_db)) -> dict:
    detail = order_detail(db, order_id)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No reconciliation result for this order.")
    return detail
