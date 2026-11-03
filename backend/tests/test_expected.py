"""Expected-amount engine. The three brief samples must reproduce exactly."""

import pytest

from app.services.expected import (
    ChannelTerms,
    CourierTerms,
    OrderFacts,
    chargeable_weight,
    expected_breakdown,
    percent_of,
    slab_price,
)
from app.services.reference_data import CHANNEL_RATE_CARDS, COURIER_RATE_CARDS


def channel(name: str) -> ChannelTerms:
    return ChannelTerms(**CHANNEL_RATE_CARDS[name])


def courier(name: str) -> CourierTerms:
    card = COURIER_RATE_CARDS[name]
    return CourierTerms(
        cod_fee_paise=card["cod_fee_paise"],
        cod_fee_pct_bp=card["cod_fee_pct_bp"],
        forward_slabs=tuple(card["forward"]),
        return_slabs=tuple(card["return"]),
    )


# ---------- the brief's three sample orders ----------

def test_brief_sample_website_cod_delivered_expects_1409():
    order = OrderFacts(value_paise=149_900, payment_mode="cod", delivery_status="delivered", dead_weight_g=450, volumetric_weight_g=400)
    result = expected_breakdown(order, channel("Website"), courier("Courier A"))

    assert result.expected_amount == 140_900
    assert (result.cod_fee, result.forward_freight, result.gateway_fee) == (3_000, 6_000, 0)
    assert (result.tcs, result.tds) == (0, 0)


def test_brief_sample_marketplace_prepaid_delivered_expects_899():
    order = OrderFacts(value_paise=119_900, payment_mode="prepaid", delivery_status="delivered")
    result = expected_breakdown(order, channel("Marketplace 1"))

    assert result.expected_amount == 89_900
    assert (result.commission, result.fixed_fee, result.freight) == (23_980, 6_020, 0)
    # Taxes are computed but kept out of the expected amount.
    assert (result.tcs, result.tds) == (600, 120)
    assert result.expected_in_bank == 89_900 - 720


def test_brief_sample_website_prepaid_returned_expects_minus_96():
    order = OrderFacts(value_paise=239_800, payment_mode="prepaid", delivery_status="returned", dead_weight_g=480, volumetric_weight_g=420)
    result = expected_breakdown(order, channel("Website"), courier("Courier B"))

    assert result.expected_amount == -9_600
    assert (result.forward_freight, result.return_freight) == (4_800, 4_800)
    assert (result.value, result.gateway_fee, result.tcs) == (0, 0, 0)
    assert result.is_returned


# ---------- building blocks ----------

@pytest.mark.parametrize(
    ("amount", "rate_bp", "expected"),
    [
        (119_900, 50, 600),  # 599.5 paise rounds half up
        (119_900, 10, 120),  # 119.9 -> 120
        (100_000, 200, 2_000),
        (1, 4_999, 0),  # 0.4999 -> 0
        (1, 5_000, 1),  # 0.5 -> 1
        (-119_900, 50, -600),  # symmetric for negative amounts
        (12_345, 0, 0),
    ],
)
def test_percent_of_rounds_half_up_to_paise(amount, rate_bp, expected):
    assert percent_of(amount, rate_bp) == expected


def test_chargeable_weight_is_the_higher_of_dead_and_volumetric():
    assert chargeable_weight(450, 900) == 900
    assert chargeable_weight(1200, 900) == 1200
    assert chargeable_weight(None, 300) == 300
    assert chargeable_weight(None, None) == 0


@pytest.mark.parametrize(
    ("weight", "price"),
    [(0, 6_000), (500, 6_000), (501, 8_500), (1000, 8_500), (1001, 12_500), (10_000, 36_000), (25_000, 36_000)],
)
def test_slab_price_uses_first_slab_covering_the_weight(weight, price):
    assert slab_price(tuple(COURIER_RATE_CARDS["Courier A"]["forward"]), weight) == price


def test_slab_price_without_slabs_is_zero():
    assert slab_price((), 700) == 0


def test_volumetric_weight_moves_order_into_heavier_slab():
    light_but_bulky = OrderFacts(value_paise=100_000, payment_mode="prepaid", delivery_status="delivered", dead_weight_g=400, volumetric_weight_g=1_500)
    result = expected_breakdown(light_but_bulky, channel("Website"), courier("Courier A"))
    assert result.chargeable_weight_g == 1_500
    assert result.forward_freight == 12_500


def test_prepaid_website_order_pays_gateway_fee_not_cod_fee():
    order = OrderFacts(value_paise=100_000, payment_mode="prepaid", delivery_status="delivered", dead_weight_g=300)
    result = expected_breakdown(order, channel("Website"), courier("Courier A"))
    assert (result.gateway_fee, result.cod_fee) == (2_000, 0)
    assert result.expected_amount == 100_000 - 2_000 - 6_000


def test_percentage_cod_fee():
    order = OrderFacts(value_paise=150_000, payment_mode="cod", delivery_status="delivered", dead_weight_g=300)
    result = expected_breakdown(order, channel("Website"), courier("Courier B"))
    assert result.cod_fee == 3_000  # 2% of 1,500


def test_rto_is_treated_like_a_return():
    order = OrderFacts(value_paise=150_000, payment_mode="cod", delivery_status="rto", dead_weight_g=900)
    result = expected_breakdown(order, channel("Website"), courier("Courier A"))
    assert result.cod_fee == 0
    assert result.expected_amount == -(8_500 + 8_500)


def test_returned_marketplace_order_expects_nothing():
    order = OrderFacts(value_paise=119_900, payment_mode="prepaid", delivery_status="returned")
    assert expected_breakdown(order, channel("Marketplace 1")).expected_amount == 0


def test_cancelled_order_expects_nothing():
    order = OrderFacts(value_paise=119_900, payment_mode="cod", delivery_status="cancelled", dead_weight_g=500)
    result = expected_breakdown(order, channel("Website"), courier("Courier A"))
    assert result.expected_amount == 0
    assert result.freight == 0


def test_taxes_never_reduce_the_expected_amount():
    order = OrderFacts(value_paise=200_000, payment_mode="prepaid", delivery_status="delivered")
    with_tax = expected_breakdown(order, ChannelTerms(commission_pct_bp=1000, tcs_pct_bp=50, tds_pct_bp=10))
    without_tax = expected_breakdown(order, ChannelTerms(commission_pct_bp=1000))
    assert with_tax.expected_amount == without_tax.expected_amount == 180_000
    assert (with_tax.tcs, with_tax.tds) == (1_000, 200)


def test_breakdown_dict_has_totals_for_the_ui():
    order = OrderFacts(value_paise=119_900, payment_mode="prepaid", delivery_status="delivered")
    data = expected_breakdown(order, channel("Marketplace 1")).to_dict()
    assert data["expected_amount"] == 89_900
    assert data["expected_in_bank"] == 89_180
    assert data["notes"] == []
