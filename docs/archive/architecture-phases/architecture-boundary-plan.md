# Architecture Boundary Plan

> Archived internal reference. Current overview: [ARCHITECTURE.md](../../ARCHITECTURE.md).

## 背景

当前 DanmuAI 已经把部分能力拆成独立模块，例如：

- `app/ai_client.py` 负责模型请求
- `app/danmu_engine.py` 负责轨道与去重
- `app/overlay.py` 负责 Qt 渲染
- `app/web_console.py` / `app/web_api/` 负责本地 Web 控制台
- `app/history.py` / `app/history_writer.py` / `app/templates.py` 负责不同类型的 SQLite 读写

但当前边界仍未完全收口。本文记录 Phase 0–5 边界规划与已执行收口，不要求读者按「待办」理解已全部未完成。

## 当前观察到的边界问题（历史记录）

### 1. `DanmuApp` 同时承担装配、编排、状态和 UI 协调

（见 `main.py::DanmuApp` — 仍为 bootstrap + 主编排器；application 层已分担状态快照与调度/timing 服务。）

### 2. Web 层穿透（Phase 1 已 largely 收口）

Phase 1 之前 Web 曾直接读私有字段；当前应通过 `build_status_snapshot()` 等公开入口。新增 Web 代码不得回退。

### 3. `DanmuEngine` 依赖 Overlay 与 SQLite

仍为已知技术债；勿扩大 `config.conn` 或新增 UI 依赖。

### 4. Storage 未分层

`ConfigStore` 仍持有共享连接；Repository 拆分为未来项。

## 目标职责边界

（略 — 见各 Phase 章节与 [CONTRIBUTING_ARCHITECTURE.md](../../CONTRIBUTING_ARCHITECTURE.md)。）

## Phase 2–5 摘要

- **Phase 2**：`RuntimeState` / `StatusSnapshotBuilder` / `ConfigService`；Web status timer 经 `DanmuApp` 管理。
- **Phase 3**：`StatsState`、`WebRuntimeState`、`GenerationPipelineState`（只读投影）。
- **Phase 4**：`RequestScheduler`（`last_api_trigger_at`）、`RequestTimingService`（timing + `rtt_history`）；[phase4-freeze.md](phase4-freeze.md)。
- **Phase 5**：`DiagnosticSnapshotBuilder`、`GET /api/diagnostics`；与 `/api/status` 分离。

## Phase 3-C 已执行边界

- 新增 `GenerationPipelineState` 只读投影层，不是主链路写模型。
- `RuntimeState.from_app()` 通过 `GenerationPipelineState.from_app(app)` 集中读取候选字段。
- 真实写入、stale 判定、队列消费仍在 `DanmuApp`。
- 未改动：`_on_screenshot_timer()` → `_on_normal_capture_tick()` → `_trigger_api_call()` → `_consume_reply_queue()`；Qt 线程模型；schema。

## Phase 5-C 结论

- 最终基线：[final-architecture-baseline.md](../../final-architecture-baseline.md)
- 冻结规则：[phase4-freeze.md](phase4-freeze.md)
- Phase 4 调度/timing 迁移已完成；Phase 5 之前不再推动更深主链路字段迁移。

完整历史段落见 git history 中本文件 2026-05 修订前版本。
