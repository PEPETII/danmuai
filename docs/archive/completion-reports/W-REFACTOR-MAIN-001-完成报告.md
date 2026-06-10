# Codex 完成报告

> 工单 ID：W-REFACTOR-MAIN-001  
> 完成时间：2026-06-01  
> 执行者：Cursor Agent（Composer）

---

## 1. 修改摘要

将 `main.py` 中的纯函数、启动参数解析、`compress_screenshot` 与 `BatchTracker` 下沉至 `app/main_helpers.py`、`app/main_launch.py`、`app/screenshot_compress.py`。`DanmuApp` 受保护主链路方法（`_trigger_api_call`、`_on_ai_reply`、`_consume_reply_queue`）仍留在 `main.py`，小方法改为单行委托；`main` 模块对旧符号 re-export，兼容脚本与既有测试。未新增线程、计时器或 `DanmuApp` 字段。

## 2. 修改的文件

- `app/main_helpers.py`（新建）
- `app/main_launch.py`（新建）
- `app/screenshot_compress.py`（新建）
- `main.py`
- `tests/test_request_scheduling.py`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/refactor/REFACTOR-CHANGELOG.md`
- `docs/templates/Codex完成报告/W-REFACTOR-MAIN-001-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `web/static/`：是
- 未修改 `app/web_console.py`：是
- 未修改 `app/web_api/`：是
- 未修改 `docs/main-pipeline-sequence.md`、`docs/runtime-state-map.md`：是（无新增线程/字段）
- `_trigger_api_call`、`_on_ai_reply`、`_consume_reply_queue` 仍在 `main.py`，调用顺序未改

## 4. 运行的命令

```bash
python scripts/boundary_guard.py
python -m pytest tests/test_boundary_guard.py tests/test_request_scheduling.py tests/test_p0_main_flow.py -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| boundary_guard | 通过 | Boundary Guard: PASS |
| pytest（工单指定三文件） | 通过 | 74 passed |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | diff 中 `_trigger_api_call`、`_on_ai_reply`、`_consume_reply_queue` 仍在 `main.py` | 三方法体仍在 `main.py`，仅小 helper 委托 | 是 |
| 2 | 无新增线程/计时器/私有字段直读 | 未新增 QTimer/QThreadPool/字段；Web/API 未改 | 是 |
| 3 | runtime/pipeline 文档无需回填 | 未改 `runtime-state-map.md`、`main-pipeline-sequence.md` | 是 |

## 7. 风险与注意事项

- `from main import compress_screenshot` / `BatchTracker` / `_check_deprecated_launch_args` 仍可用（re-export）。
- `_calc_auto_interval` 仍留在 `DanmuApp`（dead code，BUG-026），本票未删除。
- `scene_fingerprint` / `live_freshness` 死代码未在本票处理（见 DELETE-CANDIDATES）。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| BUG-026 | `_calc_auto_interval` 无调用方 | 否（完成报告引用；可后续删除票） |
| BUG-047 | scene gate 恒空（已下沉为 `scene_api_block_reason()`） | 否 |
| BUG-051 | `compress_screenshot` 与 `image_compress` 重复 | 否 |
| DELETE-CANDIDATES | `scene_fingerprint` / `live_freshness` 未引用符号 | 否 |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/refactor/REFACTOR-CHANGELOG.md](../../refactor/REFACTOR-CHANGELOG.md)

## 10. 建议下一个工单

- `W-REFACTOR-MAIN-002`：补 `DanmuApp` façade / bridge 边界，清理 Web 可见状态读取路径。
