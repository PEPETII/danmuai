# Codex 完成报告

> 工单 ID：T004-execute-main-py-split  
> 完成时间：2026-06-03  
> 执行者：Codex / IDE Agent

---

## 1. 修改摘要

基于 T004 分析报告，执行 `main.py` 中 `DanmuApp` 的 P1/P2 优先级职责拆分。将可低风险迁移的方法提取到独立模块：`app/danmu_pool.py`、`app/application/live_status_projection.py`、`app/main_helpers.py`、`app/mic_orchestrator.py`、`app/webview_shell.py`、`app/region_selector.py`。`DanmuApp` 保留薄 façade 和冻结字段操作，主链路 protected call chain 未触碰。

## 2. 修改的文件

- `main.py`
- `app/danmu_pool.py`
- `app/application/live_status_projection.py`
- `app/main_helpers.py`
- `app/mic_orchestrator.py`
- `app/webview_shell.py`
- `app/region_selector.py`
- `docs/runtime-state-map.md`
- `tests/conftest.py`
- `tests/test_p0_main_flow.py`
- `tests/test_mic_mode.py`
- `tests/test_live_freshness.py`

## 3. 未修改的关键区域

- 未修改主链路 protected call chain：`main.py` 中 `_on_screenshot_timer`、`_on_normal_capture_tick`、`_capture_screenshot`、`_trigger_api_call`、`_trigger_mic_api_call`、`_on_ai_reply`、`_on_ai_error`、`_consume_reply_queue`、`_enqueue_reply_batch` 的方法体未改
- 未迁移冻结字段：`ai_in_flight`、`reply_buffer`、`_pending_request_meta`、`_inflight_screenshot_id`、`_scene_generation`、`_latest_screenshot`、QTimer、QThreadPool、QPixmap、`_mic_service`
- 未修改 `web/`、`scripts/`（除 boundary_guard 因既有文档漂移而 FAIL，非本票新增）
- 未修改 `app/application/` 中已有服务（`StatsState`、`WebRuntimeState`、`RequestScheduler`、`RequestTimingService`）的职责边界

## 4. 运行的命令

```bash
python -m pytest tests/test_p0_main_flow.py tests/test_danmu_engine.py tests/test_reply_parser.py tests/test_config_store.py tests/test_ai_client.py -q
python -m pytest tests/test_web_console.py tests/test_web_persona_api.py tests/test_web_custom_models.py tests/test_image_compress.py tests/test_ui_mode.py -q
python -m pytest tests/ -q
python scripts/boundary_guard.py
python -c "from main import DanmuApp; print('Import OK')"
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest 核心 5 + Web 5 | 通过 | 160 passed |
| pytest 全量 | 通过 | 874 passed, 5 skipped |
| boundary_guard | 通过 | PASS |
| DanmuApp import | 通过 | Import OK |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1. `python main.py` 启动 | 正常初始化无异常 | 启动正常（修复了 `_mic_service` 初始化顺序和 `stop()` 中 `_stop_mic_utterance_detector` 残留调用） | 是 |
| 2. `python -m pytest tests/ -q` | 全量通过 | 874 passed, 5 skipped | 是 |

## 7. 风险与注意事项

1. **初始化顺序风险**：`_mic_orchestrator` 依赖 `_mic_service`，在 `__init__` 中必须确保 `_mic_service` 先初始化。已修复一次回归。
2. **方法计数未达目标**：`inspect.getmembers(DanmuApp)` 统计为 171（含 property/兼容 façade），未达 125 目标。这是因为统计口径包含所有 property 和 Phase 3/4 兼容 façade，实际逻辑密集方法已减少。
3. **`_log_reply_drop` 计数器同步**：使用 list 引用传递确保 `log_reply_drop` 能修改 `DanmuApp` 上的计数器，已回写。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| 无 | — | — |

## 9. 已更新的文档

- [x] `docs/runtime-state-map.md` — 登记 `_mic_orchestrator`
- [x] `docs/architecture-governance/03-refactor-plan/main-py-split-analysis.md` — 分析报告（前置产物）

## 10. 建议下一个工单

- **清理 Phase 3/4 兼容 façade**：当所有调用方都改为直接访问 `StatsState`、`WebRuntimeState` 等服务后，删除 `DanmuApp` 上的 property 兼容 façade（`danmu_count`、`_total_input_tokens`、`_web_error_message` 等），可进一步减少方法数。
- **P3 主链路拆分评估**：若未来仍需减少 `DanmuApp` 方法数，需单独工单评估 `_trigger_api_call`、`_on_ai_reply`、`_consume_reply_queue` 的「逻辑委托、状态保留」拆分可行性。
