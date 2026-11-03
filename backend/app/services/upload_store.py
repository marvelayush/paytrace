"""Uploaded files waiting between inspection and processing.

A file is inspected first (headers, mapping suggestion, 20-row preview). Only after the user approves
a mapping is it processed. In between it waits on disk under an unguessable token, with a small JSON
note of who uploaded it for which source. Processed or abandoned files are deleted.
"""

import json
import secrets
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from fastapi import UploadFile

from app.config import get_settings
from app.services.parsing import SUPPORTED_EXTENSIONS

CHUNK_BYTES = 1024 * 1024
ABANDONED_AFTER_SECONDS = 24 * 60 * 60


class UploadRejected(ValueError):
    """The file is the wrong type or too large."""


@dataclass
class StoredUpload:
    token: str
    source_id: int
    filename: str
    extension: str
    uploaded_by: int
    created_at: float

    @property
    def path(self) -> Path:
        return _folder() / f"{self.token}{self.extension}"


def _folder() -> Path:
    folder = Path(get_settings().upload_dir)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _note_path(token: str) -> Path:
    return _folder() / f"{token}.json"


def _safe_filename(name: str | None) -> str:
    base = Path(name or "upload").name  # never trust directories in a client-supplied name
    return "".join(char for char in base if char.isprintable())[:200] or "upload"


async def save_upload(file: UploadFile, source_id: int, user_id: int) -> StoredUpload:
    filename = _safe_filename(file.filename)
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise UploadRejected("Upload a .csv or .xlsx file.")

    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    stored = StoredUpload(
        token=secrets.token_urlsafe(24),
        source_id=source_id,
        filename=filename,
        extension=extension,
        uploaded_by=user_id,
        created_at=time.time(),
    )
    size = 0
    with stored.path.open("wb") as handle:
        while chunk := await file.read(CHUNK_BYTES):
            size += len(chunk)
            if size > max_bytes:
                handle.close()
                stored.path.unlink(missing_ok=True)
                raise UploadRejected(f"The file is larger than {get_settings().max_upload_mb} MB.")
            handle.write(chunk)
    if size == 0:
        stored.path.unlink(missing_ok=True)
        raise UploadRejected("The file is empty.")

    _note_path(stored.token).write_text(json.dumps(asdict(stored)), encoding="utf-8")
    remove_abandoned()
    return stored


def load_upload(token: str) -> StoredUpload | None:
    if not token.replace("-", "").replace("_", "").isalnum():
        return None
    note = _note_path(token)
    if not note.exists():
        return None
    stored = StoredUpload(**json.loads(note.read_text(encoding="utf-8")))
    return stored if stored.path.exists() else None


def discard_upload(stored: StoredUpload) -> None:
    stored.path.unlink(missing_ok=True)
    _note_path(stored.token).unlink(missing_ok=True)
    _suggestion_path(stored.token).unlink(missing_ok=True)


def remove_abandoned() -> None:
    cutoff = time.time() - ABANDONED_AFTER_SECONDS
    for path in _folder().iterdir():
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)


def _suggestion_path(token: str) -> Path:
    return _folder() / f"{token}.suggestion.json"


def save_suggestion(token: str, suggestion: dict) -> None:
    """Keep what the suggester proposed, so the approved version records it (AI accuracy can be reviewed later)."""
    _suggestion_path(token).write_text(json.dumps(suggestion), encoding="utf-8")


def read_suggestion(token: str) -> dict | None:
    path = _suggestion_path(token)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
