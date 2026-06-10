# Codex 完成报告

> 工单 ID：W-CONC-001
> 完成时间：2026-06-08
> 执行者：Codex

---

## 1. 修改摘要

修复 [bug-03 缺陷 2](../../bug-audit/bug-audit/bug-03.md)：`HistoryWriter` 后台线程 `flush()` 此前直接 `self.config.conn.executemany(...) + commit()`，绕开 `ConfigStore._write_lock`。当主线程持锁做 `set`/`set_batch` 时，WAL 写者互斥 + `PRAGMA busy_timeout=5000` 可能不足以覆盖截图/API 延宕，导致 `OperationalError('database is locked')` 后**整批**弹幕历史永久丢失。

修复方案：`ConfigStore` 暴露 `@contextmanager with_write_lock()` 上下文管理器，与 `set`/`set_batch` 共享同一把 `_write_lock`；`HistoryWriter.flush()` 在临界区内 `executemany + commit`，避免主线程持锁时抛 `database is locked`。普通 SET 仍走 `set`/`set_batch`；`with_write_lock` 限制同包模块（`HistoryWriter` 等）使用，禁止 HTTP 线程 / Web 路由 / 其他包模块直接调用。

新增 4 个并发/契约 pytest 用例覆盖：(1) 主线程持锁时后台 `flush` 阻塞等待且**不**抛 `OperationalError`；(2) `flush` 走 `with_write_lock` 上下文而非裸 `executemany`（防止退步）；(3) `with_write_lock` 产出 `self.conn` 且释放后可重入；(4) `with_write_lock` 与 `set` 互斥。

## 2. 修改的文件

- `app/config_store.py`（`from contextlib import contextmanager` import + `ConfigStore.with_write_lock()` 新增方法）
- `app/history_writer.py`（顶部 docstring 注释 + `flush()` 改用 `with self.config.with_write_lock():` 包裹 `executemany + commit`）
- `tests/test_history_writer.py`（既有 `test_history_writer_logs_flush_failures` 保留；新增 `test_history_writer_waits_for_config_store_write_lock` 与 `test_history_writer_does_not_call_executemany_without_lock`）
- `tests/test_config_store.py`（新增 `test_with_write_lock_yields_conn_and_releases` 与 `test_with_write_lock_blocks_other_writer`）
- `docs/CONTRIBUTING_ARCHITECTURE.md`（§8「存储边界」追加「写入临界区（W-CONC-001）」一段）
- `docs/工单列表/工单/W-CONC-001.md`（工单正文）
- `docs/当前仓库状态.md`（顶部「最近变更」插入 W-CONC-001 段，更新「最后更新」日期）
- `docs/工单列表.md`（工单登记表追加 W-CONC-001 行，更新「最后更新」日期）

## 3. 未修改的关键区域

- 未修改 `main.py`：是
- 未修改 `app/main_*mixin.py`：是（`HistoryWriter(self.config)` 实例化不变）
- 未修改 `app/ai_client.py`、`app/danmu_engine.py`、`app/overlay.py`：是
- 未修改 `app/web_api/*`、`app/personae.py`、`app/persona_contract.py`：是
- 未修改 `web/static/*`：是
- 未修改 `requirements.txt`、锁文件、CI、打包配置：是
- 未修改 `ConfigStore.set` / `set_batch` / `set_api_key` / `meme_barrage_library_*` 既有持锁路径：是
- 未修改 `Boundary Guard` 规则实现：是

## 4. 运行的命令

```bash
# 定向
E:\test\danmu\.venv-build\Scripts\python.exe -m pytest tests/test_history_writer.py tests/test_config_store.py -q

# 架构回归
E:\test\danmu\.venv-build\Scripts\python.exe scripts/boundary_guard.py

# 全量
E:\test\danmu\.venv-build\Scripts\python.exe -m pytest tests/ -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 定向 pytest | 通过 | 18 passed（既有 14 + 新增 4） |
| boundary_guard | 通过 | PASS |
| 全量 pytest | 通过 | 见下方统计 |

全量 pytest：基线 1053 passed, 5 skipped → 本工单新增 4 个用例，**全量通过**（最终统计见对话末尾回报）。

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1. 定向 pytest | 18 passed | 通过 | 是 |
| 2. boundary_guard | PASS | PASS | 是 |
| 3. 全量 pytest | 不退步 | 不退步（数字见末尾回报） | 是 |

详细功能验证需在真实运行环境中进行（主线程 set + 后台 flush 真实持锁场景），本工单以自动化并发测试覆盖。

### §6.2 固定原文

> 已检查限制 / 边界入口文件、AGENTS.md、README.md 和相关项目说明文件，本次无需更新。

## 7. 风险与注意事项

- `with_write_lock()` 是**进程内**临界区（`threading.Lock`），不跨进程；多实例仍受 `SingleInstanceGuard` 串行化，与修复前一致。
- `threading.Lock` 不可重入：同线程内嵌套 `with with_write_lock():` 会死锁（本工单 flush 与 set 路径不相交，无实际风险）。
- 公开 `with_write_lock` 后必须限制同包使用；docstring 已明确「仅供同包模块在 SQLite 写入临界区使用；HTTP 线程 / Web 路由 / 其他包模块不得直接调用」；`docs/CONTRIBUTING_ARCHITECTURE.md` §8 已添加「写入临界区（W-CONC-001）」段落作为架构边界。
- 主线程 `set` 持锁窗口仅 `executemany + commit`（微秒级）；后台 `flush` 在主线程持锁时**会**阻塞，但阻塞时长仍受主线程 SET 操作时长约束。
- `tests/test_history_writer.py` 既有 `test_history_writer_logs_flush_failures` 用 `MagicMock` 模拟 `config`；`MagicMock.with_write_lock()` 自动成为可调用 mock，进入 `with` 块时返回新的 `MagicMock` 上下文（`__enter__` / `__exit__`）—— 故既有用例**不**依赖 `with_write_lock` 真实存在，迁移成本为零。
- `tests/test_history_writer_does_not_call_executemany_without_lock` 用 stub 校验：在 `with_write_lock` 临界区外调用 `executemany` / `commit` 会直接 `assert` 失败，强制保证未来维护者不能悄悄退步为裸 `executemany`。

## 8. 发现但未处理的问题

无（本工单仅修复 bug-03 缺陷 2；缺陷 1 `/api/session` 鉴权由 W-SEC-001 修复，缺陷 3 陈旧 `AiRunnable` 未在本工单范围）。

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)（顶部「最近变更」插入 W-CONC-001 段；「最后更新」改为 `2026-06-08（W-CONC-001）`）
- [x] [docs/工单列表.md](../../工单列表.md)（工单登记表追加 W-CONC-001 行；「最后更新」改为 `2026-06-08（W-CONC-001）`）
- [x] [docs/CONTRIBUTING_ARCHITECTURE.md](../../CONTRIBUTING_ARCHITECTURE.md)（§8 追加「写入临界区（W-CONC-001）」段落）
- [x] [docs/工单列表/工单/W-CONC-001.md](../../工单列表/工单/W-CONC-001.md)（本工单正文）
- [x] [docs/templates/Codex完成报告/W-CONC-001-完成报告.md](../../templates/Codex完成报告/W-CONC-001-完成报告.md)（本完成报告）

## 10. 建议下一个工单

- bug-03 缺陷 3：stop() 后陈旧 `AiRunnable` 污染新会话的 in-flight 槽位（已登记在 bug-03.md，建议立项为独立 W-CONC-002 或 W-AI-RUNNABLE-LIFECYCLE-001）。
- `with_write_lock` 公开后，未来若 `personae.py` / `templates.py` / `font_registry.py` / 烂梗采集等子模块也走同一连接批量写入，应直接复用 `with_write_lock`，避免再次出现「同 SQLite 连接多线程写入」的退步。
- 后续可在 Boundary Guard 增加规则：检测 `config.conn.executemany` / `config.conn.execute(...)` 出现在 `with self._write_lock:` 块外（在白名单 `config_store.py` / `history_writer.py` 之外）。
