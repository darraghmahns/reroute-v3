import time

from jose import jwt


def _build_token(sub: str, audience: str, issuer: str, secret: str) -> str:
    claims = {
        "sub": sub,
        "aud": audience,
        "iss": issuer,
        "iat": int(time.time()),
        "exp": int(time.time()) + 600,
        "scope": "openid profile email",
        "email": "rider@example.com",
        "name": "Rider Example",
    }
    return jwt.encode(claims, secret, algorithm="HS256")


def test_users_me_requires_auth(client):
    response = client.get("/v1/users/me")
    assert response.status_code == 401


def test_users_me_returns_claims_when_token_valid(client, monkeypatch):
    audience = "https://api.reroute.training"
    domain = "dev-example.us.auth0.com"
    secret = "test-secret"

    token = _build_token(
        sub="auth0|user123",
        audience=audience,
        issuer=f"https://{domain}/",
        secret=secret,
    )

    response = client.get(
        "/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["auth0_sub"] == "auth0|user123"
    assert body["email"] == "rider@example.com"
    assert body["name"] == "Rider Example"


def test_users_me_rejects_token_with_wrong_audience(client):
    domain = "dev-example.us.auth0.com"
    secret = "test-secret"

    bad_audience_token = _build_token(
        sub="auth0|user456",
        audience="https://api.example.com",
        issuer=f"https://{domain}/",
        secret=secret,
    )

    response = client.get(
        "/v1/users/me",
        headers={"Authorization": f"Bearer {bad_audience_token}"},
    )

    assert response.status_code == 401
