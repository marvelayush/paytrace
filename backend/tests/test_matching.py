"""Reconciliation engine: agreement with the reference engine, every status rule, boundaries, and leak detection."""

from datetime import date, timedelta

import polars as pl
import pytest

from app.sample_data.frames import PARTNER_IDS, inputs_from_sample
from app.sample_data.generator import SampleData, generate
from app.services.expected import ChannelTerms, CourierTerms, OrderFacts, expected_breakdown
from app.services.matching import FLAGGED_STATUSES, auto_match_rate, expected_amounts, reconcile
from app.services.reference_data import CHANNEL_RATE_CARDS, COURIER_RATE_CARDS

AS_OF = date(2026, 11, 3)


@pytest.fixture(scope="module")
def month() -> SampleData:
    return generate(n_orders=6_000, seed=11)


@pytest.fixture(scope="module")
def month_results(month):
    results, unmatched = reconcile(inputs_from_sample(month), AS_OF, 7)
    return results, unmatched


def _result(results: pl.DataFrame, order_id: str) -> dict:
    return results.filter(pl.col("order_id") == order_id).to_dicts()[0]


# ---------- the vectorised engine agrees with the readable reference ----------

def test_vectorised_expected_amounts_match_the_reference_engine(month):
    inputs = inputs_from_sample(month)
    vectorised = expected_amounts(inputs.orders, inputs.rate_cards, inputs.slabs)
    by_id = {row["order_id"]: row for row in vectorised.to_dicts()}
    for order in month.orders:
        courier = COURIER_RATE_CARDS.get(order["courier"]) if order["courier"] else None
        reference = expected_breakdown(
            OrderFacts(order["value_paise"], order["payment_mode"], order["delivery_status"], order["dead_weight_g"], order["volumetric_weight_g"]),
            ChannelTerms(**CHANNEL_RATE_CARDS[order["channel"]]),
            CourierTerms(courier["cod_fee_paise"], courier["cod_fee_pct_bp"], tuple(courier["forward"]), tuple(courier["return"])) if courier else None,
        )
        row = by_id[order["order_id"]]
        assert (row["expected_paise"], row["exp_tcs"], row["exp_tds"], row["expected_freight_paise"]) == (
            reference.expected_amount, reference.tcs, reference.tds, reference.freight,
        ), order["order_id"]


# ---------- the brief's samples ----------

def test_brief_samples_reconcile_exactly(month_results):
    results, _ = month_results
    cod = _result(results, "ORD-W-204118")
    assert (cod["expected_paise"], cod["received_paise"], cod["diff_paise"], cod["status"]) == (140_900, 0, -140_900, "unpaid_past_due")

    marketplace = _result(results, "ORD-M-88120")
    assert (marketplace["expected_paise"], marketplace["received_paise"], marketplace["diff_paise"], marketplace["status"]) == (89_900, 86_200, -3_700, "short_paid")
    assert (marketplace["tcs_paise"], marketplace["tds_paise"]) == (600, 120)  # shown separately, not leakage

    returned = _result(results, "ORD-W-204377")
    assert (returned["expected_paise"], returned["received_paise"], returned["diff_paise"], returned["status"]) == (-9_600, -14_200, -4_600, "freight_overcharged")
    assert returned["partner_id"] == PARTNER_IDS["Courier B"]


# ---------- every injected leak is caught ----------

def test_every_injected_leak_is_flagged(month, month_results):
    results, _ = month_results
    statuses = dict(zip(results["order_id"].to_list(), results["status"].to_list()))
    orders = {order["order_id"]: order for order in month.orders}
    missed = []
    for order_id, leak_type, _ in month.injected:
        order = orders[order_id]
        # A lost return is only flagged once its 7-day receipt window has passed.
        if leak_type == "lost_return" and order["returned_date"] + timedelta(days=7) >= AS_OF:
            assert statuses[order_id] == "pending"
            continue
        # Money nobody has paid yet only becomes overdue after the partner's settlement cycle (A3).
        cycle = 10 if leak_type == "unremitted_cod" else 7
        if leak_type in ("unremitted_cod", "unpaid_settlement") and order["delivered_date"] + timedelta(days=cycle) >= AS_OF:
            assert statuses[order_id] == "pending"
            continue
        if statuses[order_id] not in FLAGGED_STATUSES:
            missed.append((order_id, leak_type, statuses[order_id]))
    assert missed == []


def test_clean_orders_are_not_flagged(month, month_results):
    results, _ = month_results
    leaked = {order_id for order_id, _, _ in month.injected}
    false_alarms = results.filter(pl.col("status").is_in(FLAGGED_STATUSES) & ~pl.col("order_id").is_in(list(leaked)))
    assert false_alarms.height == 0


def test_auto_match_rate_meets_the_brief_target(month_results):
    results, unmatched = month_results
    assert auto_match_rate(results) >= 98.0
    assert unmatched == {"settlement": 0, "cod": 0, "freight": 0}


# ---------- rules on hand-made orders ----------

def _single_order(
    status: str = "delivered", channel: str = "Marketplace 1", value: int = 100_000, mode: str = "prepaid",
    courier: str | None = None, delivered: date | None = date(2026, 10, 1), returned: date | None = None,
    settlements: list[dict] | None = None, cod: list[dict] | None = None, freight: list[dict] | None = None,
    receipts: list[dict] | None = None, weight: int | None = None,
) -> SampleData:
    data = SampleData(start=date(2026, 9, 25), end=date(2026, 9, 25))
    data.orders = [{
        "order_id": "T-1", "channel": channel, "courier": courier, "awb": "AWB1" if courier else None,
        "order_date": date(2026, 9, 25), "delivered_date": delivered, "returned_date": returned, "value_paise": value,
        "payment_mode": mode, "delivery_status": status, "dead_weight_g": weight, "volumetric_weight_g": weight,
    }]
    data.settlements = [{"order_id": "T-1", "tcs": 0, "tds": 0, **line} for line in (settlements or [])]
    data.cod_remittances = [{"order_id": None, "awb": "AWB1", **line} for line in (cod or [])]
    data.freight_lines = [{"courier": courier, "order_id": "T-1", "awb": "AWB1", "cod_fee": 0, **line} for line in (freight or [])]
    data.receipts = receipts or []
    return data


def _status(data: SampleData, as_of: date = AS_OF) -> dict:
    results, _ = reconcile(inputs_from_sample(data), as_of, 7)
    return results.to_dicts()[0]


# Marketplace 1 on ₹1,000: 20% commission (200) + ₹60.20 fixed fee = expected ₹739.80; TCS ₹5.00, TDS ₹1.00.
EXPECTED_M1 = 73_980


@pytest.mark.parametrize(
    ("received", "status", "overpaid"),
    [
        (EXPECTED_M1, "settled", False),
        (EXPECTED_M1 - 1_000, "settled", False),  # exactly ₹10 short: within tolerance
        (EXPECTED_M1 - 1_001, "short_paid", False),  # ₹10.01 short: flagged
        (EXPECTED_M1 + 1_000, "settled", False),
        (EXPECTED_M1 + 1_001, "settled", True),  # overpaid more than ₹10: settled, flagged as overpaid
    ],
)
def test_ten_rupee_boundary(received, status, overpaid):
    # The partner withholds TCS and TDS from the net; they are added back, never counted as leakage.
    line = {"net": received - 500 - 100, "tcs": 500, "tds": 100}
    result = _status(_single_order(settlements=[line]))
    assert (result["status"], result["overpaid"], result["diff_paise"]) == (status, overpaid, received - EXPECTED_M1)


def test_tax_withheld_is_not_leakage():
    result = _status(_single_order(settlements=[{"net": EXPECTED_M1 - 600, "tcs": 500, "tds": 100}]))
    assert (result["status"], result["diff_paise"], result["tcs_paise"], result["tds_paise"]) == ("settled", 0, 500, 100)


def test_multiple_settlement_lines_are_summed():
    lines = [{"net": 50_000, "tcs": 500, "tds": 100}, {"net": EXPECTED_M1 - 600 - 50_000}]
    result = _status(_single_order(settlements=lines))
    assert (result["status"], result["received_paise"]) == ("settled", EXPECTED_M1)


def test_unpaid_before_due_date_is_pending_and_after_is_unpaid():
    delivered = date(2026, 10, 30)
    assert _status(_single_order(delivered=delivered), as_of=delivered + timedelta(days=7))["status"] == "pending"
    late = _status(_single_order(delivered=delivered), as_of=delivered + timedelta(days=8))
    assert (late["status"], late["at_risk_paise"], late["age_days"]) == ("unpaid_past_due", EXPECTED_M1, 1)


def test_cod_remitted_by_awb_only_is_matched():
    # Website ₹1,000 COD via Courier A (300 g): expected 1,000 − 30 COD fee − 60 freight = ₹910.
    data = _single_order(channel="Website", mode="cod", courier="Courier A", weight=300, cod=[{"amount": 100_000}],
                         freight=[{"leg": "forward", "freight": 6_000, "cod_fee": 3_000}])
    result = _status(data)
    assert (result["status"], result["expected_paise"], result["received_paise"]) == ("settled", 91_000, 91_000)
    assert result["partner_id"] == PARTNER_IDS["Courier A"]


def test_unremitted_cod_is_owed_by_the_courier():
    data = _single_order(channel="Website", mode="cod", courier="Courier A", weight=300)
    result = _status(data)
    assert (result["status"], result["partner_id"]) == ("unpaid_past_due", PARTNER_IDS["Courier A"])


@pytest.mark.parametrize(("charged", "status"), [(6_000 + 1_000, "settled"), (6_000 + 1_001, "freight_overcharged")])
def test_freight_overcharge_boundary(charged, status):
    # Paid in full by the gateway; only the courier's freight differs from the ₹60 slab.
    data = _single_order(channel="Website", courier="Courier A", weight=300, settlements=[{"net": 100_000 - 2_000}],
                         freight=[{"leg": "forward", "freight": charged}])
    assert _status(data)["status"] == status


def test_freight_overcharge_wins_over_short_payment():
    data = _single_order(channel="Website", courier="Courier A", weight=300, settlements=[{"net": 50_000}],
                         freight=[{"leg": "forward", "freight": 12_500}])
    assert _status(data)["status"] == "freight_overcharged"


def test_return_without_warehouse_scan_is_flagged_after_the_window():
    returned_on = date(2026, 10, 20)
    data = _single_order(status="returned", channel="Website", courier="Courier B", weight=480, returned=returned_on,
                         freight=[{"leg": "forward", "freight": 4_800}, {"leg": "return", "freight": 4_800}])
    assert _status(data, as_of=returned_on + timedelta(days=7))["status"] == "pending"
    lost = _status(data, as_of=returned_on + timedelta(days=8))
    assert (lost["status"], lost["at_risk_paise"], lost["partner_id"]) == ("return_not_received", 100_000, PARTNER_IDS["Courier B"])


def test_return_with_scan_is_settled():
    returned_on = date(2026, 10, 20)
    data = _single_order(status="returned", channel="Website", courier="Courier B", weight=480, returned=returned_on,
                         freight=[{"leg": "forward", "freight": 4_800}, {"leg": "return", "freight": 4_800}],
                         receipts=[{"order_id": "T-1", "received_at": date(2026, 10, 22)}])
    assert _status(data)["status"] == "settled"


def test_in_transit_order_is_pending():
    assert _status(_single_order(status="in_transit", delivered=None))["status"] == "pending"
