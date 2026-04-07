from flask import request
from flask_jwt_extended import decode_token
from flask_jwt_extended.exceptions import JWTDecodeError
from flask_socketio import disconnect

from app.auth.identity import same_user_id
from app.extensions import db, socketio
from app.models import ServerProfile, ServerProfileAccess, User
from app.services.docker_service import get_container, stream_logs


def register_console_handlers(sio):
    @sio.on("connect")
    def on_connect(auth):
        token = None
        if isinstance(auth, dict):
            token = auth.get("token")
        if not token:
            token = request.args.get("token")
        if not token:
            return False
        try:
            decoded = decode_token(token)
        except JWTDecodeError:
            return False
        try:
            uid = int(decoded["sub"])
        except (ValueError, TypeError, KeyError):
            return False
        user = db.session.get(User, uid)
        if not user or user.role not in ("admin", "member"):
            return False
        request.environ["jwt_user_id"] = uid
        request.environ["jwt_role"] = user.role
        return True

    @sio.on("join_console")
    def on_join_console(data):
        uid = request.environ.get("jwt_user_id")
        role = request.environ.get("jwt_role")
        if uid is None:
            return disconnect()
        profile_id = (data or {}).get("profile_id")
        try:
            profile_id = int(profile_id)
        except (TypeError, ValueError):
            return
        profile = ServerProfile.query.get(profile_id)
        if not profile:
            return
        if role != "admin" and not same_user_id(profile.owner_id, uid):
            shared = ServerProfileAccess.query.filter_by(
                profile_id=profile.id,
                user_id=uid,
            ).first()
            if not shared:
                return disconnect()
        sid = request.sid
        container = get_container(profile)
        if not container or container.status != "running":
            sio.emit(
                "log_line",
                {
                    "line": "[gsm] Container not running. Press Start, wait until the dashboard shows Running (first image pull can take several minutes), then switch tabs or refresh to reconnect logs.\n",
                },
                to=sid,
            )
            return

        def log_worker():
            try:
                for chunk in stream_logs(container, tail=100):
                    sio.emit("log_line", {"line": chunk}, to=sid)
            except Exception:
                sio.emit("log_line", {"line": "[gsm] Log stream ended.\n"}, to=sid)

        sio.start_background_task(log_worker)
