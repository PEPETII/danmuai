# Codex 完成报告

> 工单 ID：W-RACE-001
> 完成时间：2026-06-08
> 执行者：Cursor Agent

---

## 1. 修改摘要

修复 bug-03 缺陷 3（陈旧 `AiRunnable` 在 `stop() → start()` 之间消耗新会话 in-flight 槽位）：在 `DanmuApp._on_ai_reply` 入口 `_pop_request_meta` 之后新增代际校验 —— 当 `meta` 为空（已被 `stop()` 清空）时打 `stale_reply_dropped` warning 并直接 `return`，既不释放新会话的 in-flight 槽位，也不入队。`_pop_request_meta` 既有 `request_meta_missing: reason=pop_before_reply` warning 保留作可观测性，本判断作为第二道防线。新增 `tests/test_p0_main_flow.py` 覆盖陈旧与正常两条路径；同时为既有 5 个 `_on_ai_reply` 单测预注册 `_register_request_meta`（行为变更后必需），并在 `docs/MAIN_PIPELINE.md` §4/§8 增补 W-RACE-001 描述。

## 2. 修改的文件

- `main.py`（仅 `_on_ai_reply` 前 ~15 行；其他位置未改）
- `tests/test_p0_main_flow.py`（新增，2 个测试）
- `tests/test_ai_pipeline.py`（既有 3 个测试预注册 meta）
- `tests/test_danmu_engine.py`（既有 1 个测试预注册 meta + bind `_register_request_meta`）
- `tests/test_live_freshness.py`（既有 1 个测试预注册 meta）
- `docs/MAIN_PIPELINE.md`（§4 加 W-RACE-001 bullet、§8 `reason=` 表新增 `stale_reply_dropped`）
- `docs/工单列表.md`（追加 W-RACE-001 行；`最后更新` 改为 `2026-06-08（W-RACE-001）`）
- `docs/当前仓库状态.md`（顶部插入 W-RACE-001 段；`最后更新` 改为 `2026-06-08（W-RACE-001）`）
- `docs/已知问题与后续事项.md`（顶部 `最后更新` 改为 `2026-06-08（W-RACE-001）`；末尾登记 ISSUE-042）
- `docs/工单列表/工单/W-RACE-001.md`（新建）
- `docs/templates/Codex完成报告/W-RACE-001-完成报告.md`（本文件）
- `docs/templates/已知问题记录/ISSUE-042-config_set_api_key_rlock_死锁.md`（新建）

## 3. 未修改的关键区域

- 未修改 `app/main_lifecycle_mixin.py`（start/stop 顺序）：是
- 未修改 `app/main_request_context_mixin.py`（`_pop_request_meta` 既有 warning 保留）：是
- 未修改 `app/ai_client.py`：是
- 未修改 `app/runnable.py`：是
- 未修改 `app/web_api/*`、`app/overlay.py`、`app/danmu_engine.py`：是
- 未修改 `web/static/*`：是
- 未修改 `docs/main-pipeline-sequence.md`（时序不变）：是
- 未修改 `requirements.txt`、锁文件、CI、打包配置：是

## 4. 运行的命令

```bash
cd E:\test\danmu
.\.venv-build\Scripts\python.exe -m pip install pytest-timeout
.\.venv-build\Scripts\python.exe -m pytest tests/test_p0_main_flow.py -q
.\.venv-build\Scripts\python.exe -m pytest tests/test_ai_pipeline.py tests/test_danmu_engine.py tests/test_live_freshness.py tests/test_mic_insert.py tests/test_request_scheduling.py tests/test_scene_freshness.py tests/test_boundary_guard_request_rules.py tests/test_p0_main_flow.py -q
.\.venv-build\Scripts\python.exe scripts/boundary_guard.py
.\.venv-build\Scripts\python.exe -m pytest tests/ -q --timeout=30 --ignore=tests/test_acceptance_gates.py --ignore=tests/test_p1_key_encryption.py --ignore=tests/test_p1_sqlite_concurrency.py --ignore=tests/test_startup_trace.py
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest test_p0_main_flow | 通过 | 2 passed（Case A 陈旧 drop、Case B 正常路径） |
| pytest _on_ai_reply 相关 8 文件 | 通过 | 70 passed（含 5 个修复后预注册 meta 的既有测试） |
| boundary_guard | 通过 | PASS |
| pytest 全量（排除已知挂起 4 文件） | 通过 | 1059 passed, 4 skipped, 0 failed |
| pytest test_p1_key_encryption | 未通过（已知） | W-CONC-001 引入的 `_write_lock` 嵌套死锁，ISSUE-042 已登记；W-RACE-001 范围外 |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1. `pytest tests/test_p0_main_flow.py -q` | 2 passed | 2 passed | 是 |
| 2. `pytest .../test_ai_pipeline.py test_danmu_engine.py test_live_freshness.py test_mic_insert.py test_request_scheduling.py test_scene_freshness.py test_p0_main_flow.py -q` | 全过 | 70 passed | 是 |
| 3. `scripts/boundary_guard.py` | PASS | PASS | 是 |
| 4. `pytest tests/ -q --timeout=30`（排除已知 4 个挂起文件） | 1059 passed, 4 skipped | 1059 passed, 4 skipped | 是 |
| 5. `git diff main.py` 仅 `_on_ai_reply` 前 ~15 行 | 是 | 是 | 是 |

## 7. 风险与注意事项

- **依赖 `_pop_request_meta` 返回空 dict（既有 missing path）** —— `_pop_request_meta` 内部在 `meta is None` 时返回 `{}` 而非 `None`，故本工单用 `if not meta:` 检测。如未来 `_pop_request_meta` 改为返回 `None` 或抛异常，需同步调整（建议同步给 `_pop_request_meta` 文档注释 + 测试）。
- **去掉「防御性陈旧 round」判断** —— 原始 spec 提议 `request_round > self.screenshot_round` 视为陈旧，但生产链路上 `_trigger_api_call` 必然 `request_round = screenshot_round`，且 `stop()`/`start()` 都不重置 `screenshot_round`；强行判断会误伤「新会话 screenshot_round 已递增、旧 reply 还在路上」等合法场景（如 `test_danmu_engine.py::test_ai_reply_queue_uses_request_context_and_fifos_results` 模拟的连续 reply）。故仅保留「meta 为空」一道判定。
- **既有 5 个 `_on_ai_reply` 单测行为变更后需预注册 meta** —— 旧行为对空 meta fallback 到默认 `source="visual"`，工单后空 meta 直接 return，最小修复是 1 行 `_register_request_meta(...)`。该变更符合生产链路真实流程（`_trigger_api_call` 必然注册 meta）。
- **不动 `app/runnable.py`** —— 陈旧 `AiRunnable` 仍能在工作线程完成是允许的；只是结果在 `_on_ai_reply` 入口丢弃。如未来要更彻底修复（如 cancel token / 缩短陈旧 window），建议另开工单。
- **不动麦克风链路** —— mic 路径走 `_handle_mic_ai_reply`，且 `mic_in_flight` 槽位独立。工单不覆盖 mic。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| ISSUE-042 | `ConfigStore.set_api_key` 外层持 `_write_lock` 后在 base64 退化分支调用 `self.set()` 嵌套持非可重入 `threading.Lock` 死锁（W-CONC-001 引入）；`test_p1_key_encryption.py::test_warning_when_setting_api_key_without_crypto` 永久阻塞 | 是（[ISSUE-042-config_set_api_key_rlock_死锁.md](../已知问题记录/ISSUE-042-config_set_api_key_rlock_死锁.md) + [已知问题与后续事项.md](../../已知问题与后续事项.md) 末段） |

建议后续工单：W-RLOCK-001 —— `ConfigStore._write_lock` 改 `threading.RLock`，或 `set_api_key` 退化分支直接走 `conn.execute` 不再调用 `self.set`。

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/MAIN_PIPELINE.md](../../MAIN_PIPELINE.md) §4 + §8
- [x] [docs/已知问题与后续事项.md](../../已知问题与后续事项.md) 登记 ISSUE-042
- [x] [docs/工单列表/工单/W-RACE-001.md](../../工单列表/工单/W-RACE-001.md)
- [x] [docs/templates/Codex完成报告/W-RACE-001-完成报告.md](../Codex完成报告/W-RACE-001-完成报告.md)（本文件）
- [x] [docs/templates/已知问题记录/ISSUE-042-config_set_api_key_rlock_死锁.md](../已知问题记录/ISSUE-042-config_set_api_key_rlock_死锁.md)

## 10. 建议下一个工单

- **W-RLOCK-001**（强烈建议）：修复 ISSUE-042 —— `ConfigStore._write_lock` 改 `threading.RLock` 或 `set_api_key` 退化分支直接走 `conn.execute`；恢复 `test_p1_key_encryption.py` 全部用例。
- 可选：**W-CANCEL-001**：在 `AiRunnable`/`AiWorker` 引入 cancel token，让 `stop()` 后能主动中断进行中的 HTTP 流式请求，从源头消灭陈旧 reply（而非在主线程入口丢弃）。范围较大，需独立工单授权。
