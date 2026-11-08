"""Processing one partner file end to end: parse with an approved mapping, store, record the outcome."""

import time
from pathlib import Path

import polars as pl
from sqlalchemy.orm import Session

from app.models import ColumnMapping, Source, Upload
from app.services.ingest import copy_frame, ingest
from app.services.parsing import FileReadError, apply_mapping, read_table


def process_file(db: Session, source: Source, mapping: ColumnMapping, path: Path, filename: str, user_id: int | None) -> Upload:
    """Parse and store a whole file. Always returns the Upload record, marked done or failed."""
    started = time.perf_counter()
    upload = Upload(source_id=source.id, mapping_id=mapping.id, filename=filename, status="processing", uploaded_by=user_id)
    db.add(upload)
    db.commit()

    try:
        frame = read_table(path)
        parsed = apply_mapping(frame, source.file_kind, mapping.mapping_json.get("columns", {}))
        result = ingest(db, upload.id, source, parsed)
        rejected = sorted(parsed.rejected + result.rejected)
        if rejected:
            errors = pl.DataFrame(
                {"upload_id": [upload.id] * len(rejected), "row_number": [row for row, _ in rejected], "reason": [reason for _, reason in rejected]},
                schema={"upload_id": pl.Int64, "row_number": pl.Int32, "reason": pl.String},
            )
            copy_frame(db, "upload_row_errors", errors)
        upload.row_count = parsed.total
        upload.rows_ok = result.rows_ok
        upload.rows_duplicate = result.rows_duplicate
        upload.rows_unmatched = result.rows_unmatched
        upload.rows_rejected = len(rejected)
        upload.status = "done"
    except FileReadError as error:
        db.rollback()
        upload = db.merge(upload)
        upload.status = "failed"
        upload.error = str(error)
    except Exception:
        db.rollback()
        upload = db.merge(upload)
        upload.status = "failed"
        upload.error = "Processing failed unexpectedly. Nothing from this file was saved."
        upload.duration_ms = int((time.perf_counter() - started) * 1000)
        db.commit()
        raise
    upload.duration_ms = int((time.perf_counter() - started) * 1000)
    db.commit()
    return upload
