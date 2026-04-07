import logging
from typing import Any

from flask import current_app, has_request_context, request

from app.extensions import db
from app.models.application_audit_log import ApplicationAuditLog
from app.models.user import User

log = logging.getLogger(__name__)


def _request_meta() -> tuple[str | None, str | None]:
    if not has_request_context():
        return None, None
    ip = request.remote_addr
    ua = (request.headers.get("User-Agent") or "")[:512] or None
    return ip, ua


def record_application_audit(
    action: str,
    *,
    actor_user_id: int | None = None,
    actor_email: str | None = None,
    resource_type: str | None = None,
    resource_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Persist one audit row in its own transaction. Never raises to callers."""
    try:
        if not current_app.config.get("AUDIT_LOG_ENABLED", True):
            return
    except RuntimeError:
        return
    ip, ua = _request_meta()
    row = ApplicationAuditLog(
        action=action[:128],
        actor_user_id=actor_user_id,
        actor_email=(actor_email[:255] if actor_email else None),
        resource_type=(resource_type[:64] if resource_type else None),
        resource_id=resource_id,
        ip_address=ip[:45] if ip else None,
        user_agent=ua,
        details=details,
    )
    try:
        db.session.add(row)
        db.session.commit()
    except Exception:
        db.session.rollback()
        log.warning("application audit log failed for action=%s", action, exc_info=True)


def actor_from_jwt() -> tuple[int | None, str | None]:
    """Best-effort actor for authenticated API routes."""
    try:
        from flask_jwt_extended import get_jwt_identity

        uid = int(get_jwt_identity())
    except Exception:
        return None, None
    user = db.session.get(User, uid)
    if not user:
        return uid, None
    return uid, user.email
