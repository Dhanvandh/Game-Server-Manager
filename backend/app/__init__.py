import os
from datetime import timedelta

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from app.auth.oauth import init_oauth
from app.extensions import cors, db, jwt, socketio
from app.sockets.console_socket import register_console_handlers


def create_app():
    app = Flask(__name__)
    # Correct scheme/host when OAuth callback is proxied through nginx (Google token exchange).
    app.wsgi_app = ProxyFix(
        app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1
    )
    app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "dev-change-me")
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://gsm:gsmsecret@localhost:5432/gsm",
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "jwt-dev-change-me")
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=1)
    app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(days=30)
    app.config["JWT_REFRESH_SECRET_KEY"] = os.environ.get(
        "JWT_REFRESH_SECRET_KEY", app.config["JWT_SECRET_KEY"] + "-refresh"
    )
    app.config["JWT_TOKEN_LOCATION"] = ["headers"]
    app.config["JWT_HEADER_NAME"] = "Authorization"
    app.config["JWT_HEADER_TYPE"] = "Bearer"

    app.config["JWT_REFRESH_COOKIE_NAME"] = "refresh_token_cookie"
    app.config["JWT_COOKIE_SECURE"] = os.environ.get("JWT_COOKIE_SECURE", "false").lower() == "true"
    app.config["JWT_COOKIE_CSRF_PROTECT"] = False
    app.config["JWT_REFRESH_CSRF"] = False
    app.config["JWT_REFRESH_COOKIE_PATH"] = "/api/auth/refresh"

    app.config["AUDIT_LOG_ENABLED"] = (
        os.environ.get("AUDIT_LOG_ENABLED", "true").strip().lower() not in ("0", "false", "no")
    )

    fe = os.environ.get("FRONTEND_URL", "http://localhost").rstrip("/")
    cors.init_app(
        app,
        resources={
            r"/api/*": {
                "origins": [fe, "http://127.0.0.1", "http://localhost:5173"],
                "supports_credentials": True,
                "allow_headers": ["Authorization", "Content-Type"],
                "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            },
            r"/socket.io/*": {"origins": [fe, "http://127.0.0.1", "http://localhost:5173"]},
        },
        supports_credentials=True,
    )
    db.init_app(app)
    app.config["JWT_BLOCKLIST_ENABLED"] = True
    jwt.init_app(app)
    from app.auth.rbac import register_jwt_blacklist_handlers

    register_jwt_blacklist_handlers(jwt)
    _socket_origins = list(
        dict.fromkeys(
            [
                fe,
                fe.replace("localhost", "127.0.0.1"),
                "http://localhost:5173",
                "http://127.0.0.1:5173",
            ]
        )
    )
    async_mode = os.environ.get("SOCKETIO_ASYNC_MODE", "eventlet")
    socketio.init_app(
        app,
        async_mode=async_mode,
        cors_allowed_origins=_socket_origins,
    )
    init_oauth(app)

    from app.routes.auth import bp as auth_bp
    from app.routes.servers import bp as servers_bp
    from app.routes.players import bp as players_bp
    from app.routes.config import bp as config_bp
    from app.routes.admin import bp as admin_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(servers_bp, url_prefix="/api/servers")
    app.register_blueprint(players_bp, url_prefix="/api/servers")
    app.register_blueprint(config_bp, url_prefix="/api/servers")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")

    register_console_handlers(socketio)

    with app.app_context():
        db.create_all()
        _migrate_legacy_roles_to_member()
        _seed_admin_if_configured()

    return app


def _seed_admin_if_configured():
    from app.models import User
    from app.auth.jwt_helpers import hash_password

    email = os.environ.get("ADMIN_EMAIL", "").strip()
    password = os.environ.get("ADMIN_PASSWORD", "").strip()
    if not email or not password:
        return
    if User.query.filter_by(email=email.lower()).first():
        return
    u = User(
        email=email.lower(),
        password_hash=hash_password(password),
        role="admin",
    )
    db.session.add(u)
    db.session.commit()


def _migrate_legacy_roles_to_member():
    from app.models import User

    changed = 0
    for legacy in ("viewer", "user"):
        changed += User.query.filter_by(role=legacy).update({"role": "member"})
    if changed:
        db.session.commit()
