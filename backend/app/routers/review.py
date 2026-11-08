"""Review queue: suggested orders for lines without an order ID. Both roles read; only finance decides."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user, require_finance_exec
from app.config import get_settings
from app.db import SessionLocal, get_db
from app.models import UnmatchedLine, User
from app.services.claims import refresh_claims
from app.services.match_ai import MatchRanker, get_ranker
from app.services.matching import reconcile_orders
from app.services.review_queue import (
    BULK_ACCEPT_MIN_CONFIDENCE,
    QueueError,
    accept_line,
    lines_sharing_candidates,
    list_lines,
    queue_counts,
    refresh_suggestions,
    reject_line,
)

router = APIRouter(prefix="/review-queue", tags=["review queue"], dependencies=[Depends(current_user)])


def get_match_ranker() -> MatchRanker:
    settings = get_settings()
    return get_ranker(settings.gemini_api_key, settings.gemini_model, settings.gemini_thinking_level or None)


def rank_in_background(line_ids: list[int], ranker: MatchRanker) -> None:
    """Runs after the upload response: AI ranking takes a few seconds per batch of lines."""
    with SessionLocal() as db:
        refresh_suggestions(db, ranker=ranker, line_ids=line_ids)
        db.commit()


class Decision(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class AcceptRequest(Decision):
    order_id: str = Field(min_length=1, max_length=40)


class BulkAcceptRequest(BaseModel):
    line_ids: list[int] = Field(min_length=1, max_length=200)


@router.get("")
def get_queue(
    status_filter: Literal["open", "accepted", "rejected"] = Query(default="open", alias="status"),
    db: Session = Depends(get_db),
) -> dict:
    return {"counts": queue_counts(db), "lines": list_lines(db, status_filter)}


@router.get("/summary")
def summary(db: Session = Depends(get_db)) -> dict:
    return queue_counts(db)


def _get_line(db: Session, line_id: int) -> UnmatchedLine:
    line = db.get(UnmatchedLine, line_id)
    if line is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Line not found.")
    return line


def _after_accept(db: Session, order_ids: list[str], accepted_line_ids: list[int]) -> dict:
    """Re-match only the orders that just got a line, refresh claims, and re-shortlist lines that suggested them."""
    rematched = reconcile_orders(db, order_ids, return_window_days=get_settings().return_receipt_days)
    refresh_claims(db)
    affected = lines_sharing_candidates(db, order_ids, exclude=accepted_line_ids)
    if affected:
        refresh_suggestions(db, ranker=None, line_ids=affected)
    return {"orders_rematched": rematched, "lines_reshortlisted": len(affected)}


@router.post("/{line_id}/accept")
def accept(line_id: int, body: AcceptRequest, db: Session = Depends(get_db), user: User = Depends(require_finance_exec)) -> dict:
    line = _get_line(db, line_id)
    try:
        order_id = accept_line(db, line, body.order_id, user, body.note)
    except QueueError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(error)) from error
    effects = _after_accept(db, [order_id], [line_id])
    db.commit()
    return {"line_id": line_id, "order_id": order_id, **effects}


@router.post("/{line_id}/reject")
def reject(line_id: int, body: Decision, db: Session = Depends(get_db), user: User = Depends(require_finance_exec)) -> dict:
    line = _get_line(db, line_id)
    try:
        reject_line(db, line, user, body.note)
    except QueueError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(error)) from error
    db.commit()
    return {"line_id": line_id, "status": "rejected"}


@router.post("/bulk-accept")
def bulk_accept(body: BulkAcceptRequest, db: Session = Depends(get_db), user: User = Depends(require_finance_exec)) -> dict:
    """Accept the suggestion of each chosen line whose confidence is at least 0.9. Others are skipped, with a reason."""
    lines = list(db.scalars(select(UnmatchedLine).where(UnmatchedLine.id.in_(body.line_ids)).order_by(UnmatchedLine.id)))
    accepted: list[tuple[int, str]] = []
    skipped: list[dict] = []
    for line in lines:
        if line.status != "open":
            skipped.append({"line_id": line.id, "reason": f"already {line.status}"})
        elif line.suggested_order_id is None or (line.confidence or 0) < BULK_ACCEPT_MIN_CONFIDENCE:
            skipped.append({"line_id": line.id, "reason": f"confidence below {BULK_ACCEPT_MIN_CONFIDENCE}"})
        elif line.suggested_order_id in {order_id for _, order_id in accepted}:
            skipped.append({"line_id": line.id, "reason": "another selected line suggests the same order"})
        else:
            accepted.append((line.id, accept_line(db, line, line.suggested_order_id, user, "Bulk accepted")))
    missing = set(body.line_ids) - {line.id for line in lines}
    skipped += [{"line_id": line_id, "reason": "not found"} for line_id in sorted(missing)]
    effects = _after_accept(db, [order_id for _, order_id in accepted], [line_id for line_id, _ in accepted]) if accepted else {}
    db.commit()
    return {"accepted": [{"line_id": line_id, "order_id": order_id} for line_id, order_id in accepted], "skipped": skipped, **effects}
