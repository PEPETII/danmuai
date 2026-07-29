# Bug 审计待确认问题验证报告（2026-07-01）

> **历史验证快照**：本文件只回答 W-BUG-AUDIT-0701-001 当时列出的 5 个待确认项，不是当前问题台账。若源码或线程边界已变化，应重新验证；现行台账见 [.local-ai/workorders/已知问题与后续事项.md](../.local-ai/workorders/已知问题与后续事项.md)。
>
> 来源：W-BUG-AUDIT-0701-001 §5「可疑但未确认的问题」
> 验证方式：代码路径静态分析 + 线程模型追踪
> 验证人：Codex Agent
> 日期：2026-07-01

---

## 5.1 `_meme_barrage_api_client` 是否真的在 quit 时泄漏

### 结论：已排除（非泄漏，但存在并发关闭风险）

### 证据

**调用链完整性**（已确认完整）：
1. `main_lifecycle_mixin.py:667-679` `quit()` → `close_meme_barrage_client()`
2. `main_meme_mixin.py:47-52` `close_meme_barrage_client()` 调用 `client.close()` 并置 `_meme_barrage_api_client = None`
3. `app/meme_barrage/client.py:74-77` `close()` 调用 `_client.close()` 并置 `_client = None`

**引用路径审计**：
- `MemeBarrageApiClient` 的唯一持有者是 `DanmuApp`（通过 `_meme_barrage_api_client`）
- `MemeFetchRunnable` 可能持有 `client` 引用（通过构造函数传入的 `self._client`）
- `MemeFetchRunnable` 的 `run()` 中：`client = self._client if self._client is not None else MemeBarrageApiClient()`

**风险分析**：
- 如果 `waitForDone(2000)` 超时，有在途 `MemeFetchRunnable` 仍在运行并持有 client 引用，此时 `close_meme_barrage_client()` 会关闭 client，但 runnable 可能仍在使用它。这可能导致 `RuntimeError`（使用已关闭的 httpx client），**但不是资源泄漏**。
- 当最后一个引用消失后，httpx client 的底层连接池会被 Python GC 回收。

### 判定

- **泄漏**：否。调用链完整，client 会被关闭且引用被清除。
- **并发风险**：低概率。waitForDone 超时后关闭 client，在途 runnable 可能遇到已关闭 client 异常。

---

## 5.2 `ai_worker_pool`/`meme_ai_pool` 退出时在途 runnable 访问已关闭 SQLite

### 结论：已确认（存在 race condition）

### 证据

**退出时序**（`main_lifecycle_mixin.py:598-768`）：
1. `stop()` → `ai_worker.mark_stopping()` + 停止 meme 定时器
2. `quit()` → `waitForDone(2000)` 等待 `capture_worker_pool`、`ai_worker_pool`、`meme_ai_pool`、`globalInstance`
3. `quit()` → 停止 web console
4. `quit()` → `self.ai_worker.close()`
5. `quit()` → `self.config.close()`（`app/config_store.py:1126-1132`）
6. `quit()` → `QApplication.quit()`

**关键缺失**：`quit()` **未等待 `meme_fetch_pool`**（`app/meme_barrage/runnable.py:23-29`）。

**MemeFetchRunnable 线程模型**（`app/meme_barrage/runnable.py:41-77`）：
- `run()` **无 stopping 标志检查**
- `on_success` / `on_error` 通过 `_MemeBarrageBridge` 的 Qt 信号（`fetch_done` / `fetch_failed`）回到主线程
- `_on_meme_fetch_success()`（`main_meme_mixin.py:209-214`）调用 `service.apply_remote_page(data)` → `store.insert_many()` → `config.meme_barrage_library_insert_many()`（访问 SQLite）

**Race condition 路径**：
1. 用户点击退出
2. `stop()` 停止 meme 定时器（不再启动新的 fetch）
3. `waitForDone` 不等待 `meme_fetch_pool`
4. 在途 `MemeFetchRunnable` 继续运行 HTTP 请求
5. `config.close()` 关闭 SQLite 连接
6. `MemeFetchRunnable` HTTP 请求完成，emit `fetch_done`（跨线程 `QueuedConnection`）
7. 主线程事件循环在 `QApplication.quit()` 之前处理排队的 `fetch_done` 槽
8. `_on_meme_fetch_success` 调用 `config.meme_barrage_library_insert_many()` → `sqlite3.ProgrammingError`

### 判定

- **存在 bug**：是。`meme_fetch_pool` 未被 `quit()` 等待，在途 fetch runnable 可能在 `config.close()` 后通过 Qt 信号回调访问已关闭 SQLite。
- **触发概率**：中。取决于退出时是否有在途烂梗采集请求（HTTP 请求耗时通常 1-3 秒）。
- **建议修复**：在 `quit()` 中添加 `meme_fetch_pool().waitForDone(2000)`，或在 `MemeFetchRunnable.run()` 中添加 stopping 标志检查。

---

## 5.3 `danmu_engine_dedup` 全局是否真的被多线程访问

### 结论：已排除（当前安全，所有调用均在主线程）

### 证据

**调用路径追踪**：

| 调用点 | 调用者 | 线程 |
|--------|--------|------|
| `app/danmu_engine.py:1107` `is_duplicate_in_recent()` | `DanmuEngine._is_duplicate()` | 主线程（`_consume_reply_queue` 定时器回调） |
| `app/floating_panel_engine.py:217` `is_duplicate_in_recent()` | `FloatingPanelEngine.is_duplicate()` | 主线程（`_consume_reply_queue` 或 `add_danmu_text`） |
| `app/danmu_engine_dedup.py:152-153` `_dedup_profile_stats` 增量 | `similarity()` | 主线程（由上述调用者同步调用） |
| `app/danmu_engine_dedup.py:198-204` `_last_duplicate_observation.update()` | `is_duplicate_in_recent()` | 主线程 |

**线程归属确认**：
- `_consume_reply_queue` 明确标注「调用线程：主线程」（`main.py:754`）
- `FloatingPanelOverlay._tick()` 是 `QTimer` 回调，在主线程
- `FloatingPanelOverlay.add_danmu_text()` 被 `_display_floating_panel_text()` 调用，后者被 `_consume_reply_queue()` 调用

### 判定

- **多线程访问**：否。所有 `is_duplicate_in_recent()` 调用路径最终都在 Qt 主线程。
- **当前安全**：是。`_dedup_profile_stats` 和 `_last_duplicate_observation` 当前无 race condition。
- **未来风险**：若未来在非主线程调用 `is_duplicate_in_recent()` 或 `similarity()`，会出现 race。建议保持当前设计约束（仅限主线程调用）。

---

## 5.4 `single_instance` 激活失败重试 2 次 `time.sleep(0.5)` 是否合理

### 结论：已排除（当前实现合理）

### 证据

**`ACTIVATION_FAILED` 触发条件**（`app/single_instance.py:62-75`）：
1. 第一次 `_activate_existing_instance()` 失败（无法连接已有实例）
2. `_listen_primary()` 失败（无法成为主实例，server name 被占用且 `removeServer` 也失败）
3. 第二次 `_activate_existing_instance()` 失败

**竞态窗口分析**：
- `ACTIVATION_FAILED` 最可能的场景：原实例正在启动，`QLocalServer` 尚未注册，新进程第一次连接失败，`_listen_primary` 也失败（server name 可能被"死锁"占用）。
- `QLocalServer.listen()` 注册通常 < 100ms，但 Qt 事件循环调度可能引入额外延迟。
- 1 秒总重试时间（2 次 × 500ms）覆盖了常见竞态窗口。

**语义分析**：
- 当前实现不区分「原实例启动中」vs「连接被拒绝」，统一重试。
- 重试后仍失败则 `sys.exit(2)`，阻止双实例启动。

### 判定

- **重试时间合理性**：是。1 秒总重试时间足以覆盖 `QLocalServer` 注册的常见竞态窗口。
- **语义优化空间**：可优化（区分具体失败原因），但当前实现功能正确。
- **建议**：维持当前实现。如需优化，可细化 `ACTIVATION_FAILED` 的子原因（连接超时 vs 连接被拒绝 vs server 名死锁）。

---

## 5.5 `web_console._prepare_stdio_for_uvicorn` devnull 句柄泄漏

### 结论：已排除（有意为之的正常行为，不构成泄漏）

### 证据

**代码意图**（`app/web_console.py:107-120`）：
```python
def _prepare_stdio_for_uvicorn() -> None:
    """PyInstaller windowed exe (console=False) has stderr=None; uvicorn logging breaks."""
    if sys.stderr is not None and sys.stdout is not None:
        return
    try:
        sink = open(os.devnull, "w", encoding="utf-8")
    except OSError:
        import io
        sink = io.StringIO()
    if sys.stderr is None:
        sys.stderr = sink
    if sys.stdout is None:
        sys.stdout = sys.stderr
```

**调用上下文**（`app/web_console_runtime.py:252-255`）：
- 仅在 `is_frozen() or sys.stderr is None` 时调用
- 目的是为 PyInstaller windowed exe（无控制台）提供可用的 stderr/stdout，否则 uvicorn logging 会崩溃

**进程模型**：
- uvicorn 在 `WebConsoleServer._run()` 的独立线程中运行，**不创建子进程**
- pywebview 桌面壳由 `app/webview_shell.py` 创建子进程，但子进程通过 `multiprocessing` 启动，会继承父进程句柄
- 但 `os.devnull`（Windows 下为 `NUL` 设备）是操作系统特殊设备文件，**不会因为未关闭而泄漏资源**

**句柄生命周期**：
- `sink` 被赋值给 `sys.stderr`/`sys.stdout`，由 Python 进程持有
- 进程退出时，操作系统会自动关闭所有句柄
- Windows 下 `NUL` 设备不占用实际文件句柄资源（内核特殊处理）

### 判定

- **句柄泄漏**：否。`sink` 被赋值给 `sys.stderr`/`sys.stdout` 是有意为之的正常行为。
- **子进程继承**：即使 pywebview 子进程继承了该句柄，进程退出时操作系统会回收，不构成泄漏。
- **建议**：维持当前实现，无需修改。

---

## 汇总

| 问题 | 结论 | 严重等级 | 建议 |
|------|------|----------|------|
| 5.1 meme client 泄漏 | 已排除 | 低 | 维持当前实现；如有需要可在 `waitForDone` 超时后延迟关闭 client |
| 5.2 退出时访问已关闭 SQLite | **已确认** | **中** | **建议修复**：在 `quit()` 中添加 `meme_fetch_pool().waitForDone(2000)` |
| 5.3 dedup 全局多线程访问 | 已排除 | 低 | 维持当前实现；保持主线程调用约束 |
| 5.4 single_instance 重试时间 | 已排除 | 低 | 维持当前实现 |
| 5.5 devnull 句柄泄漏 | 已排除 | 低 | 维持当前实现 |

---

## 已确认 bug 详情

**问题 ID**：ISSUE-072（新增）
**标题**：`quit()` 未等待 `meme_fetch_pool`，在途 MemeFetchRunnable 可能在 `config.close()` 后访问已关闭 SQLite
**严重等级**：中
**影响功能**：应用退出稳定性
**证据文件**：
- `app/main_lifecycle_mixin.py:690-722`（`quit()` 等待 pools，缺失 `meme_fetch_pool`）
- `app/meme_barrage/runnable.py:41-77`（`MemeFetchRunnable` 无 stopping 检查）
- `app/meme_barrage/store.py:14-41`（`MemeBarrageStore` 访问 `ConfigStore`）
**根因分析**：`quit()` 等待了 `ai_worker_pool`、`meme_ai_pool`、`capture_worker_pool`、`globalInstance`，但遗漏了 `meme_fetch_pool`（独立 `QThreadPool`，用于烂梗远程采集）。在途 `MemeFetchRunnable` 的 HTTP 请求可能跨越 `config.close()`，其 `on_success` 回调通过 Qt 信号回到主线程，触发 SQLite 访问。
**最小修复建议**：在 `main_lifecycle_mixin.py:quit()` 的 pool 等待段添加 `meme_fetch_pool().waitForDone(2000)`。
**需要补充的测试**：`test_quit_waits_meme_fetch_pool` — 模拟在途 fetch，验证 quit 时不会触发 `ProgrammingError`。
