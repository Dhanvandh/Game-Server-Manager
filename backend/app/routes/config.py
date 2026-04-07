import os

from flask import Blueprint, abort, jsonify, request
from flask_jwt_extended import jwt_required

from app.auth.rbac import require_role
from app.routes.servers import _get_profile
from app.services.audit_log import actor_from_jwt, record_application_audit
from app.services.docker_service import resolve_volume_host_path

bp = Blueprint("config", __name__)


def _safe_join(root: str, rel: str) -> str | None:
    rel = (rel or "").lstrip("/").replace("\\", "/")
    if ".." in rel.split("/"):
        return None
    full = os.path.normpath(os.path.join(root, rel))
    root_norm = os.path.normpath(root)
    if not full.startswith(root_norm):
        return None
    return full


@bp.get("/<int:profile_id>/config")
@jwt_required()
def get_config(profile_id):
    p = _get_profile(profile_id)
    rel = request.args.get("path", "server.properties")
    root = resolve_volume_host_path(p)
    full = _safe_join(root, rel)
    if not full:
        return jsonify({"error": "invalid path"}), 400
    if not os.path.isfile(full):
        return jsonify({"path": rel, "content": ""})
    with open(full, encoding="utf-8", errors="replace") as f:
        return jsonify({"path": rel, "content": f.read()})


@bp.get("/<int:profile_id>/config/files")
@jwt_required()
def list_config_files(profile_id):
    """Relative paths under the server data directory (for picking which file to open)."""
    p = _get_profile(profile_id)
    root = os.path.abspath(resolve_volume_host_path(p))
    if not os.path.isdir(root):
        return jsonify({"files": [], "truncated": False})
    out: list[str] = []
    max_files = 800
    max_depth = 12
    root_depth = root.count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        depth = dirpath.count(os.sep) - root_depth
        if depth > max_depth:
            dirnames[:] = []
            continue
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            rel_dir = ""
        for fn in filenames:
            if fn.startswith("."):
                continue
            rel = f"{rel_dir}/{fn}".replace("\\", "/") if rel_dir else fn
            out.append(rel)
            if len(out) >= max_files:
                return jsonify({"files": sorted(out), "truncated": True})
    return jsonify({"files": sorted(out), "truncated": False})


@bp.put("/<int:profile_id>/config")
@require_role("admin")
def put_config(profile_id):
    p = _get_profile(profile_id)
    body = request.get_json(silent=True) or {}
    rel = body.get("path", "server.properties")
    content = body.get("content")
    if content is None:
        return jsonify({"error": "content required"}), 400
    root = resolve_volume_host_path(p)
    full = _safe_join(root, rel)
    if not full:
        return jsonify({"error": "invalid path"}), 400
    parent = os.path.dirname(full)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(str(content))
    a_uid, a_email = actor_from_jwt()
    record_application_audit(
        "server.config.write",
        actor_user_id=a_uid,
        actor_email=a_email,
        resource_type="server_profile",
        resource_id=profile_id,
        details={"path": rel},
    )
    return jsonify({"ok": True})
