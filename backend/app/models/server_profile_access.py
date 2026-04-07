from datetime import datetime

from app.extensions import db


class ServerProfileAccess(db.Model):
    __tablename__ = "server_profile_access"
    __table_args__ = (
        db.UniqueConstraint(
            "profile_id",
            "user_id",
            name="uq_server_profile_access_profile_user",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(
        db.Integer,
        db.ForeignKey("server_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
