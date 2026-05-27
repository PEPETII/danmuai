"""Integration tests for RecentActivityState wired into DanmuApp."""

import time
from unittest.mock import patch

from app.memory.activity import RecentActivityState
from app.memory.activity_prompt import format_activity_prompt_line
from app.scene_memory import SceneMemoryStore
from app.window_info import ACTIVITY_TYPE_GAME, ACTIVITY_TYPE_GAME_LAUNCHER, ActivityObservation
from main import DanmuApp

from tests.conftest import bind_minimal_danmu_app
from tests.fakes import FakeConfig
from tests.test_p0_main_flow import _make_minimal_app


def _cfg_with_memory_mode(mode: str) -> FakeConfig:
    cfg = FakeConfig()
    cfg.get = lambda key, default="": {"memory_mode": mode}.get(key, default)
    cfg.get_int = lambda key, default=0: 10 if key == "memory_window" else default
    return cfg


def _obs_coding():
    return ActivityObservation(
        activity_type="coding",
        main_scene="编程",
        app_or_game_name="",
        topic_hint="",
        confidence=0.9,
        observed_at=time.monotonic(),
    )


def _obs_game_launcher(name="Steam"):
    return ActivityObservation(
        activity_type=ACTIVITY_TYPE_GAME_LAUNCHER,
        main_scene="游戏启动器",
        app_or_game_name=name,
        topic_hint="",
        confidence=0.85,
        observed_at=time.monotonic(),
    )


def _obs_game(name="英雄联盟"):
    return ActivityObservation(
        activity_type=ACTIVITY_TYPE_GAME,
        main_scene="游戏",
        app_or_game_name=name,
        topic_hint="",
        confidence=0.9,
        observed_at=time.monotonic(),
    )


class TestMemoryModeOffNoCollect:
    def test_off_mode_no_collect(self):
        app = DanmuApp.__new__(DanmuApp)
        bind_minimal_danmu_app(app, config=FakeConfig())
        app._collect_activity_observation = DanmuApp._collect_activity_observation.__get__(app, DanmuApp)
        app._memory_mode = DanmuApp._memory_mode.__get__(app, DanmuApp)
        app._memory_enabled = DanmuApp._memory_enabled.__get__(app, DanmuApp)
        app._last_activity_collect_at = 0.0

        with patch("main.get_foreground_window_info") as mock_fn:
            app._collect_activity_observation()
            mock_fn.assert_not_called()

    def test_off_mode_no_inject(self):
        app = DanmuApp.__new__(DanmuApp)
        bind_minimal_danmu_app(app, config=FakeConfig())
        app._append_scene_memory_to_user_pt = DanmuApp._append_scene_memory_to_user_pt.__get__(app, DanmuApp)
        app._memory_mode = DanmuApp._memory_mode.__get__(app, DanmuApp)
        app._activity_state = RecentActivityState()
        app._activity_state.record_observation(_obs_coding())

        result = app._append_scene_memory_to_user_pt("prompt")
        assert result == "prompt"


class TestCollectActivityExceptionSafe:
    def test_exception_does_not_propagate(self):
        cfg = _cfg_with_memory_mode("scene_card")
        app = DanmuApp.__new__(DanmuApp)
        bind_minimal_danmu_app(app, config=cfg)
        app._collect_activity_observation = DanmuApp._collect_activity_observation.__get__(app, DanmuApp)
        app._memory_mode = DanmuApp._memory_mode.__get__(app, DanmuApp)
        app._memory_enabled = DanmuApp._memory_enabled.__get__(app, DanmuApp)
        app._last_activity_collect_at = 0.0

        with patch("main.get_foreground_window_info", side_effect=OSError("broken")):
            app._collect_activity_observation()

    def test_none_return_does_not_crash(self):
        cfg = _cfg_with_memory_mode("scene_card")
        app = DanmuApp.__new__(DanmuApp)
        bind_minimal_danmu_app(app, config=cfg)
        app._collect_activity_observation = DanmuApp._collect_activity_observation.__get__(app, DanmuApp)
        app._memory_mode = DanmuApp._memory_mode.__get__(app, DanmuApp)
        app._memory_enabled = DanmuApp._memory_enabled.__get__(app, DanmuApp)
        app._last_activity_collect_at = 0.0

        with patch("main.get_foreground_window_info", return_value=None):
            app._collect_activity_observation()


class TestActivitySummaryInjectsLine:
    def test_coding_summary_injected(self):
        cfg = _cfg_with_memory_mode("scene_card")
        app = DanmuApp.__new__(DanmuApp)
        bind_minimal_danmu_app(app, config=cfg, _scene_generation=0)
        app._append_scene_memory_to_user_pt = DanmuApp._append_scene_memory_to_user_pt.__get__(app, DanmuApp)
        app._memory_mode = DanmuApp._memory_mode.__get__(app, DanmuApp)
        app._activity_state = RecentActivityState()
        app._activity_state.record_observation(_obs_coding())

        result = app._append_scene_memory_to_user_pt("请生成弹幕：")
        assert "近期状态：" in result
        assert "写代码" in result

    def test_only_one_activity_line(self):
        cfg = _cfg_with_memory_mode("scene_card")
        app = DanmuApp.__new__(DanmuApp)
        bind_minimal_danmu_app(app, config=cfg, _scene_generation=0)
        app._append_scene_memory_to_user_pt = DanmuApp._append_scene_memory_to_user_pt.__get__(app, DanmuApp)
        app._memory_mode = DanmuApp._memory_mode.__get__(app, DanmuApp)
        app._activity_state = RecentActivityState()
        app._activity_state.record_observation(_obs_coding())

        result = app._append_scene_memory_to_user_pt("请生成弹幕：")
        assert result.count("近期状态：") == 1


class TestActivityEmptyFallbackToSceneMemory:
    def test_empty_activity_falls_back(self):
        cfg = _cfg_with_memory_mode("scene_card")
        app = DanmuApp.__new__(DanmuApp)
        bind_minimal_danmu_app(app, config=cfg, _scene_generation=0)
        app._append_scene_memory_to_user_pt = DanmuApp._append_scene_memory_to_user_pt.__get__(app, DanmuApp)
        app._memory_mode = DanmuApp._memory_mode.__get__(app, DanmuApp)
        app._activity_state = RecentActivityState()

        store = SceneMemoryStore()
        store.context.tone_hint = "轻松"
        app._scene_memory = store

        result = app._append_scene_memory_to_user_pt("请生成弹幕：")
        assert "近期状态：" not in result


class TestPromptNoWindowTitle:
    def test_no_window_title_in_prompt(self):
        cfg = _cfg_with_memory_mode("scene_card")
        app = DanmuApp.__new__(DanmuApp)
        bind_minimal_danmu_app(app, config=cfg, _scene_generation=0)
        app._append_scene_memory_to_user_pt = DanmuApp._append_scene_memory_to_user_pt.__get__(app, DanmuApp)
        app._memory_mode = DanmuApp._memory_mode.__get__(app, DanmuApp)

        state = RecentActivityState()
        obs = ActivityObservation(
            activity_type="coding",
            main_scene="编程",
            app_or_game_name="",
            topic_hint="",
            confidence=0.9,
            observed_at=time.monotonic(),
        )
        state.record_observation(obs)
        app._activity_state = state

        result = app._append_scene_memory_to_user_pt("prompt")
        assert "Code.exe" not in result
        assert "Visual Studio Code" not in result

    def test_no_exe_in_prompt(self):
        state = RecentActivityState()
        obs = ActivityObservation(
            activity_type="coding",
            main_scene="编程",
            app_or_game_name="",
            topic_hint="",
            confidence=0.9,
            observed_at=time.monotonic(),
        )
        state.record_observation(obs)

        line = format_activity_prompt_line(state)
        assert ".exe" not in line


class TestGameLauncherNotPlayingGame:
    def test_steam_not_playing_game(self):
        state = RecentActivityState()
        for _ in range(3):
            state.record_observation(_obs_game_launcher("Steam"))
        assert "玩" not in state.activity_summary
        assert "游戏平台" in state.activity_summary

    def test_wegame_not_playing_game(self):
        state = RecentActivityState()
        for _ in range(3):
            state.record_observation(_obs_game_launcher("WeGame"))
        assert "玩" not in state.activity_summary
        assert "游戏平台" in state.activity_summary

    def test_real_game_shows_playing(self):
        state = RecentActivityState()
        state.record_observation(_obs_game("英雄联盟"))
        assert "玩" in state.activity_summary
        assert "英雄联盟" in state.activity_summary

    def test_steam_in_prompt_not_playing(self):
        cfg = _cfg_with_memory_mode("scene_card")
        app = DanmuApp.__new__(DanmuApp)
        bind_minimal_danmu_app(app, config=cfg, _scene_generation=0)
        app._append_scene_memory_to_user_pt = DanmuApp._append_scene_memory_to_user_pt.__get__(app, DanmuApp)
        app._memory_mode = DanmuApp._memory_mode.__get__(app, DanmuApp)

        state = RecentActivityState()
        state.record_observation(_obs_game_launcher("Steam"))
        app._activity_state = state

        result = app._append_scene_memory_to_user_pt("prompt")
        assert "玩" not in result
        assert "游戏平台" in result


class TestThrottle:
    def test_throttle_within_1s(self):
        cfg = _cfg_with_memory_mode("scene_card")
        app = DanmuApp.__new__(DanmuApp)
        bind_minimal_danmu_app(app, config=cfg)
        app._collect_activity_observation = DanmuApp._collect_activity_observation.__get__(app, DanmuApp)
        app._memory_mode = DanmuApp._memory_mode.__get__(app, DanmuApp)
        app._memory_enabled = DanmuApp._memory_enabled.__get__(app, DanmuApp)
        app._last_activity_collect_at = time.monotonic()

        with patch("main.get_foreground_window_info") as mock_fn:
            app._collect_activity_observation()
            mock_fn.assert_not_called()

    def test_throttle_expired_collects(self):
        cfg = _cfg_with_memory_mode("scene_card")
        app = DanmuApp.__new__(DanmuApp)
        bind_minimal_danmu_app(app, config=cfg)
        app._collect_activity_observation = DanmuApp._collect_activity_observation.__get__(app, DanmuApp)
        app._memory_mode = DanmuApp._memory_mode.__get__(app, DanmuApp)
        app._memory_enabled = DanmuApp._memory_enabled.__get__(app, DanmuApp)
        app._last_activity_collect_at = time.monotonic() - 2.0

        from app.window_info import WindowActivity

        with patch("main.get_foreground_window_info", return_value=WindowActivity(title="test", exe_name="Code.exe", pid=123)):
            with patch("main.classify_foreground_window") as mock_classify:
                mock_classify.return_value = _obs_coding()
                app._collect_activity_observation()
                mock_classify.assert_called_once()


class TestReset:
    def test_reset_clears_activity_state(self):
        cfg = _cfg_with_memory_mode("scene_card")
        app = _make_minimal_app()
        app.config = cfg
        app._activity_state = RecentActivityState()
        app._activity_state.record_observation(_obs_coding())
        app._last_activity_collect_at = time.monotonic()
        assert not app._activity_state.is_empty()

        app._activity_state.reset()
        app._last_activity_collect_at = 0.0
        assert app._activity_state.is_empty()
        assert app._last_activity_collect_at == 0.0


class TestSceneSwitchRecorded:
    def test_activity_state_records_switch_without_scene_probe(self):
        """普通模式无场景探测；活动状态仍可通过 API 记录切换。"""
        app = _make_minimal_app()
        app._activity_state = RecentActivityState()
        initial_count = app._activity_state.switching_count
        app._activity_state.record_scene_switch()
        assert app._activity_state.switching_count == initial_count + 1
