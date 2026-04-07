def test_register_and_me(client):
    r = client.post(
        "/api/auth/register",
        json={"email": "u@test.com", "password": "secret123"},
    )
    assert r.status_code == 201
    r = client.post(
        "/api/auth/login",
        json={"email": "u@test.com", "password": "secret123"},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert "access_token" in data
    token = data["access_token"]
    r2 = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 200
    body = r2.get_json()
    assert body["email"] == "u@test.com"
    assert body["role"] == "member"
