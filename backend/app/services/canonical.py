"""Canonical fields: the columns PayTrace needs from each kind of partner file.

Every uploaded file is mapped onto these fields (by a saved mapping, the AI suggester or the user),
then parsed into typed values. Keeping the list in one place means parsing, validation, the AI prompt
and the mapping screen all agree.
"""

from dataclasses import dataclass
from typing import Literal

FieldType = Literal["text", "order_id", "date", "datetime", "money", "weight", "payment_mode", "delivery_status", "leg"]


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    type: FieldType
    required: bool = False
    description: str = ""
    pii: bool = False  # masked at ingestion and before anything is sent to the AI


def _f(name: str, label: str, type: FieldType, required: bool = False, description: str = "", pii: bool = False) -> FieldSpec:
    return FieldSpec(name, label, type, required, description, pii)


CANONICAL_FIELDS: dict[str, list[FieldSpec]] = {
    "orders": [
        _f("order_id", "Order ID", "order_id", True, "The brand's order number"),
        _f("order_date", "Order date", "date", True),
        _f("value", "Order value", "money", True, "Amount the customer paid, including GST"),
        _f("payment_mode", "Payment mode", "payment_mode", True, "COD or prepaid"),
        _f("delivery_status", "Delivery status", "delivery_status", True, "Delivered, returned, RTO, in transit, cancelled"),
        _f("delivered_date", "Delivered date", "date"),
        _f("returned_date", "Returned date", "date", description="Date the courier marked the return or RTO"),
        _f("awb", "AWB / tracking number", "text"),
        _f("courier", "Courier", "text", description="Courier name; only for orders we ship ourselves"),
        _f("dead_weight", "Dead weight", "weight"),
        _f("volumetric_weight", "Volumetric weight", "weight"),
        _f("customer_name", "Customer name", "text", pii=True),
        _f("customer_phone", "Customer phone", "text", pii=True),
        _f("customer_address", "Customer address", "text", pii=True),
        _f("pincode", "Pincode", "text"),
    ],
    "settlement": [
        _f("order_id", "Order ID", "order_id", True),
        _f("settlement_date", "Settlement date", "date", True),
        _f("gross", "Gross amount", "money", description="Sale amount before deductions"),
        _f("commission", "Commission", "money"),
        _f("fees", "Other fees", "money", description="Fixed, shipping, gateway or other fees"),
        _f("tcs", "GST TCS", "money", description="Tax collected at source (tax, not leakage)"),
        _f("tds", "Income-tax TDS", "money", description="Tax deducted at source (tax, not leakage)"),
        _f("net", "Net paid", "money", True, "Amount actually paid out for this line"),
        _f("reference", "Line reference", "text"),
    ],
    "cod_remittance": [
        _f("order_id", "Order ID", "order_id", description="Order ID or AWB is required"),
        _f("awb", "AWB / tracking number", "text", description="Order ID or AWB is required"),
        _f("remittance_date", "Remittance date", "date", True),
        _f("amount", "Amount remitted", "money", True),
        _f("utr", "Bank UTR", "text"),
    ],
    "freight_invoice": [
        _f("awb", "AWB / tracking number", "text", description="AWB or order ID is required"),
        _f("order_id", "Order ID", "order_id", description="AWB or order ID is required"),
        _f("invoice_no", "Invoice number", "text"),
        _f("charged_weight", "Charged weight", "weight"),
        _f("leg", "Leg", "leg", True, "Forward or return / RTO"),
        _f("freight", "Freight charge", "money", True),
        _f("cod_fee", "COD charge", "money"),
    ],
    "warehouse_returns": [
        _f("order_id", "Order ID", "order_id", description="Order ID or AWB is required"),
        _f("awb", "AWB / tracking number", "text", description="Order ID or AWB is required"),
        _f("received_at", "Received at", "datetime", True, "When the return was scanned in at the warehouse"),
    ],
}

# For these kinds at least one of the listed fields must be mapped and filled on every row.
ONE_OF_REQUIRED: dict[str, tuple[str, ...]] = {
    "cod_remittance": ("order_id", "awb"),
    "freight_invoice": ("awb", "order_id"),
    "warehouse_returns": ("order_id", "awb"),
}


def fields_for(file_kind: str) -> list[FieldSpec]:
    return CANONICAL_FIELDS[file_kind]


def field_names(file_kind: str) -> list[str]:
    return [spec.name for spec in CANONICAL_FIELDS[file_kind]]
