"""直播新鲜度辅助模块（常量、退避与本地兜底纯函数）。

与 main.DanmuApp 配合：

- **过期回复丢弃**：main._is_reply_stale 当前恒为不丢弃，_record_stale_drop 路径未触发。
  三档 freshness TTL 常量仍保留；freshness 配置仅影响 main 截图间隔因子，不丢弃队列回复。
- **截图退避（dormant）**：30s 窗口内 stale 丢弃 ≥ 4 次时抬高截图间隔的逻辑仍保留，
  供单测与未来策略；当前因无 stale 丢弃，退避通常由 API 成功回复降级等级。
- **模型缓慢检测**：当前 in-flight 请求 ≥ 4s，或历史 RTT P90 ≥ 6s 时判定为慢，
  触发本地兜底等降级策略。
- **本地兜底批次**：模型响应慢时队列/画面可能空窗，从公式化弹幕库抽样生成轻量弹幕填充。
  （`is_model_slow` / `build_local_fallback_batch` **未接入 main 主链路**，2026-05-28：仅单元测试覆盖，上屏见后续工单。）

本文件提供常量、状态快照与纯函数；不持有 Qt/线程状态。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from app.reply_parser import normalize_reply_batch
from app.translations import tr

# --- 模型缓慢判定（双条件，满足其一即 is_model_slow=True）---
SLOW_REQUEST_SEC = 4.0  # 当前进行中的请求已耗时 ≥ 4s
SLOW_RTT_P90_SEC = 6.0  # 历史 RTT 样本 ≥3 条时，P90 ≥ 6s

# --- 截图退避：过期丢弃突发 → 加大截图间隔 ---
STALE_DROP_WINDOW_SEC = 30.0  # 统计滑动窗口长度
STALE_DROP_BURST_THRESHOLD = 4  # 窗口内丢弃次数达到此值则 should_backoff_screenshot
MAX_SCREENSHOT_BACKOFF_LEVEL = 4  # 退避等级上限（0=无退避）
MAX_SCREENSHOT_INTERVAL_MS = 12_000  # 退避后截图间隔硬顶 12s

@dataclass(frozen=True)
class LiveStatusSnapshot:
    """Web 控制台「直播状态」区展示用的不可变快照（由 main._build_live_status_snapshot 组装）。"""

    analyzing: bool = False
    local_fallback: bool = False
    delay_sec: float = 0.0
    stale_drops: int = 0

    def primary_message(self) -> str:
        """控制台直播区主文案：本地兜底 > 分析中 > 默认运行描述。"""
        if self.local_fallback:
            return tr("control.live_fallback")
        if self.analyzing:
            return tr("control.live_analyzing")
        return tr("control.status_running_desc")

    def detail_message(self) -> str:
        """副文案：当前延迟与 stale 丢弃计数（统计字段；当前策略下通常为 0）。"""
        delay = max(0.0, self.delay_sec)
        return tr("control.live_detail").format(
            delay=f"{delay:.1f}",
            drops=self.stale_drops,
        )


def build_local_fallback_batch(
    scene_count: int = 2,
    filler_count: int = 3,
    *,
    config=None,
) -> list[str]:
    """生成无需 API 的轻量兜底弹幕批次（经 normalize_reply_batch 截断/补齐）。

    未接入 main 主链路（2026-05-28）：仅单元测试覆盖；慢模型上屏见后续工单。

    模型响应慢或节奏空窗时，若不上屏会造成画面长时间无弹幕；本地兜底用池内短句
    快速填充视觉空白，且标记为 replaceable fallback，后续 AI 回复可顶掉。
    策略：从已启用的公式化弹幕库抽样；两库皆关或池为空则返回空批次。
    """
    from app.danmu_pool import load_danmu_pool_for_config, sample_danmu_for_config

    pool = load_danmu_pool_for_config(config)
    if not pool:
        return []
    total = scene_count + filler_count
    picked = sample_danmu_for_config(config, min(total, len(pool)))
    return normalize_reply_batch(
        picked,
        scene_count=scene_count,
        filler_count=filler_count,
        allow_shortfall=True,
        config=config,
    )


def prune_stale_drop_times(times: list[float], now: float | None = None) -> list[float]:
    """保留 STALE_DROP_WINDOW_SEC（30s）内的过期丢弃时间戳，供退避突发计数。"""
    now = time.monotonic() if now is None else now
    cutoff = now - STALE_DROP_WINDOW_SEC
    return [t for t in times if t >= cutoff]


def should_backoff_screenshot(stale_drop_times: list[float], now: float | None = None) -> bool:
    """是否应进入截图退避：先 prune 到 30s 窗口内，丢弃次数 ≥ STALE_DROP_BURST_THRESHOLD（4）。"""
    pruned = prune_stale_drop_times(stale_drop_times, now)
    return len(pruned) >= STALE_DROP_BURST_THRESHOLD


def screenshot_interval_ms(base_interval_sec: int, backoff_level: int) -> int:
    """按退避等级放大截图间隔：base_ms × (1 + 0.5 × level)，再 cap 到 MAX_SCREENSHOT_INTERVAL_MS。

    level 钳在 0..MAX_SCREENSHOT_BACKOFF_LEVEL；0.5 步进使退避渐进而非指数爆炸，
    最大 12s 避免长时间停截导致画面与弹幕完全脱节。
    """
    base_ms = max(1000, base_interval_sec * 1000)
    level = min(max(0, backoff_level), MAX_SCREENSHOT_BACKOFF_LEVEL)
    scaled = int(base_ms * (1.0 + 0.5 * level))
    return min(scaled, MAX_SCREENSHOT_INTERVAL_MS)


def is_model_slow(rtt_history: list[float], inflight_elapsed: float, *, in_flight: bool) -> bool:
    """判定模型是否偏慢：当前请求超时 OR 历史 RTT P90 过慢（双条件 OR）。

    未接入 main 主链路（2026-05-28）：仅单元测试覆盖；触发本地兜底见后续工单。

    1) in_flight 且 inflight_elapsed ≥ SLOW_REQUEST_SEC（4s）——单请求已拖太久；
    2) rtt_history 至少 3 条，排序取 P90 ≥ SLOW_RTT_P90_SEC（6s）——近期整体偏慢。
    任一为真则 main 可走本地兜底等降级，避免用户长时间看空白屏。
    """
    if in_flight and inflight_elapsed >= SLOW_REQUEST_SEC:
        return True
    if len(rtt_history) >= 3:
        sorted_rtt = sorted(rtt_history)
        idx = int(len(sorted_rtt) * 0.9)
        p90 = sorted_rtt[min(idx, len(sorted_rtt) - 1)]
        if p90 >= SLOW_RTT_P90_SEC:
            return True
    return False
