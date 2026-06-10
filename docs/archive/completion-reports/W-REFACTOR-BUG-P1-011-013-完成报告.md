# Codex 完成报告

> 工单 ID：W-REFACTOR-BUG-P1-011-013  
> 完成时间：2026-06-03  
> 执行者：Codex / Cursor Agent

---

## 1. 修改摘要

修复 BUG-011：将 `MAX_IN_FLIGHT` / `MAX_MIC_IN_FLIGHT` 从 `DanmuApp` 死写字段迁至 `app/main_helpers.py` 模块常量，并在 `_has_visual_request_in_flight`、`_has_mic_request_in_flight`、`_trigger_api_call` 门控处真正读取。

修复 BUG-013（W-003）：在 `main._on_normal_capture_tick` in-flight 分支接入 `_maybe_inject_local_fallback`，慢模型时调用 `is_model_slow` + `build_local_fallback_batch` 入队，`LiveStatusSnapshot.local_fallback` 经 `live_status_projection` 反映至 Web `live_local_fallback` / `live_message`。

## 2. 修改的文件

- `app/main_helpers.py`
- `app/application/live_status_projection.py`
- `app/live_freshness.py`
- `main.py`
- `tests/conftest.py`
- `tests/test_live_freshness.py`
- `tests/test_request_scheduling.py`
- `docs/runtime-state-map.md`
- `docs/bug-audit/BUGS-OVERVIEW.md`
- `docs/bug-audit/TEST-GAPS.md`
- `docs/已知问题与后续事项.md`
- `docs/当前仓库状态.md`
- `docs/templates/Codex完成报告/W-REFACTOR-BUG-P1-011-013-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `web/static/`：是
- 未修改 `app/web_console_support.py`：是
- 未新增 QTimer / QThreadPool：是
- 未改视觉/麦克风双轨并行策略：是

## 4. 运行的命令

```bash
python -m pytest tests/test_live_freshness.py tests/test_request_scheduling.py -q
python scripts/boundary_guard.py
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest | 通过 | `tests/test_live_freshness.py` + `tests/test_request_scheduling.py` — 29 passed |
| boundary_guard | 通过 | 登记 `_local_fallback_active` 后 PASS |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 公式化弹幕库开启 + 慢模型 in-flight ≥4s | 控制台 `live_message` 显示本地兜底文案 | 未在本环境实机跑（单测覆盖注入与投影） | 待负责人 |
| 2 | `grep self.MAX_IN_FLIGHT main.py` 无结果 | 无实例属性 | 是 | 是 |

## 7. 风险与注意事项

- 公式化弹幕库关闭时不会注入 fallback，UI 保持「分析中」——符合设计。
- BUG-046 随本票一并关闭（`is_model_slow` / `build_local_fallback_batch` 已接 main）。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| 无 | — | — |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/bug-audit/BUGS-OVERVIEW.md](../../bug-audit/BUGS-OVERVIEW.md)
- [x] [docs/已知问题与后续事项.md](../../已知问题与后续事项.md)（ISSUE-003 已修复）
- [x] [docs/runtime-state-map.md](../../runtime-state-map.md)

## 10. 建议下一个工单

- BUG-012 / BUG-021（浏览器 fallback 启动时序）可独立推进。
