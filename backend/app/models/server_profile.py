from datetime import datetime

from app.extensions import db


class ServerProfile(db.Model):
    __tablename__ = "server_profiles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    game_type = db.Column(db.String(64), nullable=False, default="minecraft")
    docker_image = db.Column(db.String(512), nullable=False)
    port = db.Column(db.Integer, nullable=False, default=25565)
    volume_path = db.Column(db.String(1024), nullable=False)
    env_vars = db.Column(db.JSON, nullable=False, default=dict)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    container_name = db.Column(db.String(256), nullable=True, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    bans = db.relationship("BanEntry", backref="profile", lazy="dynamic", cascade="all, delete-orphan")
    access_users = db.relationship(
        "ServerProfileAccess",
        backref="profile",
        lazy="dynamic",
        cascade="all, delete-orphan",
        foreign_keys="ServerProfileAccess.profile_id",
    )
