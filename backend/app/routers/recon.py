"""Reconciliation runs."""

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user, require_finance_exec
from app.config import get_settings
from app.db import get_db
from app.models import ReconRun, User
from app.services.matching import run_reconciliation

router = APIRouter(prefix="/recon", tags=["reconciliation"], dependencies=[Depends(current_user)])


def reconcile_now(db: Session, user_id: int | None) -> dict:
    """Run reconciliation and commit. Shared by the manual trigger and by every processed upload."""
    summary = run_reconciliation(db, started_by=user_id, return_window_days=get_settings().return_receipt_days)
    db.commit()
    return summary.as_dict()


@router.post("/runs", status_code=status.HTTP_201_CREATED)
def start_run(db: Session = Depends(get_db), user: User = Depends(require_finance_exec)) -> dict:
    return reconcile_now(db, user.id)


@router.get("/runs/latest")
def latest_run(db: Session = Depends(get_db)) -> dict | None:
    run = db.scalar(select(ReconRun).where(ReconRun.finished_at.is_not(None)).order_by(ReconRun.id.desc()).limit(1))
    if run is None:
        return None
    return {**(run.stats_json or {}), "finished_at": run.finished_at.isoformat() if run.finished_at else None}
