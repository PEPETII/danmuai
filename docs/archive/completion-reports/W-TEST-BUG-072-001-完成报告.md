# Codex 完成报告

> 工单 ID：W-TEST-BUG-072-001  
> 完成时间：2026-06-03  
> 执行者：Codex

---

## 1. 修改摘要

闭合 [TEST-GAPS.md](../../bug-audit/TEST-GAPS.md) §6 BUG-072：用**真实** `WebConsoleBridge` + `QApplication.processEvents()` 补充 `invoke_on_main`（`BlockingQueuedConnection`）与 `save_config_requested`（`QueuedConnection` + `threading.Event`）同抢 Qt 主线程的回归测试。场景 A 验证 ~150ms 争用下不死锁且 `save_config_via_bridge` 仍 `ok=True`；场景 B 验证主线程被 invoke 占用时 HTTP 侧 `save_timeout` 契约（并对共享 `result`  dict 做返回快照，避免迟到的 `_on_save_config` 将 `ok` 翻为 `True`）。本票**仅**测试与文档。

## 2. 修改的文件

- `tests/test_web_console.py`
- `docs/bug-audit/TEST-GAPS.md`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/W-TEST-BUG-072-001-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `main.py`：是
- 未修改 `app/**`：是
- 未修改 `web/static/**`：是
- 未修改 `community-site/**`：是
- 未修改 `supabase/**`：是

## 4. 运行的命令

```bash
python -m pytest tests/test_web_console.py -k "invoke_on_main_timeout_under_main_thread_load or save_config_times_out_when_invoke" -q
```

（上述命令连续执行 3 次。）

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| scoped pytest | 通过 | **2 passed** ×3 runs（~0.8–1.0s/次） |
| boundary_guard | 未跑 | 纯 `tests/` + 文档，未触达 Web/API 边界 |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | scoped pytest `-k` 两条用例 | 全部通过 | **2 passed** ×3 | 是 |
| 2 | `git diff --name-only` 无 `main.py` / `app/` | 仅 tests + docs | 是 | 是 |
| 3 | 运行中同时保存配置 + 读弹幕/人格写路径 | 偶发 504 仍可能存在；与场景 B 一致 | 待负责人 | — |

## 7. 风险与注意事项

- 测试在 pytest 主线程充当 Qt GUI 线程；与生产 uvicorn 线程模型不同，但信号连接语义一致。
- `save_config_via_bridge` 与 `_on_save_config` 共享同一 `result` dict：HTTP `done.wait` 超时后槽仍可能写入 `ok=True`（P0 假成功风险的一部分）；场景 B 用 `dict(...)` 快照断言超时瞬间的 HTTP 回执。
- `test_save_config_via_bridge_returns_success_under_main_thread_load` 仍为 `SimpleNamespace` stub，不替代本票 Qt 路径。

## 8. 发现但未处理的问题

| 问题 | 说明 | 已记录 |
|------|------|--------|
| BUG-072 生产缓解 | `SAVE_CONFIG_TIMEOUT_SEC`、重活移出主线程等 | 否；建议 `W-BUG-072-FIX-001` |
| `BUGS-OVERVIEW` / `P3-LOW` 仍标 BUG-072 待修复 | 测试闭合缺口 ≠ 消除 P3 风险 | 否 |
| RISK-002 `mic_in_flight` 并发 | TEST-GAPS §6 剩余项 | 否 |
| 超时后共享 dict 被槽改写 | 与 P0-CRITICAL 保存语义相关 | 否 |

## 9. scoped diff 结论

本票改动路径：

- `tests/test_web_console.py`
- `docs/bug-audit/TEST-GAPS.md`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/W-TEST-BUG-072-001-完成报告.md`

未触及 `app/**`、`main.py`、`web/static/**`、`community-site/**`、`supabase/**`。

## 10. 已更新的文档

- [x] [docs/bug-audit/TEST-GAPS.md](../../bug-audit/TEST-GAPS.md)
- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] 本完成报告

## 11. 建议下一个工单

- TEST-GAPS §6 剩余：RISK-002 `mic_in_flight` 并发、BUG-038 WebSocket 并发等。
- 若需消除 504 / 超时后 dict 被改写：另开 `W-BUG-072-FIX-001` 授权 `app/web_console.py` + `boundary_guard`。
