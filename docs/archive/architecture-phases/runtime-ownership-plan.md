# Runtime Ownership Plan

> Archived Phase 2.5 design. Current field registry: [runtime-state-map.md](../../runtime-state-map.md).

## 范围

定义运行态字段归属与迁移顺序的历史规划。多项已落地（`StatsState`, `WebRuntimeState`, `RequestScheduler`, `RequestTimingService`）。

## 已落地摘要

| 目标 | 状态 |
|------|------|
| `StatsState` | 已迁移统计字段 |
| `WebRuntimeState` | 已迁移 Web 错误与展示缓存 |
| `GenerationPipelineState` | 只读投影 |
| `RequestScheduler` / `RequestTimingService` | 调度与 timing 所有权已迁移 |
| `_rhythm_check_timer` | 已移除（产品仅普通模式） |

## 仍留在 DanmuApp

`reply_buffer`, `ai_in_flight`, `_latest_screenshot`, `_scene_generation`, Qt 定时器、`QPixmap` 等 — 见 [phase4-freeze.md](phase4-freeze.md).

完整字段归属表见 git history 中 `docs/runtime-ownership-plan.md` 修订前版本（约 300 行）。
