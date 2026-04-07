from flask import Blueprint, abort, jsonify, request
from flask_jwt_extended import jwt_required

from app.auth.rbac import require_role
from app.extensions import db
from app.models import BanEntry
from app.routes.servers import _get_profile
from app.services.audit_log import actor_from_jwt, record_application_audit
from app.services.docker_service import get_container

bp = Blueprint("players", __name__)


@bp.get("/<int:profile_id>/players")
@jwt_required()
def list_players(profile_id):
    p = _get_profile(profile_id)
    container = get_container(p)
    names = []
    if container and container.status == "running":
        try:
            ec, out = container.exec_run("rcon-cli list", demux=True)
            if ec == 0 and out and isinstance(out, tuple):
                raw = (out[0] or b"").decode(errors="replace")
                if raw.strip():
                    names = [{"name": raw.strip(), "source": "rcon"}]
        except Exception:
            pass
    return jsonify(
        {
            "connected": names,
            "note": "Install rcon-cli in the image for live player names.",
        }
    )


@bp.get("/<int:profile_id>/bans")
@jwt_required()
def list_bans(profile_id):
    _get_profile(profile_id)
    rows = BanEntry.query.filter_by(profile_id=profile_id).order_by(BanEntry.created_at.desc()).all()
    return jsonify(
        [
            {
                "id": b.id,
                "player_name": b.player_name,
                "reason": b.reason,
                "created_at": b.created_at.isoformat() + "Z",
            }
            for b in rows
        ]
    )


@bp.post("/<int:profile_id>/bans")
@require_role("admin")
def add_ban(profile_id):
    _get_profile(profile_id)
    data = request.get_json(silent=True) or {}
    name = (data.get("player_name") or "").strip()
    if not name:
        return jsonify({"error": "player_name required"}), 400
    reason = (data.get("reason") or "").strip() or None
    b = BanEntry(profile_id=profile_id, player_name=name, reason=reason)
    db.session.add(b)
    db.session.commit()
    a_uid, a_email = actor_from_jwt()
    record_application_audit(
        "server.ban.create",
        actor_user_id=a_uid,
        actor_email=a_email,
        resource_type="ban",
        resource_id=b.id,
        details={"profile_id": profile_id, "player_name": name},
    )
    return jsonify({"id": b.id}), 201


@bp.delete("/<int:profile_id>/bans/<int:ban_id>")
@require_role("admin")
def delete_ban(profile_id, ban_id):
    _get_profile(profile_id)
    b = BanEntry.query.filter_by(id=ban_id, profile_id=profile_id).first()
    if not b:
        abort(404)
    pname = b.player_name
    db.session.delete(b)
    db.session.commit()
    a_uid, a_email = actor_from_jwt()
    record_application_audit(
        "server.ban.delete",
        actor_user_id=a_uid,
        actor_email=a_email,
        resource_type="ban",
        resource_id=ban_id,
        details={"profile_id": profile_id, "player_name": pname},
    )
    return jsonify({"ok": True})
