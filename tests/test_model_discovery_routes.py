from dataclasses import dataclass

from app.web_api.model_discovery_routes import register_model_discovery_routes
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


@dataclass
class FakeModel:
    value: str

    def to_dict(self):
        return {"id": self.value, "supports_vision": None}


@dataclass
class FakeResult:
    models: tuple
    discovery_kind: str
    source: str
    source_url: str | None
    verified_at: str | None
    fetched_at: str | None
    status: str
    warnings: tuple = ()
    request_url: str | None = None


def make_client(monkeypatch, result):
    app = FastAPI()
    def check_token(token):
        if token != "Bearer ok":
            raise HTTPException(status_code=401, detail="Unauthorized")

    register_model_discovery_routes(app, check_token)
    monkeypatch.setattr("app.web_api.model_discovery_routes.discover_models", lambda *args, **kwargs: result)
    return TestClient(app)


def test_requires_auth(monkeypatch):
    client = make_client(monkeypatch, FakeResult((), "curated_fallback", "curated", None, None, None, "unknown"))
    response = client.post("/api/model-discovery", json={"provider_id": "openai"})
    assert response.status_code == 401


def test_account_discovery_serializes_without_api_key(monkeypatch):
    result = FakeResult(
        (FakeModel("account-model"),),
        "account_discovery",
        "account",
        "https://docs.example",
        "v",
        "f",
        "ok",
        request_url="https://api.example/models",
    )
    client = make_client(monkeypatch, result)
    response = client.post("/api/model-discovery", headers={"Authorization": "Bearer ok"}, json={"provider_id": "openai", "api_key": "SECRET"})
    assert response.status_code == 200
    assert response.json()["discovery_kind"] == "account_discovery"
    assert "SECRET" not in response.text


def test_fallback_preserves_unknown_capability(monkeypatch):
    client = make_client(
        monkeypatch,
        FakeResult(
            (FakeModel("fallback"),),
            "curated_fallback",
            "curated",
            None,
            None,
            "f",
            "fallback_request_error",
        ),
    )
    response = client.post("/api/model-discovery", headers={"Authorization": "Bearer ok"}, json={"provider_id": "openai", "ttl_seconds": 999999})
    assert response.status_code == 422

    response = client.post("/api/model-discovery", headers={"Authorization": "Bearer ok"}, json={"provider_id": "openai"})
    assert response.status_code == 200
    assert response.json()["discovery_kind"] == "curated_fallback"
    assert response.json()["models"][0]["supports_vision"] is None


def test_catalog_contract_is_not_registered_here():
    app = FastAPI()
    register_model_discovery_routes(app, lambda _: None)
    assert not any(route.path == "/api/model-catalog" for route in app.routes)
