"""Idempotent creation of reference data: partners, sources, starting rate cards and v1 column mappings."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ColumnMapping, Partner, RateCard, Source, WeightSlab
from app.sample_data.formats import format_for
from app.services import reference_data as ref
from app.services.fingerprint import header_fingerprint


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


def seed_initial_mappings(db: Session, created_by: int | None) -> int:
    """Version 1 mapping for every source, matching that partner's standard layout. Returns how many were added."""
    added = 0
    sources = db.execute(select(Source, Partner).join(Partner, Partner.id == Source.partner_id)).all()
    for source, partner in sources:
        has_mapping = db.scalar(select(ColumnMapping.id).where(ColumnMapping.source_id == source.id).limit(1))
        if has_mapping is not None:
            continue
        layout = format_for(partner.name, source.file_kind)
        db.add(
            ColumnMapping(
                source_id=source.id,
                version=1,
                mapping_json=layout.mapping(),
                header_fingerprint=header_fingerprint(layout.headers),
                created_by=created_by,
                approved_at=datetime.now(timezone.utc),
                is_active=True,
                notes="Seeded: the partner's standard report layout.",
            )
        )
        added += 1
    db.flush()
    return added
