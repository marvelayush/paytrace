from datetime import date
from pathlib import Path

import polars as pl
import pytest

from app.sample_data.formats import FORMAT_CHANGED, FORMATS
from app.services.parsing import (
    ROW_NUMBER,
    FileReadError,
    apply_mapping,
    date_series,
    delivery_status_expr,
    leg_expr,
    money_expr,
    payment_mode_expr,
    read_table,
)

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data"


def _frame(**columns: list) -> pl.DataFrame:
    return pl.DataFrame(columns).with_row_index(ROW_NUMBER, offset=1)


@pytest.mark.parametrize(
    ("text", "paise"),
    [("1199.00", 119_900), ("1,199.00", 119_900), ("₹1,23,456.70", 12_345_670), ("Rs. 99", 9_900), ("INR 5", 500),
     ("(12.50)", -1_250), ("-47.96", -4_796), ("0.29", 29), ("  854.8 ", 85_480), ("abc", None), ("", None), (None, None)],
)
def test_money_parsing(text, paise):
    assert pl.select(money_expr(pl.lit(text, dtype=pl.String))).item() == paise


@pytest.mark.parametrize(
    "values",
    [["2026-10-13", "2026-10-01"], ["13/10/2026", "01/10/2026"], ["13-10-2026", "01-10-2026"], ["13-Oct-2026", "01-Oct-2026"],
     ["2026-10-13 00:00:00", "2026-10-01 00:00:00"]],
)
def test_date_formats_are_detected_per_column(values):
    assert date_series(pl.Series(values)).to_list() == [date(2026, 10, 13), date(2026, 10, 1)]


def test_unparseable_dates_become_null():
    assert date_series(pl.Series(["31/31/2026", "13/10/2026"])).to_list() == [None, date(2026, 10, 13)]


@pytest.mark.parametrize(
    ("text", "status"),
    [("Delivered", "delivered"), ("Shipped - Delivered", "delivered"), ("Shipped - Returned to Seller", "returned"),
     ("RTO", "rto"), ("out_for_delivery", "in_transit"), ("SHIPPED", "in_transit"), ("completed", "delivered"),
     ("Cancelled", "cancelled"), ("lost", None)],
)
def test_delivery_status_words(text, status):
    assert pl.select(delivery_status_expr(pl.lit(text))).item() == status


@pytest.mark.parametrize(("text", "mode"), [("COD", "cod"), ("cash", "cod"), ("Prepaid", "prepaid"), ("online", "prepaid"), ("??", None)])
def test_payment_mode_words(text, mode):
    assert pl.select(payment_mode_expr(pl.lit(text))).item() == mode


@pytest.mark.parametrize(("text", "leg"), [("Forward", "forward"), ("FWD", "forward"), ("RTO", "return"), ("RET", "return")])
def test_leg_words(text, leg):
    assert pl.select(leg_expr(pl.lit(text))).item() == leg


def test_rejected_rows_name_the_row_column_and_value():
    frame = _frame(**{"Order": ["ORD-1", "ORD-2", ""], "Date": ["13/10/2026", "99/99/2026", "13/10/2026"], "Net": ["10", "20", "x"]})
    result = apply_mapping(frame, "settlement", {"order_id": "Order", "settlement_date": "Date", "net": "Net"})

    assert result.rows.height == 1
    assert result.rejected == [
        (2, "Settlement date: '99/99/2026' is not a date"),
        (3, "Order ID is empty; Net paid: 'x' is not an amount"),
    ]


def test_unmapped_required_field_rejects_every_row():
    frame = _frame(Order=["ORD-1"], Net=["10"])
    result = apply_mapping(frame, "settlement", {"order_id": "Order", "net": "Net"})
    assert result.rows.height == 0
    assert "Settlement date is not mapped" in result.rejected[0][1]


def test_courier_line_needs_order_id_or_awb():
    frame = _frame(AWB=["", "X1"], Date=["2026-10-01", "2026-10-01"], Amount=["5", "5"])
    result = apply_mapping(frame, "cod_remittance", {"awb": "AWB", "remittance_date": "Date", "amount": "Amount"})
    assert [row for row, _ in result.rejected] == [1]
    assert "Order ID or AWB / tracking number is required" in result.rejected[0][1]


def test_weight_in_kg_header_is_converted_to_grams():
    frame = _frame(**{"Waybill": ["W1"], "Dir": ["FWD"], "Freight": ["71"], "Charged Wt (kg)": ["0.90"]})
    result = apply_mapping(frame, "freight_invoice", {"awb": "Waybill", "leg": "Dir", "freight": "Freight", "charged_weight": "Charged Wt (kg)"})
    assert result.rows["charged_weight"].to_list() == [900]


def test_unsupported_file_type_is_refused(tmp_path):
    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF")
    with pytest.raises(FileReadError):
        read_table(path)


@pytest.mark.parametrize("layout", [*FORMATS, FORMAT_CHANGED], ids=lambda layout: layout.filename)
def test_every_sample_file_parses_cleanly_with_its_mapping(layout):
    folder = SAMPLE_DIR / "format_changed" if layout is FORMAT_CHANGED else SAMPLE_DIR
    frame = read_table(folder / layout.filename)
    result = apply_mapping(frame, layout.file_kind, layout.mapping()["columns"])
    assert result.rejected == []
    # Lines without an order ID are not rejected: they wait in the review queue.
    unmatched = result.unmatched.height if result.unmatched is not None else 0
    assert result.rows.height + unmatched == frame.height > 0
    assert unmatched < 0.01 * frame.height


def test_brief_rows_parse_to_exact_values():
    marketplace = read_table(SAMPLE_DIR / "marketplace1_settlement.xlsx")
    layout = next(f for f in FORMATS if f.filename == "marketplace1_settlement.xlsx")
    rows = apply_mapping(marketplace, "settlement", layout.mapping()["columns"]).rows
    line = rows.filter(pl.col("order_id") == "ORD-M-88120").to_dicts()[0]
    assert (line["gross"], line["commission"], line["fees"], line["tcs"], line["tds"], line["net"]) == (119_900, 23_980, 9_720, 600, 120, 85_480)
    assert line["settlement_date"] == date(2026, 10, 13)

    orders = read_table(SAMPLE_DIR / "website_orders.csv")
    layout = next(f for f in FORMATS if f.filename == "website_orders.csv")
    rows = apply_mapping(orders, "orders", layout.mapping()["columns"]).rows
    order = rows.filter(pl.col("order_id") == "ORD-W-204377").to_dicts()[0]
    assert (order["value"], order["payment_mode"], order["delivery_status"], order["dead_weight"]) == (239_800, "prepaid", "returned", 480)
