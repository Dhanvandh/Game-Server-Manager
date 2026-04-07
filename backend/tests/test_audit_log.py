from app.models import ApplicationAuditLog


def test_register_creates_audit_row(client, app):
    r = client.post(
        "/api/auth/register",
        json={"email": "audit@test.com", "password": "secret123"},
    )
    assert r.status_code == 201
    with app.app_context():
        rows = ApplicationAuditLog.query.filter_by(action="auth.register").all()
        assert len(rows) == 1
        assert rows[0].actor_email == "audit@test.com"


def test_login_failure_audit(client, app):
    r = client.post(
        "/api/auth/login",
        json={"email": "nobody@test.com", "password": "wrong"},
    )
    assert r.status_code == 401
    with app.app_context():
        rows = ApplicationAuditLog.query.filter_by(action="auth.login.failure").all()
        assert len(rows) >= 1


def test_admin_lists_audit_logs(client, app):
    with app.app_context():
        from app.extensions import db
        from app.models import User
        from app.auth.jwt_helpers import hash_password

        adm = User(
            email="adm_audit@test.com",
            password_hash=hash_password("x"),
            role="admin",
        )
        db.session.add(adm)
        db.session.commit()

    r = client.post(
        "/api/auth/login",
        json={"email": "adm_audit@test.com", "password": "x"},
    )
    token = r.get_json()["access_token"]
    r2 = client.get(
        "/api/admin/audit-logs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 200
    assert isinstance(r2.get_json(), list)
