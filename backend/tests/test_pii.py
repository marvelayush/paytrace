import polars as pl
import pytest

from app.services.pii import (
    mask_address,
    mask_name,
    mask_name_expr,
    mask_phone,
    mask_phone_expr,
    mask_sample_rows,
    pii_kind_of_column,
)


@pytest.mark.parametrize(("raw", "masked"), [("Meera Iyer", "M***r"), ("  Dev ", "D***v"), ("A", "A***"), ("", None), (None, None)])
def test_mask_name(raw, masked):
    assert mask_name(raw) == masked


@pytest.mark.parametrize(
    ("raw", "masked"),
    [("9845012345", "98******45"), ("+91 98450-12345", "91******45"), ("123", "******"), ("", None), (None, None)],
)
def test_mask_phone(raw, masked):
    assert mask_phone(raw) == masked


def test_mask_address_keeps_only_the_city():
    assert mask_address("14, Lake View Road, Bengaluru") == "Bengaluru"
    assert mask_address("   ") is None


def test_polars_expressions_match_the_scalar_rules():
    names = ["Meera Iyer", "A", "", None, " Rohan Das "]
    phones = ["9845012345", "+91 98450-12345", "12", None, ""]
    frame = pl.DataFrame({"name": names, "phone": phones})
    result = frame.select(mask_name_expr(pl.col("name")).alias("name"), mask_phone_expr(pl.col("phone")).alias("phone"))
    assert result["name"].to_list() == [mask_name(name) for name in names]
    assert result["phone"].to_list() == [mask_phone(phone) for phone in phones]


@pytest.mark.parametrize(
    ("header", "values", "kind"),
    [
        ("Customer Name", ["Meera Iyer"], "name"),
        ("Buyer", ["Rohan Das"], "name"),
        ("Customer Phone", ["9845012345"], "phone"),
        ("Contact", ["98450 12345"], "phone"),
        ("Shipping Address", ["1, MG Road, Pune"], "address"),
        ("Email", ["a@b.co"], "email"),
        ("AWB No", ["7100204118"], None),  # 10 digits but a tracking number, not a phone
        ("Courier Partner", ["Courier A"], None),
        ("Order Number", ["ORD-W-1"], None),
        ("Net Payout", ["854.80"], None),
    ],
)
def test_pii_column_detection(header, values, kind):
    assert pii_kind_of_column(header, values) == kind


def test_mask_sample_rows_masks_only_pii_columns():
    headers = ["Order Number", "Customer Name", "Customer Phone", "Shipping Address", "Order Total"]
    rows = [{"Order Number": "ORD-W-1", "Customer Name": "Meera Iyer", "Customer Phone": "9845012345",
             "Shipping Address": "14, Lake View Road, Bengaluru", "Order Total": "1499.00"}]
    assert mask_sample_rows(headers, rows) == [{"Order Number": "ORD-W-1", "Customer Name": "M***r", "Customer Phone": "98******45",
                                                 "Shipping Address": "Bengaluru", "Order Total": "1499.00"}]
