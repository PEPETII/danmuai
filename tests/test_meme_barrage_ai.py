"""烂梗 AI 识别展示解析与降级。"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.config_store import ConfigStore
from app.meme_barrage.ai_select import (
    build_meme_select_user_prompt,
    parse_meme_ai_selection,
)
from app.meme_barrage.service import MemeBarrageService
from main import DanmuApp


def test_parse_meme_ai_selection_keeps_candidates_only():
    candidates = ["画面相关", "无关梗", "另一句"]
    text = '["画面相关", "编造的句子"]'
    selected = parse_meme_ai_selection(text, candidates)
    assert selected == ["画面相关"]


def test_build_meme_select_user_prompt_includes_count():
    prompt = build_meme_select_user_prompt(["A", "B"], 2)
    assert "2" in prompt
    assert "1. A" in prompt


def test_ai_select_failed_enqueues_fallback_prefix(tmp_path):
    config = ConfigStore(db_path=tmp_path / "meme_ai_fail.db")
    app = DanmuApp.__new__(DanmuApp)
    app.config = config
    app.logger = MagicMock()
    app._meme_ai_in_flight = True
    service = MemeBarrageService(config)
    app._meme_barrage_service = service

    candidates = [f"c{i}" for i in range(10)]
    app._on_meme_ai_select_failed(candidates, 3)

    assert service.display_queue_size() == 3
    batch = service.pop_display_batch(3)
    assert batch == ["c0", "c1", "c2"]
    assert app._meme_ai_in_flight is False


def test_ai_select_done_empty_falls_back(tmp_path):
    config = ConfigStore(db_path=tmp_path / "meme_ai_empty.db")
    app = DanmuApp.__new__(DanmuApp)
    app.config = config
    app.logger = MagicMock()
    service = MemeBarrageService(config)
    app._meme_barrage_service = service

    candidates = ["a", "b", "c", "d"]
    app._on_meme_ai_select_done([], fallback_candidates=candidates, fallback_n=2)

    assert service.pop_display_batch(2) == ["a", "b"]
