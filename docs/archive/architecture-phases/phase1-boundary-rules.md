# Phase 1 Boundary Rules

> Archived. Current rules: [CONTRIBUTING_ARCHITECTURE.md](../../CONTRIBUTING_ARCHITECTURE.md).

## 目的

DanmuAI Phase 1 边界收口后的执行约束（历史文档）。适用于 `main.py`、`app/web_console.py`、`app/web_api/*` 等。

## 核心规则摘要

### Web / API

- 禁止新增 `danmu_app._`、`app._`、`ai_worker._` 等私有访问
- 必须使用 `build_status_snapshot()`、`apply_web_config_payload()` 等公开 façade
- 临时例外：`TODO(phase2-boundary): reason=..., current_private_access=..., target_public_api=...`

### 运行态字段

- 新字段登记：[runtime-state-map.md](../../runtime-state-map.md)
- Web 状态只经 `build_status_snapshot()` / `StatusSnapshotBuilder`

### 定时器 / 主链路

- 新 `QTimer` / `QThreadPool` / 线程点 → 同步 [main-pipeline-sequence.md](../../main-pipeline-sequence.md)
- 保护链：`_on_screenshot_timer()` → `_on_normal_capture_tick()` → `_capture_screenshot()` → `_trigger_api_call()` → `_on_ai_reply()` → `_consume_reply_queue()`
- （历史文档中的 `_check_rhythm_trigger()` 已随实时模式移除）

### Storage

- 禁止扩散 `config.conn`（白名单见 Boundary Guard）

### DanmuEngine

- 允许现状 Overlay/SQLite 耦合；禁止扩大

## 提交前检查

1. 搜索 Web/API 私有访问  
2. 对照 `runtime-state-map.md`  
3. 对照 `main-pipeline-sequence.md`  
4. `python scripts/boundary_guard.py`

完整 Phase 1 原文（含代码行号引用）见 git history 中 `docs/phase1-boundary-rules.md` 文档治理前修订。
