"""Synthetic but realistic month of orders and partner lines, with labelled leakage.

Produces *canonical* records (paise, Python dates). `formats.py` then writes them out in each
partner's own file layout. Correct amounts come from the same expected-amount engine the app uses,
so every order is right unless leakage was deliberately injected, and each injected leak is
recorded in `SampleData.injected` so tests and the benchmark can check it is found.

Customers are invented. No real person's data is used anywhere.
"""

import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from app.services.expected import (
    ChannelTerms,
    CourierTerms,
    OrderFacts,
    expected_breakdown,
    percent_of,
    slab_price,
)
from app.services.reference_data import CHANNEL_RATE_CARDS, COURIER_RATE_CARDS

# Channel mix for a month (sums to 1). Website orders ship through our couriers; 55% are COD (brief).
CHANNEL_SHARE = {
    "Website": 0.40,
    "Marketplace 1": 0.20,
    "Marketplace 2": 0.15,
    "Marketplace 3": 0.10,
    "QuickCom 1": 0.09,
    "QuickCom 2": 0.06,
}
ORDER_ID_PREFIX = {
    "Website": ("ORD-W-", 200_001),
    "Marketplace 1": ("ORD-M-", 83_000),
    "Marketplace 2": ("ORD-N-", 50_001),
    "Marketplace 3": ("ORD-P-", 30_001),
    "QuickCom 1": ("ORD-Q-", 10_001),
    "QuickCom 2": ("ORD-R-", 70_001),
}
WEBSITE_COD_SHARE = 0.55
COURIER_A_SHARE = 0.6
SETTLEMENT_DAYS = {"Website": 3, "Courier A": 10, "Courier B": 10, "default": 7}

# Leakage rates (share of eligible orders), tuned to land near 1.5% of order value overall.
LEAK_UNREMITTED_COD = 0.02  # of delivered COD orders
LEAK_UNPAID_SETTLEMENT = 0.015  # of delivered marketplace / quick-commerce orders
LEAK_SHORT_COMMISSION = 0.035  # of delivered marketplace / quick-commerce orders
LEAK_WRONG_SLAB = 0.04  # of website shipments
LEAK_LOST_RETURN = 0.06  # of returned / RTO orders
NOISE_SMALL_DIFF = 0.01  # within ₹10: must stay settled
NOISE_OVERPAID = 0.002

FIRST_NAMES = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Ananya", "Vihaan", "Isha", "Arjun", "Saanvi", "Kiran", "Nisha", "Dev", "Pooja", "Rahul", "Lakshmi", "Farhan", "Zoya", "Tenzin", "Gurpreet"]
LAST_NAMES = ["Sharma", "Iyer", "Reddy", "Nair", "Khan", "Das", "Patel", "Gowda", "Menon", "Singh", "Rao", "Kulkarni", "Bose", "Joshi", "Fernandes"]
CITIES = [("Bengaluru", "560"), ("Mumbai", "400"), ("Delhi", "110"), ("Chennai", "600"), ("Hyderabad", "500"), ("Pune", "411"), ("Kolkata", "700"), ("Jaipur", "302"), ("Kochi", "682"), ("Lucknow", "226")]
STREETS = ["Lake View Road", "MG Road", "Station Road", "Temple Street", "Park Avenue", "Church Lane", "Ring Road", "Market Road"]
PRICE_POINTS = [299, 399, 499, 599, 699, 799, 899, 999, 1199, 1299, 1499, 1699, 1899, 1999, 2398, 2499, 2799, 2999, 3499, 3999, 4999]


@dataclass
class SampleData:
    start: date
    end: date
    orders: list[dict] = field(default_factory=list)
    settlements: list[dict] = field(default_factory=list)
    cod_remittances: list[dict] = field(default_factory=list)
    freight_lines: list[dict] = field(default_factory=list)
    receipts: list[dict] = field(default_factory=list)
    # (order_id, leak_type, amount_paise)
    injected: list[tuple[str, str, int]] = field(default_factory=list)
    # Lines sent without an order ID (review queue): {kind, partner, order_id (the truth), ambiguous}
    missing_ids: list[dict] = field(default_factory=list)

    @property
    def order_value_paise(self) -> int:
        return sum(order["value_paise"] for order in self.orders)

    @property
    def leak_value_paise(self) -> int:
        return sum(amount for _, _, amount in self.injected)


def _channel_terms(name: str) -> ChannelTerms:
    return ChannelTerms(**CHANNEL_RATE_CARDS[name])


def _courier_terms(name: str) -> CourierTerms:
    card = COURIER_RATE_CARDS[name]
    return CourierTerms(
        cod_fee_paise=card["cod_fee_paise"],
        cod_fee_pct_bp=card["cod_fee_pct_bp"],
        forward_slabs=tuple(card["forward"]),
        return_slabs=tuple(card["return"]),
    )


CHANNELS = {name: _channel_terms(name) for name in CHANNEL_RATE_CARDS}
COURIERS = {name: _courier_terms(name) for name in COURIER_RATE_CARDS}


class _Generator:
    def __init__(self, n_orders: int, seed: int, start: date, days: int, number_offset: int = 0) -> None:
        self.rng = random.Random(seed)
        self.number_offset = number_offset  # shifts order numbers and AWBs, for extra batches that must not collide
        self.n_orders = n_orders
        self.start = start
        self.days = days
        self.data = SampleData(start=start, end=start + timedelta(days=days - 1))
        self._utr = 900_000_000
        self._invoice = {"Courier A": 0, "Courier B": 0}

    # ---------- small helpers ----------

    def _price(self) -> int:
        # Log-normal around ₹1,200, snapped to realistic price points.
        target = self.rng.lognormvariate(math.log(1_200) - 0.5 * 0.45**2, 0.45)
        return min(PRICE_POINTS, key=lambda point: abs(point - target)) * 100

    def _weights(self, value_paise: int) -> tuple[int, int]:
        dead = int(250 + value_paise / 100 * 0.35 + self.rng.randint(-120, 200))
        dead = max(150, round(dead / 10) * 10)
        bulky = self.rng.random() < 0.25  # duvets and pillows are light but bulky
        volumetric = int(dead * (self.rng.uniform(1.2, 2.2) if bulky else self.rng.uniform(0.6, 1.0)))
        return dead, max(100, round(volumetric / 10) * 10)

    def _customer(self) -> dict:
        city, pin_prefix = self.rng.choice(CITIES)
        return {
            "customer_name": f"{self.rng.choice(FIRST_NAMES)} {self.rng.choice(LAST_NAMES)}",
            "customer_phone": f"{self.rng.choice('6789')}{self.rng.randint(0, 999_999_999):09d}",
            "customer_address": f"{self.rng.randint(1, 240)}, {self.rng.choice(STREETS)}, {city}",
            "pincode": f"{pin_prefix}{self.rng.randint(1, 99):03d}",
        }

    def _awb(self, courier: str, number: int) -> str:
        return f"CA{7_100_000_000 + number}" if courier == "Courier A" else f"{345_600_000_000 + number}"

    def _next_utr(self) -> str:
        self._utr += self.rng.randint(1, 9)
        return f"UTIB{self._utr}"

    def _invoice_no(self, courier: str, day: date) -> str:
        return f"{'CA' if courier == 'Courier A' else 'CB'}-INV-{day:%Y%m}-{day.day:02d}"

    # ---------- orders ----------

    def build(self) -> SampleData:
        counts = self._channel_counts()
        for channel, count in counts.items():
            prefix, base = ORDER_ID_PREFIX[channel]
            for index in range(count):
                number = base + self.number_offset + index
                self._make_order(channel, f"{prefix}{number}", number)
        return self.data

    def _channel_counts(self) -> dict[str, int]:
        counts = {name: int(self.n_orders * share) for name, share in CHANNEL_SHARE.items()}
        counts["Website"] += self.n_orders - sum(counts.values())
        return counts

    def _make_order(self, channel: str, order_id: str, number: int) -> None:
        rng = self.rng
        order_date = self.start + timedelta(days=rng.randrange(self.days))
        value = self._price()
        is_website = channel == "Website"
        payment_mode = "cod" if is_website and rng.random() < WEBSITE_COD_SHARE else "prepaid"
        courier = ("Courier A" if rng.random() < COURIER_A_SHARE else "Courier B") if is_website else None
        dead, volumetric = self._weights(value)

        roll = rng.random()
        rto_rate = 0.10 if payment_mode == "cod" else 0.03
        if roll < 0.005:
            status = "in_transit"
        elif is_website and roll < 0.005 + rto_rate:
            status = "rto"
        elif roll < 0.005 + (rto_rate if is_website else 0) + 0.06:
            status = "returned"
        else:
            status = "delivered"

        delivered = None if status in ("in_transit", "rto") else order_date + timedelta(days=rng.randint(2, 6))
        returned = None
        if status == "returned":
            returned = delivered + timedelta(days=rng.randint(5, 12))  # type: ignore[operator]
        elif status == "rto":
            returned = order_date + timedelta(days=rng.randint(7, 12))

        order = {
            "order_id": order_id,
            "channel": channel,
            "courier": courier,
            "awb": self._awb(courier, number) if courier else None,
            "order_date": order_date,
            "delivered_date": delivered,
            "returned_date": returned,
            "value_paise": value,
            "payment_mode": payment_mode,
            "delivery_status": status,
            "dead_weight_g": dead if is_website else None,
            "volumetric_weight_g": volumetric if is_website else None,
            **(self._customer() if is_website else {"customer_name": None, "customer_phone": None, "customer_address": None, "pincode": f"{rng.choice(CITIES)[1]}{rng.randint(1, 99):03d}"}),
        }
        self.data.orders.append(order)
        self._lines_for(order)

    # ---------- partner lines ----------

    def _lines_for(self, order: dict) -> None:
        if order["delivery_status"] == "in_transit":
            return
        channel_terms = CHANNELS[order["channel"]]
        courier_terms = COURIERS[order["courier"]] if order["courier"] else None
        facts = OrderFacts(
            value_paise=order["value_paise"],
            payment_mode=order["payment_mode"],
            delivery_status=order["delivery_status"],
            dead_weight_g=order["dead_weight_g"],
            volumetric_weight_g=order["volumetric_weight_g"],
        )
        breakdown = expected_breakdown(facts, channel_terms, courier_terms)
        returned = order["delivery_status"] in ("returned", "rto")

        if order["channel"] == "Website":
            if order["payment_mode"] == "prepaid":
                self._gateway_lines(order, channel_terms, refunded=returned)
            elif not returned:
                self._cod_remittance(order)
            self._freight(order, courier_terms, breakdown.chargeable_weight_g, returned)  # type: ignore[arg-type]
        else:
            self._marketplace_lines(order, channel_terms, reversed_=returned)

        if returned:
            self._receipt(order)

    def _gateway_lines(self, order: dict, terms: ChannelTerms, refunded: bool) -> None:
        value = order["value_paise"]
        fee = percent_of(value, terms.gateway_pct_bp)
        paid_on = (order["delivered_date"] or order["order_date"]) + timedelta(days=SETTLEMENT_DAYS["Website"])
        line = {"partner": "Website", "order_id": order["order_id"], "settlement_date": paid_on, "gross": value,
                "commission": 0, "fees": fee, "tcs": 0, "tds": 0, "net": value - fee, "reference": f"PG-{order['order_id'][-6:]}"}
        self.data.settlements.append(line)
        if refunded:
            refund_on = order["returned_date"] + timedelta(days=2)
            self.data.settlements.append({**line, "settlement_date": refund_on, "gross": -value, "fees": -fee,
                                          "net": -(value - fee), "reference": f"RF-{order['order_id'][-6:]}"})

    def _marketplace_lines(self, order: dict, terms: ChannelTerms, reversed_: bool) -> None:
        rng = self.rng
        partner = order["channel"]
        value = order["value_paise"]
        commission = percent_of(value, terms.commission_pct_bp)
        fees = terms.fixed_fee_paise
        tcs = percent_of(value, terms.tcs_pct_bp)
        tds = percent_of(value, terms.tds_pct_bp)
        paid_on = order["delivered_date"] + timedelta(days=SETTLEMENT_DAYS["default"]) if order["delivered_date"] else order["returned_date"]

        if not reversed_ and rng.random() < LEAK_UNPAID_SETTLEMENT:
            self.data.injected.append((order["order_id"], "unpaid_settlement", value - commission - fees))
            return

        extra_fee = 0
        if not reversed_:
            roll = rng.random()
            if roll < LEAK_SHORT_COMMISSION:
                extra_fee = rng.choice([2_500, 4_000, 6_000, 9_900, 15_000])
                self.data.injected.append((order["order_id"], "short_commission", extra_fee))
            elif roll < LEAK_SHORT_COMMISSION + NOISE_SMALL_DIFF:
                extra_fee = rng.choice([100, 500, 1_000])  # within the ₹10 tolerance
            elif roll < LEAK_SHORT_COMMISSION + NOISE_SMALL_DIFF + NOISE_OVERPAID:
                extra_fee = -5_000  # partner under-deducted: we were overpaid by ₹50

        reference = f"{partner[:2].upper()}{partner[-1]}-{order['order_id'][-5:]}"
        net = value - commission - fees - extra_fee - tcs - tds
        if not reversed_ and rng.random() < 0.04:
            # Paid in two lines: the sale, then a separate fee line a few days later.
            self.data.settlements.append({"partner": partner, "order_id": order["order_id"], "settlement_date": paid_on,
                                          "gross": value, "commission": commission, "fees": 0, "tcs": tcs, "tds": tds,
                                          "net": value - commission - tcs - tds, "reference": reference})
            self.data.settlements.append({"partner": partner, "order_id": order["order_id"],
                                          "settlement_date": paid_on + timedelta(days=3), "gross": 0, "commission": 0,
                                          "fees": fees + extra_fee, "tcs": 0, "tds": 0, "net": -(fees + extra_fee),
                                          "reference": f"{reference}-ADJ"})
            return

        line = {"partner": partner, "order_id": order["order_id"], "settlement_date": paid_on, "gross": value,
                "commission": commission, "fees": fees + extra_fee, "tcs": tcs, "tds": tds, "net": net, "reference": reference}
        self.data.settlements.append(line)
        if reversed_:
            self.data.settlements.append({**line, "settlement_date": order["returned_date"] + timedelta(days=3),
                                          "gross": -value, "commission": -commission, "fees": -fees, "tcs": -tcs,
                                          "tds": -tds, "net": -net, "reference": f"{reference}-REV"})

    def _cod_remittance(self, order: dict) -> None:
        if self.rng.random() < LEAK_UNREMITTED_COD:
            courier = COURIERS[order["courier"]]
            expected = order["value_paise"] - courier.cod_fee_paise - percent_of(order["value_paise"], courier.cod_fee_pct_bp)
            self.data.injected.append((order["order_id"], "unremitted_cod", expected))
            return
        has_order_id = self.rng.random() > 0.05  # some remittance lines carry only the AWB
        self.data.cod_remittances.append({
            "courier": order["courier"],
            "order_id": order["order_id"] if has_order_id else None,
            "awb": order["awb"],
            "remittance_date": order["delivered_date"] + timedelta(days=self.rng.randint(6, 10)),
            "amount": order["value_paise"],
            "utr": self._next_utr(),
        })

    def _freight(self, order: dict, terms: CourierTerms, weight: int, returned: bool) -> None:
        charged_weight = weight
        if self.rng.random() < LEAK_WRONG_SLAB:
            # Billed one or two slabs heavier than the parcel really was.
            limits = sorted(limit for limit, _ in terms.forward_slabs)
            heavier = [limit for limit in limits if limit > weight]
            if heavier:
                charged_weight = heavier[min(len(heavier) - 1, self.rng.randint(0, 1))] - self.rng.randint(0, 80)
        shipped_on = order["order_date"] + timedelta(days=1)
        legs = [("forward", terms.forward_slabs)] + ([("return", terms.return_slabs)] if returned else [])
        for leg, slabs in legs:
            correct = slab_price(slabs, weight)
            charged = slab_price(slabs, charged_weight)
            if charged != correct:
                self.data.injected.append((order["order_id"], "wrong_weight_slab", charged - correct))
            cod_fee = 0
            if leg == "forward" and order["payment_mode"] == "cod" and not returned:
                cod_fee = terms.cod_fee_paise + percent_of(order["value_paise"], terms.cod_fee_pct_bp)
            self.data.freight_lines.append({
                "courier": order["courier"],
                "awb": order["awb"],
                "order_id": order["order_id"],
                "invoice_no": self._invoice_no(order["courier"], shipped_on if leg == "forward" else order["returned_date"]),
                "charged_weight_g": charged_weight,
                "leg": leg,
                "freight": charged,
                "cod_fee": cod_fee,
            })

    def _receipt(self, order: dict) -> None:
        if self.rng.random() < LEAK_LOST_RETURN:
            self.data.injected.append((order["order_id"], "lost_return", order["value_paise"]))
            return
        scanned = datetime.combine(order["returned_date"] + timedelta(days=self.rng.randint(1, 5)), time(self.rng.randint(9, 19), self.rng.randint(0, 59)))
        self.data.receipts.append({"order_id": order["order_id"], "awb": order["awb"], "received_at": scanned})


# ---------- the brief's three sample orders, exactly ----------

def _brief_orders() -> tuple[list[dict], list[dict], list[dict], list[dict], list[tuple[str, str, int]]]:
    blank_customer = {"customer_name": None, "customer_phone": None, "customer_address": None}
    orders = [
        {"order_id": "ORD-W-204118", "channel": "Website", "courier": "Courier A", "awb": "CA7100004118",
         "order_date": date(2026, 10, 1), "delivered_date": date(2026, 10, 4), "returned_date": None,
         "value_paise": 149_900, "payment_mode": "cod", "delivery_status": "delivered",
         "dead_weight_g": 450, "volumetric_weight_g": 400, "customer_name": "Meera Iyer",
         "customer_phone": "9845012345", "customer_address": "14, Lake View Road, Bengaluru", "pincode": "560034"},
        {"order_id": "ORD-M-88120", "channel": "Marketplace 1", "courier": None, "awb": None,
         "order_date": date(2026, 10, 2), "delivered_date": date(2026, 10, 6), "returned_date": None,
         "value_paise": 119_900, "payment_mode": "prepaid", "delivery_status": "delivered",
         "dead_weight_g": None, "volumetric_weight_g": None, **blank_customer, "pincode": "400053"},
        {"order_id": "ORD-W-204377", "channel": "Website", "courier": "Courier B", "awb": "345600004377",
         "order_date": date(2026, 10, 3), "delivered_date": date(2026, 10, 7), "returned_date": date(2026, 10, 14),
         "value_paise": 239_800, "payment_mode": "prepaid", "delivery_status": "returned",
         "dead_weight_g": 480, "volumetric_weight_g": 420, "customer_name": "Rohan Das",
         "customer_phone": "9731198765", "customer_address": "3, Park Avenue, Kolkata", "pincode": "700016"},
    ]
    settlements = [
        # ORD-M-88120: ₹37 more fees deducted than the rate card allows -> received ₹862 vs expected ₹899.
        {"partner": "Marketplace 1", "order_id": "ORD-M-88120", "settlement_date": date(2026, 10, 13), "gross": 119_900,
         "commission": 23_980, "fees": 9_720, "tcs": 600, "tds": 120, "net": 85_480, "reference": "MA1-88120"},
        # ORD-W-204377: paid through the gateway, then refunded on return.
        {"partner": "Website", "order_id": "ORD-W-204377", "settlement_date": date(2026, 10, 10), "gross": 239_800,
         "commission": 0, "fees": 4_796, "tcs": 0, "tds": 0, "net": 235_004, "reference": "PG-204377"},
        {"partner": "Website", "order_id": "ORD-W-204377", "settlement_date": date(2026, 10, 16), "gross": -239_800,
         "commission": 0, "fees": -4_796, "tcs": 0, "tds": 0, "net": -235_004, "reference": "RF-204377"},
    ]
    # ORD-W-204377 billed on 900 g instead of 480 g on both legs: ₹71 + ₹71 instead of ₹48 + ₹48.
    freight = [
        {"courier": "Courier B", "awb": "345600004377", "order_id": "ORD-W-204377", "invoice_no": "CB-INV-202610-04",
         "charged_weight_g": 900, "leg": "forward", "freight": 7_100, "cod_fee": 0},
        {"courier": "Courier B", "awb": "345600004377", "order_id": "ORD-W-204377", "invoice_no": "CB-INV-202610-14",
         "charged_weight_g": 900, "leg": "return", "freight": 7_100, "cod_fee": 0},
    ]
    receipts = [{"order_id": "ORD-W-204377", "awb": "345600004377", "received_at": datetime(2026, 10, 16, 11, 20)}]
    # ORD-W-204118: COD collected but never remitted, and not yet invoiced -> received ₹0.
    injected = [("ORD-W-204118", "unremitted_cod", 140_900), ("ORD-M-88120", "short_commission", 3_700),
                ("ORD-W-204377", "wrong_weight_slab", 4_600)]
    return orders, settlements, freight, receipts, injected


BRIEF_ORDER_IDS = ("ORD-W-204118", "ORD-M-88120", "ORD-W-204377")


def generate(
    n_orders: int = 30_000,
    seed: int = 20261001,
    start: date = date(2026, 9, 21),
    days: int = 30,
    include_brief_samples: bool = True,
    missing_id_share: float = 0.0,
    ambiguous_pairs: int = 0,
    number_offset: int = 0,
) -> SampleData:
    """A month of orders (default 21 Sep – 20 Oct 2026) with every partner's lines and injected leakage.

    `missing_id_share` > 0 sends that share of marketplace / quick-commerce settlement lines and courier COD
    lines without an order ID (and without the AWB), plus `ambiguous_pairs` pairs of look-alike lines, for the
    review queue. Off by default, so tests and the benchmark see every line with its ID.
    """
    data = _Generator(n_orders, seed, start, days, number_offset).build()
    if include_brief_samples:
        _add_brief_samples(data)
    if missing_id_share > 0 or ambiguous_pairs > 0:
        _strip_order_ids(data, missing_id_share, ambiguous_pairs, random.Random(seed + 7))
    return data


def _add_brief_samples(data: SampleData) -> None:
    """Replace three generated orders with the brief's sample orders, exactly."""
    orders, settlements, freight, receipts, injected = _brief_orders()
    ids = set(BRIEF_ORDER_IDS)
    # A brief ID outside the generated range (small runs) would add an extra order: drop the last
    # generated order of the same channel instead, so the total stays exactly `n_orders`.
    generated_ids = {order["order_id"] for order in data.orders}
    for brief_order in orders:
        if brief_order["order_id"] not in generated_ids:
            same_channel = [order for order in data.orders if order["channel"] == brief_order["channel"] and order["order_id"] not in ids]
            ids.add(same_channel[-1]["order_id"])
    # Drop the generated orders being replaced, and every line that pointed at them
    # (by order ID or by their own AWB), before adding the exact brief versions.
    replaced_awbs = {order["awb"] for order in data.orders if order["order_id"] in ids and order["awb"]}

    def belongs_to_replaced(line: dict) -> bool:
        return line.get("order_id") in ids or line.get("awb") in replaced_awbs

    data.orders = [order for order in data.orders if order["order_id"] not in ids] + orders
    data.settlements = [line for line in data.settlements if not belongs_to_replaced(line)] + settlements
    data.cod_remittances = [line for line in data.cod_remittances if not belongs_to_replaced(line)]
    data.freight_lines = [line for line in data.freight_lines if not belongs_to_replaced(line)] + freight
    data.receipts = [line for line in data.receipts if not belongs_to_replaced(line)] + receipts
    data.injected = [leak for leak in data.injected if leak[0] not in ids] + injected


def _strip_order_ids(data: SampleData, share: float, ambiguous_pairs: int, rng: random.Random) -> None:
    """Blank the order ID (and AWB) on some paid lines, as partners sometimes send them."""
    protected = set(BRIEF_ORDER_IDS) | {order_id for order_id, _, _ in data.injected}
    orders = {order["order_id"]: order for order in data.orders}
    lines_per_order = Counter(line["order_id"] for line in data.settlements)
    # Single-line payouts only: a split payment with one line missing would be a different story.
    settlement = [line for line in data.settlements if line["partner"] != "Website" and line["order_id"] not in protected
                  and lines_per_order[line["order_id"]] == 1 and orders[line["order_id"]]["delivery_status"] == "delivered"]
    cod = [line for line in data.cod_remittances if line["order_id"] and line["order_id"] not in protected]

    chosen: list[tuple[str, dict, bool]] = []
    # Look-alike pairs: same partner and sale value, delivered on the same day. Their lines differ only in date.
    by_look = defaultdict(list)
    for line in settlement:
        by_look[(line["partner"], line["gross"], orders[line["order_id"]]["delivered_date"])].append(line)
    pairs = [group[:2] for _, group in sorted(by_look.items(), key=lambda item: str(item[0])) if len(group) >= 2]
    rng.shuffle(pairs)
    for pair in pairs[:ambiguous_pairs]:
        chosen += [("settlement", line, True) for line in pair]
    taken = {id(line) for _, line, _ in chosen}
    pool = [line for line in settlement if id(line) not in taken]
    chosen += [("settlement", line, False) for line in rng.sample(pool, min(len(pool), round(len(pool) * share)))]
    chosen += [("cod_remittance", line, False) for line in rng.sample(cod, min(len(cod), round(len(cod) * share * 2)))]

    for kind, line, ambiguous in chosen:
        partner = line["partner"] if kind == "settlement" else line["courier"]
        data.missing_ids.append({"kind": kind, "partner": partner, "order_id": line["order_id"], "ambiguous": ambiguous})
        line["order_id"] = None
        if kind == "settlement":
            # The partner's own reference, not derived from our order number (otherwise the match would be trivial).
            line["reference"] = f"{partner[:2].upper()}{partner[-1]}-U{rng.randint(100_000, 999_999)}"
        else:
            line["awb"] = None
