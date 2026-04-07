from datetime import datetime
from functools import wraps

from flask import jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.extensions import db
from app.models import BlacklistedToken, User


def register_jwt_blacklist_handlers(jwt_manager):
    """Wire access-token blacklist checks into Flask-JWT-Extended (after signature validation)."""

    @jwt_manager.token_in_blocklist_loader
    def _access_token_blacklisted(_jwt_header, jwt_payload):
        if jwt_payload.get("type") != "access":
            return False
        jti = jwt_payload.get("jti")
        if not jti:
            return False
        row = db.session.get(BlacklistedToken, jti)
        if row is None:
            return False
        if row.expires_at < datetime.utcnow():
            return False
        return True


def require_role(*roles):
    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            # Always use the role stored in the database so promotions/demotions apply
            # immediately without requiring a new access token.
            uid = int(get_jwt_identity())
            user = db.session.get(User, uid)
            if not user or user.role not in roles:
                return jsonify({"error": "Forbidden"}), 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator
