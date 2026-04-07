from flask import Blueprint, jsonify, request

from app.auth.rbac import require_role
from app.extensions import db
from app.models import ApplicationAuditLog, User
from app.services.audit_log import actor_from_jwt, record_application_audit

bp = Blueprint("admin", __name__)


@bp.get("/users")
@require_role("admin")
def list_users():
    rows = User.query.order_by(User.id).all()
    return jsonify(
        [
            {
                "id": u.id,
                "email": u.email,
                "role": u.role,
                "has_password": bool(u.password_hash),
                "google_linked": bool(u.google_sub),
            }
            for u in rows
        ]
    )


@bp.patch("/users/<int:user_id>")
@require_role("admin")
def patch_user(user_id):
    u = User.query.get_or_404(user_id)
    data = request.get_json(silent=True) or {}
    old_role = u.role
    role_changed = False
    if "role" in data:
        role = data["role"]
        if role not in ("admin", "member"):
            return jsonify({"error": "invalid role"}), 400
        u.role = role
        role_changed = True
    db.session.commit()
    if role_changed:
        a_uid, a_email = actor_from_jwt()
        record_application_audit(
            "admin.user.role_change",
            actor_user_id=a_uid,
            actor_email=a_email,
            resource_type="user",
            resource_id=u.id,
            details={
                "target_email": u.email,
                "role_before": old_role,
                "role_after": u.role,
            },
        )
    return jsonify({"ok": True, "id": u.id, "role": u.role})


@bp.get("/audit-logs")
@require_role("admin")
def list_audit_logs():
    try:
        limit = int(request.args.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    prefix = (request.args.get("action_prefix") or "").strip()

    q = ApplicationAuditLog.query.order_by(ApplicationAuditLog.id.desc())
    if prefix:
        q = q.filter(ApplicationAuditLog.action.startswith(prefix))
    rows = q.offset(offset).limit(limit).all()
    return jsonify(
        [
            {
                "id": r.id,
                "created_at": r.created_at.isoformat() + "Z",
                "action": r.action,
                "actor_user_id": r.actor_user_id,
                "actor_email": r.actor_email,
                "resource_type": r.resource_type,
                "resource_id": r.resource_id,
                "ip_address": r.ip_address,
                "user_agent": r.user_agent,
                "details": r.details,
            }
            for r in rows
        ]
    )
