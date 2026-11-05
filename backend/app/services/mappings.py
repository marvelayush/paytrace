"""Column mappings: preview on 20 rows, approve as a new version, roll back to an earlier one.

The brief's rule for when AI is wrong: mappings are previewed on 20 rows, approved before saving,
and versioned for rollback. Nothing here runs without an explicit user action, and every approval
or rollback is written to the audit log.
"""

from datetime import date, datetime, timezone

import polars as pl
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import ColumnMapping, Source, User
from app.services.audit import record_audit
from app.services.canonical import CANONICAL_FIELDS, ONE_OF_REQUIRED
from app.services.fingerprint import header_fingerprint
from app.services.mapping_ai import LOW_CONFIDENCE, MappingSuggestion
from app.services.mapping_checks import plausibility_warnings
from app.services.parsing import ROW_NUMBER, apply_mapping
from app.services.pii import mask_address, mask_name, mask_phone

PREVIEW_ROWS = 20
PII_MASK = {"customer_name": mask_name, "customer_phone": mask_phone, "customer_address": mask_address}


class MappingInvalid(ValueError):
    pass


def _json_value(value: object) -> object:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def build_preview(
    frame: pl.DataFrame,
    file_kind: str,
    columns: dict[str, str | None],
    suggestion: MappingSuggestion | None = None,
) -> dict:
    """Apply a mapping to the first 20 rows and report, per field and per cell, what parses and what does not."""
    sample = frame.head(PREVIEW_ROWS)
    parsed = apply_mapping(sample, file_kind, columns)
    typed = parsed.all_rows if parsed.all_rows is not None else parsed.rows
    rejected_reasons = dict(parsed.rejected)
    warnings = plausibility_warnings(file_kind, typed, columns)

    fields = []
    for spec in CANONICAL_FIELDS[file_kind]:
        column = columns.get(spec.name)
        errors = parsed.cell_errors.get(spec.name, [])
        suggested = suggestion.fields.get(spec.name) if suggestion else None
        # Confidence only describes the AI's pick; once the user chose a different column it no longer applies.
        confidence = suggested.confidence if suggested and suggested.source_column == column else None
        reason = suggested.reason if suggested and suggested.source_column == column else None
        one_of = ONE_OF_REQUIRED.get(file_kind, ())
        missing_required = spec.required and not column
        warning = warnings.get(spec.name) if column else None
        needs_confirmation = bool(
            missing_required
            or errors
            or warning
            or (column and confidence is not None and confidence < LOW_CONFIDENCE)
        )
        fields.append({
            "name": spec.name,
            "label": spec.label,
            "type": spec.type,
            "required": spec.required,
            "one_of_group": list(one_of) if spec.name in one_of else None,
            "description": spec.description,
            "pii": spec.pii,
            "source_column": column,
            "confidence": confidence,
            "reason": reason,
            "error_count": len(errors),
            "warning": warning,
            "needs_confirmation": needs_confirmation,
        })

    rows = []
    for record, raw in zip(typed.to_dicts(), sample.to_dicts()):
        row_number = record[ROW_NUMBER]
        values, raw_values, errors = {}, {}, {}
        for spec in CANONICAL_FIELDS[file_kind]:
            column = columns.get(spec.name)
            value = record.get(spec.name)
            source_text = raw.get(column) if column else None
            if spec.name in PII_MASK:
                value = PII_MASK[spec.name](value)
                source_text = PII_MASK[spec.name](source_text)
            values[spec.name] = _json_value(value)
            raw_values[spec.name] = source_text
        for name, problems in parsed.cell_errors.items():
            for problem_row, message in problems:
                if problem_row == row_number:
                    errors[name] = message
        rows.append({
            "row_number": row_number,
            "values": values,
            "raw": raw_values,
            "errors": errors,
            "row_error": rejected_reasons.get(row_number) if not errors else None,
        })

    return {
        "fields": fields,
        "rows": rows,
        "rows_checked": sample.height,
        "rows_with_errors": len(parsed.rejected),
    }


def validate_columns(file_kind: str, columns: dict[str, str | None], headers: list[str]) -> dict[str, str | None]:
    """Only known fields, only real headers, every required field present."""
    known = {spec.name: spec for spec in CANONICAL_FIELDS[file_kind]}
    unknown = set(columns) - set(known)
    if unknown:
        raise MappingInvalid(f"Unknown fields: {', '.join(sorted(unknown))}.")
    cleaned = {name: (columns.get(name) or None) for name in known}
    for name, column in cleaned.items():
        if column is not None and column not in headers:
            raise MappingInvalid(f"'{column}' is not a column in this file.")
    missing = [spec.label for spec in known.values() if spec.required and not cleaned[spec.name]]
    if missing:
        raise MappingInvalid(f"Map the required fields first: {', '.join(missing)}.")
    one_of = ONE_OF_REQUIRED.get(file_kind)
    if one_of and not any(cleaned[name] for name in one_of):
        raise MappingInvalid(f"Map at least one of: {', '.join(known[name].label for name in one_of)}.")
    return cleaned


def mapping_snapshot(mapping: ColumnMapping) -> dict:
    return {"id": mapping.id, "version": mapping.version, "columns": mapping.mapping_json.get("columns", {}), "is_active": mapping.is_active}


def approve_mapping(
    db: Session,
    source: Source,
    user: User,
    columns: dict[str, str | None],
    headers: list[str],
    suggestion: MappingSuggestion | None,
    notes: str | None,
) -> ColumnMapping:
    """Save the mapping as the next version and make it the active one."""
    cleaned = validate_columns(source.file_kind, columns, headers)
    previous = db.scalar(select(ColumnMapping).where(ColumnMapping.source_id == source.id, ColumnMapping.is_active))
    next_version = (db.scalar(select(func.max(ColumnMapping.version)).where(ColumnMapping.source_id == source.id)) or 0) + 1

    db.execute(update(ColumnMapping).where(ColumnMapping.source_id == source.id).values(is_active=False))
    mapping = ColumnMapping(
        source_id=source.id,
        version=next_version,
        mapping_json={"columns": {name: column for name, column in cleaned.items() if column}},
        header_fingerprint=header_fingerprint(headers),
        created_by=user.id,
        approved_at=datetime.now(timezone.utc),
        is_active=True,
        ai_suggested_json=suggestion.model_dump() if suggestion else None,
        notes=(notes or "").strip()[:500] or None,
    )
    db.add(mapping)
    db.flush()
    record_audit(
        db, user, "mapping.approve", "column_mapping", mapping.id,
        before=mapping_snapshot(previous) if previous else None, after=mapping_snapshot(mapping),
    )
    return mapping


def rollback_mapping(db: Session, source: Source, mapping: ColumnMapping, user: User) -> ColumnMapping:
    """Make an earlier version active again. Nothing is deleted."""
    previous = db.scalar(select(ColumnMapping).where(ColumnMapping.source_id == source.id, ColumnMapping.is_active))
    db.execute(update(ColumnMapping).where(ColumnMapping.source_id == source.id).values(is_active=False))
    mapping.is_active = True
    db.flush()
    record_audit(
        db, user, "mapping.rollback", "column_mapping", mapping.id,
        before=mapping_snapshot(previous) if previous else None, after=mapping_snapshot(mapping),
    )
    return mapping
