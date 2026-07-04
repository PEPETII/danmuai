"""纯辅助函数与小数据类型（W-REFACTOR-MAIN-001）。

职责边界：
- 主链路常量定义（VISUAL_INFLIGHT_WARN_SEC=45s、MAX_IN_FLIGHT=1、MAX_MIC_IN_FLIGHT=1）
- BatchTracker 数据类（视觉批次锚点元数据）
- 纯函数辅助（reply_request_id、density_right_target 等）

与 DanmuApp 关系：本模块不依赖 DanmuApp，可安全用于单元测试。
DanmuApp 通过 from app.main_helpers import ... 使用这些常量和函数。

代码归属判断：无 Qt 导入、无 DanmuApp 依赖的纯逻辑代码放这里。
"""

from __future__ import annotations

from app.danmu_engine import DanmuItem

VISUAL_INFLIGHT_WARN_SEC = 45.0
# Hung stream / no callback: force-release visual slot (S-011); before 60s double-retry ceiling (S-012).
VISUAL_INFLIGHT_RECOVER_SEC = 48.0
# AiRunnable wall clock: hung SSE must error before double-retry ceiling (S-012).
REQUEST_WALL_CLOCK_SEC = 45.0
# W-PERF-STREAM-001：流式首内容超时 — 从请求开始到收到第一个 content delta 的最大等待时间。
# 超过此时间仍未收到 content，视为"模型未产出弹幕"，提前终止流式响应。
STREAM_FIRST_CONTENT_TIMEOUT_SEC: float = 20.0
MAX_IN_FLIGHT = 1
MAX_MIC_IN_FLIGHT = 1
# S-009: consecutive capture failures before surfacing Web status bar warning.
CAPTURE_FAIL_WARN_THRESHOLD = 3
# W-PERF-TIMER-001：topmost 健康检查间隔与心跳（约 9s 无条件重申 @ 1500ms × 6）。
TOPMOST_HEALTH_INTERVAL_MS = 1500
TOPMOST_HEALTH_HEARTBEAT_TICKS = 6


class BatchTracker:
    """当前视觉批次的锚点元数据（普通模式）。

    anchor_item：本批首条成功上屏弹幕；滚到屏幕 75% 宽处时写入 next_generation_time，
    供 API 调度 debug 日志（_log_api_schedule）与批次观测，不驱动额外截图定时器。
    """

    def __init__(self, batch_id: int):
        self.batch_id = batch_id
        self.anchor_item: DanmuItem | None = None
        self.next_generation_time: float = 0.0


def reply_request_id(
    request_round: int,
    screenshot_id: int,
    scene_generation: int,
) -> tuple[int, int, int]:
    return (int(request_round), int(screenshot_id), int(scene_generation))


def density_right_target(min_n: int) -> int:
    if min_n <= 0:
        return 2
    return max(1, min_n // 3)


def config_flag_enabled(config, key: str, *, default: str = "0") -> bool:
    return str(config.get(key, default) or default).strip() == "1"


def queue_capacity(config, normal_reply_count: int) -> int:
    """回复队列容量；reply_queue_max_items=0 表示无裁剪，否则 clamp 到 1..9999。"""
    configured = config.get_int("reply_queue_max_items", 0)
    if configured <= 0:
        return 0
    return max(1, min(configured, 9999))


def log_api_schedule(
    logger,
    *,
    decision: str,
    source: str,
    block_reason: str = "",
    batch,
    rtt_avg: float,
    buffer_size: int,
    visible_count: int,
    in_flight: bool,
    scene_gen: int = 0,
) -> None:
    """API 调度 debug 日志（纯函数，无状态修改）。"""
    from app.api_schedule import api_schedule_debug_enabled, format_api_schedule_log

    if not api_schedule_debug_enabled():
        return
    batch_id = batch.batch_id if batch else None
    next_gen = batch.next_generation_time if batch else 0.0
    logger.debug(
        format_api_schedule_log(
            decision=decision,
            source=source,
            batch_id=batch_id,
            next_generation_time=next_gen,
            rtt_avg=rtt_avg,
            buffer_size=buffer_size,
            visible_count=visible_count,
            in_flight=in_flight,
            block_reason=block_reason,
            scene_gen=scene_gen,
            cooldown_left_ms=0,
        )
    )
