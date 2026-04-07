import os
from datetime import datetime
from urllib.parse import quote

from flask import Blueprint, current_app, jsonify, redirect, request
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_jwt_identity,
    jwt_required,
    set_refresh_cookies,
    unset_jwt_cookies,
)
from sqlalchemy import or_

from app.auth.jwt_helpers import (
    access_token_additional_claims,
    hash_password,
    prune_expired_blacklisted_tokens,
    verify_password,
)
from app.auth.oauth import google_credentials_present, oauth
from app.extensions import db
from app.models import BlacklistedToken, User
from app.services.audit_log import record_application_audit

bp = Blueprint("auth", __name__)


@bp.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"error": "email and password required"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "email already registered"}), 409
    u = User(email=email, password_hash=hash_password(password), role="member")
    db.session.add(u)
    db.session.commit()
    record_application_audit(
        "auth.register",
        actor_user_id=u.id,
        actor_email=u.email,
        resource_type="user",
        resource_id=u.id,
    )
    return jsonify({"ok": True, "id": u.id}), 201


def _tokens_response(user: User):
    access = create_access_token(
        identity=str(user.id),
        additional_claims=access_token_additional_claims(user.role),
    )
    refresh = create_refresh_token(identity=str(user.id))
    body = {
        "access_token": access,
        "user": {"id": user.id, "email": user.email, "role": user.role},
    }
    resp = jsonify(body)
    set_refresh_cookies(resp, refresh)
    return resp


@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    user = User.query.filter_by(email=email).first()
    if not user or not verify_password(password, user.password_hash):
        record_application_audit(
            "auth.login.failure",
            actor_email=email or None,
            details={"reason": "invalid_credentials"},
        )
        return jsonify({"error": "Invalid credentials"}), 401
    record_application_audit(
        "auth.login.success",
        actor_user_id=user.id,
        actor_email=user.email,
        resource_type="user",
        resource_id=user.id,
    )
    return _tokens_response(user)


@bp.post("/refresh")
@jwt_required(refresh=True, locations=["cookies"])
def refresh():
    uid = get_jwt_identity()
    user = User.query.get(int(uid))
    if not user:
        return jsonify({"error": "User not found"}), 401
    access = create_access_token(
        identity=str(user.id),
        additional_claims=access_token_additional_claims(user.role),
    )
    return jsonify({"access_token": access})


@bp.post("/logout")
def logout():
    prune_expired_blacklisted_tokens(commit=False)
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        raw = auth[7:].strip()
        if raw:
            try:
                decoded = decode_token(raw)
                jti = decoded.get("jti")
                exp = decoded.get("exp")
                if jti and exp is not None:
                    expires_at = datetime.utcfromtimestamp(int(exp))
                    if db.session.get(BlacklistedToken, jti) is None:
                        db.session.add(
                            BlacklistedToken(jti=str(jti)[:64], expires_at=expires_at)
                        )
            except Exception:
                pass
    db.session.commit()
    resp = jsonify({"ok": True})
    unset_jwt_cookies(resp)
    return resp


@bp.get("/me")
@jwt_required()
def me():
    uid = int(get_jwt_identity())
    user = db.session.get(User, uid)
    if not user:
        return jsonify({"error": "Not found"}), 404
    return jsonify(
        {
            "id": user.id,
            "email": user.email,
            "role": user.role,
        }
    )


@bp.get("/google/enabled")
def google_oauth_enabled():
    has_id, has_secret = google_credentials_present()
    enabled = bool(current_app.config.get("GOOGLE_OAUTH_ENABLED"))
    hint = None
    if not has_id:
        hint = "GOOGLE_CLIENT_ID is missing or empty in the backend container (.env + docker compose)."
    elif not has_secret:
        hint = "GOOGLE_CLIENT_SECRET is missing or empty in the backend container."
    elif not enabled:
        hint = "Credentials are set but OAuth init failed; check backend logs (registration error)."
    return jsonify({"enabled": enabled, "hint": hint})


@bp.get("/google")
def google_start():
    if not current_app.config.get("GOOGLE_OAUTH_ENABLED"):
        return jsonify({"error": "Google OAuth not configured"}), 400
    redirect_uri = os.environ.get("OAUTH_REDIRECT_URI", "").strip()
    if not redirect_uri:
        return jsonify({"error": "OAUTH_REDIRECT_URI not set"}), 400
    return oauth.google.authorize_redirect(redirect_uri)


@bp.get("/google/callback")
def google_callback():
    if not current_app.config.get("GOOGLE_OAUTH_ENABLED"):
        return jsonify({"error": "Google OAuth not configured"}), 400
    if request.args.get("error"):
        current_app.logger.warning(
            "Google OAuth callback returned error=%s description=%s",
            request.args.get("error"),
            request.args.get("error_description"),
        )
        return redirect(_frontend_url("/login?error=oauth"))
    try:
        # Do not pass redirect_uri here — Authlib merges it from the authorize step;
        # passing it again causes: "multiple values for keyword argument 'redirect_uri'".
        token = oauth.google.authorize_access_token()
    except Exception as e:
        current_app.logger.exception("Google OAuth token exchange failed: %s", e)
        return redirect(_frontend_url("/login?error=oauth"))
    userinfo = token.get("userinfo")
    if not userinfo:
        resp = oauth.google.get("https://openidconnect.googleapis.com/v1/userinfo")
        userinfo = resp.json()
    email = (userinfo.get("email") or "").strip().lower()
    sub = userinfo.get("sub")
    if not email or not sub:
        return redirect(_frontend_url("/login?error=oauth"))
    user = User.query.filter(or_(User.google_sub == sub, User.email == email)).first()
    account_created = False
    if not user:
        user = User(email=email, google_sub=sub, role="member", password_hash=None)
        db.session.add(user)
        db.session.commit()
        account_created = True
    elif not user.google_sub:
        user.google_sub = sub
        db.session.commit()
    record_application_audit(
        "auth.oauth.google.login",
        actor_user_id=user.id,
        actor_email=user.email,
        resource_type="user",
        resource_id=user.id,
        details={"account_created": account_created},
    )
    access = create_access_token(
        identity=str(user.id),
        additional_claims=access_token_additional_claims(user.role),
    )
    refresh = create_refresh_token(identity=str(user.id))
    fe = _frontend_url("/oauth-callback")
    target = f"{fe}?access_token={quote(access)}"
    r = redirect(target)
    set_refresh_cookies(r, refresh)
    return r


def _frontend_url(path: str) -> str:
    base = os.environ.get("FRONTEND_URL", "http://localhost").rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return base + path
