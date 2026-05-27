"""Tests for RecentActivityState and summary generation."""

import time

from app.memory.activity import (
    ACTIVITY_OBSERVATION_WINDOW_SEC,
    FREQUENT_SWITCH_THRESHOLD,
    RecentActivityState,
)
from app.window_info import (
    ACTIVITY_TYPE_BROWSER,
    ACTIVITY_TYPE_CHAT,
    ACTIVITY_TYPE_DESKTOP,
    ACTIVITY_TYPE_GAME,
    ACTIVITY_TYPE_GAME_LAUNCHER,
    ACTIVITY_TYPE_IDE,
    ACTIVITY_TYPE_UNKNOWN,
    ACTIVITY_TYPE_VIDEO,
    ActivityObservation,
)


def _obs(
    activity_type: str,
    main_scene: str = "",
    app_or_game_name: str = "",
    confidence: float = 0.9,
    observed_at: float = 0.0,
) -> ActivityObservation:
    if observed_at == 0.0:
        observed_at = time.monotonic()
    return ActivityObservation(
        activity_type=activity_type,
        main_scene=main_scene,
        app_or_game_name=app_or_game_name,
        topic_hint="",
        confidence=confidence,
        observed_at=observed_at,
    )


def _obs_coding(name: str = "VS Code") -> ActivityObservation:
    return _obs(ACTIVITY_TYPE_IDE, main_scene="IDE", app_or_game_name=name)


def _obs_browsing() -> ActivityObservation:
    return _obs(ACTIVITY_TYPE_BROWSER, main_scene="浏览器")


def _obs_game(name: str = "英雄联盟") -> ActivityObservation:
    return _obs(ACTIVITY_TYPE_GAME, main_scene="游戏", app_or_game_name=name)


def _obs_video() -> ActivityObservation:
    return _obs(ACTIVITY_TYPE_VIDEO, main_scene="浏览器")


def _obs_chat(name: str = "微信") -> ActivityObservation:
    return _obs(ACTIVITY_TYPE_CHAT, main_scene="聊天", app_or_game_name=name)


def _obs_desktop() -> ActivityObservation:
    return _obs(ACTIVITY_TYPE_DESKTOP, main_scene="桌面", confidence=0.6)


class TestRecordObservation:
    def test_single_coding_observation(self):
        state = RecentActivityState()
        state.record_observation(_obs_coding())
        assert state.activity_type == "coding"
        assert "写代码" in state.activity_summary

    def test_three_coding_observations_stable(self):
        state = RecentActivityState()
        for _ in range(3):
            state.record_observation(_obs_coding())
        assert state.activity_type == "coding"

    def test_single_unknown_does_not_confirm(self):
        state = RecentActivityState()
        state.record_observation(_obs(ACTIVITY_TYPE_UNKNOWN, confidence=0.3))
        assert state.activity_type == "unknown"
        assert state.activity_summary == ""

    def test_game_immediate_switch(self):
        state = RecentActivityState()
        for _ in range(5):
            state.record_observation(_obs_coding())
        state.record_observation(_obs_game())
        assert state.activity_type == ACTIVITY_TYPE_GAME

    def test_game_launcher_stays_launcher(self):
        state = RecentActivityState()
        for _ in range(3):
            state.record_observation(
                _obs(ACTIVITY_TYPE_GAME_LAUNCHER, main_scene="游戏启动器", app_or_game_name="Steam")
            )
        assert state.activity_type == "game_launcher"


class TestSummaryGeneration:
    def test_coding_summary(self):
        state = RecentActivityState()
        for _ in range(3):
            state.record_observation(_obs_coding())
        assert state.activity_summary == "用户正在写代码"

    def test_coding_with_browsing_and_frequent_switching(self):
        state = RecentActivityState()
        for _ in range(3):
            state.record_observation(_obs_coding())
        state.record_observation(_obs_browsing())
        state.record_observation(_obs_coding())
        state.record_observation(_obs_browsing())
        state._scene_switch_times = [time.monotonic()] * FREQUENT_SWITCH_THRESHOLD
        state.switching_count = FREQUENT_SWITCH_THRESHOLD
        state.is_frequent_switching = True
        state._recalculate()
        assert state.activity_type == "coding"
        assert "写代码" in state.activity_summary
        assert "查询资料" in state.activity_summary

    def test_coding_without_frequent_switch_no_browsing_hint(self):
        state = RecentActivityState()
        for _ in range(5):
            state.record_observation(_obs_coding())
        assert "查询资料" not in state.activity_summary

    def test_game_with_name(self):
        state = RecentActivityState()
        state.record_observation(_obs_game("英雄联盟"))
        assert state.activity_summary == "用户正在玩《英雄联盟》"

    def test_game_without_name(self):
        state = RecentActivityState()
        state.record_observation(_obs(ACTIVITY_TYPE_GAME, main_scene="游戏", app_or_game_name=""))
        assert state.activity_summary == "用户正在玩一款游戏"

    def test_game_launcher_summary_with_name(self):
        state = RecentActivityState()
        state.record_observation(
            _obs(ACTIVITY_TYPE_GAME_LAUNCHER, main_scene="游戏启动器", app_or_game_name="Steam")
        )
        assert state.activity_type == "game_launcher"
        assert "游戏平台" in state.activity_summary
        assert "Steam" in state.activity_summary
        assert "玩" not in state.activity_summary

    def test_game_launcher_summary_without_name(self):
        state = RecentActivityState()
        state.record_observation(
            _obs(ACTIVITY_TYPE_GAME_LAUNCHER, main_scene="游戏启动器", app_or_game_name="")
        )
        assert state.activity_type == "game_launcher"
        assert state.activity_summary == "用户正在打开游戏平台"

    def test_browsing_summary(self):
        state = RecentActivityState()
        for _ in range(3):
            state.record_observation(_obs_browsing())
        assert state.activity_summary == "用户正在浏览网页"

    def test_browsing_frequent_switching(self):
        state = RecentActivityState()
        for _ in range(4):
            state.record_observation(_obs_browsing())
        state._scene_switch_times = [time.monotonic()] * FREQUENT_SWITCH_THRESHOLD
        state.switching_count = FREQUENT_SWITCH_THRESHOLD
        state.is_frequent_switching = True
        state._recalculate()
        assert "多个页面" in state.activity_summary

    def test_video_summary(self):
        state = RecentActivityState()
        for _ in range(3):
            state.record_observation(_obs_video())
        assert state.activity_summary == "用户正在观看视频"

    def test_chat_summary(self):
        state = RecentActivityState()
        for _ in range(3):
            state.record_observation(_obs_chat())
        assert state.activity_summary == "用户正在聊天"

    def test_desktop_summary(self):
        state = RecentActivityState()
        for _ in range(3):
            state.record_observation(_obs_desktop())
        assert state.activity_summary == "用户在桌面上操作"

    def test_unknown_no_summary(self):
        state = RecentActivityState()
        state.record_observation(_obs(ACTIVITY_TYPE_UNKNOWN, confidence=0.3))
        assert state.activity_summary == ""

    def test_unknown_frequent_switching(self):
        state = RecentActivityState()
        state.activity_type = "unknown"
        state.is_frequent_switching = True
        state._build_summary()
        assert "多个窗口" in state.activity_summary

    def test_summary_max_length(self):
        state = RecentActivityState()
        state.activity_type = "coding"
        state.is_frequent_switching = True
        state._observations = [_obs_coding(), _obs_browsing()]
        state._build_summary()
        assert len(state.activity_summary) <= 60 + 3


class TestSceneSwitch:
    def test_record_scene_switch(self):
        state = RecentActivityState()
        state.record_scene_switch()
        assert state.switching_count == 1
        assert not state.is_frequent_switching

    def test_frequent_switching_threshold(self):
        state = RecentActivityState()
        for _ in range(FREQUENT_SWITCH_THRESHOLD):
            state.record_scene_switch()
        assert state.is_frequent_switching

    def test_scene_switch_window_expiry(self):
        state = RecentActivityState()
        old_time = time.monotonic() - ACTIVITY_OBSERVATION_WINDOW_SEC - 1
        state._scene_switch_times = [old_time]
        state.record_scene_switch()
        assert state.switching_count == 1


class TestOnSceneChange:
    def test_game_scene_change_clears_state(self):
        state = RecentActivityState()
        state.record_observation(_obs_game("英雄联盟"))
        assert state.activity_summary != ""
        state.on_scene_change(new_generation=5)
        assert state.scene_generation == 5
        assert state.activity_summary == ""
        assert state.app_or_game_name == ""

    def test_non_game_scene_change_keeps_state(self):
        state = RecentActivityState()
        for _ in range(3):
            state.record_observation(_obs_coding())
        summary_before = state.activity_summary
        state.on_scene_change(new_generation=5)
        assert state.activity_summary == summary_before

    def test_scene_change_increments_switch(self):
        state = RecentActivityState()
        state.on_scene_change(new_generation=1)
        assert state.switching_count == 1


class TestReset:
    def test_reset_clears_everything(self):
        state = RecentActivityState()
        for _ in range(5):
            state.record_observation(_obs_coding())
        assert not state.is_empty()
        state.reset()
        assert state.activity_type == "unknown"
        assert state.activity_summary == ""
        assert state.switching_count == 0
        assert state.is_empty()


class TestIsEmpty:
    def test_empty_initially(self):
        state = RecentActivityState()
        assert state.is_empty()

    def test_not_empty_after_observation(self):
        state = RecentActivityState()
        state.record_observation(_obs_coding())
        assert not state.is_empty()


class TestObservationWindowExpiry:
    def test_old_observations_expired(self):
        state = RecentActivityState()
        old_time = time.monotonic() - ACTIVITY_OBSERVATION_WINDOW_SEC - 10
        state._observations.append(_obs(ACTIVITY_TYPE_IDE, observed_at=old_time))
        state.record_observation(_obs_browsing())
        assert len(state._observations) == 1
        assert state.activity_type == "browsing"
