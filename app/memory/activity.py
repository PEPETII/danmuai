"""前台窗口活动追踪（不是弹幕内容记忆）。

RecentActivityState 记录用户最近在做什么（写代码/浏览/游戏/视频等），
通过 window_info 前台窗口识别推断。
activity_summary 被 app/memory/activity_prompt.py 消费，拼入 AI prompt 的活动状态段。
与 BulletDedupMemory 的区别：后者记录已播弹幕文本用于去重，本模块记录用户行为类型用于场景理解。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.window_info import ACTIVITY_TYPE_GAME, ACTIVITY_TYPE_GAME_LAUNCHER, ActivityObservation

ACTIVITY_OBSERVATION_WINDOW_SEC = 300  # 观察窗口：5 分钟内的活动才参与计算
FREQUENT_SWITCH_THRESHOLD = 4  # 频繁切换判定：窗口内切换 ≥4 次
STABLE_OBSERVATION_COUNT = 3  # 稳定判定：同一类型出现 ≥3 次视为稳定
ACTIVITY_SUMMARY_MAX_LEN = 60  # 活动摘要最大长度

ACTIVITY_TYPE_LAUNCHER = "game_launcher"


@dataclass
class RecentActivityState:
    activity_type: str = "unknown"
    activity_summary: str = ""
    main_scene: str = ""
    app_or_game_name: str = ""
    topic_hint: str = ""
    switching_count: int = 0
    is_frequent_switching: bool = False
    confidence: float = 0.0
    updated_at: float = 0.0
    scene_generation: int = 0

    _observations: list[ActivityObservation] = field(
        default_factory=list, repr=False,
    )
    _scene_switch_times: list[float] = field(
        default_factory=list, repr=False,
    )

    def is_empty(self) -> bool:
        return not self.activity_summary and self.activity_type == "unknown"

    def record_observation(self, obs: ActivityObservation) -> None:
        now = time.monotonic()
        cutoff = now - ACTIVITY_OBSERVATION_WINDOW_SEC
        self._observations = [
            o for o in self._observations if o.observed_at >= cutoff
        ]
        self._observations.append(obs)
        self._recalculate()

    def record_scene_switch(self) -> None:
        now = time.monotonic()
        cutoff = now - ACTIVITY_OBSERVATION_WINDOW_SEC
        self._scene_switch_times = [
            t for t in self._scene_switch_times if t >= cutoff
        ]
        self._scene_switch_times.append(now)
        self.switching_count = len(self._scene_switch_times)
        self.is_frequent_switching = self.switching_count >= FREQUENT_SWITCH_THRESHOLD

    def on_scene_change(self, new_generation: int) -> None:
        self.scene_generation = new_generation
        self.record_scene_switch()
        # 游戏场景切换意味着完全不同的上下文，旧活动摘要不再适用
        if self.activity_type == ACTIVITY_TYPE_GAME:
            self._observations.clear()
            self.activity_summary = ""
            self.main_scene = ""
            self.app_or_game_name = ""
            self.topic_hint = ""

    def reset(self) -> None:
        self.activity_type = "unknown"
        self.activity_summary = ""
        self.main_scene = ""
        self.app_or_game_name = ""
        self.topic_hint = ""
        self.switching_count = 0
        self.is_frequent_switching = False
        self.confidence = 0.0
        self.updated_at = 0.0
        self.scene_generation = 0
        self._observations.clear()
        self._scene_switch_times.clear()

    # 状态重算逻辑：
    # 1. 按观察窗口过滤过期记录
    # 2. 统计各类型出现次数，取 dominant_type
    # 3. 特殊规则：最新观察为游戏→强制游戏；coding+browsing+频繁切换→coding
    # 4. 更新 main_scene/app_or_game_name/topic_hint/confidence
    # 5. 构建 activity_summary 自然语言摘要
    def _recalculate(self) -> None:
        if not self._observations:
            return

        now = time.monotonic()
        cutoff = now - ACTIVITY_OBSERVATION_WINDOW_SEC
        recent = [o for o in self._observations if o.observed_at >= cutoff]
        if not recent:
            return

        type_counts: dict[str, int] = {}
        for o in recent:
            t = _normalize_activity_type(o.activity_type)
            type_counts[t] = type_counts.get(t, 0) + 1

        dominant_type = max(type_counts, key=type_counts.get)
        dominant_count = type_counts[dominant_type]
        total = len(recent)

        latest = recent[-1]

        if latest.activity_type == ACTIVITY_TYPE_GAME:
            self.activity_type = ACTIVITY_TYPE_GAME
        elif latest.activity_type == ACTIVITY_TYPE_GAME_LAUNCHER:
            self.activity_type = ACTIVITY_TYPE_LAUNCHER
        elif dominant_count >= STABLE_OBSERVATION_COUNT or dominant_count / total >= 0.5:
            self.activity_type = dominant_type
        else:
            self.activity_type = "unknown"

        has_coding = type_counts.get("coding", 0) > 0
        has_browsing = type_counts.get("browsing", 0) > 0
        if has_coding and has_browsing and self.is_frequent_switching:
            self.activity_type = "coding"

        self.main_scene = latest.main_scene
        self.app_or_game_name = latest.app_or_game_name
        self.topic_hint = latest.topic_hint
        self.scene_generation = latest.scene_generation
        self.confidence = dominant_count / total if total > 0 else 0.0
        self.updated_at = now

        self._build_summary()

    def _build_summary(self) -> None:
        parts: list[str] = []

        if self.activity_type == "coding":
            parts.append("用户正在写代码")
            if self.is_frequent_switching and self._has_browsing_in_window():
                parts.append("并多次切换浏览器查询资料")
        elif self.activity_type == "browsing":
            if self.is_frequent_switching:
                parts.append("用户在多个页面之间切换")
            else:
                parts.append("用户正在浏览网页")
        elif self.activity_type == ACTIVITY_TYPE_GAME:
            if self.app_or_game_name:
                parts.append(f"用户正在玩《{self.app_or_game_name}》")
            else:
                parts.append("用户正在玩一款游戏")
        elif self.activity_type == ACTIVITY_TYPE_LAUNCHER:
            if self.app_or_game_name:
                parts.append(f"用户正在打开游戏平台{self.app_or_game_name}")
            else:
                parts.append("用户正在打开游戏平台")
        elif self.activity_type == "video":
            if self.app_or_game_name:
                parts.append(f"用户正在观看《{self.app_or_game_name}》")
            else:
                parts.append("用户正在观看视频")
        elif self.activity_type == "chat":
            parts.append("用户正在聊天")
        elif self.activity_type == "desktop":
            parts.append("用户在桌面上操作")
        else:
            if self.is_frequent_switching:
                parts.append("用户正在多个窗口之间切换，当前意图不明确")

        summary = "，".join(p for p in parts if p)
        if len(summary) > ACTIVITY_SUMMARY_MAX_LEN:
            summary = summary[:ACTIVITY_SUMMARY_MAX_LEN - 3] + "..."
        self.activity_summary = summary

    def _has_browsing_in_window(self) -> bool:
        now = time.monotonic()
        cutoff = now - ACTIVITY_OBSERVATION_WINDOW_SEC
        for o in self._observations:
            if o.observed_at >= cutoff and _normalize_activity_type(o.activity_type) == "browsing":
                return True
        return False


def _normalize_activity_type(activity_type: str) -> str:
    return activity_type
