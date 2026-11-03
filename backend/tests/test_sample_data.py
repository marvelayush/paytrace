"""The sample-data generator: realistic, repeatable, and containing the brief's orders exactly."""

from collections import Counter

import pytest

from app.sample_data.formats import FORMAT_CHANGED, FORMATS, render_amount
from app.sample_data.generator import BRIEF_ORDER_IDS, generate
from app.services.canonical import CANONICAL_FIELDS, ONE_OF_REQUIRED
from app.services.fingerprint import header_fingerprint


@pytest.fixture(scope="module")
def data():
    return generate(n_orders=3_000, seed=7)


def test_same_seed_gives_the_same_data():
    assert generate(n_orders=500, seed=1).orders == generate(n_orders=500, seed=1).orders


def test_brief_orders_are_included_exactly(data):
    orders = {order["order_id"]: order for order in data.orders}
    for order_id in BRIEF_ORDER_IDS:
        assert order_id in orders
    assert orders["ORD-W-204118"]["value_paise"] == 149_900
    assert orders["ORD-W-204377"]["delivery_status"] == "returned"


def test_unremitted_brief_order_has_no_remittance_or_freight(data):
    awb = next(order["awb"] for order in data.orders if order["order_id"] == "ORD-W-204118")
    assert not [line for line in data.cod_remittances if line["order_id"] == "ORD-W-204118" or line["awb"] == awb]
    assert not [line for line in data.freight_lines if line["awb"] == awb]


def test_order_ids_are_unique(data):
    counts = Counter(order["order_id"] for order in data.orders)
    assert max(counts.values()) == 1
    assert len(data.orders) == 3_000


def test_website_cod_share_is_about_55_percent():
    big = generate(n_orders=10_000, seed=3)
    website = [order for order in big.orders if order["channel"] == "Website"]
    cod_share = sum(order["payment_mode"] == "cod" for order in website) / len(website)
    assert 0.52 < cod_share < 0.58


def test_leakage_is_about_one_and_a_half_percent_of_value():
    big = generate(n_orders=10_000, seed=3)
    share = big.leak_value_paise / big.order_value_paise
    assert 0.01 < share < 0.025  # about 1.5% (brief); random variation at this size
    assert {leak_type for _, leak_type, _ in big.injected} == {
        "unremitted_cod", "unpaid_settlement", "short_commission", "wrong_weight_slab", "lost_return",
    }


def test_every_line_points_at_a_real_order(data):
    order_ids = {order["order_id"] for order in data.orders}
    awbs = {order["awb"] for order in data.orders if order["awb"]}
    assert all(line["order_id"] in order_ids for line in data.settlements)
    assert all(line["awb"] in awbs for line in data.cod_remittances + data.freight_lines)
    assert all(line["order_id"] in order_ids for line in data.receipts)


def test_average_order_value_is_around_1200(data):
    average = data.order_value_paise / len(data.orders) / 100
    assert 1_000 < average < 1_400


@pytest.mark.parametrize("layout", [*FORMATS, FORMAT_CHANGED], ids=lambda layout: layout.filename)
def test_every_layout_maps_all_required_fields(layout):
    mapped = set(layout.mapping()["columns"])
    required = {spec.name for spec in CANONICAL_FIELDS[layout.file_kind] if spec.required}
    assert required <= mapped
    if layout.file_kind in ONE_OF_REQUIRED:
        assert mapped & set(ONE_OF_REQUIRED[layout.file_kind])


def test_changed_layout_has_a_different_fingerprint():
    original = next(f for f in FORMATS if f.partner == "Marketplace 1" and f.file_kind == "settlement")
    assert header_fingerprint(original.headers) != header_fingerprint(FORMAT_CHANGED.headers)


def test_fingerprint_ignores_order_case_and_spacing():
    assert header_fingerprint(["Order ID", "Net  Payout"]) == header_fingerprint(["net payout ", "ORDER ID"])


@pytest.mark.parametrize(
    ("paise", "style", "text"),
    [(119_900, "plain", "1199.00"), (119_900, "commas", "1,199.00"), (12_345_600, "rupee", "₹1,23,456.00"), (-4_796, "plain", "-47.96")],
)
def test_amount_rendering(paise, style, text):
    assert render_amount(paise, style) == text
