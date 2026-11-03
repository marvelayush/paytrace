import pytest
from sqlalchemy import select

from app.models import AuditLog, Partner, RateCard
from app.services.seeding import seed_reference_data


@pytest.fixture
def seeded(db):
    partners = seed_reference_data(db)
    db.commit()
    return partners


def _card_for(client, partner_name: str, partners) -> dict:
    partner_id = partners[partner_name].id
    return next(card for card in client.get("/rate-cards").json() if card["partner_id"] == partner_id)


def test_seeding_is_idempotent(db, seeded):
    seed_reference_data(db)
    db.commit()
    assert db.query(Partner).count() == 9
    assert db.query(RateCard).count() == 8  # 6 channels + 2 couriers; warehouse has no rates


def test_both_roles_can_read_partners_and_rate_cards(finance_client, founder_client, seeded):
    for client in (finance_client, founder_client):
        assert len(client.get("/partners").json()) == 9
        cards = client.get("/rate-cards").json()
        assert len(cards) == 8


def test_rate_cards_require_sign_in(client, seeded):
    assert client.get("/rate-cards").status_code == 401


def test_courier_card_lists_slabs_in_weight_order(finance_client, seeded):
    card = _card_for(finance_client, "Courier A", seeded)
    forward = [slab for slab in card["slabs"] if slab["leg"] == "forward"]
    assert [slab["up_to_g"] for slab in forward] == [500, 1000, 2000, 5000, 10000]
    assert card["cod_fee_paise"] == 3000


def _terms(card: dict, **changes) -> dict:
    body = {key: card[key] for key in card if key not in ("id", "partner_id")}
    body.update(changes)
    return body


def test_finance_can_edit_a_rate_card_and_it_is_audited(finance_client, seeded, db):
    card = _card_for(finance_client, "Marketplace 1", seeded)
    response = finance_client.put(f"/rate-cards/{card['id']}", json=_terms(card, commission_pct_bp=1900))

    assert response.status_code == 200
    assert response.json()["commission_pct_bp"] == 1900

    entry = db.scalar(select(AuditLog).where(AuditLog.action == "rate_card.update"))
    assert entry is not None
    assert entry.before_json["commission_pct_bp"] == 2000
    assert entry.after_json["commission_pct_bp"] == 1900


def test_editing_slabs_replaces_them(finance_client, seeded):
    card = _card_for(finance_client, "Courier B", seeded)
    new_slabs = [{"leg": "forward", "up_to_g": 750, "price_paise": 5500}, {"leg": "return", "up_to_g": 750, "price_paise": 5000}]
    response = finance_client.put(f"/rate-cards/{card['id']}", json=_terms(card, slabs=new_slabs))
    assert response.status_code == 200
    assert response.json()["slabs"] == new_slabs


def test_duplicate_slab_is_rejected(finance_client, seeded):
    card = _card_for(finance_client, "Courier B", seeded)
    slabs = [{"leg": "forward", "up_to_g": 500, "price_paise": 1}, {"leg": "forward", "up_to_g": 500, "price_paise": 2}]
    response = finance_client.put(f"/rate-cards/{card['id']}", json=_terms(card, slabs=slabs))
    assert response.status_code == 422


@pytest.mark.parametrize("bad", [{"commission_pct_bp": -1}, {"commission_pct_bp": 10_001}, {"fixed_fee_paise": -5}])
def test_out_of_range_terms_are_rejected(finance_client, seeded, bad):
    card = _card_for(finance_client, "Marketplace 2", seeded)
    assert finance_client.put(f"/rate-cards/{card['id']}", json=_terms(card, **bad)).status_code == 422


def test_new_version_with_a_later_effective_date(finance_client, seeded):
    card = _card_for(finance_client, "Marketplace 2", seeded)
    body = _terms(card, effective_from="2026-10-01", commission_pct_bp=1700)
    body["partner_id"] = card["partner_id"]

    created = finance_client.post("/rate-cards", json=body)
    assert created.status_code == 201
    duplicate = finance_client.post("/rate-cards", json=body)
    assert duplicate.status_code == 409


def test_unknown_rate_card_is_404(finance_client, seeded):
    card = _card_for(finance_client, "Marketplace 2", seeded)
    assert finance_client.put("/rate-cards/999999", json=_terms(card)).status_code == 404


def test_cofounder_cannot_edit(founder_client, seeded):
    card = _card_for(founder_client, "Marketplace 1", seeded)
    assert founder_client.put(f"/rate-cards/{card['id']}", json=_terms(card)).status_code == 403
