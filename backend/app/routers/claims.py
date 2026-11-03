"""Claims grouped by partner, status changes (finance only, audited) and evidence export (both roles)."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user, require_finance_exec
from app.db import get_db
from app.models import Claim, Partner, User
from app.services.claims import ClaimTransitionError, change_status, claim_items, claim_summary, evidence_sources, list_claims
from app.services.evidence_export import evidence_csv, evidence_pdf
from app.services.matching import today_in_india

router = APIRouter(prefix="/claims", tags=["claims"], dependencies=[Depends(current_user)])


class StatusChange(BaseModel):
    status: Literal["filed", "recovered", "rejected"]
    reference: str | None = Field(default=None, max_length=80)


def _claim_with_items(db: Session, claim_id: int) -> tuple[dict, list[dict]]:
    row = db.execute(select(Claim, Partner.name).join(Partner, Partner.id == Claim.partner_id).where(Claim.id == claim_id)).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Claim not found.")
    claim, partner_name = row
    items = claim_items(db, claim.id)
    reasons: dict[str, dict] = {}
    for item in items:
        entry = reasons.setdefault(item["reason_status"], {"count": 0, "amount_paise": 0})
        entry["count"] += 1
        entry["amount_paise"] += item["amount_paise"]
    ages = [item["age_days"] for item in items if item["age_days"] is not None]
    return claim_summary(claim, partner_name, len(items), reasons, max(ages) if ages else None), items


@router.get("")
def claims(status_filter: str | None = Query(default=None, alias="status", pattern="^(open|filed|recovered|rejected)$"),
           db: Session = Depends(get_db)) -> list[dict]:
    return list_claims(db, status_filter)


@router.get("/{claim_id}")
def claim(claim_id: int, db: Session = Depends(get_db)) -> dict:
    summary, items = _claim_with_items(db, claim_id)
    return {**summary, "items": items}


@router.patch("/{claim_id}")
def update_claim(claim_id: int, body: StatusChange, db: Session = Depends(get_db), user: User = Depends(require_finance_exec)) -> dict:
    record = db.get(Claim, claim_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Claim not found.")
    try:
        change_status(db, record, body.status, user, body.reference)
    except ClaimTransitionError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(error)) from error
    db.commit()
    summary, items = _claim_with_items(db, claim_id)
    return {**summary, "items": items}


def _filename(summary: dict, extension: str) -> str:
    partner = summary["partner_name"].lower().replace(" ", "-")
    return f"claim-{summary['id']}-{partner}-evidence.{extension}"


@router.get("/{claim_id}/evidence.csv")
def export_csv(claim_id: int, db: Session = Depends(get_db)) -> Response:
    summary, items = _claim_with_items(db, claim_id)
    sources = evidence_sources(db, [item["order_id"] for item in items])
    return Response(
        content=evidence_csv(summary, items, sources),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{_filename(summary, "csv")}"'},
    )


@router.get("/{claim_id}/evidence.pdf")
def export_pdf(claim_id: int, db: Session = Depends(get_db)) -> Response:
    summary, items = _claim_with_items(db, claim_id)
    return Response(
        content=evidence_pdf(summary, items, today_in_india()),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{_filename(summary, "pdf")}"'},
    )
