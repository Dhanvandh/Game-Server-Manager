from datetime import datetime

from app.extensions import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=True)
    google_sub = db.Column(db.String(255), unique=True, nullable=True, index=True)
    role = db.Column(db.String(32), nullable=False, default="member")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    server_profiles = db.relationship(
        "ServerProfile", backref="owner", lazy="dynamic", foreign_keys="ServerProfile.owner_id"
    )
    shared_profiles = db.relationship(
        "ServerProfileAccess",
        backref="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
        foreign_keys="ServerProfileAccess.user_id",
    )
