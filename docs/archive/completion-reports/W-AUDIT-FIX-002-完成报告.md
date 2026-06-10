# Codex 完成报告

> 工单 ID：`W-AUDIT-FIX-002`  
> 完成时间：2026-05-31  
> 执行者：Codex

---

## 1. 修改摘要

修复了 `W-AUDIT-001` 中 `/api/config` 之外的剩余高优先级与基线问题：单实例守卫不再误判主实例，退出时先等线程池再关 HTTP client，启动同步等待窗口大幅缩短，Windows + Python 3.14 下的 `tests/test_single_instance.py` 不再在 skip 后触发后置崩溃，状态轮询 toast 增加节流，`HistoryWriter.flush()` 失败可见日志，`mic_test_send` 改为经 `DanmuApp` 公共 facade 访问麦克风能力与 probe 入口。

## 2. 修改的文件

- `E:/test/danmu/README.md`
- `E:/test/danmu/app/history_writer.py`
- `E:/test/danmu/app/mic_test_send.py`
- `E:/test/danmu/app/single_instance.py`
- `E:/test/danmu/app/startup_trace.py`
- `E:/test/danmu/docs/main-pipeline-sequence.md`
- `E:/test/danmu/docs/已知问题与后续事项.md`
- `E:/test/danmu/docs/工单列表.md`
- `E:/test/danmu/docs/当前仓库状态.md`
- `E:/test/danmu/docs/templates/工单/W-AUDIT-FIX-002-修复审计剩余高优先级与测试基线问题.md`
- `E:/test/danmu/docs/templates/Codex完成报告/W-AUDIT-FIX-002-完成报告.md`
- `E:/test/danmu/main.py`
- `E:/test/danmu/tests/test_history_writer.py`
- `E:/test/danmu/tests/test_mic_test_send.py`
- `E:/test/danmu/tests/test_single_instance.py`
- `E:/test/danmu/tests/test_startup_trace.py`
- `E:/test/danmu/tests/test_web_console.py`
- `E:/test/danmu/tests/test_webview_shell.py`
- `E:/test/danmu/web/static/app.js`

## 3. 未修改的关键区域

- 未修改主链路截图 / AI / 回复解析 / 入队 / 上屏顺序：是
- 未新增线程模型：是
- 未修改打包脚本与依赖清单：是
- 未触碰 `RequestScheduler` / `RequestTimingService` 所有权边界：是

## 4. 运行的命令

```bash
python -m pytest tests/test_single_instance.py tests/test_web_console.py tests/test_history_writer.py tests/test_mic_test_send.py -q
python -m pytest tests/test_startup_trace.py -q
python -m pytest tests/ -q
python -m ruff check app main.py tests scripts
python scripts/boundary_guard.py
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| `pytest` | 通过 | `750 passed, 1 skipped` |
| `ruff` | 通过 | `app main.py tests scripts` 全绿 |
| `boundary_guard` | 通过 | `Boundary Guard: PASS` |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 受影响子集测试通过 | `73 passed, 1 skipped` | 是 |
| 2 | 全量 pytest 通过且无 `0xc0000139` 后置崩溃 | `750 passed, 1 skipped`，未再打印致命异常 | 是 |
| 3 | Ruff 与 Boundary Guard 同步恢复绿灯 | 均 PASS | 是 |

## 7. 风险与注意事项

- `tests/test_single_instance.py` 对 Windows + Python 3.14 的处理是“明确 skip + README 支持边界说明”，不是宣称该环境已完全支持。
- 启动等待本轮是“同步窗口收紧”，不是彻底移除 `attach_web_console()` 的同步等待逻辑。
- `mic_test_send` 已通过 `DanmuApp` facade 访问麦克风能力与采样/探针入口，但 `send_mic_probe()` 内部仍复用 `AiWorker` 现有实现契约。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| ISSUE-001 | `docs/archive/` 历史设计仍可能误导 Agent | 是 |
| ISSUE-003 | `live_freshness` 本地 fallback 仍未接入主链路 | 是 |
| ISSUE-035 | `layout_mode` 放大残影待真机复现 | 是 |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](/E:/test/danmu/docs/当前仓库状态.md)
- [x] [docs/工单列表.md](/E:/test/danmu/docs/工单列表.md)
- [x] [docs/main-pipeline-sequence.md](/E:/test/danmu/docs/main-pipeline-sequence.md)
- [x] [docs/已知问题与后续事项.md](/E:/test/danmu/docs/已知问题与后续事项.md)
- [x] [docs/templates/工单/W-AUDIT-FIX-002-修复审计剩余高优先级与测试基线问题.md](</E:/test/danmu/docs/templates/工单/W-AUDIT-FIX-002-修复审计剩余高优先级与测试基线问题.md>)
- [x] [docs/templates/Codex完成报告/W-AUDIT-FIX-002-完成报告.md](</E:/test/danmu/docs/templates/Codex完成报告/W-AUDIT-FIX-002-完成报告.md>)

## 10. 建议下一个工单

- 若继续追 `W-AUDIT-001` 风险尾项，优先拆 `live_freshness` 本地 fallback 接线与 `layout_mode` 放大残影真机验收。
