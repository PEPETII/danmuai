"""覆盖测试：BUG-AI-DEDUP-CONTEXT-001 — AI prompt 反重复上下文注入。

验证以下实现：
1. ``FloatingPanelEngine.recent_sent_view()`` 返回 ``_recent`` 的只读 tuple 快照
2. ``DanmuApp._recent_sent_danmu_for_prompt(limit)`` 按 ``danmu_render_mode`` 路由：
   - scrolling/默认 → ``engine.recent`` 反转后取前 ``limit``
   - floating_panel → ``floating_panel_engine.recent_sent_view()`` 反转后取前 ``limit``
   - 异常 → 返回空列表 + warning 日志
3. ``DanmuApp._build_visual_prompts`` 在末尾追加 "最近已发送的弹幕（请勿重复上述内容）" 段：
   - 非空时追加，空时跳过

测试约定（与 AGENTS.md §A.4.4 一致）：
- 不 ``from test_xxx import ...``
- 临时目录用 ``workspace_tmp`` fixture（重定向到 ``.pytest_tmp/``）
- 共享假对象来自 ``tests/fakes.py``；最小 DanmuApp 来自 ``make_minimal_danmu_app``
"""
from __future__ import annotations

from collections import deque
from unittest.mock import Mock

from app.config_store import ConfigStore
from app.floating_panel_engine import FloatingPanelEngine
from main import DanmuApp

from tests.conftest import make_minimal_danmu_app


# ---------------------------------------------------------------------------
# 辅助工厂
# ---------------------------------------------------------------------------


def _make_floating_panel_engine(workspace_tmp) -> FloatingPanelEngine:
    """构造一个真实 FloatingPanelEngine（参考 test_floating_panel_engine.py 的 _engine）。"""
    store = ConfigStore(db_path=workspace_tmp / "fp_engine.db")
    store.set("dedup_threshold", "1.0")
    engine = FloatingPanelEngine(store)
    engine.set_panel_height(400.0)
    return engine


def _stub_personae(app, *, persona: str = "persona-1") -> None:
    """挂上最小 personae Mock，返回非空 system_pt / user_pt。"""
    app.personae = Mock(
        pick_random=Mock(return_value=persona),
        get_prompt=Mock(return_value=("system_prompt_base", "user_prompt_base")),
    )


# ---------------------------------------------------------------------------
# 用例 1：FloatingPanelEngine.recent_sent_view 空快照
# ---------------------------------------------------------------------------


def test_recent_sent_view_returns_empty_tuple_when_empty(workspace_tmp):
    """空 _recent → recent_sent_view() 返回 () 且类型为 tuple。"""
    engine = _make_floating_panel_engine(workspace_tmp)

    result = engine.recent_sent_view()

    assert result == ()
    assert isinstance(result, tuple)


# ---------------------------------------------------------------------------
# 用例 2：scrolling 模式 _recent_sent_danmu_for_prompt 反转 + 最近在前
# ---------------------------------------------------------------------------


def test_recent_sent_danmu_for_prompt_scrolling_mode():
    """danmu_render_mode 默认/scrolling → 从 engine.recent 反转取前 limit。

    deque 末尾是最近发送（["a","b","c"] 中 "c" 最新）；反转后最近在前。
    """
    app = make_minimal_danmu_app()
    # FakeConfig 默认无 danmu_render_mode → get 返回 "" → 走 scrolling 分支
    # FakeEngine 无 recent 属性，手动挂上 deque（与生产 DanmuEngine.recent 同型）
    app.engine.recent = deque(["a", "b", "c"])

    result = app._recent_sent_danmu_for_prompt(10)

    assert result == ["c", "b", "a"]


# ---------------------------------------------------------------------------
# 用例 3：scrolling 模式截断到 limit
# ---------------------------------------------------------------------------


def test_recent_sent_danmu_for_prompt_truncates_to_limit():
    """15 条 recent + limit=10 → 取最近 10 条，反转后 d14..d5。"""
    app = make_minimal_danmu_app()
    app.engine.recent = deque([f"d{i}" for i in range(15)])  # d0(旧) .. d14(新)

    result = app._recent_sent_danmu_for_prompt(10)

    assert len(result) == 10
    # 最近 10 条 = d14, d13, ..., d5（反转后最近在前）
    assert result == [f"d{i}" for i in range(14, 4, -1)]


# ---------------------------------------------------------------------------
# 用例 4：floating_panel 模式 _recent_sent_danmu_for_prompt
# ---------------------------------------------------------------------------


def test_recent_sent_danmu_for_prompt_floating_panel_mode(workspace_tmp):
    """danmu_render_mode=floating_panel → 从 floating_panel_engine.recent_sent_view() 取。

    用 add_text(skip_dedup=True) 公开 API 写入 3 条，避免触碰 _recent 私有字段。
    """
    app = make_minimal_danmu_app()
    app.config.set("danmu_render_mode", "floating_panel")

    engine = _make_floating_panel_engine(workspace_tmp)
    # 公开 API：skip_dedup=True 绕过去重，依次写入 a/b/c（c 最近）
    for idx, text in enumerate(["a", "b", "c"]):
        item = engine.add_text(text, item_height=32.0, skip_dedup=True, now=float(idx))
        assert item is not None  # 确认 add_text 成功
    app.floating_panel_engine = engine

    result = app._recent_sent_danmu_for_prompt(10)

    assert len(result) == 3
    assert result == ["c", "b", "a"]  # 最近在前


# ---------------------------------------------------------------------------
# 用例 5：异常隔离 → 返回空列表 + warning 日志
# ---------------------------------------------------------------------------


def test_recent_sent_danmu_for_prompt_returns_empty_on_exception(monkeypatch):
    """config.get 抛异常 → 返回 [] 且记录 warning（不向上抛出）。"""
    app = make_minimal_danmu_app()

    def raise_on_get(*_args, **_kwargs):
        raise RuntimeError("config boom")

    monkeypatch.setattr(app.config, "get", raise_on_get)

    result = app._recent_sent_danmu_for_prompt(10)

    assert result == []
    # FakeLogger.warning 收集 _recent_sent_danmu_for_prompt failed 消息
    assert any(
        "_recent_sent_danmu_for_prompt failed" in msg
        for msg in app.logger.warning_messages
    )


# ---------------------------------------------------------------------------
# 用例 6：_build_visual_prompts 注入反重复段（非空 recent）
# ---------------------------------------------------------------------------


def test_build_visual_prompts_injects_recent_sent_segment():
    """recent 非空 → system_pt 末尾追加 "最近已发送的弹幕（请勿重复上述内容）：…"。

    _build_visual_prompts 调用链较复杂（personae / append_nickname /
    append_live_topic / _inject_knowledge_prompt / _recent_sent_danmu_for_prompt），
    但 make_minimal_danmu_app 已绑定主链路方法，且 FakeConfig 缺 user_nickname /
    live_topic / knowledge_runtime → 中间步骤均为 no-op，可直接走真实路径。
    """
    app = make_minimal_danmu_app()
    _stub_personae(app)
    app.engine.recent = deque(["旧弹幕1", "旧弹幕2"])  # 旧弹幕2 最近

    result = app._build_visual_prompts(request_round=1, screenshot_id=1, batch_id=1)

    assert result is not None
    system_pt = result[0]
    assert "最近已发送的弹幕（请勿重复上述内容）" in system_pt
    # " | ".join(["旧弹幕2", "旧弹幕1"]) → "旧弹幕2 | 旧弹幕1"（最近在前）
    assert "旧弹幕2 | 旧弹幕1" in system_pt


# ---------------------------------------------------------------------------
# 用例 7：_build_visual_prompts 跳过注入（空 recent）
# ---------------------------------------------------------------------------


def test_build_visual_prompts_skips_inject_when_empty():
    """recent 为空 → system_pt 不包含 "最近已发送的弹幕" 段。"""
    app = make_minimal_danmu_app()
    _stub_personae(app)
    app.engine.recent = deque()  # 空

    result = app._build_visual_prompts(request_round=1, screenshot_id=1, batch_id=1)

    assert result is not None
    system_pt = result[0]
    assert "最近已发送的弹幕" not in system_pt
