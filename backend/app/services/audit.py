"""Audit trail: who changed what, with before/after snapshots."""

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def record_audit(
    db: Session,
    user: User,
    action: str,
    entity: str,
    entity_id: Any,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    """Add an audit entry to the current transaction (committed together with the change itself)."""
    db.add(
        AuditLog(
            user_id=user.id,
            action=action,
            entity=entity,
            entity_id=str(entity_id),
            before_json=before,
            after_json=after,
        )
    )
