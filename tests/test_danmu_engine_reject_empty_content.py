"""Test that danmu_engine rejects empty/whitespace-only content before deduplication."""

import pytest
from app.config_store import ConfigStore
from app.danmu_engine import DanmuEngine, DanmuItem


@pytest.fixture()
def engine(workspace_tmp):
    db_path = workspace_tmp / "config.db"
    store = ConfigStore(db_path=db_path)
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "2")
    eng = DanmuEngine(store)
    eng.recent.clear()
    eng.recent_exact_set.clear()
    eng.screen_width = 1000.0
    return eng


def test_add_item_rejects_empty_string(engine):
    """add_item should reject DanmuItem with empty string content."""
    item = DanmuItem(content="", persona="test", batch_id=0, scene_generation=0)
    result = engine.add_item(item)
    assert result is False


def test_add_item_rejects_whitespace_only(engine):
    """add_item should reject DanmuItem with whitespace-only content."""
    item = DanmuItem(content="   ", persona="test", batch_id=0, scene_generation=0)
    result = engine.add_item(item)
    assert result is False


def test_add_text_rejects_empty_string(engine):
    """add_text should reject empty string before deduplication."""
    result = engine.add_text("")
    assert result is None


def test_add_text_rejects_whitespace_only(engine):
    """add_text should reject whitespace-only string before deduplication."""
    result = engine.add_text("   ")
    assert result is None


def test_add_item_accepts_valid_content(engine):
    """add_item should accept DanmuItem with valid non-empty content."""
    item = DanmuItem(content="Hello World", persona="test", batch_id=0, scene_generation=0)
    result = engine.add_item(item)
    assert result is True


def test_add_text_accepts_valid_content(engine):
    """add_text should accept valid non-empty content."""
    result = engine.add_text("Hello World")
    assert result is not None
    assert result.content == "Hello World"
