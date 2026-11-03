"""Each partner's own file layout: header names, column order, date and amount styles, units, CSV or Excel.

Partners deliberately disagree (DD-MM-YYYY vs ISO dates, "₹1,199.00" vs "1199", grams vs kg,
AWB-only remittances...), which is exactly why PayTrace needs per-source column mappings.
"""

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from openpyxl import Workbook

from app.sample_data.generator import SampleData

AmountStyle = Literal["plain", "commas", "rupee"]


@dataclass(frozen=True)
class FileFormat:
    partner: str
    file_kind: str
    filename: str
    columns: list[tuple[str | None, str]]  # (canonical field or None for an extra column, header)
    date_format: str = "%Y-%m-%d"
    datetime_format: str = "%Y-%m-%d %H:%M"
    amount_style: AmountStyle = "plain"
    weight_unit: Literal["g", "kg"] = "g"
    excel: bool = False
    words: dict[str, dict[str, str]] = field(default_factory=dict)  # canonical value -> partner wording

    @property
    def headers(self) -> list[str]:
        return [header for _, header in self.columns]

    def mapping(self) -> dict:
        """The column mapping that reads this layout (seeded as version 1 for the source)."""
        return {"columns": {canonical: header for canonical, header in self.columns if canonical}}


STATUS_WORDS_TITLE = {"delivered": "Delivered", "returned": "Returned", "rto": "RTO", "in_transit": "In Transit", "cancelled": "Cancelled"}
PAYMENT_WORDS = {"cod": "COD", "prepaid": "Prepaid"}

FORMATS: list[FileFormat] = [
    FileFormat("Website", "orders", "website_orders.csv", [
        ("order_id", "Order Number"), ("order_date", "Order Date"), ("value", "Order Total (INR)"),
        ("payment_mode", "Payment Method"), ("delivery_status", "Shipment Status"), ("delivered_date", "Delivered On"),
        ("returned_date", "Returned On"), ("awb", "AWB"), ("courier", "Courier Partner"), ("dead_weight", "Weight (g)"),
        ("volumetric_weight", "Volumetric Weight (g)"), ("customer_name", "Customer Name"),
        ("customer_phone", "Customer Phone"), ("customer_address", "Shipping Address"), ("pincode", "Pincode"),
    ], words={"payment_mode": PAYMENT_WORDS, "delivery_status": STATUS_WORDS_TITLE}),
    FileFormat("Website", "settlement", "website_gateway_settlement.csv", [
        ("settlement_date", "Txn Date"), ("order_id", "Merchant Order ID"), ("gross", "Amount"), ("fees", "MDR Fee"),
        ("net", "Settled Amount"), ("reference", "Settlement ID"),
    ], date_format="%d/%m/%Y"),
    FileFormat("Marketplace 1", "orders", "marketplace1_orders.csv", [
        ("order_id", "order-id"), ("order_date", "purchase-date"), ("value", "item-price"),
        ("payment_mode", "payment-method"), ("delivery_status", "order-status"), ("delivered_date", "delivery-date"),
        ("returned_date", "return-date"), ("pincode", "ship-postal-code"),
    ], date_format="%d-%m-%Y", words={"payment_mode": PAYMENT_WORDS, "delivery_status": {
        "delivered": "Shipped - Delivered", "returned": "Shipped - Returned to Seller", "in_transit": "Shipped - In Transit"}}),
    FileFormat("Marketplace 1", "settlement", "marketplace1_settlement.xlsx", [
        ("settlement_date", "Settlement Date"), ("order_id", "Order ID"), ("gross", "Sale Amount"),
        ("commission", "Commission Fee"), ("fees", "Other Fees"), ("tcs", "TCS (GST)"), ("tds", "TDS (194-O)"),
        ("net", "Net Payout"), ("reference", "Txn Ref"),
    ], excel=True),
    FileFormat("Marketplace 2", "orders", "marketplace2_orders.csv", [
        ("order_id", "SubOrderNo"), ("order_date", "OrderDate"), ("value", "SellingPrice"), ("payment_mode", "PaymentType"),
        ("delivery_status", "Status"), ("delivered_date", "DeliveredDate"), ("returned_date", "ReturnDate"), ("pincode", "Pincode"),
    ], date_format="%d/%m/%Y", amount_style="commas", words={"payment_mode": {"prepaid": "PREPAID", "cod": "COD"},
        "delivery_status": {"delivered": "DELIVERED", "returned": "RETURNED", "in_transit": "SHIPPED"}}),
    FileFormat("Marketplace 2", "settlement", "marketplace2_settlement.csv", [
        ("settlement_date", "Payment Date"), ("order_id", "Sub Order No"), ("gross", "Order Value"),
        ("commission", "Marketplace Commission"), ("fees", "Fixed Fee"), ("tcs", "GST TCS"), ("tds", "TDS"),
        ("net", "Final Settlement"), ("reference", "Payment Ref"),
    ], date_format="%d-%m-%Y", amount_style="commas"),
    FileFormat("Marketplace 3", "orders", "marketplace3_orders.csv", [
        ("order_id", "Order Ref"), ("order_date", "Created At"), ("value", "Amount (₹)"), ("payment_mode", "Mode"),
        ("delivery_status", "Fulfilment Status"), ("delivered_date", "Delivered At"), ("returned_date", "Returned At"),
        ("pincode", "PIN"),
    ], date_format="%d-%b-%Y", amount_style="rupee", words={"payment_mode": PAYMENT_WORDS, "delivery_status": STATUS_WORDS_TITLE}),
    FileFormat("Marketplace 3", "settlement", "marketplace3_settlement.csv", [
        ("order_id", "Order Ref"), ("settlement_date", "Remittance Date"), ("gross", "Gross"), ("commission", "Commission"),
        ("fees", "Charges"), ("tcs", "TCS"), ("tds", "TDS"), ("net", "Net Amount"), ("reference", "Remittance Ref"),
    ], date_format="%d-%b-%Y", amount_style="rupee"),
    FileFormat("QuickCom 1", "orders", "quickcom1_orders.csv", [
        ("order_id", "order_id"), ("order_date", "order_date"), ("value", "order_value"), ("payment_mode", "payment"),
        ("delivery_status", "status"), ("delivered_date", "delivered_at"), ("returned_date", "returned_at"), ("pincode", "pincode"),
    ], words={"payment_mode": {"prepaid": "online", "cod": "cash"}, "delivery_status": {
        "delivered": "completed", "returned": "returned", "in_transit": "out_for_delivery"}}),
    FileFormat("QuickCom 1", "settlement", "quickcom1_payouts.csv", [
        ("settlement_date", "payout_date"), ("order_id", "order_id"), ("gross", "gross_sales"), ("commission", "platform_fee"),
        ("fees", "other_charges"), ("tcs", "tcs"), ("tds", "tds"), ("net", "payout_amount"), ("reference", "payout_ref"),
    ]),
    FileFormat("QuickCom 2", "orders", "quickcom2_orders.csv", [
        ("order_id", "Order No."), ("order_date", "Date"), ("value", "Bill Amount"), ("payment_mode", "Payment"),
        ("delivery_status", "Order Status"), ("delivered_date", "Delivery Date"), ("returned_date", "Return Date"),
        ("pincode", "Delivery Pincode"),
    ], date_format="%d/%m/%Y", amount_style="commas", words={"payment_mode": PAYMENT_WORDS, "delivery_status": STATUS_WORDS_TITLE}),
    FileFormat("QuickCom 2", "settlement", "quickcom2_payouts.csv", [
        ("settlement_date", "Payout Date"), ("order_id", "Order No."), ("gross", "Bill Amount"), ("commission", "Commission"),
        ("fees", "Platform Charges"), ("tcs", "TCS u/s 52"), ("tds", "TDS u/s 194-O"), ("net", "Net Payable"),
        ("reference", "Payout ID"),
    ], date_format="%d/%m/%Y", amount_style="commas"),
    FileFormat("Courier A", "cod_remittance", "courierA_cod_remittance.csv", [
        ("remittance_date", "Remittance Date"), ("awb", "AWB No"), ("order_id", "Order Ref"), ("amount", "COD Amount"),
        ("utr", "UTR No"),
    ], date_format="%d-%m-%Y"),
    FileFormat("Courier A", "freight_invoice", "courierA_freight_invoice.csv", [
        ("invoice_no", "Invoice No"), ("awb", "AWB No"), ("order_id", "Order Ref"), ("charged_weight", "Billed Weight (g)"),
        ("leg", "Shipment Type"), ("freight", "Freight Charges"), ("cod_fee", "COD Charges"), (None, "Total"),
    ], words={"leg": {"forward": "Forward", "return": "RTO"}}),
    FileFormat("Courier B", "cod_remittance", "courierB_cod_remittance.csv", [
        ("remittance_date", "remit_date"), ("awb", "awb"), ("amount", "collected_amount"), ("utr", "bank_ref"),
    ]),
    FileFormat("Courier B", "freight_invoice", "courierB_freight_invoice.csv", [
        ("invoice_no", "Invoice"), ("awb", "Waybill"), ("charged_weight", "Charged Wt (kg)"), ("leg", "Direction"),
        ("freight", "Freight"), ("cod_fee", "COD Fee"),
    ], weight_unit="kg", words={"leg": {"forward": "FWD", "return": "RET"}}),
    FileFormat("Warehouse", "warehouse_returns", "warehouse_return_scans.csv", [
        ("received_at", "Scan Time"), ("order_id", "Order No"), ("awb", "AWB"), (None, "Condition"),
    ], datetime_format="%d/%m/%Y %H:%M"),
]

# The same Marketplace 1 settlement report after the partner silently changed its layout:
# renamed and reordered columns, CSV instead of Excel. Used to demo AI column mapping.
FORMAT_CHANGED = FileFormat("Marketplace 1", "settlement", "marketplace1_settlement_NEW_FORMAT.csv", [
    ("order_id", "Order Reference"), ("settlement_date", "Payout Date"), ("gross", "Gross Sales"),
    ("commission", "Platform Commission"), ("fees", "Fees & Charges"), ("tcs", "TCS Withheld"), ("tds", "TDS Withheld"),
    ("net", "Amount Credited"), ("reference", "Reference No"),
], date_format="%Y-%m-%d")


def format_for(partner: str, file_kind: str) -> FileFormat:
    return next(fmt for fmt in FORMATS if fmt.partner == partner and fmt.file_kind == file_kind)


# ---------- rendering values ----------

def _indian_grouping(rupees_text: str) -> str:
    whole, _, fraction = rupees_text.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups) + "," + tail
    return f"{whole}.{fraction}"


def render_amount(paise: int, style: AmountStyle) -> str:
    sign = "-" if paise < 0 else ""
    text = f"{abs(paise) / 100:.2f}"
    if style == "plain":
        return sign + text
    grouped = _indian_grouping(text)
    return sign + ("₹" + grouped if style == "rupee" else grouped)


def _render(fmt: FileFormat, canonical: str | None, record: dict) -> object:
    if canonical is None:
        return _extra_column(fmt, record)
    key = {"value": "value_paise", "dead_weight": "dead_weight_g", "volumetric_weight": "volumetric_weight_g",
           "charged_weight": "charged_weight_g"}.get(canonical, canonical)
    value = record.get(key)
    if value is None:
        return ""
    if canonical in fmt.words:
        return fmt.words[canonical].get(value, value)
    if isinstance(value, datetime):
        return value if fmt.excel else value.strftime(fmt.datetime_format)
    if isinstance(value, date):
        return value if fmt.excel else value.strftime(fmt.date_format)
    if canonical in ("value", "gross", "commission", "fees", "tcs", "tds", "net", "amount", "freight", "cod_fee"):
        return value / 100 if fmt.excel else render_amount(value, fmt.amount_style)
    if canonical.endswith("weight"):
        return f"{value / 1000:.2f}" if fmt.weight_unit == "kg" else str(value)
    return value


def _extra_column(fmt: FileFormat, record: dict) -> str:
    """Columns PayTrace does not need (left unmapped), filled with plausible values."""
    if fmt.file_kind == "freight_invoice":
        return render_amount(record["freight"] + record["cod_fee"], fmt.amount_style)
    return "Good"


def _records_for(fmt: FileFormat, data: SampleData) -> list[dict]:
    if fmt.file_kind == "orders":
        rows = [order for order in data.orders if order["channel"] == fmt.partner]
        return sorted(rows, key=lambda row: (row["order_date"], row["order_id"]))
    if fmt.file_kind == "settlement":
        return sorted((line for line in data.settlements if line["partner"] == fmt.partner), key=lambda line: line["settlement_date"])
    if fmt.file_kind == "cod_remittance":
        return sorted((line for line in data.cod_remittances if line["courier"] == fmt.partner), key=lambda line: line["remittance_date"])
    if fmt.file_kind == "freight_invoice":
        return sorted((line for line in data.freight_lines if line["courier"] == fmt.partner), key=lambda line: line["invoice_no"])
    return sorted(data.receipts, key=lambda line: line["received_at"])


def write_file(fmt: FileFormat, records: list[dict], out_dir: Path) -> Path:
    path = out_dir / fmt.filename
    rows = [[_render(fmt, canonical, record) for canonical, _ in fmt.columns] for record in records]
    if fmt.excel:
        workbook = Workbook(write_only=True)
        sheet = workbook.create_sheet("Settlement")
        sheet.append(fmt.headers)
        for row in rows:
            sheet.append(row)
        workbook.save(path)
    else:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(fmt.headers)
            writer.writerows(rows)
    return path


def write_all(data: SampleData, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [write_file(fmt, _records_for(fmt, data), out_dir) for fmt in FORMATS]
    changed_dir = out_dir / "format_changed"
    changed_dir.mkdir(exist_ok=True)
    paths.append(write_file(FORMAT_CHANGED, _records_for(FORMAT_CHANGED, data), changed_dir))
    return paths
