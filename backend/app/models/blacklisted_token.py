from datetime import datetime

from app.extensions import db


class BlacklistedToken(db.Model):
    __tablename__ = "blacklisted_tokens"

    jti = db.Column(db.String(64), primary_key=True)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
