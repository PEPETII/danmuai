"""应用生命周期内统计的真实所有者；从 DanmuApp 启动到完全关闭，内存态、不入库。

与 StatsState（单轮：生成弹幕→停止弹幕）和 LifetimeStats（跨重启持久化）区分。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class ApplicationStatsState:
    """DanmuApp 初始化时创建一次；start()/stop() 不重置。"""

    danmu_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    start_time: float = field(default_factory=time.monotonic)

    def add_tokens(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        self.total_input_tokens += int(input_tokens or 0)
        self.total_output_tokens += int(output_tokens or 0)

    def add_danmu(self, count: int = 1) -> None:
        self.danmu_count += int(count or 0)

    def runtime_sec(self, now: float | None = None) -> float:
        if self.start_time <= 0:
            return 0.0
        current = time.monotonic() if now is None else float(now)
        return max(0.0, current - self.start_time)
