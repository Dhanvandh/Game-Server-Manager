import uuid
from datetime import datetime
from typing import Any

import bcrypt

from app.extensions import db
from app.models.blacklisted_token import BlacklistedToken


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    return bcrypt.checkpw(plain.encode("utf-8"), password_hash.encode("utf-8"))


def access_token_additional_claims(role: str) -> dict[str, Any]:
    """Claims merged into access JWTs: existing ``role`` plus a unique ``jti`` for revocation."""
    return {"role": role, "jti": str(uuid.uuid4())}


def prune_expired_blacklisted_tokens(*, commit: bool = True) -> int:
    """Delete blacklist rows past ``expires_at``. Returns number of rows deleted."""
    deleted = BlacklistedToken.query.filter(
        BlacklistedToken.expires_at < datetime.utcnow()
    ).delete()
    if commit:
        db.session.commit()
    return deleted
