from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from tests.api.test_plans import db_override, override_current_user  # noqa: F401

from app.main import app
from app.repositories.strava import StravaCredentialRepository
from app.repositories.user import UserRepository


def test_strava_webhook_triggers_adjustment(client: TestClient, db_override) -> None:
    # Seed a plan for the default test user via the API
    generation_payload = {"goal": "Webhook Test", "duration_weeks": 4}
    response = client.post("/v1/plans/generate", json=generation_payload)
    assert response.status_code == 201

    SessionLocal = db_override
    with SessionLocal() as session:
        user_repo = UserRepository(session)
        user = user_repo.get_by_auth0_sub("auth0|user")
        assert user is not None

        credential_repo = StravaCredentialRepository(session)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        credential_repo.upsert_from_token_exchange(
            user_id=user.id,
            athlete_id=999001,
            access_token="access-token",
            refresh_token="refresh-token",
            token_type="Bearer",
            scope=["read"],
            expires_at=expires_at,
        )

    dispatcher = app.state.test_plan_dispatcher
    dispatcher.adjust_calls.clear()

    webhook_event = {
        "object_type": "activity",
        "object_id": 12345,
        "aspect_type": "create",
        "owner_id": 999001,
        "updates": {},
    }

    response = client.post("/v1/integrations/strava/webhook", json=webhook_event)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] in {"queued", "completed"}

    assert dispatcher.adjust_calls, "expected adjustment dispatched"
    dispatched_user_id, dispatched_plan_id, adjust_request = dispatcher.adjust_calls[0]
    assert adjust_request.reason.startswith("Strava create event")
