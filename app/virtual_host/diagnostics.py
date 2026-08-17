"""虚拟主播 E2E 诊断事件。

诊断事件只记录可安全关联链路的标识、状态和耗时，不记录 prompt、模型响应、
凭据或音频内容。日志正文采用单行 JSON，便于从 startup.log/控制台提取统计。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.logger import SanitizedLogger

logger = logging.getLogger(__name__)
_project_logger = SanitizedLogger()

_SAFE_FIELDS = frozenset(
    {
        "status",
        "error",
        "reason",
        "decision",
        "relevance",
        "probability",
        "event_kind",
        "batch_id",
        "screenshot_id",
        "scene_generation",
        "request_latency_ms",
        "scene_latency_ms",
        "chat_latency_ms",
        "tts_latency_ms",
        "event_to_playback_latency_ms",
        "playback_duration_ms",
        "segment_index",
        "segment_count",
        "segment_chars",
        "text_chars",
        "source",
        "priority",
        "accepted",
        "applied",
    }
)


def _safe_value(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.split())[:160]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)[:160]


def log_diagnostic(
    event: str,
    *,
    runtime_generation: int | None = None,
    turn_id: int | None = None,
    model_id: str | None = None,
    **fields: Any,
) -> None:
    """记录虚拟主播 E2E 诊断事件；未知字段默认丢弃以避免泄露输入内容。"""

    payload: dict[str, Any] = {
        "component": "virtual_host",
        "event": str(event),
        "runtime_generation": runtime_generation,
        "turn_id": turn_id,
        "model_id": " ".join(str(model_id or "").split())[:160],
    }
    payload.update(
        {
            key: _safe_value(value)
            for key, value in fields.items()
            if key in _SAFE_FIELDS
        }
    )
    message = f"virtual_host_diag {json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
    try:
        _project_logger.info(message)
    except Exception:
        logger.info(message)


__all__ = ["log_diagnostic"]
