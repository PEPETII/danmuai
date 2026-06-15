"""Lifetime counters persisted in config.db (survive restarts).

累计指标（弹幕数 / 运行时长 / token）从 ``DanmuApp`` 会话内计数；会话结束时
``LifetimeStats.stop()`` 把临时值并入 ``ConfigStore`` 中的
``stats_lifetime_danmu`` / ``stats_lifetime_seconds`` / ``stats_lifetime_input_tokens`` /
``stats_lifetime_output_tokens`` 等键，**不**重置（用户可永久累加）。

新增累计键时请同步 ``CONFIG_DEFAULTS`` 段（在 ``app.config_defaults`` 中无显式默认）；
``merge_from_session`` 在 stop() 时调用，HTTP 线程**勿**直接调（须经 ``WebConsoleBridge``）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config_store import ConfigStore

STATS_LIFETIME_DANMU = "stats_lifetime_danmu"
STATS_LIFETIME_RUNTIME_SEC = "stats_lifetime_runtime_sec"
STATS_LIFETIME_TOKENS = "stats_lifetime_tokens"
STATS_LIFETIME_INPUT_TOKENS = "stats_lifetime_input_tokens"
STATS_LIFETIME_OUTPUT_TOKENS = "stats_lifetime_output_tokens"


class LifetimeStats:
    def __init__(self, config: "ConfigStore"):
        self._config = config
        self._danmu = max(0, config.get_int(STATS_LIFETIME_DANMU, 0))
        self._runtime_sec = max(0.0, config.get_float(STATS_LIFETIME_RUNTIME_SEC, 0.0))
        self._input_tokens = max(0, config.get_int(STATS_LIFETIME_INPUT_TOKENS, 0))
        self._output_tokens = max(0, config.get_int(STATS_LIFETIME_OUTPUT_TOKENS, 0))
        legacy_total = max(0, config.get_int(STATS_LIFETIME_TOKENS, 0))
        tracked = self._input_tokens + self._output_tokens
        self._untracked_tokens = max(0, legacy_total - tracked)
        self._dirty = False

    def add_danmu(self, count: int = 1) -> None:
        if count < 0:
            raise ValueError("count must be non-negative")
        if count <= 0:
            return
        self._danmu += count
        self._dirty = True

    def add_tokens(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts must be non-negative")
        changed = False
        if input_tokens > 0:
            self._input_tokens += input_tokens
            changed = True
        if output_tokens > 0:
            self._output_tokens += output_tokens
            changed = True
        if changed:
            self._dirty = True

    def total_tokens(self) -> int:
        return self._input_tokens + self._output_tokens + self._untracked_tokens

    def _persist_token_keys(self) -> dict[str, str]:
        payload = {
            STATS_LIFETIME_DANMU: str(self._danmu),
            STATS_LIFETIME_INPUT_TOKENS: str(self._input_tokens),
            STATS_LIFETIME_OUTPUT_TOKENS: str(self._output_tokens),
        }
        if self._untracked_tokens > 0:
            payload[STATS_LIFETIME_TOKENS] = str(self.total_tokens())
        return payload

    def flush_pending(self) -> None:
        """Persist in-memory counters (batched; safe to call often)."""
        if not self._dirty:
            return
        self._config.set_batch(self._persist_token_keys())
        self._dirty = False

    def flush_runtime(self, session_sec: float) -> bool:
        """Persist session runtime into lifetime counters; return True on success."""
        if session_sec <= 0:
            self.flush_pending()
            return True
        new_runtime = self._runtime_sec + session_sec
        payload = self._persist_token_keys()
        payload[STATS_LIFETIME_RUNTIME_SEC] = str(new_runtime)
        self._config.set_batch(payload)
        self._runtime_sec = new_runtime
        self._dirty = False
        return True

    def display_runtime_sec(self, session_sec: float = 0.0) -> float:
        return self._runtime_sec + max(0.0, session_sec)

    def snapshot(self, *, session_runtime_sec: float = 0.0) -> dict[str, int | float]:
        return {
            "lifetime_danmu_count": self._danmu,
            "lifetime_runtime_sec": self.display_runtime_sec(session_runtime_sec),
            "lifetime_input_tokens": self._input_tokens,
            "lifetime_output_tokens": self._output_tokens,
            "lifetime_total_tokens": self.total_tokens(),
        }
