# Codex 完成报告

> 工单 ID：W-REFACTOR-MAIN-002  
> 完成时间：2026-06-01  
> 执行者：Cursor Agent（Composer）

---

## 1. 修改摘要

在 `DanmuApp` 上补齐 status/diagnostics/probe 相关公开 façade（单行委托至既有私有实现），并让 `app/application/` 与 `app/web_api/routes.py` 经 façade 或 snapshot builder 读取运行态。`/api/probe` 与 `/api/custom-models/probe` 改为调用 `probe_api_connection()`，不再在路由内联 `probe_connection` 与掩码 Key 解析。未改主链路顺序、HTTP 响应形状与 bridge 写主线程语义。

## 2. 修改的文件

- `main.py`
- `app/application/runtime_state.py`
- `app/application/diagnostic_snapshot.py`
- `app/web_api/routes.py`
- `tests/test_request_scheduling.py`
- `tests/test_web_console.py`
- `docs/CONTRIBUTING_ARCHITECTURE.md`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/refactor/REFACTOR-CHANGELOG.md`
- `docs/templates/Codex完成报告/W-REFACTOR-MAIN-002-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `web/static/`：是
- 未修改 `community-site/`：是
- 未修改 `_trigger_api_call` / `_on_ai_reply` / `_consume_reply_queue` 调用顺序：是
- 未修改 `app/web_console.py`（已合规，无需改动）：是
- 未修改 `app/mic_test_send.py`：是（见 §8）
- 未改 `docs/main-pipeline-sequence.md`、`docs/runtime-state-map.md`：是（无新增 DanmuApp 字段/线程）

## 4. 运行的命令

```bash
python scripts/boundary_guard.py
python -m pytest tests/test_boundary_guard.py tests/test_request_scheduling.py tests/test_web_console.py -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| boundary_guard | 通过 | Boundary Guard: PASS |
| pytest（工单指定三文件） | 通过 | 111 passed |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | Web/API diff 无新增 `danmu_app._*` / `app._*` / `ai_worker._*` | `routes.py` 仅调用公开 façade；`web_console.py` 未改 | 是 |
| 2 | `/api/status` 与 `/api/diagnostics` 仍分离 | 仍经 `build_status_snapshot()` / `build_diagnostic_snapshot()` | 是 |
| 3 | bridge 写主线程路径未旁路 | `invoke_on_main` / `save_config_via_bridge` 未改 | 是 |
| 4 | 新增 façade 落点符合 CONTRIBUTING_ARCHITECTURE | 已更新公开入口列表 | 是 |

## 7. 风险与注意事项

- `POST /api/probe` 路由处理函数改名为 `probe_api_connection_route`（路径与 JSON 响应不变）。
- `RuntimeState.from_app` 对测试 `SimpleNamespace` 仍兼容：优先 `visible_display_count` / `build_live_status_snapshot`，回退旧 `_` 前缀（若有）。
- `application` 层经公开方法访问调度服务；主链路内部仍可使用 `_get_request_scheduler` 等私有入口。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| BUG-006 | `run_mic_test_send` 主线程阻塞 | 否（范围外；见 BUG-FIX-MERGE-PLAN） |
| BUG-008 | mic probe `pop_before_reply` / `ai_worker._emit_result` | 否（`app/mic_test_send.py` 不在本票允许区） |
| BUG-026 | `_calc_auto_interval` 死代码 | 否（工单禁止删除） |
| BUG-051 | `compress_screenshot` 与 `image_compress` 重复 | 否（工单禁止合并） |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/refactor/REFACTOR-CHANGELOG.md](../../refactor/REFACTOR-CHANGELOG.md)
- [x] [docs/CONTRIBUTING_ARCHITECTURE.md](../../CONTRIBUTING_ARCHITECTURE.md)

## 10. 建议下一个工单

- `W-REFACTOR-COMMUNITY-001` 或 `W-REFACTOR-TEST-001`（见 [refactor/REFACTOR-TASKS.md](../../refactor/REFACTOR-TASKS.md)）
- 独立 bug 票：`app/mic_test_send.py` 去除 `ai_worker._resolve_request_credentials` / `_emit_result` 直读（BUG-006/008）
