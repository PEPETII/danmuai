"""Startup phase timing for cold-start diagnosis (dev log + frozen startup.log).

``mark(phase)`` / ``elapsed(phase)`` 记录冷启动各阶段耗时（import / Qt 初始化 / 截图线程启动 / Web
终端绑定等），开发模式写到 stderr，冻结模式下追加到 ``%APPDATA%/DanmuAI/startup.log``。

调用方式：``main.py`` 在每个阶段首尾包 ``t0 = time.monotonic()`` + ``startup_trace.mark("phase_name", t0)``；
**不**在每次启动累积（一次性，仅本进程内有效）。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.bundle_paths import append_frozen_log, frozen_log_path, is_frozen
from app.env_config import get as get_env

_logger = logging.getLogger(__name__)

_ORIGIN: float | None = None


def mark_app_start() -> None:
    """Record perf_counter origin; call once at the beginning of main()."""
    global _ORIGIN
    _ORIGIN = time.perf_counter()


def _elapsed_ms() -> float:
    if _ORIGIN is None:
        return 0.0
    return (time.perf_counter() - _ORIGIN) * 1000.0


def _should_write_file() -> bool:
    if is_frozen():
        return True
    env = get_env("DANMU_STARTUP_TRACE").strip().lower()
    return env in ("1", "true", "yes", "on")


def _format_fields(fields: dict[str, Any]) -> str:
    if not fields:
        return ""
    parts = []
    for key, value in fields.items():
        if isinstance(value, float):
            parts.append(f"{key}={value:.1f}")
        else:
            parts.append(f"{key}={value}")
    return " " + " ".join(parts)


def log_startup(phase: str, **fields: Any) -> None:
    """Log a startup phase with ms offset from mark_app_start()."""
    ms = _elapsed_ms()
    suffix = _format_fields(fields)
    line = f"[+{ms:.1f}ms] {phase}{suffix}"

    if is_frozen():
        append_frozen_log(line)
    elif _should_write_file():
        try:
            path = frozen_log_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(f"{line}\n")
        except OSError:
            pass

    _logger.info("[startup] %s", line)


def web_console_ready_timeout() -> float:
    """Max main-thread wait for uvicorn bind during attach_web_console."""
    # Too short causes startup_ok=False → pywebview never attaches → browser-only UX.
    return 1.5 if is_frozen() else 0.5
