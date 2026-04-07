def test_logout_blacklists_access_token(client, app):
    client.post(
        "/api/auth/register",
        json={"email": "bl@test.com", "password": "secret123"},
    )
    r = client.post(
        "/api/auth/login",
        json={"email": "bl@test.com", "password": "secret123"},
    )
    assert r.status_code == 200
    token = r.get_json()["access_token"]

    r_me = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_me.status_code == 200

    r_out = client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_out.status_code == 200

    r_blocked = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_blocked.status_code == 401
