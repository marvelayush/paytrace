"""Idempotent creation of reference data: partners, sources and starting rate cards."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Partner, RateCard, Source, WeightSlab
from app.services import reference_data as ref


def seed_reference_data(db: Session) -> dict[str, Partner]:
    """Create any missing partners, sources and rate cards. Existing rows are left untouched."""
    partners: dict[str, Partner] = {}
    for name, kind, settlement_days in ref.PARTNERS:
        partner = db.scalar(select(Partner).where(Partner.name == name))
        if partner is None:
            partner = Partner(name=name, kind=kind, settlement_days=settlement_days)
            db.add(partner)
            db.flush()
        partners[name] = partner

        for file_kind, label in ref.SOURCE_KINDS_BY_PARTNER_KIND[kind]:
            exists = db.scalar(select(Source).where(Source.partner_id == partner.id, Source.file_kind == file_kind))
            if exists is None:
                db.add(Source(partner_id=partner.id, file_kind=file_kind, name=f"{name} {label}"))

    for name, terms in ref.CHANNEL_RATE_CARDS.items():
        _ensure_rate_card(db, partners[name], dict(terms), slabs=[])

    for name, card in ref.COURIER_RATE_CARDS.items():
        slabs = [("forward", up_to, price) for up_to, price in card["forward"]]
        slabs += [("return", up_to, price) for up_to, price in card["return"]]
        terms = {"cod_fee_paise": card["cod_fee_paise"], "cod_fee_pct_bp": card["cod_fee_pct_bp"]}
        _ensure_rate_card(db, partners[name], terms, slabs)

    db.flush()
    return partners


def _ensure_rate_card(db: Session, partner: Partner, terms: dict, slabs: list[tuple[str, int, int]]) -> None:
    exists = db.scalar(
        select(RateCard).where(
            RateCard.partner_id == partner.id, RateCard.effective_from == ref.RATE_CARDS_EFFECTIVE_FROM
        )
    )
    if exists is not None:
        return
    card = RateCard(partner_id=partner.id, effective_from=ref.RATE_CARDS_EFFECTIVE_FROM, **terms)
    db.add(card)
    db.flush()
    for leg, up_to_g, price_paise in slabs:
        db.add(WeightSlab(rate_card_id=card.id, leg=leg, up_to_g=up_to_g, price_paise=price_paise))
