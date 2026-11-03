"""The money-at-risk dashboard (both roles)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db import get_db
from app.services.dashboard import dashboard

router = APIRouter(tags=["dashboard"], dependencies=[Depends(current_user)])


@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db)) -> dict:
    return dashboard(db)
