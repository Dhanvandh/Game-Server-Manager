from datetime import datetime

from app.extensions import db


class ApplicationAuditLog(db.Model):
    """Append-only application / security audit events (no passwords or tokens)."""

    __tablename__ = "application_audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    action = db.Column(db.String(128), nullable=False, index=True)
    actor_user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_email = db.Column(db.String(255), nullable=True)
    resource_type = db.Column(db.String(64), nullable=True, index=True)
    resource_id = db.Column(db.Integer, nullable=True, index=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(512), nullable=True)
    details = db.Column(db.JSON, nullable=True)
