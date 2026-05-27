# RequestScheduler Plan

> Archived. Implemented: `app/application/request_scheduler.py`. Current rules: [CONTRIBUTING_ARCHITECTURE.md](../../CONTRIBUTING_ARCHITECTURE.md).

## 范围

`RequestScheduler` 是 Phase 4-B 的设计文档。Phase 4-D 已将 `last_api_trigger_at` 真实所有权迁入 `RequestScheduler`。

## 历史说明

文档编写时仍存在 realtime/rhythm 调度描述；产品已移除实时模式，普通模式为 `screenshot_timer` → `_on_normal_capture_tick()` → `_trigger_api_call()`。

## 当前职责

- 视觉请求触发调度判断（`min_api_interval`、in-flight 等）
- 持有 `last_api_trigger_at`
- 不负责：发起 AI、回复队列、Overlay、Qt 定时器

## 回归测试

`tests/test_request_scheduling.py` — 提交调度相关改动前必须运行。

完整 Phase 4-B/C/D 记录见 git history 中 `docs/request-scheduler-plan.md` 修订前版本。
