"""Writing parsed partner rows into Postgres, fast and without duplicates.

Rows go in with COPY into a temporary table, then one INSERT ... SELECT moves them into the real table:
- orders are upserted by order_id (a later report may update the delivery status);
- partner lines are de-duplicated by a hash of their canonical values (md5, computed by Postgres), so
  uploading the same report twice never double-counts money (A26). Exact repeats inside one file are
  rejected as duplicates with a reason.
Personal data is masked before anything is written (DPDP Act 2023).
"""

from dataclasses import dataclass

import polars as pl
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Partner, Source
from app.services.parsing import ROW_NUMBER, ParseResult
from app.services.pii import mask_name_expr, mask_phone_expr

DUPLICATE_IN_FILE = "Duplicate of an earlier row in this file"
HASH_KEY = "hash_key"


@dataclass
class IngestResult:
    rows_ok: int
    rows_duplicate: int
    rejected: list[tuple[int, str]]


def _driver_connection(db: Session):
    """The psycopg connection behind the session, inside the session's current transaction."""
    return db.connection().connection.driver_connection


def copy_frame(db: Session, table: str, frame: pl.DataFrame) -> None:
    """Bulk-load a DataFrame with COPY (CSV). Column names must match the table's."""
    if frame.is_empty():
        return
    columns = ", ".join(frame.columns)
    payload = frame.write_csv(include_header=False, null_value="", datetime_format="%Y-%m-%d %H:%M:%S%z")
    with _driver_connection(db).cursor() as cursor:
        with cursor.copy(f"COPY {table} ({columns}) FROM STDIN WITH (FORMAT csv)") as copy:
            copy.write(payload)


def _hash_key(columns: list[str]) -> pl.Expr:
    """A text key of the canonical values; Postgres turns it into the md5 line hash."""
    return pl.concat_str([pl.col(name).cast(pl.String).fill_null("") for name in columns], separator="|").alias(HASH_KEY)


def _split_in_file_duplicates(frame: pl.DataFrame, key: pl.Expr) -> tuple[pl.DataFrame, list[tuple[int, str]]]:
    with_key = frame.with_columns(key.alias("__dedupe"))
    first = with_key.select(pl.col("__dedupe").is_first_distinct()).to_series()
    duplicates = with_key.filter(~first)
    rejected = [(row, DUPLICATE_IN_FILE) for row in duplicates[ROW_NUMBER].to_list()]
    return with_key.filter(first).drop("__dedupe"), rejected


def _stage_and_insert(db: Session, table: str, staged: pl.DataFrame, columns: list[str], conflict: str) -> int:
    """COPY into a temp table, then insert new lines only. Returns how many were inserted."""
    temp = f"tmp_{table}"
    # Same columns, no constraints: line_hash is only filled in by the INSERT below.
    db.execute(text(f"CREATE TEMP TABLE {temp} ON COMMIT DROP AS SELECT * FROM {table} WITH NO DATA"))
    db.execute(text(f"ALTER TABLE {temp} ADD COLUMN {HASH_KEY} text"))
    copy_frame(db, temp, staged.select([*columns, HASH_KEY]))
    target_columns = ", ".join([*columns, "line_hash"])
    source_columns = ", ".join([*columns, f"md5({HASH_KEY})"])
    inserted = db.execute(
        text(f"INSERT INTO {table} ({target_columns}) SELECT {source_columns} FROM {temp} ON CONFLICT {conflict} DO NOTHING")
    ).rowcount
    db.execute(text(f"DROP TABLE {temp}"))
    return inserted


def _courier_ids(db: Session) -> dict[str, int]:
    rows = db.execute(select(Partner.name, Partner.id).where(Partner.kind == "courier")).all()
    return {name.strip().lower(): partner_id for name, partner_id in rows}


# ---------- one function per file kind ----------

def _ingest_orders(db: Session, source: Source, rows: pl.DataFrame) -> IngestResult:
    rows, rejected = _split_in_file_duplicates(rows, pl.col("order_id"))
    courier_ids = _courier_ids(db)
    frame = rows.select(
        pl.col("order_id"),
        pl.lit(source.partner_id).alias("channel_partner_id"),
        pl.col("courier").str.strip_chars().str.to_lowercase().replace_strict(courier_ids, default=None, return_dtype=pl.Int64).alias("courier_partner_id"),
        pl.col("awb"),
        pl.col("order_date"),
        pl.col("delivered_date"),
        pl.col("returned_date"),
        pl.col("value").alias("value_paise"),
        pl.col("payment_mode"),
        pl.col("delivery_status"),
        pl.col("dead_weight").alias("dead_weight_g"),
        pl.col("volumetric_weight").alias("volumetric_weight_g"),
        mask_name_expr(pl.col("customer_name")).alias("customer_name_masked"),
        mask_phone_expr(pl.col("customer_phone")).alias("customer_phone_masked"),
        pl.col("pincode"),
        # customer_address is deliberately not stored: only city/pincode are needed (DPDP).
    )
    columns = frame.columns
    db.execute(text("CREATE TEMP TABLE tmp_orders ON COMMIT DROP AS SELECT * FROM orders WITH NO DATA"))
    copy_frame(db, "tmp_orders", frame)
    updates = ", ".join(f"{name} = EXCLUDED.{name}" for name in columns if name != "order_id")
    db.execute(text(f"INSERT INTO orders ({', '.join(columns)}) SELECT {', '.join(columns)} FROM tmp_orders ON CONFLICT (order_id) DO UPDATE SET {updates}"))
    db.execute(text("DROP TABLE tmp_orders"))
    return IngestResult(rows_ok=frame.height, rows_duplicate=0, rejected=rejected)


def _ingest_lines(
    db: Session,
    table: str,
    rows: pl.DataFrame,
    upload_id: int,
    partner_column: str | None,
    partner_id: int,
    selected: list[pl.Expr],
    hash_columns: list[str],
) -> IngestResult:
    key = _hash_key(hash_columns)
    rows, rejected = _split_in_file_duplicates(rows, key)
    extra = [pl.lit(partner_id).alias(partner_column)] if partner_column else []
    staged = rows.select(
        pl.lit(upload_id).alias("upload_id"),
        *extra,
        *selected,
        pl.col(ROW_NUMBER).cast(pl.Int32).alias("row_number"),
        key,
    )
    columns = [name for name in staged.columns if name != HASH_KEY]
    conflict = f"({partner_column}, line_hash)" if partner_column else "(line_hash)"
    inserted = _stage_and_insert(db, table, staged, columns, conflict)
    return IngestResult(rows_ok=inserted, rows_duplicate=staged.height - inserted, rejected=rejected)


def ingest(db: Session, upload_id: int, source: Source, parsed: ParseResult) -> IngestResult:
    """Write the parsed rows of one upload. Runs inside the caller's transaction."""
    rows = parsed.rows
    kind = source.file_kind
    if kind == "orders":
        result = _ingest_orders(db, source, rows)
    elif kind == "settlement":
        selected = [pl.col(name).alias(target) for name, target in (
            ("order_id", "order_id"), ("settlement_date", "settlement_date"), ("gross", "gross_paise"),
            ("commission", "commission_paise"), ("fees", "fees_paise"), ("tcs", "tcs_paise"), ("tds", "tds_paise"),
            ("net", "net_paise"), ("reference", "raw_ref"))]
        # Missing money columns count as zero (e.g. a gateway report has no commission or TCS).
        rows = rows.with_columns(pl.col(name).fill_null(0) for name in ("gross", "commission", "fees", "tcs", "tds"))
        result = _ingest_lines(db, "settlement_lines", rows, upload_id, "partner_id", source.partner_id, selected,
                               ["order_id", "settlement_date", "gross", "commission", "fees", "tcs", "tds", "net", "reference"])
    elif kind == "cod_remittance":
        selected = [pl.col("order_id"), pl.col("awb"), pl.col("remittance_date"), pl.col("amount").alias("amount_paise"), pl.col("utr")]
        result = _ingest_lines(db, "cod_remittances", rows, upload_id, "courier_partner_id", source.partner_id, selected,
                               ["order_id", "awb", "remittance_date", "amount", "utr"])
    elif kind == "freight_invoice":
        rows = rows.with_columns(pl.col("cod_fee").fill_null(0))
        selected = [pl.col("order_id"), pl.col("awb"), pl.col("charged_weight").alias("charged_weight_g"), pl.col("leg"),
                    pl.col("freight").alias("freight_paise"), pl.col("cod_fee").alias("cod_fee_paise"), pl.col("invoice_no")]
        result = _ingest_lines(db, "freight_lines", rows, upload_id, "courier_partner_id", source.partner_id, selected,
                               ["awb", "order_id", "invoice_no", "leg", "charged_weight", "freight", "cod_fee"])
    elif kind == "warehouse_returns":
        rows = rows.with_columns(pl.col("received_at").dt.convert_time_zone("UTC"))
        selected = [pl.col("order_id"), pl.col("received_at")]
        if "awb" in rows.columns:
            # Receipts that carry only an AWB are stored against the AWB's order at matching time; keep the AWB as ID.
            selected = [pl.coalesce(pl.col("order_id"), pl.col("awb")).alias("order_id"), pl.col("received_at")]
        result = _ingest_lines(db, "warehouse_receipts", rows, upload_id, None, source.partner_id, selected,
                               ["order_id", "awb", "received_at"])
    else:
        raise ValueError(f"Unknown file kind {kind}")
    return result
