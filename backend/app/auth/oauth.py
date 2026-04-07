import logging
import os

from authlib.integrations.flask_client import OAuth

oauth = OAuth()
log = logging.getLogger(__name__)


def _env_trim(key: str) -> str:
    v = os.environ.get(key, "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1].strip()
    return v


def init_oauth(app):
    app.config["GOOGLE_OAUTH_ENABLED"] = False
    client_id = _env_trim("GOOGLE_CLIENT_ID")
    client_secret = _env_trim("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        return
    try:
        oauth.init_app(app)
        oauth.register(
            name="google",
            client_id=client_id,
            client_secret=client_secret,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
        app.config["GOOGLE_OAUTH_ENABLED"] = True
    except Exception as e:
        log.exception("Google OAuth registration failed: %s", e)
        app.config["GOOGLE_OAUTH_ENABLED"] = False


def google_credentials_present() -> tuple[bool, bool]:
    return bool(_env_trim("GOOGLE_CLIENT_ID")), bool(_env_trim("GOOGLE_CLIENT_SECRET"))
