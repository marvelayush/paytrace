from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MappingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    version: int
    columns: dict[str, str]
    is_active: bool
    approved_at: datetime | None
    created_at: datetime
    created_by_name: str | None
    engine: str | None  # which suggester proposed it (llm / fuzzy / saved) or None for seeded
    notes: str | None


class SourceOut(BaseModel):
    id: int
    partner_id: int
    partner_name: str
    partner_kind: str
    file_kind: str
    name: str
    active_mapping_version: int | None
    mapping_versions: int
    last_upload_at: datetime | None


class PreviewField(BaseModel):
    name: str
    label: str
    type: str
    required: bool
    one_of_group: list[str] | None
    description: str
    pii: bool
    source_column: str | None
    confidence: float | None
    reason: str | None
    error_count: int
    warning: str | None = None  # plausibility check, e.g. TCS and TDS look swapped
    needs_confirmation: bool


class PreviewRow(BaseModel):
    row_number: int
    values: dict[str, Any]
    raw: dict[str, str | None]
    errors: dict[str, str]
    row_error: str | None


class PreviewOut(BaseModel):
    fields: list[PreviewField]
    rows: list[PreviewRow]
    rows_checked: int
    rows_with_errors: int


class SuggestionOut(BaseModel):
    engine: Literal["llm", "fuzzy", "saved"]
    notice: str | None


class InspectOut(BaseModel):
    token: str
    filename: str
    source: SourceOut
    headers: list[str]
    decision: Literal["reuse", "review"]
    active_mapping: MappingOut | None
    matched_version: int | None  # an older saved version whose layout matches this file, if any
    suggestion: SuggestionOut
    preview: PreviewOut


class PreviewRequest(BaseModel):
    token: str = Field(min_length=8, max_length=64)
    columns: dict[str, str | None]


class ApproveRequest(PreviewRequest):
    notes: str | None = Field(default=None, max_length=500)


class ProcessRequest(BaseModel):
    mapping_id: int


class UploadOut(BaseModel):
    id: int
    source_id: int
    source_name: str
    partner_name: str
    file_kind: str
    mapping_version: int | None
    filename: str
    row_count: int
    rows_ok: int
    rows_rejected: int
    rows_duplicate: int
    status: str
    error: str | None
    uploaded_by_name: str | None
    created_at: datetime
    duration_ms: int | None


class ProcessOut(BaseModel):
    upload: UploadOut
    reconciliation: dict[str, Any] | None  # summary of the run triggered by this upload (Milestone 5)


class RowErrorOut(BaseModel):
    row_number: int
    reason: str
