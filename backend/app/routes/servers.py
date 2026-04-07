import logging
import threading

from flask import Blueprint, abort, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import or_, select

from app.auth.identity import same_user_id
from app.auth.rbac import require_role
from app.extensions import db
from app.models import ServerProfile, ServerProfileAccess, User
from app.services.docker_service import (
    container_status,
    create_game_container,
    remove_container,
    resolve_volume_host_path,
    stop_server,
    try_start_synchronously,
)
from app.services.audit_log import actor_from_jwt, record_application_audit
from app.services.docker_feedback import clear_docker_error, get_docker_error, set_docker_error
from app.services.stats_service import stats_for_profile

log = logging.getLogger(__name__)

bp = Blueprint("servers", __name__)


def _uid_role():
    uid = int(get_jwt_identity())
    user = db.session.get(User, uid)
    if not user:
        abort(401)
    return uid, user.role


def _can_view_profile(p: ServerProfile, uid: int, role: str) -> bool:
    if role == "admin" or same_user_id(p.owner_id, uid):
        return True
    return (
        ServerProfileAccess.query.filter_by(profile_id=p.id, user_id=uid).first()
        is not None
    )


def _require_owner_or_admin(p: ServerProfile):
    uid, role = _uid_role()
    if role != "admin" and not same_user_id(p.owner_id, uid):
        abort(403)


def _get_profile(profile_id: int) -> ServerProfile:
    uid, role = _uid_role()
    p = ServerProfile.query.get_or_404(profile_id)
    if not _can_view_profile(p, uid, role):
        abort(403)
    return p


@bp.get("")
@jwt_required()
def list_profiles():
    uid, role = _uid_role()
    q = ServerProfile.query.order_by(ServerProfile.id)
    if role != "admin":
        # Subquery avoids LEFT JOIN + DISTINCT edge cases on some DBs and matches
        # _can_view_profile: owned profiles OR shared via server_profile_access.
        shared_ids = select(ServerProfileAccess.profile_id).where(
            ServerProfileAccess.user_id == uid
        )
        q = q.filter(or_(ServerProfile.owner_id == uid, ServerProfile.id.in_(shared_ids)))
    rows = q.all()
    out = []
    for p in rows:
        st = container_status(p)
        if st.get("running"):
            clear_docker_error(p.id)
        out.append(
            {
                "id": p.id,
                "name": p.name,
                "game_type": p.game_type,
                "docker_image": p.docker_image,
                "port": p.port,
                "volume_path": p.volume_path,
                "env_vars": p.env_vars or {},
                "owner_id": p.owner_id,
                "viewer_ids": [r.user_id for r in p.access_users],
                "can_manage": role == "admin" or same_user_id(p.owner_id, uid),
                "container_name": p.container_name,
                "status": st,
                "last_docker_error": get_docker_error(p.id),
            }
        )
    return jsonify(out)


@bp.post("")
@require_role("admin")
def create_profile():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    owner_id = data.get("owner_id")
    if owner_id is None:
        owner_id = int(get_jwt_identity())
    try:
        owner_id = int(owner_id)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid owner_id"}), 400
    vol = (data.get("volume_path") or "").strip()
    p = ServerProfile(
        name=name,
        game_type=(data.get("game_type") or "minecraft").strip(),
        docker_image=(data.get("docker_image") or "itzg/minecraft-server:latest").strip(),
        port=int(data.get("port") or 25565),
        volume_path=vol or "pending",
        env_vars=data.get("env_vars") if isinstance(data.get("env_vars"), dict) else {},
        owner_id=owner_id,
        container_name=(data.get("container_name") or None),
    )
    db.session.add(p)
    db.session.flush()
    if not vol:
        p.volume_path = str(p.id)
    db.session.commit()
    a_uid, a_email = actor_from_jwt()
    record_application_audit(
        "server.profile.create",
        actor_user_id=a_uid,
        actor_email=a_email,
        resource_type="server_profile",
        resource_id=p.id,
        details={"name": p.name, "owner_id": owner_id},
    )
    return jsonify({"id": p.id}), 201


@bp.get("/<int:profile_id>")
@jwt_required()
def get_profile(profile_id):
    p = _get_profile(profile_id)
    uid, role = _uid_role()
    st = container_status(p)
    if st.get("running"):
        clear_docker_error(profile_id)
    return jsonify(
        {
            "id": p.id,
            "name": p.name,
            "game_type": p.game_type,
            "docker_image": p.docker_image,
            "port": p.port,
            "volume_path": p.volume_path,
            "env_vars": p.env_vars or {},
            "owner_id": p.owner_id,
            "viewer_ids": [r.user_id for r in p.access_users],
            "can_manage": role == "admin" or same_user_id(p.owner_id, uid),
            "container_name": p.container_name,
            "status": st,
            "last_docker_error": get_docker_error(p.id),
        }
    )


@bp.patch("/<int:profile_id>")
@require_role("admin")
def patch_profile(profile_id):
    p = ServerProfile.query.get_or_404(profile_id)
    data = request.get_json(silent=True) or {}
    for field in (
        "name",
        "game_type",
        "docker_image",
        "port",
        "volume_path",
        "container_name",
    ):
        if field in data:
            val = data[field]
            if field == "port":
                val = int(val)
            setattr(p, field, val)
    if "env_vars" in data and isinstance(data["env_vars"], dict):
        p.env_vars = data["env_vars"]
    if "owner_id" in data:
        p.owner_id = int(data["owner_id"])
    db.session.commit()
    a_uid, a_email = actor_from_jwt()
    record_application_audit(
        "server.profile.patch",
        actor_user_id=a_uid,
        actor_email=a_email,
        resource_type="server_profile",
        resource_id=p.id,
        details={"name": p.name, "updated_fields": list(data.keys())},
    )
    return jsonify({"ok": True})


@bp.get("/<int:profile_id>/access")
@jwt_required()
def get_profile_access(profile_id):
    p = _get_profile(profile_id)
    _require_owner_or_admin(p)
    users = (
        User.query.order_by(User.email)
        .with_entities(User.id, User.email, User.role)
        .all()
    )
    viewer_ids = [r.user_id for r in p.access_users]
    return jsonify(
        {
            "owner_id": p.owner_id,
            "viewer_ids": viewer_ids,
            "users": [
                {"id": u.id, "email": u.email, "role": u.role}
                for u in users
            ],
        }
    )


@bp.put("/<int:profile_id>/access")
@jwt_required()
def put_profile_access(profile_id):
    p = _get_profile(profile_id)
    _require_owner_or_admin(p)
    data = request.get_json(silent=True) or {}
    raw_ids = data.get("viewer_ids")
    if not isinstance(raw_ids, list):
        return jsonify({"error": "viewer_ids must be a list of user ids"}), 400
    old_viewers = sorted([r.user_id for r in p.access_users])
    try:
        viewer_ids = sorted({int(v) for v in raw_ids if int(v) != p.owner_id})
    except (TypeError, ValueError):
        return jsonify({"error": "viewer_ids must contain integer ids"}), 400

    allowed_ids = {
        u.id
        for u in User.query.filter(
            User.id.in_(viewer_ids), User.role.in_(("member", "admin"))
        ).all()
    }
    viewer_ids = [uid for uid in viewer_ids if uid in allowed_ids]

    ServerProfileAccess.query.filter_by(profile_id=p.id).delete()
    for uid in viewer_ids:
        db.session.add(ServerProfileAccess(profile_id=p.id, user_id=uid))
    db.session.commit()
    a_uid, a_email = actor_from_jwt()
    record_application_audit(
        "server.profile.access_update",
        actor_user_id=a_uid,
        actor_email=a_email,
        resource_type="server_profile",
        resource_id=p.id,
        details={
            "name": p.name,
            "viewer_ids_before": old_viewers,
            "viewer_ids_after": viewer_ids,
        },
    )
    return jsonify({"ok": True, "owner_id": p.owner_id, "viewer_ids": viewer_ids})


@bp.delete("/<int:profile_id>")
@require_role("admin")
def delete_profile(profile_id):
    p = ServerProfile.query.get_or_404(profile_id)
    pname = p.name
    db.session.delete(p)
    db.session.commit()
    a_uid, a_email = actor_from_jwt()
    record_application_audit(
        "server.profile.delete",
        actor_user_id=a_uid,
        actor_email=a_email,
        resource_type="server_profile",
        resource_id=profile_id,
        details={"name": pname},
    )
    return jsonify({"ok": True})


@bp.post("/<int:profile_id>/start")
@jwt_required()
def start(profile_id):
    p = _get_profile(profile_id)
    _require_owner_or_admin(p)
    clear_docker_error(profile_id)
    quick = try_start_synchronously(p)
    if quick is not None:
        try:
            db.session.commit()
            a_uid, a_email = actor_from_jwt()
            record_application_audit(
                "server.container.start",
                actor_user_id=a_uid,
                actor_email=a_email,
                resource_type="server_profile",
                resource_id=profile_id,
                details={"name": p.name, "sync": True, "result": quick},
            )
            return jsonify(quick), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    app = current_app._get_current_object()
    pid = profile_id

    def job():
        with app.app_context():
            try:
                prof = db.session.get(ServerProfile, pid)
                if not prof:
                    set_docker_error(pid, "Profile not found in database.")
                    return
                create_game_container(prof)
                db.session.commit()
                clear_docker_error(pid)
                log.info("Background start finished for profile %s", pid)
            except Exception as e:
                db.session.rollback()
                msg = f"{type(e).__name__}: {e}"
                set_docker_error(pid, msg)
                log.exception("Background start failed for profile %s: %s", pid, e)

    a_uid, a_email = actor_from_jwt()
    record_application_audit(
        "server.container.start",
        actor_user_id=a_uid,
        actor_email=a_email,
        resource_type="server_profile",
        resource_id=profile_id,
        details={"name": p.name, "sync": False, "status": "background"},
    )
    threading.Thread(target=job, daemon=True).start()
    return (
        jsonify(
            {
                "status": "starting",
                "message": "Start is running in the background. The first launch can take several minutes while Docker pulls the image. Wait until status shows Running, then refresh the console tab.",
                "profile_id": pid,
            }
        ),
        202,
    )


@bp.post("/<int:profile_id>/stop")
@jwt_required()
def stop(profile_id):
    p = _get_profile(profile_id)
    _require_owner_or_admin(p)
    try:
        info = stop_server(p)
        a_uid, a_email = actor_from_jwt()
        record_application_audit(
            "server.container.stop",
            actor_user_id=a_uid,
            actor_email=a_email,
            resource_type="server_profile",
            resource_id=profile_id,
            details={"name": p.name, "docker_status": info.get("status")},
        )
        return jsonify(info)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.post("/<int:profile_id>/container/remove")
@require_role("admin")
def remove_container_action(profile_id):
    """Remove the Docker container only (POST avoids proxies blocking DELETE)."""
    p = _get_profile(profile_id)
    clear_docker_error(profile_id)
    try:
        info = remove_container(p)
        if info.get("status") in ("removed", "not_found"):
            p.container_name = None
            db.session.commit()
        a_uid, a_email = actor_from_jwt()
        record_application_audit(
            "server.container.remove",
            actor_user_id=a_uid,
            actor_email=a_email,
            resource_type="server_profile",
            resource_id=profile_id,
            details={"name": p.name, "docker": info},
        )
        return jsonify(info)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.delete("/<int:profile_id>/container")
@require_role("admin")
def delete_container_legacy(profile_id):
    """Same as POST …/container/remove (kept for scripts)."""
    p = _get_profile(profile_id)
    try:
        info = remove_container(p)
        if info.get("status") in ("removed", "not_found"):
            p.container_name = None
            db.session.commit()
        a_uid, a_email = actor_from_jwt()
        record_application_audit(
            "server.container.remove",
            actor_user_id=a_uid,
            actor_email=a_email,
            resource_type="server_profile",
            resource_id=profile_id,
            details={"name": p.name, "docker": info, "legacy_route": True},
        )
        return jsonify(info)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.get("/<int:profile_id>/stats")
@jwt_required()
def stats(profile_id):
    p = _get_profile(profile_id)
    snap = stats_for_profile(p)
    if snap is None:
        return jsonify({"cpu_percent": 0, "mem_usage_mb": 0, "mem_limit_mb": 0})
    return jsonify(snap)
