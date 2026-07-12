"""视觉主链路 ID 链的只读投影（screenshot_id / scene_generation 相关元数据）。

W-GENPIPELINE-EXTRACT 上下文：
    本 dataclass 是**只读投影层**，与 ``app/application/generation_pipeline.py``（行为层）
    互补。行为层（``GenerationPipeline`` 服务）承载回复消费与三路分发逻辑；
    本投影层仅供诊断快照 / 状态展示读取 ``latest_displayed_*`` 等公开 @property。

    Phase 4 冻结：写路径与运行态所有权仍在 DanmuApp（含回复队列、Qt 定时器、
    场景代龄、在途计数等）。本 dataclass 不持写状态，不实例化 Qt 对象。

Boundary Guard 要求集中经 from_app 读取，禁止在 RuntimeState 内散落 getattr(app, ...)。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from main import DanmuApp


@dataclass(frozen=True)
class GenerationPipelineState:
    """诊断与状态展示用只读快照；真实所有权仍在 DanmuApp（Phase 4 冻结，勿迁入本 dataclass 写路径）。

    与 ``GenerationPipeline`` 服务（行为层）的关系：服务在 ``consume_reply_queue`` /
    ``handle_reply_parsed`` 经 façade 写回；本 dataclass 仅经 ``from_app`` 读
    ``DanmuApp.latest_displayed_round`` / ``latest_*_screenshot_id`` @property，
    与 ``set_latest_displayed_from_pipeline`` 写路径对称，供 ``/api/diagnostics`` 等只读消费。
    """

    latest_displayed_round: int = 0
    latest_requested_screenshot_id: int = 0
    latest_queued_screenshot_id: int = 0
    latest_displayed_screenshot_id: int = 0

    @classmethod
    def from_app(cls, app: "DanmuApp") -> "GenerationPipelineState":
        return cls(
            latest_displayed_round=app.latest_displayed_round,
            latest_requested_screenshot_id=app.latest_requested_screenshot_id,
            latest_queued_screenshot_id=app.latest_queued_screenshot_id,
            latest_displayed_screenshot_id=app.latest_displayed_screenshot_id,
        )
