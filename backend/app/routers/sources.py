"""Sources (one per partner report) and their versioned column mappings."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import current_user, require_finance_exec
from app.db import get_db
from app.models import ColumnMapping, Partner, Source, Upload, User
from app.schemas.uploads import ApproveRequest, MappingOut, PreviewOut, PreviewRequest, SourceOut
from app.services.mapping_ai import MappingSuggestion
from app.services.mappings import MappingInvalid, approve_mapping, build_preview, rollback_mapping
from app.services.parsing import FileReadError, headers_of, read_table
from app.services.upload_store import load_upload, read_suggestion

router = APIRouter(tags=["sources and mappings"], dependencies=[Depends(current_user)])


def mapping_out(mapping: ColumnMapping, author: str | None) -> MappingOut:
    suggestion = mapping.ai_suggested_json or {}
    return MappingOut(
        id=mapping.id,
        source_id=mapping.source_id,
        version=mapping.version,
        columns=mapping.mapping_json.get("columns", {}),
        is_active=mapping.is_active,
        approved_at=mapping.approved_at,
        created_at=mapping.created_at,
        created_by_name=author,
        engine=suggestion.get("engine"),
        notes=mapping.notes,
    )


def source_out(db: Session, source: Source, partner: Partner) -> SourceOut:
    active = db.scalar(select(ColumnMapping.version).where(ColumnMapping.source_id == source.id, ColumnMapping.is_active))
    versions = db.scalar(select(func.count()).select_from(ColumnMapping).where(ColumnMapping.source_id == source.id)) or 0
    last_upload = db.scalar(select(func.max(Upload.created_at)).where(Upload.source_id == source.id))
    return SourceOut(
        id=source.id,
        partner_id=partner.id,
        partner_name=partner.name,
        partner_kind=partner.kind,
        file_kind=source.file_kind,
        name=source.name,
        active_mapping_version=active,
        mapping_versions=versions,
        last_upload_at=last_upload,
    )


def get_source(db: Session, source_id: int) -> tuple[Source, Partner]:
    row = db.execute(select(Source, Partner).join(Partner, Partner.id == Source.partner_id).where(Source.id == source_id)).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Source not found.")
    return row[0], row[1]


@router.get("/sources", response_model=list[SourceOut])
def list_sources(db: Session = Depends(get_db)) -> list[SourceOut]:
    rows = db.execute(select(Source, Partner).join(Partner, Partner.id == Source.partner_id).order_by(Partner.id, Source.id)).all()
    return [source_out(db, source, partner) for source, partner in rows]


@router.get("/sources/{source_id}/mappings", response_model=list[MappingOut])
def list_mappings(source_id: int, db: Session = Depends(get_db)) -> list[MappingOut]:
    get_source(db, source_id)
    rows = db.execute(
        select(ColumnMapping, User.name)
        .outerjoin(User, User.id == ColumnMapping.created_by)
        .where(ColumnMapping.source_id == source_id)
        .order_by(ColumnMapping.version.desc())
    ).all()
    return [mapping_out(mapping, author) for mapping, author in rows]


def _stored_file_for(db: Session, source: Source, token: str):
    stored = load_upload(token)
    if stored is None or stored.source_id != source.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="That upload has expired. Upload the file again.")
    try:
        frame = read_table(stored.path, max_rows=200)
    except FileReadError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    return stored, frame


@router.post("/sources/{source_id}/mappings/preview", response_model=PreviewOut)
def preview_mapping(
    source_id: int, body: PreviewRequest, db: Session = Depends(get_db), user: User = Depends(require_finance_exec)
) -> dict:
    """Re-run the 20-row check after the user changes a column choice."""
    source, _ = get_source(db, source_id)
    _, frame = _stored_file_for(db, source, body.token)
    return build_preview(frame, source.file_kind, body.columns)


@router.post("/sources/{source_id}/mappings", response_model=MappingOut, status_code=status.HTTP_201_CREATED)
def approve(
    source_id: int, body: ApproveRequest, db: Session = Depends(get_db), user: User = Depends(require_finance_exec)
) -> MappingOut:
    """Approve the reviewed mapping: saved as the next version and made active (old versions kept)."""
    source, _ = get_source(db, source_id)
    stored, frame = _stored_file_for(db, source, body.token)
    suggestion_json = read_suggestion(stored.token)
    try:
        mapping = approve_mapping(
            db, source, user, body.columns, headers_of(frame),
            MappingSuggestion.model_validate(suggestion_json) if suggestion_json else None, body.notes,
        )
    except MappingInvalid as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    db.commit()
    return mapping_out(mapping, user.name)


@router.post("/sources/{source_id}/mappings/{mapping_id}/rollback", response_model=MappingOut)
def rollback(
    source_id: int, mapping_id: int, db: Session = Depends(get_db), user: User = Depends(require_finance_exec)
) -> MappingOut:
    source, _ = get_source(db, source_id)
    mapping = db.get(ColumnMapping, mapping_id)
    if mapping is None or mapping.source_id != source.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Mapping version not found.")
    rollback_mapping(db, source, mapping, user)
    db.commit()
    author = db.scalar(select(User.name).where(User.id == mapping.created_by)) if mapping.created_by else None
    return mapping_out(mapping, author)

