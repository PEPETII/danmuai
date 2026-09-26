from types import SimpleNamespace

from app.application.diagnostic_snapshot import DiagnosticSnapshotBuilder
from app.application.status_snapshot import StatusSnapshotBuilder
from app.main_request_context_mixin import DanmuAppRequestContextMixin

from tests.diagnostics_helpers import make_diagnostic_app


class _Context:
    def public_projection(self):
        return SimpleNamespace(
            profile_id="profile-b",
            model_id="shared-model",
            provider_id="custom_openai",
            api_family="openai_chat_completions",
            endpoint_host="api.example.com",
            max_tokens=900,
            temperature=0.7,
            thinking="off",
        )


class _RequestMetaApp(DanmuAppRequestContextMixin):
    def __init__(self):
        self._pending_request_meta = {}
        self.logger = SimpleNamespace(debug=lambda *_args, **_kwargs: None)

    @staticmethod
    def _reply_request_id(request_round, screenshot_id, scene_generation):
        return request_round, screenshot_id, scene_generation


def test_request_metadata_keeps_only_safe_context_projection():
    app = _RequestMetaApp()
    app._register_request_meta(1, 2, 3, "visual", request_context=_Context())

    context = app._pending_request_meta[(1, 2, 3)]["request_context"]
    assert context == {
        "profile_id": "profile-b",
        "model_id": "shared-model",
        "provider_id": "custom_openai",
        "api_family": "openai_chat_completions",
        "endpoint_host": "api.example.com",
        "max_tokens": 900,
        "temperature": 0.7,
        "thinking": "off",
    }
    assert "api_key" not in context
    assert "endpoint" not in context


def test_status_and_diagnostics_use_latest_request_context_projection():
    app = make_diagnostic_app()
    app.get_request_context_projection = lambda: {
        "profile_id": "profile-b",
        "model_id": "shared-model",
        "provider_id": "custom_openai",
        "api_family": "openai_chat_completions",
        "endpoint_host": "api.example.com",
        "max_tokens": 900,
        "temperature": 0.7,
        "thinking": "off",
    }

    status = StatusSnapshotBuilder(app).build()
    assert status["request_context"]["profile_id"] == "profile-b"
    assert status["active_model_id"] == "shared-model"
    assert status["inferred_provider_id"] == "custom_openai"

    diagnostics = DiagnosticSnapshotBuilder(app).build()["config_context"]
    assert diagnostics["profile_id"] == "profile-b"
    assert diagnostics["active_model_id"] == "shared-model"
    assert diagnostics["provider_id"] == "custom_openai"
    assert diagnostics["api_family"] == "openai_chat_completions"
    assert diagnostics["api_endpoint_host"] == "api.example.com"
