"""Returns tracker (both roles read; only a finance executive can confirm a return by hand)."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import current_user, require_finance_exec
from app.config import get_settings
from app.db import get_db
from app.models import User
from app.services.claims import refresh_claims
from app.services.matching import reconcile_orders
from app.services.returns import (
    ReturnFilters,
    ReturnNotEligible,
    mark_received_manually,
    returns_summary,
    returns_tracker,
)

router = APIRouter(prefix="/returns", tags=["returns"], dependencies=[Depends(current_user)])


class ManualReceipt(BaseModel):
    note: str = Field(min_length=3, max_length=500, description="Why it counts as received without a scan")
    received_on: date | None = None


@router.get("")
def list_returns(
    status_filter: Literal["overdue", "waiting", "received"] | None = Query(default=None, alias="status"),
    courier: str | None = Query(default=None, max_length=20),
    age: Literal["0-7", "8-15", "16-30", "30+"] | None = None,
    q: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    filters = ReturnFilters(status=status_filter, courier=courier, age=age, search=q)
    return returns_tracker(db, filters, get_settings().return_receipt_days, limit=limit, offset=offset)


@router.get("/summary")
def summary(db: Session = Depends(get_db)) -> dict:
    return returns_summary(db, get_settings().return_receipt_days)


@router.post("/{order_id}/manual-receipt")
def mark_received(
    order_id: str, body: ManualReceipt, db: Session = Depends(get_db), user: User = Depends(require_finance_exec)
) -> dict:
    """Confirm a return as received without a warehouse scan. Audited; the order is re-matched straight away."""
    window = get_settings().return_receipt_days
    try:
        result = mark_received_manually(db, order_id, user, body.note, body.received_on, window)
    except LookupError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ReturnNotEligible as error:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(error)) from error
    reconcile_orders(db, [order_id], return_window_days=window)
    refresh_claims(db)
    db.commit()
    return result
