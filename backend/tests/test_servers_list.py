"""Regression: members must see servers they own or that are shared with them."""

import pytest


@pytest.fixture()
def member_token(client, app):
    with app.app_context():
        from app.extensions import db
        from app.models import User
        from app.auth.jwt_helpers import hash_password

        m = User(
            email="owner_member@test.com",
            password_hash=hash_password("secret123"),
            role="member",
        )
        db.session.add(m)
        db.session.flush()
        mid = m.id
        db.session.commit()

    r = client.post(
        "/api/auth/login",
        json={"email": "owner_member@test.com", "password": "secret123"},
    )
    assert r.status_code == 200
    return r.get_json()["access_token"], mid


def test_member_lists_owned_profile(client, app, member_token):
    token, mid = member_token
    with app.app_context():
        from app.extensions import db
        from app.models import ServerProfile

        p = ServerProfile(
            name="owned-srv",
            game_type="minecraft",
            docker_image="itzg/minecraft-server:latest",
            port=25565,
            volume_path="pending",
            env_vars={},
            owner_id=mid,
        )
        db.session.add(p)
        db.session.flush()
        if p.volume_path == "pending":
            p.volume_path = str(p.id)
        db.session.commit()
        pid = p.id

    r = client.get(
        "/api/servers",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    rows = r.get_json()
    ids = {x["id"] for x in rows}
    assert pid in ids
    owned = next(x for x in rows if x["id"] == pid)
    assert owned.get("can_manage") is True


def test_member_lists_shared_viewer_profile(client, app, member_token):
    token, mid = member_token
    with app.app_context():
        from app.extensions import db
        from app.models import ServerProfile, ServerProfileAccess, User
        from app.auth.jwt_helpers import hash_password

        other = User(
            email="other_owner@test.com",
            password_hash=hash_password("x"),
            role="member",
        )
        db.session.add(other)
        db.session.flush()
        oid = other.id
        p = ServerProfile(
            name="shared-srv",
            game_type="minecraft",
            docker_image="itzg/minecraft-server:latest",
            port=25566,
            volume_path="pending",
            env_vars={},
            owner_id=oid,
        )
        db.session.add(p)
        db.session.flush()
        if p.volume_path == "pending":
            p.volume_path = str(p.id)
        db.session.add(ServerProfileAccess(profile_id=p.id, user_id=mid))
        db.session.commit()
        pid = p.id

    r = client.get(
        "/api/servers",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    rows = r.get_json()
    ids = {x["id"] for x in rows}
    assert pid in ids
    shared = next(x for x in rows if x["id"] == pid)
    assert shared.get("can_manage") is False
