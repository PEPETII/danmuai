# Codex 完成报告

> 工单 ID：T010-round2-architecture-rationalization  
> 完成时间：2026-06-03  
> 执行者：Codex / GPT-5

---

## 1. 修改摘要

按“第二轮架构合理化拆分计划”落地 Phase 0-3：先锁定文档基线，再继续拆分 `main.py`、`app/web_console.py`、`app/ai_client.py`。保留受保护主链路顺序、Web/Bridge 公开入口和 `AiWorker` 生命周期不变，把纯 helper、launch/attach 辅助、Web console runtime/WS/config 辅助、AI request/support 辅助下沉到独立模块。结果是 `main.py` 收口到 1700 行，`app/web_console.py` 收口到 485 行，`app/ai_client.py` 收口到 390 行。

## 2. 修改的文件

- `main.py`
- `app/main_launch.py`
- `app/main_launch_mixin.py`
- `app/main_state_mixin.py`
- `app/main_web_facade_mixin.py`
- `app/main_mic_probe.py`
- `app/web_console.py`
- `app/web_console_support.py`
- `app/web_console_ws.py`
- `app/web_console_runtime.py`
- `app/ai_client.py`
- `app/ai_client_support.py`
- `app/ai_client_requests.py`
- `app/mic_orchestrator.py`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/refactor/README.md`
- `docs/refactor/TEST-MAPPING.md`
- `docs/templates/Codex完成报告/T010-round2-architecture-rationalization-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `web/static/**`：是
- 未修改 `community-site/**`：是
- 未修改 `supabase/**`：是
- 未修改 `app/danmu_engine.py`：是
- 未修改 `app/overlay.py`：是
- 未改变受保护主链路顺序：`_on_screenshot_timer` → `_on_normal_capture_tick` → `_capture_screenshot` → `_trigger_api_call` → `_on_ai_reply` → `_enqueue_reply_batch` → `_consume_reply_queue`

## 4. 运行的命令

```bash
python -m ruff check main.py app/main_launch.py app/main_launch_mixin.py app/web_console.py app/web_console_support.py
python scripts/boundary_guard.py
python -m pytest tests/test_ai_client.py tests/test_mic_mode.py tests/test_web_auth.py tests/test_web_bridge.py tests/test_web_server.py tests/test_web_status.py tests/test_web_websocket.py tests/test_capture_flow.py tests/test_ai_pipeline.py tests/test_reply_enqueue.py -q
python -m ruff check app main.py tests scripts
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 定向 pytest | 通过 | `169 passed` |
| boundary_guard | 通过 | `Boundary Guard: PASS` |
| 定向 ruff | 通过 | 相关拆分文件 `All checks passed!` |
| 全仓 ruff | 失败 | 范围外既有 2 项：`app/region_selector.py` 未使用 import；`scripts/rebalance_t008_tests2.py` import 排序 |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1. 统计核心文件行数 | `main.py <= 1700`，`app/web_console.py < 500`，`app/ai_client.py < 550` | 实际为 1700 / 485 / 390 | 是 |
| 2. 检查兼容入口 | `DanmuApp.build_status_snapshot()`、`DanmuApp.apply_web_config_payload()`、`save_config_via_bridge()`、`WebConsoleBridge.invoke_on_main()` 仍可用 | 相关测试全部通过 | 是 |
| 3. 检查测试映射文档 | Phase 0 基线与 Phase 1-3 新模块都有落点说明 | `docs/refactor/README.md`、`docs/refactor/TEST-MAPPING.md` 已更新 | 是 |

## 7. 风险与注意事项

- `main.py` 已压到目标线，但仍承载生命周期与受保护主链路；后续继续拆分时必须避免把状态所有权迁出 `DanmuApp`。
- `app/web_console.py` 依然保留稳定 re-export 以兼容现有测试和调用点；不要在后续小票中直接删这些兼容入口。
- 全仓 `ruff` 仍有 2 个范围外既有问题，本票只记录，不顺手修复。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| 无 | 本轮未新增范围外问题；仅复核到既有全仓 ruff 告警 2 项 | 是 |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/refactor/README.md](../../refactor/README.md)
- [x] [docs/refactor/TEST-MAPPING.md](../../refactor/TEST-MAPPING.md)
- [x] [docs/templates/Codex完成报告/T010-round2-architecture-rationalization-完成报告.md](./T010-round2-architecture-rationalization-完成报告.md)

## 10. 建议下一个工单

- 单独开一张小票处理全仓 `ruff` 的 2 个既有告警，避免后续把“验证失败”与“架构拆分回归”混在一起。
