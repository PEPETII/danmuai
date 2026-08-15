import sqlite3

from app.config_store import ConfigStore


def _raw_config(db_path, key):
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def test_provider_scoped_tts_secrets_are_isolated_masked_and_encrypted(tmp_path):
    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path)
    try:
        store.set_tts_secret("mimo", "api_key", "mimo-secret")
        store.set_tts_secret("dashscope", "api_key", "dash-secret")
        store.set_tts_secret("doubao", "app_id", "app-id")
        store.set_tts_secret("doubao", "access_token", "access-token")

        assert store.get_tts_secret("mimo", "api_key") == "mimo-secret"
        assert store.get_tts_secret("dashscope", "api_key") == "dash-secret"
        assert store.get_tts_secret("mimo", "access_token") == ""
        assert store.get_tts_secret("doubao", "api_key") == ""
        assert store.get_tts_secret_masked("doubao", "access_token") == "********"
        assert store.get_tts_secret_masked("doubao", "missing") == ""

        stored = _raw_config(db_path, "tts_secret:doubao:access_token")
        assert stored and stored != "access-token"
        assert "access-token" not in stored
    finally:
        store.close()


def test_provider_scoped_tts_secret_delete_and_empty_set_remove_both_rows(tmp_path):
    store = ConfigStore(tmp_path / "config.db")
    try:
        store.set_tts_secret("mimo", "api_key", "secret")
        assert store.delete_tts_secret("mimo", "api_key") is True
        assert store.delete_tts_secret("mimo", "api_key") is False
        assert store.get_tts_secret("mimo", "api_key") == ""

        store.set_tts_secret("mimo", "api_key", "secret")
        store.set_tts_secret("mimo", "api_key", "")
        assert store.get_tts_secret("mimo", "api_key") == ""
    finally:
        store.close()


def test_legacy_tts_key_with_empty_provider_migrates_to_mimo_idempotently(tmp_path):
    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path)
    store.set_tts_api_key("legacy-mimo")
    store.set("tts_provider", "")
    store.close()

    store = ConfigStore(db_path)
    try:
        assert store.get_tts_secret("mimo", "api_key") == "legacy-mimo"
        assert store.get_tts_api_key() == ""
        first_value = _raw_config(db_path, "tts_secret:mimo:api_key")
    finally:
        store.close()

    store = ConfigStore(db_path)
    try:
        assert store.get_tts_secret("mimo", "api_key") == "legacy-mimo"
        assert _raw_config(db_path, "tts_secret:mimo:api_key") == first_value
    finally:
        store.close()


def test_legacy_tts_key_with_explicit_provider_migrates_to_that_provider(tmp_path):
    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path)
    store.set_tts_api_key("legacy-dashscope")
    store.set("tts_provider", "dashscope_qwen")
    store.close()

    store = ConfigStore(db_path)
    try:
        assert store.get_tts_secret("dashscope", "api_key") == "legacy-dashscope"
        assert store.get_tts_secret("mimo", "api_key") == ""
        assert store.get_tts_api_key() == ""
    finally:
        store.close()


def test_unknown_provider_keeps_legacy_tts_key(tmp_path):
    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path)
    store.set_tts_api_key("legacy-unknown")
    store.set("tts_provider", "future_provider")
    store.close()

    store = ConfigStore(db_path)
    try:
        assert store.get_tts_api_key() == "legacy-unknown"
        assert store.get_tts_secret("future_provider", "api_key") == ""
    finally:
        store.close()


def test_doubao_legacy_key_does_not_fill_app_id_or_access_token(tmp_path):
    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path)
    store.set_tts_api_key("legacy-doubao")
    store.set("tts_provider", "doubao")
    store.close()

    store = ConfigStore(db_path)
    try:
        assert store.get_tts_api_key() == ""
        assert store.get_tts_secret("doubao", "api_key") == "legacy-doubao"
        assert store.get_tts_secret("doubao", "app_id") == ""
        assert store.get_tts_secret("doubao", "access_token") == ""

        store.set_tts_secret("doubao", "app_id", "app-id")
        store.set_tts_secret("doubao", "access_token", "access-token")
        assert store.get_tts_secret("doubao", "api_key") == "legacy-doubao"
    finally:
        store.close()
