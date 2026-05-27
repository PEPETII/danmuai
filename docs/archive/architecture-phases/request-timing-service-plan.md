# RequestTimingService Plan

> Archived. Implemented: `app/application/request_timing_service.py`.

## 范围

Phase 4-E/F 已将 `request_started_at_by_id` 与 `rtt_history` 真实所有权迁入 `RequestTimingService`。

## 当前职责

- 记录/消费 request timing、RTT 样本
- 提供 avg RTT 与 smart cooldown 数据基础
- 不负责：触发 API、队列、Overlay、Qt

## 回归测试

`tests/test_request_scheduling.py`

完整历史见 git history 中 `docs/request-timing-service-plan.md` 修订前版本。
