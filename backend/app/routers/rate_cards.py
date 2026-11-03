"""Partners and their rate cards. Reading is open to both roles; edits are finance-only and audited."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth import current_user, require_finance_exec
from app.db import get_db
from app.models import Partner, RateCard, User, WeightSlab
from app.schemas.rate_cards import PartnerOut, RateCardCreate, RateCardOut, RateCardTerms
from app.services.audit import record_audit

router = APIRouter(tags=["rate cards"], dependencies=[Depends(current_user)])

TERM_FIELDS = (
    "effective_from",
    "commission_pct_bp",
    "fixed_fee_paise",
    "cod_fee_paise",
    "cod_fee_pct_bp",
    "gateway_pct_bp",
    "tcs_pct_bp",
    "tds_pct_bp",
)


def _slabs_by_card(db: Session, card_ids: list[int]) -> dict[int, list[WeightSlab]]:
    slabs: dict[int, list[WeightSlab]] = {card_id: [] for card_id in card_ids}
    rows = db.scalars(
        select(WeightSlab)
        .where(WeightSlab.rate_card_id.in_(card_ids))
        .order_by(WeightSlab.leg, WeightSlab.up_to_g)
    )
    for slab in rows:
        slabs[slab.rate_card_id].append(slab)
    return slabs


def _card_out(card: RateCard, slabs: list[WeightSlab]) -> RateCardOut:
    data = {field: getattr(card, field) for field in TERM_FIELDS}
    return RateCardOut(id=card.id, partner_id=card.partner_id, slabs=slabs, **data)  # type: ignore[arg-type]


def _snapshot(card: RateCard, slabs: list[WeightSlab]) -> dict:
    """JSON-safe copy of a card for the audit log."""
    return _card_out(card, slabs).model_dump(mode="json")


@router.get("/partners", response_model=list[PartnerOut])
def list_partners(db: Session = Depends(get_db)) -> list[Partner]:
    return list(db.scalars(select(Partner).order_by(Partner.id)))


@router.get("/rate-cards", response_model=list[RateCardOut])
def list_rate_cards(db: Session = Depends(get_db)) -> list[RateCardOut]:
    cards = list(db.scalars(select(RateCard).order_by(RateCard.partner_id, RateCard.effective_from.desc())))
    slabs = _slabs_by_card(db, [card.id for card in cards])
    return [_card_out(card, slabs[card.id]) for card in cards]


def _check_effective_date_free(db: Session, partner_id: int, terms: RateCardTerms, card_id: int | None) -> None:
    clash = db.scalar(
        select(RateCard).where(RateCard.partner_id == partner_id, RateCard.effective_from == terms.effective_from)
    )
    if clash is not None and clash.id != card_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"This partner already has a rate card from {terms.effective_from}."
        )


def _write_slabs(db: Session, card_id: int, terms: RateCardTerms) -> list[WeightSlab]:
    db.execute(delete(WeightSlab).where(WeightSlab.rate_card_id == card_id))
    slabs = [
        WeightSlab(rate_card_id=card_id, leg=slab.leg, up_to_g=slab.up_to_g, price_paise=slab.price_paise)
        for slab in sorted(terms.slabs, key=lambda slab: (slab.leg, slab.up_to_g))
    ]
    db.add_all(slabs)
    return slabs


@router.post("/rate-cards", response_model=RateCardOut, status_code=status.HTTP_201_CREATED)
def create_rate_card(
    body: RateCardCreate, db: Session = Depends(get_db), user: User = Depends(require_finance_exec)
) -> RateCardOut:
    """Add a new effective-dated version of a partner's rates. Older versions keep applying to older orders."""
    if db.get(Partner, body.partner_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Partner not found.")
    _check_effective_date_free(db, body.partner_id, body, card_id=None)

    card = RateCard(partner_id=body.partner_id, **{field: getattr(body, field) for field in TERM_FIELDS})
    db.add(card)
    db.flush()
    slabs = _write_slabs(db, card.id, body)
    db.flush()
    record_audit(db, user, "rate_card.create", "rate_card", card.id, after=_snapshot(card, slabs))
    db.commit()
    return _card_out(card, slabs)


@router.put("/rate-cards/{card_id}", response_model=RateCardOut)
def update_rate_card(
    card_id: int, body: RateCardTerms, db: Session = Depends(get_db), user: User = Depends(require_finance_exec)
) -> RateCardOut:
    card = db.get(RateCard, card_id)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Rate card not found.")
    _check_effective_date_free(db, card.partner_id, body, card_id=card.id)

    before = _snapshot(card, _slabs_by_card(db, [card.id])[card.id])
    for field in TERM_FIELDS:
        setattr(card, field, getattr(body, field))
    slabs = _write_slabs(db, card.id, body)
    db.flush()
    record_audit(db, user, "rate_card.update", "rate_card", card.id, before=before, after=_snapshot(card, slabs))
    db.commit()
    return _card_out(card, slabs)
