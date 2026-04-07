from datetime import datetime

from app.extensions import db


class BanEntry(db.Model):
    __tablename__ = "ban_list"

    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(db.Integer, db.ForeignKey("server_profiles.id"), nullable=False, index=True)
    player_name = db.Column(db.String(128), nullable=False)
    reason = db.Column(db.String(512), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
