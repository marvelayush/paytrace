"""Uploading partner files: inspect (mapping + preview), process, history and rejected rows."""

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth import current_user, require_finance_exec
from app.config import get_settings
from app.db import get_db
from app.models import ColumnMapping, Partner, Source, UnmatchedLine, Upload, UploadRowError, User
from app.routers.recon import reconcile_now
from app.routers.review import get_match_ranker, rank_in_background
from app.routers.sources import get_source, mapping_out, source_out
from app.schemas.uploads import InspectOut, ProcessOut, ProcessRequest, RowErrorOut, SuggestionOut, UploadOut
from app.services.canonical import CANONICAL_FIELDS
from app.services.csv_safe import csv_text
from app.services.fingerprint import header_fingerprint
from app.services.mapping_ai import FieldSuggestion, MappingSuggester, MappingSuggestion, get_suggester
from app.services.mappings import build_preview
from app.services.match_ai import MatchRanker, RuleRanker
from app.services.parsing import FileReadError, headers_of, read_table, sample_rows
from app.services.review_queue import refresh_suggestions
from app.services.upload_processing import process_file
from app.services.upload_store import UploadRejected, discard_upload, load_upload, save_suggestion, save_upload

router = APIRouter(tags=["uploads"], dependencies=[Depends(current_user)])

INSPECT_ROWS = 200  # enough to detect date formats and fill the 20-row preview


def get_mapping_suggester() -> MappingSuggester:
    settings = get_settings()
    return get_suggester(settings.gemini_api_key, settings.gemini_model, settings.gemini_thinking_level or None)


def _saved_suggestion(mapping: ColumnMapping, file_kind: str) -> MappingSuggestion:
    columns = mapping.mapping_json.get("columns", {})
    return MappingSuggestion(
        engine="saved",
        fields={
            spec.name: FieldSuggestion(
                source_column=columns.get(spec.name),
                confidence=1.0 if columns.get(spec.name) else 0.0,
                reason=f"Saved mapping v{mapping.version}",
            )
            for spec in CANONICAL_FIELDS[file_kind]
        },
    )


@router.post("/uploads/inspect", response_model=InspectOut)
async def inspect_upload(
    source_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_finance_exec),
    suggester: MappingSuggester = Depends(get_mapping_suggester),
) -> InspectOut:
    """Store the file, recognise its layout and propose a mapping with a 20-row preview.

    Known layout (header fingerprint matches the active mapping) -> "reuse": it can be processed at once.
    New layout -> "review": the AI (or fuzzy fallback) proposes a mapping the user must check and approve.
    """
    source, partner = get_source(db, source_id)
    try:
        stored = await save_upload(file, source.id, user.id)
    except UploadRejected as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    try:
        frame = read_table(stored.path, max_rows=INSPECT_ROWS)
    except FileReadError as error:
        discard_upload(stored)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    if frame.height == 0:
        discard_upload(stored)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The file has headers but no rows.")

    headers = headers_of(frame)
    fingerprint = header_fingerprint(headers)
    active = db.scalar(select(ColumnMapping).where(ColumnMapping.source_id == source.id, ColumnMapping.is_active))
    matching_old = db.scalar(
        select(ColumnMapping)
        .where(ColumnMapping.source_id == source.id, ColumnMapping.header_fingerprint == fingerprint, ~ColumnMapping.is_active)
        .order_by(ColumnMapping.version.desc())
    )

    if active is not None and active.header_fingerprint == fingerprint:
        decision = "reuse"
        suggestion = _saved_suggestion(active, source.file_kind)
    elif matching_old is not None:
        decision = "review"  # an older version fits this layout: propose it, but the user confirms
        suggestion = _saved_suggestion(matching_old, source.file_kind)
    else:
        decision = "review"
        suggestion = suggester.suggest(source.file_kind, headers, sample_rows(frame, 20))
    save_suggestion(stored.token, suggestion.model_dump())

    author = None
    if active is not None and active.created_by:
        author = db.scalar(select(User.name).where(User.id == active.created_by))
    return InspectOut(
        token=stored.token,
        filename=stored.filename,
        source=source_out(db, source, partner),
        headers=headers,
        decision=decision,
        active_mapping=mapping_out(active, author) if active else None,
        matched_version=matching_old.version if matching_old is not None and decision == "review" else None,
        suggestion=SuggestionOut(engine=suggestion.engine, notice=suggestion.notice),
        preview=build_preview(frame, source.file_kind, suggestion.columns(), suggestion),
    )


def upload_out(db: Session, upload: Upload) -> UploadOut:
    source, partner = db.execute(
        select(Source, Partner).join(Partner, Partner.id == Source.partner_id).where(Source.id == upload.source_id)
    ).one()
    version = db.scalar(select(ColumnMapping.version).where(ColumnMapping.id == upload.mapping_id)) if upload.mapping_id else None
    uploader = db.scalar(select(User.name).where(User.id == upload.uploaded_by)) if upload.uploaded_by else None
    return UploadOut(
        id=upload.id,
        source_id=source.id,
        source_name=source.name,
        partner_name=partner.name,
        file_kind=source.file_kind,
        mapping_version=version,
        filename=upload.filename,
        row_count=upload.row_count,
        rows_ok=upload.rows_ok,
        rows_rejected=upload.rows_rejected,
        rows_duplicate=upload.rows_duplicate,
        rows_unmatched=upload.rows_unmatched,
        status=upload.status,
        error=upload.error,
        uploaded_by_name=uploader,
        created_at=upload.created_at,
        duration_ms=upload.duration_ms,
    )


@router.post("/uploads/{token}/process", response_model=ProcessOut)
def process_upload(
    token: str,
    body: ProcessRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(require_finance_exec),
    ranker: MatchRanker = Depends(get_match_ranker),
) -> ProcessOut:
    """Process the whole file with an approved mapping of its source."""
    stored = load_upload(token)
    if stored is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="That upload has expired. Upload the file again.")
    source, _ = get_source(db, stored.source_id)
    mapping = db.get(ColumnMapping, body.mapping_id)
    if mapping is None or mapping.source_id != source.id or mapping.approved_at is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Choose an approved mapping for this source.")
    try:
        upload = process_file(db, source, mapping, stored.path, stored.filename, user.id)
    finally:
        discard_upload(stored)
    # New data changes results: re-run reconciliation straight away so nothing on screen is stale.
    reconciliation = reconcile_now(db, user.id) if upload.status == "done" and upload.rows_ok else None
    if upload.status == "done" and upload.rows_unmatched:
        queue_new_lines(db, upload.id, ranker, background)
    return ProcessOut(upload=upload_out(db, upload), reconciliation=reconciliation)


def queue_new_lines(db: Session, upload_id: int, ranker: MatchRanker, background: BackgroundTasks) -> None:
    """Rule suggestions at once for this upload's lines without an order ID; AI ranking after the response."""
    line_ids = list(db.scalars(select(UnmatchedLine.id).where(UnmatchedLine.upload_id == upload_id, UnmatchedLine.status == "open")))
    refresh_suggestions(db, ranker=None, line_ids=line_ids)
    if not isinstance(ranker, RuleRanker):
        db.execute(update(UnmatchedLine).where(UnmatchedLine.id.in_(line_ids)).values(ai_note="pending"))
        background.add_task(rank_in_background, line_ids, ranker)
    else:
        db.execute(update(UnmatchedLine).where(UnmatchedLine.id.in_(line_ids)).values(ai_note=ranker.note))
    db.commit()


@router.get("/uploads", response_model=list[UploadOut])
def list_uploads(limit: int = 100, db: Session = Depends(get_db)) -> list[UploadOut]:
    limit = max(1, min(limit, 500))
    uploads = db.scalars(select(Upload).order_by(Upload.created_at.desc(), Upload.id.desc()).limit(limit))
    return [upload_out(db, upload) for upload in uploads]


def _get_upload(db: Session, upload_id: int) -> Upload:
    upload = db.get(Upload, upload_id)
    if upload is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Upload not found.")
    return upload


@router.get("/uploads/{upload_id}", response_model=UploadOut)
def get_upload(upload_id: int, db: Session = Depends(get_db)) -> UploadOut:
    return upload_out(db, _get_upload(db, upload_id))


@router.get("/uploads/{upload_id}/errors", response_model=list[RowErrorOut])
def upload_errors(upload_id: int, limit: int = 500, db: Session = Depends(get_db)) -> list[UploadRowError]:
    _get_upload(db, upload_id)
    limit = max(1, min(limit, 5000))
    return list(
        db.scalars(select(UploadRowError).where(UploadRowError.upload_id == upload_id).order_by(UploadRowError.row_number).limit(limit))
    )


@router.get("/uploads/{upload_id}/errors.csv")
def upload_errors_csv(upload_id: int, db: Session = Depends(get_db)) -> Response:
    upload = _get_upload(db, upload_id)
    rows = db.execute(
        select(UploadRowError.row_number, UploadRowError.reason).where(UploadRowError.upload_id == upload_id).order_by(UploadRowError.row_number)
    ).all()
    stem = upload.filename.rsplit(".", 1)[0]
    return Response(
        content=csv_text(["row_number", "reason"], rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{stem}-rejected-rows.csv"'},
    )
