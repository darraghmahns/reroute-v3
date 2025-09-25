from urllib.parse import parse_qs, urlparse


def test_strava_authorize_url_generation(client):
    response = client.get("/v1/integrations/strava/connect")
    assert response.status_code == 200

    body = response.json()
    authorize_url = body["authorize_url"]

    parsed = urlparse(authorize_url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "www.strava.com"
    assert parsed.path == "/oauth/authorize"

    params = parse_qs(parsed.query)

    assert params["client_id"] == ["12345"]
    assert params["response_type"] == ["code"]
    assert params["scope"] == ["read,activity:read_all"]
    assert params["redirect_uri"] == ["https://example.com/strava/callback"]
    assert params["approval_prompt"] == ["auto"]
    assert "state" in params
    assert len(params["state"][0]) == 32

    state_cookie = response.cookies.get("strava_oauth_state")
    assert state_cookie
    assert len(state_cookie) == 32
