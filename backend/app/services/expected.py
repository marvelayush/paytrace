"""Expected-amount engine: what each order *should* bring in, itemised.

These are plain, pure functions over integer paise (A10). They are the readable reference
implementation; the vectorised Polars version in `matching.py` must agree with them, and a test
checks that it does on thousands of generated orders.

Model (see docs/ASSUMPTIONS.md):
- Delivered order: expected = value − commission − fixed fee − gateway fee (prepaid) − COD fee (COD)
  − forward freight. TCS and TDS are computed separately and are NOT part of the expected amount (A6):
  they are tax credits, not leakage.
- Returned / RTO order: the sale and the channel's fees are reversed (A15), so the expected amount is
  minus the freight on both legs.
- Cancelled order: nothing expected.
- Freight applies only when the order shipped through one of our couriers (website orders). Chargeable
  weight is the higher of dead and volumetric weight, priced from the courier's slabs (A9).
"""

from dataclasses import asdict, dataclass, field

from app.models.enums import RETURNED_STATUSES

BASIS_POINTS = 10_000


@dataclass(frozen=True)
class ChannelTerms:
    """The sales channel's rate card. Percentages are basis points (1% = 100 bp)."""

    commission_pct_bp: int = 0
    fixed_fee_paise: int = 0
    gateway_pct_bp: int = 0
    tcs_pct_bp: int = 0
    tds_pct_bp: int = 0


@dataclass(frozen=True)
class CourierTerms:
    """The courier's rate card: COD fee and weight slabs per leg, as (up_to_g, price_paise)."""

    cod_fee_paise: int = 0
    cod_fee_pct_bp: int = 0
    forward_slabs: tuple[tuple[int, int], ...] = ()
    return_slabs: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class OrderFacts:
    value_paise: int
    payment_mode: str  # "cod" | "prepaid"
    delivery_status: str  # delivered | returned | rto | in_transit | cancelled
    dead_weight_g: int | None = None
    volumetric_weight_g: int | None = None


@dataclass(frozen=True)
class ExpectedBreakdown:
    """Where every rupee of an order is expected to go. All amounts in paise."""

    value: int = 0
    commission: int = 0
    fixed_fee: int = 0
    gateway_fee: int = 0
    cod_fee: int = 0
    forward_freight: int = 0
    return_freight: int = 0
    tcs: int = 0
    tds: int = 0
    chargeable_weight_g: int = 0
    is_returned: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def freight(self) -> int:
        return self.forward_freight + self.return_freight

    @property
    def expected_amount(self) -> int:
        """Expected money for the order before tax. This is what received money is compared with."""
        return (
            self.value
            - self.commission
            - self.fixed_fee
            - self.gateway_fee
            - self.cod_fee
            - self.forward_freight
            - self.return_freight
        )

    @property
    def expected_in_bank(self) -> int:
        """What should actually land in the bank: the expected amount less tax withheld at source."""
        return self.expected_amount - self.tcs - self.tds

    def to_dict(self) -> dict:
        data = asdict(self)
        data["notes"] = list(self.notes)
        data["freight"] = self.freight
        data["expected_amount"] = self.expected_amount
        data["expected_in_bank"] = self.expected_in_bank
        return data


def percent_of(amount_paise: int, rate_bp: int) -> int:
    """`rate_bp` basis points of an amount, rounded half up to the nearest paisa."""
    if amount_paise < 0:
        return -percent_of(-amount_paise, rate_bp)
    return (amount_paise * rate_bp + BASIS_POINTS // 2) // BASIS_POINTS


def chargeable_weight(dead_weight_g: int | None, volumetric_weight_g: int | None) -> int:
    """The higher of dead and volumetric weight (A9). Missing weights count as 0."""
    return max(dead_weight_g or 0, volumetric_weight_g or 0)


def slab_price(slabs: tuple[tuple[int, int], ...], weight_g: int) -> int:
    """Price of the first slab whose upper limit covers the weight.

    Heavier than the last slab: the last slab's price applies (A16). No slabs: 0.
    """
    if not slabs:
        return 0
    for up_to_g, price_paise in sorted(slabs):
        if weight_g <= up_to_g:
            return price_paise
    return max(slabs)[1]


def expected_breakdown(
    order: OrderFacts,
    channel: ChannelTerms,
    courier: CourierTerms | None = None,
) -> ExpectedBreakdown:
    """Itemised expected amount for one order. `courier` is None when the channel ships the order itself."""
    if order.delivery_status == "cancelled":
        return ExpectedBreakdown(notes=("Cancelled before shipping: nothing expected.",))

    weight = chargeable_weight(order.dead_weight_g, order.volumetric_weight_g)
    forward_freight = slab_price(courier.forward_slabs, weight) if courier else 0

    if order.delivery_status in RETURNED_STATUSES:
        return_freight = slab_price(courier.return_slabs, weight) if courier else 0
        return ExpectedBreakdown(
            forward_freight=forward_freight,
            return_freight=return_freight,
            chargeable_weight_g=weight,
            is_returned=True,
            notes=("Returned: sale and channel fees reversed, freight on both legs is a cost.",),
        )

    value = order.value_paise
    is_cod = order.payment_mode == "cod"
    cod_fee = 0
    if is_cod and courier:
        cod_fee = courier.cod_fee_paise + percent_of(value, courier.cod_fee_pct_bp)

    return ExpectedBreakdown(
        value=value,
        commission=percent_of(value, channel.commission_pct_bp),
        fixed_fee=channel.fixed_fee_paise,
        gateway_fee=0 if is_cod else percent_of(value, channel.gateway_pct_bp),
        cod_fee=cod_fee,
        forward_freight=forward_freight,
        tcs=percent_of(value, channel.tcs_pct_bp),
        tds=percent_of(value, channel.tds_pct_bp),
        chargeable_weight_g=weight,
    )
