"""Regression tests: TTS provider credentials must never leak across platforms."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.application.config_service import MASKED_API_KEY
from app.config_store import ConfigStore
from app.danmu_read_service import DanmuReadService, export_danmu_read_config
from app.tts.config_credentials import (
    all_masked_tts_credentials,
    clear_stored_tts_credentials,
    masked_tts_credentials,
    stored_tts_credentials,
)
from app.tts_providers import (
    TTS_PROVIDER_DASHSCOPE_QWEN,
    TTS_PROVIDER_DOUBAO,
    TTS_PROVIDER_MIMO,
    TTS_PROVIDER_MINIMAX,
)
from app.web_api.danmu_read import get_voices
from PyQt6.QtCore import QObject

from tests.conftest import bind_minimal_danmu_app


def _make_read_service(config: ConfigStore) -> DanmuReadService:
    from main import DanmuApp

    app = DanmuApp.__new__(DanmuApp)
    QObject.__init__(app)
    bind_minimal_danmu_app(app)
    object.__setattr__(app, "config", config)
    return DanmuReadService(app)


def test_stored_tts_credentials_only_read_own_provider(workspace_tmp):
    store = ConfigStore(workspace_tmp / "stored_isolated.db")
    secrets = {
        TTS_PROVIDER_MIMO: "key-mimo",
        TTS_PROVIDER_MINIMAX: "key-minimax",
        TTS_PROVIDER_DOUBAO: "key-doubao",
        "dashscope": "key-dashscope",
    }
    try:
        for provider, secret in secrets.items():
            store.set_tts_secret(provider, "api_key", secret)
        for provider, secret in secrets.items():
            assert stored_tts_credentials(store, provider)["api_key"] == secret
            for other, other_secret in secrets.items():
                if other == provider:
                    continue
                assert stored_tts_credentials(store, other)["api_key"] == other_secret
    finally:
        store.close()


def test_global_tts_api_key_fallback_is_mimo_only(workspace_tmp):
    store = ConfigStore(workspace_tmp / "legacy_global.db")
    try:
        store.set_tts_api_key("legacy-only-mimo")
        assert stored_tts_credentials(store, TTS_PROVIDER_MIMO)["api_key"] == "legacy-only-mimo"
        assert stored_tts_credentials(store, TTS_PROVIDER_MINIMAX) == {}
        assert stored_tts_credentials(store, TTS_PROVIDER_DOUBAO) == {}
        assert stored_tts_credentials(store, "dashscope") == {}
    finally:
        store.close()


def test_masked_credentials_do_not_use_global_key_for_non_mimo(workspace_tmp):
    store = ConfigStore(workspace_tmp / "masked_global.db")
    try:
        store.set_tts_api_key("legacy-only-mimo")
        assert masked_tts_credentials(store, TTS_PROVIDER_MIMO)["api_key"] == MASKED_API_KEY
        assert masked_tts_credentials(store, TTS_PROVIDER_MINIMAX) == {}
        assert masked_tts_credentials(store, "dashscope") == {}
    finally:
        store.close()


def test_apply_config_saves_non_mimo_key_without_global_pollution(workspace_tmp):
    store = ConfigStore(workspace_tmp / "apply_non_mimo.db")
    service = _make_read_service(store)
    try:
        service.apply_config(
            {
                "provider": TTS_PROVIDER_MINIMAX,
                "model_id": "speech-2.8-turbo",
                "credentials": {"api_key": "minimax-secret"},
            }
        )
        assert store.get_tts_secret(TTS_PROVIDER_MINIMAX, "api_key") == "minimax-secret"
        assert store.get_tts_api_key() == ""
        assert store.get_tts_secret(TTS_PROVIDER_MIMO, "api_key") == ""
    finally:
        store.close()


def test_apply_config_mimo_writes_provider_scoped_secret_only(workspace_tmp):
    store = ConfigStore(workspace_tmp / "apply_mimo.db")
    service = _make_read_service(store)
    try:
        service.apply_config({"credentials": {"api_key": "mimo-secret"}})
        assert store.get_tts_secret(TTS_PROVIDER_MIMO, "api_key") == "mimo-secret"
        assert store.get_tts_api_key() == ""
    finally:
        store.close()


def test_provider_credentials_survive_switch_save_and_reload(workspace_tmp):
    store = ConfigStore(workspace_tmp / "switch_reload.db")
    service = _make_read_service(store)
    presets = {
        TTS_PROVIDER_MIMO: ("", "mimo-v2.5-tts", "key-a"),
        TTS_PROVIDER_MINIMAX: (TTS_PROVIDER_MINIMAX, "speech-2.8-turbo", "key-b"),
        TTS_PROVIDER_DOUBAO: (TTS_PROVIDER_DOUBAO, "seed-tts-2.0", "key-c"),
        TTS_PROVIDER_DASHSCOPE_QWEN: (
            TTS_PROVIDER_DASHSCOPE_QWEN,
            "qwen3-tts-flash-2025-11-27",
            "key-d",
        ),
    }
    try:
        for wire_provider, (stored_provider, model_id, api_key) in presets.items():
            patch = {"credentials": {"api_key": api_key}}
            if stored_provider:
                patch["provider"] = stored_provider
                patch["model_id"] = model_id
            service.apply_config(patch)
            exported = export_danmu_read_config(store)
            assert exported["credentials"].get("api_key") in ("", MASKED_API_KEY)
            if wire_provider == TTS_PROVIDER_MIMO:
                assert stored_tts_credentials(store, TTS_PROVIDER_MIMO)["api_key"] == api_key
            else:
                canonical = "dashscope" if wire_provider == TTS_PROVIDER_DASHSCOPE_QWEN else wire_provider
                assert stored_tts_credentials(store, canonical)["api_key"] == api_key

        assert store.get_tts_secret(TTS_PROVIDER_MIMO, "api_key") == "key-a"
        assert store.get_tts_secret(TTS_PROVIDER_MINIMAX, "api_key") == "key-b"
        assert store.get_tts_secret(TTS_PROVIDER_DOUBAO, "api_key") == "key-c"
        assert store.get_tts_secret("dashscope", "api_key") == "key-d"

        all_masked = all_masked_tts_credentials(store)
        assert all_masked[TTS_PROVIDER_MIMO]["api_key"] == MASKED_API_KEY
        assert all_masked[TTS_PROVIDER_MINIMAX]["api_key"] == MASKED_API_KEY
        assert all_masked[TTS_PROVIDER_DOUBAO]["api_key"] == MASKED_API_KEY
        assert all_masked["dashscope"]["api_key"] == MASKED_API_KEY

        store.set_batch({"tts_provider": TTS_PROVIDER_MINIMAX, "tts_model_id": "speech-2.8-turbo"})
        exported = export_danmu_read_config(store)
        assert exported["credentials"] == {"api_key": MASKED_API_KEY}
        assert exported["api_key"] == MASKED_API_KEY
        assert exported["provider_credentials"][TTS_PROVIDER_MIMO]["api_key"] == MASKED_API_KEY
        assert exported["provider_credentials"][TTS_PROVIDER_DOUBAO]["api_key"] == MASKED_API_KEY
        assert TTS_PROVIDER_MINIMAX in exported["provider_credentials"]
    finally:
        store.close()


def test_export_empty_for_unconfigured_provider_even_when_others_have_keys(workspace_tmp):
    store = ConfigStore(workspace_tmp / "export_empty.db")
    try:
        store.set_tts_secret(TTS_PROVIDER_MIMO, "api_key", "only-mimo")
        store.set_batch(
            {"tts_provider": TTS_PROVIDER_MINIMAX, "tts_model_id": "speech-2.8-turbo"}
        )
        exported = export_danmu_read_config(store)
        assert exported["credentials"] == {}
        assert exported["api_key"] == ""
        assert exported["provider_credentials"][TTS_PROVIDER_MIMO]["api_key"] == MASKED_API_KEY
        assert TTS_PROVIDER_MINIMAX not in exported["provider_credentials"]
    finally:
        store.close()


def test_get_voices_uses_provider_scoped_credentials():
    app = MagicMock()
    app.config = MagicMock()
    seen: list[str] = []

    def fake_stored(config, provider):
        assert config is app.config
        seen.append(provider)
        return {"api_key": f"secret-{provider}"}

    def fake_list_voices(provider, model, *, credentials, force_refresh):
        assert credentials == {"api_key": f"secret-{provider}"}
        from app.tts.types import VoiceDescriptor

        return [VoiceDescriptor(id="voice-1", name="Voice")]

    manager = MagicMock()
    manager.catalog.require_model.return_value.status = "active"
    manager.list_voices.side_effect = fake_list_voices

    with (
        patch("app.web_api.danmu_read.stored_tts_credentials", side_effect=fake_stored),
        patch("app.web_api.danmu_read.get_tts_manager", return_value=manager),
    ):
        result = get_voices(app, TTS_PROVIDER_MINIMAX, "speech-2.8-turbo")

    assert seen == [TTS_PROVIDER_MINIMAX]
    assert result["voices"][0]["id"] == "voice-1"


def test_clear_stored_tts_credentials_removes_only_target_provider(workspace_tmp):
    store = ConfigStore(workspace_tmp / "clear_one.db")
    try:
        store.set_tts_secret(TTS_PROVIDER_MIMO, "api_key", "mimo-key")
        store.set_tts_secret("dashscope", "api_key", "dash-key")
        assert clear_stored_tts_credentials(store, "dashscope") is True
        assert stored_tts_credentials(store, "dashscope") == {}
        assert stored_tts_credentials(store, TTS_PROVIDER_MIMO)["api_key"] == "mimo-key"
    finally:
        store.close()


def test_apply_config_clear_credentials_via_api(workspace_tmp):
    store = ConfigStore(workspace_tmp / "clear_via_apply.db")
    service = _make_read_service(store)
    try:
        service.apply_config(
            {
                "provider": TTS_PROVIDER_DASHSCOPE_QWEN,
                "model_id": "qwen3-tts-flash-2025-11-27",
                "credentials": {"api_key": "dash-key"},
            }
        )
        assert stored_tts_credentials(store, "dashscope")["api_key"] == "dash-key"
        service.apply_config({"clear_credentials": True})
        assert stored_tts_credentials(store, "dashscope") == {}
        assert all_masked_tts_credentials(store).get("dashscope") is None
    finally:
        store.close()


def test_apply_config_empty_api_key_clears_provider_secret(workspace_tmp):
    store = ConfigStore(workspace_tmp / "clear_empty_key.db")
    service = _make_read_service(store)
    try:
        service.apply_config({"credentials": {"api_key": "minimax-key"}, "provider": TTS_PROVIDER_MINIMAX})
        assert stored_tts_credentials(store, TTS_PROVIDER_MINIMAX)["api_key"] == "minimax-key"
        service.apply_config({"provider": TTS_PROVIDER_MINIMAX, "api_key": ""})
        assert stored_tts_credentials(store, TTS_PROVIDER_MINIMAX) == {}
    finally:
        store.close()
