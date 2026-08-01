from app.web_api.routes import register_web_routes
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


def _client():
    app = FastAPI()

    class Bridge:
        danmu_app = type("App", (), {"config": object()})()

    def check_token(authorization=None):
        if authorization != "Bearer test-token":
            raise HTTPException(status_code=401, detail="unauthorized")

    register_web_routes(app, Bridge(), check_token)
    return TestClient(app)


def test_resolve_requires_auth():
    response = _client().post("/api/model-api/resolve", json={"endpoint": "https://openrouter.ai/api/v1", "model_id": "openai/gpt-4o"})
    assert response.status_code == 401


def test_openrouter_exact_host_and_catalog_model():
    response = _client().post(
        "/api/model-api/resolve",
        headers={"Authorization": "Bearer test-token"},
        json={"endpoint": "https://openrouter.ai/api/v1", "model_id": "google/gemini-3.1-flash-lite"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"]["id"] == "openrouter"
    assert payload["provider_id"] == payload["provider"]["id"]
    assert payload["api_family"] == "openai_chat_completions"
    assert payload["endpoint_profile"]["api_family"] == "openai_chat_completions"
    assert payload["model"]["id"] == "google/gemini-3.1-flash-lite"


def test_unknown_model_has_null_capabilities_and_stable_unknown_signal():
    response = _client().post(
        "/api/model-api/resolve",
        headers={"Authorization": "Bearer test-token"},
        json={"endpoint": "https://api.openai.com/v1", "model_id": "not-in-catalog"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["model"] is None
    assert payload["capabilities"]["vision"] is None
    assert payload["capabilities"]["image_input"] is None
    assert "unknown_model" in payload["warnings"]


def test_hunyuan_exposes_lifecycle_and_migration():
    response = _client().post(
        "/api/model-api/resolve",
        headers={"Authorization": "Bearer test-token"},
        json={"endpoint": "https://api.hunyuan.cloud.tencent.com/v1", "provider_id": "hunyuan"},
    )
    assert response.status_code == 200
    provider = response.json()["provider"]
    assert provider["lifecycle_status"] == "migrating"
    assert provider["migration"]["official_url"]


def test_resolve_does_not_echo_api_key_and_rejects_invalid_endpoint():
    client = _client()
    response = client.post(
        "/api/model-api/resolve",
        headers={"Authorization": "Bearer test-token"},
        json={"endpoint": "not-a-url", "api_key": "secret-value"},
    )
    assert response.status_code == 400
    assert "secret-value" not in response.text
