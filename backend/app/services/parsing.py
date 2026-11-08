"""Reading partner files (CSV or Excel) and turning mapped columns into typed values.

Everything is vectorised with Polars: no Python loop runs per row, so 1 lakh rows parse in well
under a second. A cell that cannot be parsed becomes null, and the row is rejected with a reason
that names the row, the column and the raw value. Rejected rows are kept and shown, never dropped silently.
"""

from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from app.services.canonical import CANONICAL_FIELDS, ONE_OF_REQUIRED, FieldSpec

SUPPORTED_EXTENSIONS = (".csv", ".xlsx")
ROW_NUMBER = "__row_number"

DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y", "%d %b %Y", "%d.%m.%Y", "%Y/%m/%d", "%d-%B-%Y", "%d %B %Y")
DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S",
    "%d-%m-%Y %H:%M", "%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S%.f",
)
ORDER_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9\-_/]{2,39}$"


class FileReadError(ValueError):
    """The file could not be read at all (wrong type, corrupt, empty)."""


# ---------- reading ----------

def read_table(path: Path, max_rows: int | None = None) -> pl.DataFrame:
    """Every column as text (Excel numbers and dates are converted to text), headers trimmed."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            frame = pl.read_csv(path, infer_schema=False, n_rows=max_rows, encoding="utf8-lossy", truncate_ragged_lines=True)
        elif suffix == ".xlsx":
            frame = pl.read_excel(path, engine="calamine")
            if max_rows is not None:
                frame = frame.head(max_rows)
            frame = frame.with_columns(pl.all().cast(pl.String))
        else:
            raise FileReadError("Only .csv and .xlsx files are supported.")
    except FileReadError:
        raise
    except Exception as error:  # Polars and the Excel reader raise many different types
        raise FileReadError(f"The file could not be read: {str(error).splitlines()[0][:200]}") from error

    frame = frame.rename({name: str(name).strip().lstrip("﻿") for name in frame.columns})
    if not frame.columns or all(name == "" for name in frame.columns):
        raise FileReadError("The file has no header row.")
    # Drop completely empty rows (common at the end of exported spreadsheets).
    frame = frame.filter(~pl.all_horizontal(pl.all().is_null() | (pl.all().str.strip_chars() == "")))
    return frame.with_row_index(ROW_NUMBER, offset=1)


def sample_rows(frame: pl.DataFrame, count: int) -> list[dict[str, str | None]]:
    return frame.drop(ROW_NUMBER).head(count).to_dicts()


def headers_of(frame: pl.DataFrame) -> list[str]:
    return [name for name in frame.columns if name != ROW_NUMBER]


# ---------- typed conversion ----------

def _clean_text(column: pl.Expr) -> pl.Expr:
    text = column.str.strip_chars()
    return pl.when(text == "").then(None).otherwise(text)


def money_expr(column: pl.Expr) -> pl.Expr:
    """'₹1,23,456.70', 'Rs. 99', '(12.00)', '-5' -> paise (Int64). Anything else -> null."""
    text = _clean_text(column)
    negative_brackets = text.str.starts_with("(") & text.str.ends_with(")")
    cleaned = (
        text.str.replace_all(r"(?i)rs\.?|inr|₹|,|\s|\(|\)", "")
        .str.replace(r"^\+", "")
    )
    rupees = cleaned.cast(pl.Float64, strict=False)
    paise = (rupees * 100).round(0).cast(pl.Int64, strict=False)
    return pl.when(negative_brackets).then(-paise).otherwise(paise)


def _best_format(values: pl.Series, formats: tuple[str, ...], as_datetime: bool) -> str | None:
    """The format that parses the most non-empty values in a sample of the column."""
    sample = values.drop_nulls().head(500)
    if sample.is_empty():
        return None
    best, best_count = None, 0
    for fmt in formats:
        if as_datetime:
            parsed = sample.str.to_datetime(fmt, strict=False)
        else:
            parsed = sample.str.to_date(fmt, strict=False)
        count = parsed.drop_nulls().len()
        if count > best_count:
            best, best_count = fmt, count
    return best


def date_series(values: pl.Series) -> pl.Series:
    """Parse dates in whichever supported format fits the column; datetimes keep only the date part."""
    text = values.str.strip_chars()
    text = text.str.replace(r"[T ]\d{1,2}:\d{2}(:\d{2})?(\.\d+)?$", "")  # '2026-10-13 00:00:00' from Excel
    fmt = _best_format(text, DATE_FORMATS, as_datetime=False)
    if fmt is None:
        return pl.Series(values.name, [None] * len(values), dtype=pl.Date)
    return text.str.to_date(fmt, strict=False)


def datetime_series(values: pl.Series) -> pl.Series:
    text = values.str.strip_chars()
    fmt = _best_format(text, DATETIME_FORMATS, as_datetime=True)
    if fmt is not None:
        return text.str.to_datetime(fmt, strict=False, time_zone="Asia/Kolkata")
    dates = date_series(values)  # date only: assume midnight IST
    return dates.cast(pl.Datetime).dt.replace_time_zone("Asia/Kolkata")


def weight_expr(column: pl.Expr, header: str) -> pl.Expr:
    """Grams (Int64). A header mentioning kg means the values are kilograms."""
    number = _clean_text(column).str.replace_all(r"(?i)kgs?|grams?|gms?|g|,|\s", "").cast(pl.Float64, strict=False)
    in_kg = "kg" in header.lower()
    grams = number * 1000 if in_kg else number
    return grams.round(0).cast(pl.Int64, strict=False)


def payment_mode_expr(column: pl.Expr) -> pl.Expr:
    text = _clean_text(column).str.to_lowercase()
    return (
        pl.when(text.str.contains(r"cod|cash|pay on delivery")).then(pl.lit("cod"))
        .when(text.str.contains(r"prepaid|online|paid|upi|card|netbanking|wallet")).then(pl.lit("prepaid"))
        .otherwise(None)
    )


def delivery_status_expr(column: pl.Expr) -> pl.Expr:
    text = _clean_text(column).str.to_lowercase()
    return (
        pl.when(text.str.contains(r"\brto\b|return to origin|returned to origin")).then(pl.lit("rto"))
        .when(text.str.contains(r"return")).then(pl.lit("returned"))
        .when(text.str.contains(r"cancel")).then(pl.lit("cancelled"))
        .when(text.str.contains(r"out[ _]for[ _]delivery|in[ _]transit")).then(pl.lit("in_transit"))
        .when(text.str.contains(r"deliver|complete")).then(pl.lit("delivered"))
        .when(text.str.contains(r"ship|dispatch|transit|pending|manifest")).then(pl.lit("in_transit"))
        .otherwise(None)
    )


def leg_expr(column: pl.Expr) -> pl.Expr:
    text = _clean_text(column).str.to_lowercase()
    return (
        pl.when(text.str.contains(r"rto|ret|reverse|rev")).then(pl.lit("return"))
        .when(text.str.contains(r"forward|fwd|fw|outbound|delivery")).then(pl.lit("forward"))
        .otherwise(None)
    )


def order_id_expr(column: pl.Expr) -> pl.Expr:
    text = _clean_text(column)
    return pl.when(text.str.contains(ORDER_ID_PATTERN)).then(text).otherwise(None)


# ---------- applying a mapping ----------

@dataclass
class ParseResult:
    """Typed rows that passed, plus a reason for every row that did not."""

    rows: pl.DataFrame  # canonical columns + ROW_NUMBER
    rejected: list[tuple[int, str]] = field(default_factory=list)
    # Valid lines with no order ID (settlement, COD): they go to the review queue, not the ledger (A43).
    unmatched: pl.DataFrame | None = None
    # field -> list of (row_number, message) for every cell that failed, for the preview
    cell_errors: dict[str, list[tuple[int, str]]] = field(default_factory=dict)
    all_rows: pl.DataFrame | None = None  # every row, typed, including rejected ones (preview only)

    @property
    def total(self) -> int:
        return self.rows.height + len(self.rejected) + (self.unmatched.height if self.unmatched is not None else 0)


TYPE_LABEL = {
    "money": "an amount",
    "date": "a date",
    "datetime": "a date and time",
    "weight": "a weight",
    "order_id": "an order ID",
    "payment_mode": "COD or prepaid",
    "delivery_status": "a known delivery status",
    "leg": "forward or return",
}


def _typed_column(frame: pl.DataFrame, spec: FieldSpec, header: str) -> pl.Series:
    raw = frame.get_column(header)
    if spec.type == "date":
        return date_series(raw).alias(spec.name)
    if spec.type == "datetime":
        return datetime_series(raw).alias(spec.name)
    expression = {
        "money": lambda c: money_expr(c),
        "weight": lambda c: weight_expr(c, header),
        "payment_mode": payment_mode_expr,
        "delivery_status": delivery_status_expr,
        "leg": leg_expr,
        "order_id": order_id_expr,
        "text": _clean_text,
    }[spec.type](pl.col(header))
    return frame.select(expression.alias(spec.name)).to_series()


# Lines that can be sent to the review queue when they carry no order ID, and the fields that identify them.
QUEUE_ID_FIELDS: dict[str, tuple[str, ...]] = {"settlement": ("order_id",), "cod_remittance": ("order_id", "awb")}
# More blank IDs than this in one file points at a wrong mapping, not at a few lines to review: reject them.
MAX_MISSING_ID_SHARE = 0.2


def _missing_id_rows(frame: pl.DataFrame, file_kind: str, columns: dict[str, str | None]) -> pl.Series | None:
    """Rows whose identifying cells are all blank, when they may go to the review queue; otherwise None."""
    id_fields = QUEUE_ID_FIELDS.get(file_kind)
    order_column = columns.get("order_id")
    if not id_fields or not order_column or order_column not in frame.columns or frame.height == 0:
        return None
    blank = pl.Series([True] * frame.height)
    for name in id_fields:
        header = columns.get(name)
        if header and header in frame.columns:
            raw = frame.get_column(header).str.strip_chars()
            blank = blank & (raw.is_null() | (raw == ""))
    if blank.sum() / frame.height > MAX_MISSING_ID_SHARE:
        return None
    return blank


def apply_mapping(frame: pl.DataFrame, file_kind: str, columns: dict[str, str | None]) -> ParseResult:
    """Convert the mapped source columns into canonical typed columns and validate every row.

    `columns` maps canonical field -> source header (or None when the file does not have it).
    """
    specs = CANONICAL_FIELDS[file_kind]
    row_numbers = frame.get_column(ROW_NUMBER)
    typed: dict[str, pl.Series] = {ROW_NUMBER: row_numbers}
    problems: list[pl.Series] = []  # per field: message or null, one entry per row
    cell_errors: dict[str, list[tuple[int, str]]] = {}
    missing_id = _missing_id_rows(frame, file_kind, columns)

    for spec in specs:
        header = columns.get(spec.name)
        if not header or header not in frame.columns:
            empty_dtype = {"money": pl.Int64, "weight": pl.Int64, "date": pl.Date}.get(spec.type, pl.String)
            if spec.type == "datetime":
                empty_dtype = pl.Datetime(time_zone="Asia/Kolkata")
            typed[spec.name] = pl.Series(spec.name, [None] * frame.height, dtype=empty_dtype)
            if spec.required:
                problems.append(pl.Series([f"{spec.label} is not mapped to any column"] * frame.height))
            continue

        raw = frame.get_column(header).str.strip_chars()
        value = _typed_column(frame, spec, header)
        typed[spec.name] = value

        is_blank = raw.is_null() | (raw == "")
        failed = value.is_null() & ~is_blank
        message = (
            pl.when(failed)
            .then(pl.lit(f"{spec.label}: '") + raw.str.slice(0, 40) + pl.lit(f"' is not {TYPE_LABEL.get(spec.type, 'valid')}"))
        )
        # A blank order ID is not an error when the line can wait in the review queue instead.
        if spec.required and not (missing_id is not None and spec.name == "order_id"):
            message = message.when(is_blank).then(pl.lit(f"{spec.label} is empty"))
        field_problem = pl.select(message.otherwise(None)).to_series()
        problems.append(field_problem)

        bad_rows = pl.DataFrame({"row": row_numbers, "message": field_problem}).filter(pl.col("message").is_not_null())
        if bad_rows.height:
            cell_errors[spec.name] = list(zip(bad_rows["row"].to_list(), bad_rows["message"].to_list()))

    result_frame = pl.DataFrame(typed)

    one_of = ONE_OF_REQUIRED.get(file_kind)
    if one_of:
        labels = " or ".join(next(spec.label for spec in specs if spec.name == name) for name in one_of)
        missing_all = pl.all_horizontal([result_frame.get_column(name).is_null() for name in one_of])
        if missing_id is not None:
            missing_all = missing_all & ~missing_id
        problems.append(pl.select(pl.when(missing_all).then(pl.lit(f"{labels} is required")).otherwise(None)).to_series())

    if problems:
        reasons = pl.DataFrame({f"p{index}": series for index, series in enumerate(problems)}).select(
            pl.concat_str(pl.all(), separator="; ", ignore_nulls=True).alias("reason")
        )["reason"]
        reasons = pl.select(pl.when(reasons == "").then(None).otherwise(reasons)).to_series()
    else:
        reasons = pl.Series([None] * frame.height, dtype=pl.String)

    bad = reasons.is_not_null()
    rejected_frame = pl.DataFrame({"row": row_numbers, "reason": reasons}).filter(bad)
    rejected = list(zip(rejected_frame["row"].to_list(), rejected_frame["reason"].to_list()))
    if missing_id is None:
        return ParseResult(rows=result_frame.filter(~bad), rejected=rejected, cell_errors=cell_errors, all_rows=result_frame)
    return ParseResult(
        rows=result_frame.filter(~bad & ~missing_id),
        rejected=rejected,
        unmatched=result_frame.filter(~bad & missing_id),
        cell_errors=cell_errors,
        all_rows=result_frame,
    )
