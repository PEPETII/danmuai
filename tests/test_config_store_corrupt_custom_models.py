import pytest
from app.config_store import ConfigStore


_CORRUPT_VALUES = [
    ("truncated_json", '{"name":"a"'),
    ("bom_prefix", "\ufeff[]"),
    ("chinese_quotes", "[\"name\":\"模型\"]"),
    ("not_json", "not-json-at-all"),
    ("number_instead_of_list", "123"),
]


@pytest.mark.parametrize("_id,value", _CORRUPT_VALUES, ids=[v[0] for v in _CORRUPT_VALUES])
def test_get_custom_models_returns_empty_on_corrupt_data(tmp_path, _id, value):
    """Inject malformed JSON into custom_models field and assert graceful fallback."""
    db = tmp_path / "config.db"
    store = ConfigStore(db_path=db)
    store.conn.execute(
        "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
        ("custom_models", value),
    )
    store.conn.commit()
    # Invalidate cache so get_custom_models reads from DB again
    store._invalidate_custom_models_cache()

    result = store.get_custom_models()
    assert result == []

    store.close()
