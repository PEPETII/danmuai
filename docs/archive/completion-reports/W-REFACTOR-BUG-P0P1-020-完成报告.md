# Codex 完成报告

> 工单 ID：W-REFACTOR-BUG-P0P1-020  
> 完成时间：2026-06-01  
> 执行者：Cursor Agent（Composer）

---

## 1. 修改摘要

修复 mic test-send probe 路径的两项缺陷：**BUG-006** 将 HTTP 从 Qt 主线程挪到既有 `QThreadPool`（`_MicProbeRunnable`），等待期间 `processEvents()` 保持定时器可运行；**BUG-008** 新增 `AiWorker.run_mic_audio_probe()`（`emit=False`），probe 不再经 `finished`/`error` 信号触发 `_pop_request_meta`，消除 `pop_before_reply` 日志污染。`send_mic_probe` 改为只经 `DanmuApp` 公开 façade，不再替换 `ai_worker._emit_result` 或直读 `_resolve_request_credentials`。

## 2. 修改的文件

- `app/ai_client.py`
- `app/mic_test_send.py`
- `main.py`
- `tests/test_mic_test_send.py`
- `tests/test_request_scheduling.py`
- `docs/main-pipeline-sequence.md`（Boundary Guard 要求：补充 `_MicProbeRunnable` 与 QThreadPool 表项）
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/W-REFACTOR-BUG-P0P1-020-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `web/static/`：是
- 未修改 `community-site/`：是
- 未修改 `app/web_api/`、`app/web_console.py`：是
- 未修改 `app/mic_capture.py`、`app/danmu_read*.py`：是
- 未修改 `_trigger_api_call` / `_on_ai_reply` / `_consume_reply_queue` 顺序：是
- 未修改 `docs/refactor/**`：是

## 4. 运行的命令

```bash
python scripts/boundary_guard.py
python -m pytest tests/test_mic_test_send.py tests/test_request_scheduling.py -q
python -m ruff check app/mic_test_send.py app/ai_client.py main.py tests/test_mic_test_send.py tests/test_request_scheduling.py
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| boundary_guard | 通过 | Boundary Guard: PASS |
| pytest（工单指定） | 通过 | 23 passed |
| ruff | 通过 | 上述文件无告警 |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 启动 `python main.py` | 未在本环境执行 | 待负责人 |
| 2 | 触发 mic test-send / probe 一次 | 未在本环境执行 | 待负责人 |
| 3 | UI 无明显卡死 | 未在本环境执行 | 待负责人 |
| 4 | 日志无 `pop_before_reply` | 单测覆盖 meta 不变 + 无 warning | 是（自动化） |
| 5 | probe 成功/失败回执真实 | 仍映射 `MicSendProbeResult` / HTTP 错误文案 | 是（单测） |

## 7. 风险与注意事项

- `invoke_on_main` 仍阻塞 HTTP 线程直至 probe 结束；验收重点是主线程在等待池结果时可处理 Qt 事件。
- `_MicProbeRunnable` 与视觉 `AiRunnable` 共用全局 `QThreadPool`；probe 使用独立 `run_mic_audio_probe`，不与 `_pending_request_meta` 交互。
- `resolve_request_credentials()` 现为 `AiWorker` 公开方法；`DanmuApp.resolve_request_credentials()` 已改调公开入口。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| BUG-005 | mic 模型支持误判（自定义 MiMo proxy） | 否（工单非目标） |
| BUG-020 | `_handle_mic_ai_reply` 不更新 scene_memory | 否（工单非目标） |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] `docs/main-pipeline-sequence.md`（Boundary Guard 同步）
- [x] 本完成报告

## 10. 建议下一个工单

- `W-REFACTOR-BUG-P0P1-004`（BUG-005 mic 模型支持误判）或 refactor 路线上的下一项 P0 bug 票。
