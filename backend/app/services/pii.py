"""Personal data masking (DPDP Act 2023).

Customer names, phones and addresses are masked at ingestion, so raw PII never reaches the database,
and masked again before any sample is sent to the AI. Scalar functions are the reference; the
Polars expressions apply the same rules to whole columns during ingestion.

Rules: name -> first letter + *** + last letter ("Meera Iyer" -> "M***r");
phone -> first 2 + ****** + last 2 digits ("9845012345" -> "98******45");
address -> city only (the last comma-separated part); pincodes are kept as they are.
"""

import re

import polars as pl

from app.services.fingerprint import normalise_header

PII_HEADER_WORDS = ("name", "phone", "mobile", "contact", "address", "email", "customer", "buyer", "recipient")
NOT_PII_HEADER_WORDS = ("courier", "partner", "file", "product", "item", "sku", "seller", "warehouse")
PHONE_PATTERN = re.compile(r"^\+?[\d\s-]{10,15}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def mask_name(name: str | None) -> str | None:
    if name is None:
        return None
    letters = name.strip()
    if not letters:
        return None
    if len(letters) == 1:
        return f"{letters}***"
    return f"{letters[0]}***{letters[-1]}"


def mask_phone(phone: str | None) -> str | None:
    if phone is None:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 4:
        return "******" if digits else None
    return f"{digits[:2]}******{digits[-2:]}"


def mask_address(address: str | None) -> str | None:
    """Keep only the city (last comma-separated part)."""
    if address is None or not address.strip():
        return None
    return address.split(",")[-1].strip() or None


def mask_email(email: str | None) -> str | None:
    if email is None or "@" not in email:
        return None
    user, _, domain = email.partition("@")
    return f"{user[:1]}***@{domain}"


# ---------- detecting PII columns in an unknown file ----------

def pii_kind_of_column(header: str, values: list[str | None]) -> str | None:
    """'name' | 'phone' | 'address' | 'email' if the column looks like personal data, else None."""
    name = normalise_header(header)
    sample = [value for value in values if value]
    if sample and all(EMAIL_PATTERN.match(value.strip()) for value in sample):
        return "email"
    if sample and all(PHONE_PATTERN.match(value.strip()) for value in sample) and not any(
        word in name for word in ("awb", "tracking", "waybill", "utr", "order", "invoice", "ref", "pin")
    ):
        return "phone"
    if any(word in name for word in NOT_PII_HEADER_WORDS):
        return None
    if any(word in name for word in ("phone", "mobile", "contact")):
        return "phone"
    if "email" in name:
        return "email"
    if "address" in name or name in ("street", "city line"):
        return "address"
    if "name" in name or any(word in name for word in ("customer", "buyer", "recipient")):
        return "name"
    return None


MASKERS = {"name": mask_name, "phone": mask_phone, "address": mask_address, "email": mask_email}


def mask_sample_rows(headers: list[str], rows: list[dict[str, str | None]]) -> list[dict[str, str | None]]:
    """Copy of `rows` with every PII-looking column masked. Used before showing or sending samples."""
    kinds = {header: pii_kind_of_column(header, [row.get(header) for row in rows]) for header in headers}
    masked = []
    for row in rows:
        masked.append({header: (MASKERS[kinds[header]](row.get(header)) if kinds[header] else row.get(header)) for header in headers})
    return masked


# ---------- the same rules as Polars expressions (ingestion) ----------

def mask_name_expr(column: pl.Expr) -> pl.Expr:
    text = column.str.strip_chars()
    return (
        pl.when(text.is_null() | (text.str.len_chars() == 0))
        .then(None)
        .when(text.str.len_chars() == 1)
        .then(text + "***")
        .otherwise(text.str.slice(0, 1) + "***" + text.str.slice(-1, 1))
    )


def mask_phone_expr(column: pl.Expr) -> pl.Expr:
    digits = column.str.replace_all(r"\D", "")
    return (
        pl.when(digits.is_null() | (digits.str.len_chars() == 0))
        .then(None)
        .when(digits.str.len_chars() < 4)
        .then(pl.lit("******"))
        .otherwise(digits.str.slice(0, 2) + "******" + digits.str.slice(-2, 2))
    )
