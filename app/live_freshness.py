"""直播新鲜度辅助模块（常量、本地兜底与慢模型检测纯函数）。

与 main.DanmuApp 配合：

- **模型缓慢检测**：当前 in-flight 请求 ≥ 4s，或历史 RTT P90 ≥ 6s 时判定为慢，
  触发本地兜底等降级策略。
- **本地兜底批次**：模型响应慢时队列/画面可能空窗，从公式化弹幕库抽样生成轻量弹幕填充。
  main 在 `_on_normal_capture_tick` in-flight 分支经 `_maybe_inject_local_fallback` 接线。

本文件提供常量、状态快照与纯函数；不持有 Qt/线程状态。

历史说明：实时模式 TTL/节奏预触发已移除；本模块当前职责为模型缓慢检测 + 本地兜底批次。
新增「实时/节奏」功能时**勿**回填到 ``live_freshness``，应单独建模块。
"""
from __future__ import annotations

from dataclasses import dataclass

from app.reply_parser import normalize_reply_batch
from app.translations import tr

# --- 模型缓慢判定（双条件，满足其一即 is_model_slow=True）---
SLOW_REQUEST_SEC = 4.0  # 当前进行中的请求已耗时 ≥ 4s
SLOW_RTT_P90_SEC = 6.0  # 历史 RTT 样本 ≥3 条时，P90 ≥ 6s


@dataclass(frozen=True)
class LiveStatusSnapshot:
    """Web 控制台「直播状态」区展示用的不可变快照（由 main._build_live_status_snapshot 组装）。"""

    analyzing: bool = False
    local_fallback: bool = False
    delay_sec: float = 0.0

    def primary_message(self) -> str:
        """控制台直播区主文案：本地兜底 > 分析中 > 默认运行描述。"""
        if self.local_fallback:
            return tr("control.live_fallback")
        if self.analyzing:
            return tr("control.live_analyzing")
        return tr("control.status_running_desc")

    def detail_message(self) -> str:
        """副文案：当前弹幕延迟（秒）。"""
        delay = max(0.0, self.delay_sec)
        return tr("control.live_detail").format(delay=f"{delay:.1f}")


def build_local_fallback_batch(
    scene_count: int = 2,
    filler_count: int = 3,
    *,
    config=None,
) -> list[str]:
    """生成无需 API 的轻量兜底弹幕批次（经 normalize_reply_batch 截断/补齐）。

    模型响应慢或节奏空窗时，若不上屏会造成画面长时间无弹幕；本地兜底用池内短句
    快速填充视觉空白，且标记为 replaceable fallback，后续 AI 回复可顶掉。
    策略：从已启用的自定义公式化弹幕库抽样；未开启或池为空则返回空批次。
    由 main._maybe_inject_local_fallback 在 is_model_slow 为真时调用。
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


def is_model_slow(rtt_history: list[float], inflight_elapsed: float, *, in_flight: bool) -> bool:
    """判定模型是否偏慢：当前请求超时 OR 历史 RTT P90 过慢（双条件 OR）。

    1) in_flight 且 inflight_elapsed ≥ SLOW_REQUEST_SEC（4s）——单请求已拖太久；
    2) rtt_history 至少 3 条，排序取 P90 ≥ SLOW_RTT_P90_SEC（6s）——近期整体偏慢。
    任一为真则 main._maybe_inject_local_fallback 可走本地兜底，避免用户长时间看空白屏。
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
