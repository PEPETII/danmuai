# DanmuAI 周期性 Bug 审计报告

> **审计日期**：2026-07-14  
> **版本**：`app/version.py::__version__ = "0.3.9"`  
> **HEAD**：`8d4e925`（`main` 与 `origin/main` 对齐；工作区存在大量未提交改动，含 bililive_dm 移除等）  
> **审计环境**：Windows；本地 Python **3.14**（README/CI 推荐 **3.12**）  
> **执行方式**：源码走读 + 可复现 PoC + 分批 pytest（`-q -x`）+ `python scripts/boundary_guard.py`  
> **边界**：默认只审计、不改业务代码；I 节 Web 社区后端按 `docs/审查.md` **不做审查**；不上传、不改 R2/Supabase 线上状态。

---

## 1. 结论总览

| 严重度 | 数量 | 摘要 |
|--------|------|------|
| **P0** | 0（本轮新确认） | 未发现可证实的「无法启动 / 发布包内密钥 / 发布源全不可用」。**待负责人**：历史 Supabase anon 轮换（KNOWN-SUPABASE-ANON-ROTATE）仍开放，属发布前安全流程项。 |
| **P1** | 1 | **SQLite 同连接双写锁**（config / pool / history 共享 `conn`，独立 `_write_lock` 与 `_pool_write_lock`）可导致跨域 `rollback` 吞掉未提交配置写，出现「set 成功、DB 无行」假保存。 |
| **P2** | 6 | HistoryWriter commit 失败不 rollback → 重复写历史；弹幕库 insert/delete commit 无 rollback；`empty_parse` 永不计入失败退避；截图 stop 路径可能卡住 `_capture_in_flight`；Overlay paint 无 pixmap 预算；`history_writer` 单测与 except 契约漂移。 |
| **P3** | 3 | 发布元数据不记录 dirty；`ConfigStore.get()` close 后静默读缓存；Python 3.14 子进程 GBK 解码告警。 |

**主链路健康（本轮已确认）**：

- `boundary_guard.py` → **PASS**
- v2 已修复回归：`test_empty_parse_failure_backoff` / `test_capture_worker_failure_release` / `test_mic_prepend_queue_preservation` → **14 passed**
- `test_webview_shell_final_fallback` + `test_release_endpoint_content_validation` + `test_p1_log_sanitization` → **30 passed**
- `test_ai_pipeline` + `test_inflight_recovery` + `test_danmu_engine` → **50 passed**（附 Python 3.14 编码 warning，非失败）
- **失败**：`tests/test_history_writer.py::test_history_writer_logs_flush_failures`（见 BUG-014）

**A–J 勾选**

| 模块 | 状态 | 结论要点 |
|------|------|----------|
| A 启动与生命周期 | ✅ | 单实例重试、WebView finalize fallback 已存在；stop 与 capture in-flight 有残余缝隙（BUG-013） |
| B 弹幕主链路 | ✅ | `_pick_track` 满载 fallback 不再屏内 clamp；empty_parse 成本策略仍松（BUG-012） |
| C 模型与成本 | ✅ | AI 管家已 `apply_thinking_disabled`；empty 成功回调仍白烧 token |
| D 麦克风/读弹幕 | ✅ | mic prepend 已 `preserve_existing=None`；条数与 `normal_reply_count` 对齐 |
| E 桌宠 | ✅ | 定向历史修复保持；未做 GUI 真机拖动/全屏叠层验证 |
| F 配置/SQLite | ✅ | **P1 双锁仍开放**；HistoryWriter / pool commit 路径有数据完整性洞 |
| G 公式化/烂梗 | ✅ | diff setter 有 rollback；insert_many/delete 无对称 rollback |
| H 发布更新 | ✅ | Setup/Portable 有 MZ/ZIP magic 校验；发布脚本不拦 dirty 工作区 |
| I Web 社区 | ⏭ | 按审查说明不做 |
| J 测试验收 | ✅ | 分批 pytest + boundary_guard；1 个 history 单测失败 |

---

## 2. 已确认 Bug

### BUG-001：同一 SQLite 连接使用两把互不嵌套的写锁，跨域 rollback 可回滚未提交配置

- **严重等级**：P1  
- **影响功能**：配置保存、自定义弹幕库写、历史写并发时的数据一致性；可能出现 UI/cache「已保存」而 DB 丢失  
- **证据文件**：`app/config_store/storage.py`（`_write_lock` / `_pool_write_lock` / 单 `self.conn`）；`app/danmu_pool.py`（pool 路径 `rollback`）；`app/history_writer.py`（与 config 共享 `conn` + `_write_lock`）  
- **证据代码**：

```107:109:app/config_store/storage.py
        self._write_lock = threading.Lock()
        # 弹幕库写操作独立锁，与配置读写互不阻塞
        self._pool_write_lock = threading.Lock()
```

```318:337:app/config_store/storage.py
    def set(self, key: str, value: str):
        ...
        with self._write_lock:
            ...
                self.conn.execute("REPLACE INTO config ...")
                self.conn.commit()
                self._cache[key] = value
            except sqlite3.DatabaseError as e:
                self.conn.rollback()
```

- **复现路径（PoC，2026-07-14 本地复现）**：

```python
# 同连接：config 写入未 commit → 另一逻辑 rollback → config commit 后行丢失
conn.execute("REPLACE INTO config VALUES ('k','v')")  # in_transaction=True
conn.rollback()  # 模拟 pool 失败路径
conn.commit()
# SELECT * FROM config → []
```

实测输出：`config after commit []`，`pool after []`。

- **根因分析**：SQLite 事务归属 **connection**，不是 Python lock。两把锁只串行「各自临界区」，不隔离事务；任一路径 `rollback()` 会撤销同连接上所有未 commit 变更。  
- **最小修复建议**：  
  1. **推荐**：全库统一单一写锁（或 `with_write_lock` 覆盖 pool 写）；或  
  2. pool/history 使用独立 `sqlite3.connect`（同文件 + WAL）；并统一 `try/commit/except: rollback`。  
- **是否建议本次自动修复**：**否**（触及 ConfigStore / danmu_pool / HistoryWriter 并发契约，需单独工单与并发测试）  
- **需要补充的测试**：`tests/test_config_store_cross_domain_transactions.py`  
  - 断言：config 未 commit 期间 pool 失败 rollback **不得**抹掉 config 变更  
  - 断言：任一路径返回成功后 DB 与 cache 一致  

> 与台账 `BUG-V2-005` / `W-AUDIT-V2-BUG-005` 为同一根因；本轮重新 PoC 确认 **仍开放**。

---

### BUG-002：HistoryWriter commit 失败不 rollback，重试会重复插入历史

- **严重等级**：P2（数据完整性；用户可见「弹幕日记」重复）  
- **影响功能**：历史记录 flush、会话回放、统计关联行数  
- **证据文件**：`app/history_writer.py`  
- **证据代码**：

```95:109:app/history_writer.py
        try:
            with self.config.with_write_lock():
                self.config.conn.executemany(
                    "INSERT INTO history ...",
                    items,
                )
                self._maybe_prune_rows()
                self.config.conn.commit()
        except sqlite3.Error:
            _logger.exception("history flush failed items=%d, will retry on next flush", len(items))
            with self._lock:
                for item in reversed(items):
                    ...
                        self._buffer.appendleft(item)
```

- **复现路径（PoC，2026-07-14）**：

1. `enqueue('c1')` → flush 时 `commit` 抛 `OperationalError`  
2. 观察：`in_transaction after fail True`，buffer 回填 1  
3. `enqueue('c2')` → flush 成功  
4. 结果：`rows [('c1',), ('c1',), ('c2',)]`，**count=3**（首条重复）

- **根因分析**：`executemany` 已进入事务；commit 失败后未 `rollback`，事务仍 active；回填 buffer 导致下次 `executemany` 再次插入；随后 commit 一次提交「旧未提交 + 新插入」。  
- **最小修复建议**：`except` 内 `try: conn.rollback() except: ...`，再回填 buffer；rollback 失败则停止后续 flush 并告警。  
- **是否建议本次自动修复**：**是**（局部 5–15 行 + 单测，不改产品设计）  
- **需要补充的测试**：扩展 `tests/test_history_writer.py`  
  - commit 抛 `sqlite3.OperationalError` 后 `not conn.in_transaction`  
  - 第二次 flush 后 `COUNT(*) == 去重后的期望条数`（无重复）  

---

### BUG-003：自定义弹幕库 insert/delete 路径 commit 无 rollback，失败后事务可能残留

- **严重等级**：P2  
- **影响功能**：公式化弹幕库批量导入/删除；与 BUG-001 叠加时更危险  
- **证据文件**：`app/danmu_pool.py`  
- **证据代码**：

```505:515:app/danmu_pool.py
        if batch:
            ...
            store.conn.executemany("INSERT OR IGNORE INTO custom_danmu_pool_entries ...", batch)
            ...
            store.conn.commit()
```

```525:532:app/danmu_pool.py
        store.conn.execute(f"DELETE FROM custom_danmu_pool_entries WHERE id IN ...")
        ...
        store.conn.commit()
```

对比 diff setter 已有：

```712:718:app/danmu_pool.py
            store.conn.commit()
    except sqlite3.DatabaseError:
        try:
            store.conn.rollback()
        except sqlite3.Error:
            pass
```

- **复现路径**：对 `custom_danmu_insert_many_for_store` / `custom_danmu_delete_*` 在 `commit` 阶段注入 `sqlite3.OperationalError`；观察 `conn.in_transaction` 是否保持 True，下一次无关写是否带上半成品变更。  
- **根因分析**：insert/delete 与 diff setter 错误处理不对称；commit 失败后连接事务态未恢复。  
- **最小修复建议**：三处写路径统一 `try commit / except: rollback; raise|log`。  
- **是否建议本次自动修复**：**是**（与 BUG-002 同模式，宜同工单）  
- **需要补充的测试**：`tests/test_danmu_pool_commit_rollback.py`  

---

### BUG-004：`empty_parse` 不计入 `_consecutive_failures`，可持续白烧视觉 API

- **严重等级**：P2（成本 / 直播无弹幕体验；产品若定义为 soft-failure 可降为设计决策）  
- **影响功能**：模型返回空数组/不可解析内容时的失败退避与暂停  
- **证据文件**：`app/application/generation_pipeline.py`、`main.py`  
- **证据代码**：

```81:107:app/application/generation_pipeline.py
        if not normalized_items:
            ...
            app.logger.warning("... reason=empty_parse")
            app.record_undisplayed("empty_parse", persona_id=persona_id)
            return False
```

```784:785:main.py
        if enqueued:
            self._reset_failure_backoff_if_needed()
```

- **复现路径**：

```text
_consecutive_failures=0 → 投递空 normalize 的 AI 成功回调
→ failures 仍为 0，paused=False，下一 tick 继续截图+请求
```

本轮实测：`after empty failures 0 paused False`。  
（对照：BUG-V2-004 已修复「空结果错误复位退避」；**未**实现「空结果累加失败」。）

- **根因分析**：成功 HTTP + 空解析被当作 soft no-op；token 仍在 `_on_ai_reply` 入口记账。  
- **最小修复建议**：产品确认后二选一：  
  1. empty_parse 计入连续失败（达到阈值暂停）；或  
  2. 独立 empty 计数器 + 告警文案，避免与 401 致命路径混淆。  
- **是否建议本次自动修复**：**否**（需产品 soft-failure 策略）  
- **需要补充的测试**：`tests/test_empty_parse_failure_backoff.py` 增「从 0 连续 N 次 empty 后 paused」用例（策略确定后）  

---

### BUG-005：CaptureRunnable 在 stopping 时静默 return；`stop()` 不清理 `_capture_in_flight`

- **严重等级**：P2  
- **影响功能**：停止/重启后截图调度；极端时 `start()` 前逻辑依赖 in-flight 位会误判  
- **证据文件**：`app/runnable.py`、`app/main_lifecycle_mixin.py`、`main.py`  
- **证据代码**：

```46:57:app/runnable.py
    def run(self) -> None:
        if self._stopping.is_set():
            return
        try:
            pixmap = execute_capture(self._plan)
        except Exception as exc:
            self._coordinator.failed.emit(...)
            return
        if self._stopping.is_set():
            return
        self._coordinator.completed.emit(pixmap)
```

`stop()`（`main_lifecycle_mixin.py` ~619–662）设置 `mark_stopping`、清 `ai_in_flight`，**无** `_capture_in_flight = False`。仅 `start()` 与 completed/failed 槽会清零。

- **复现路径**：

1. PoC：`stopping.set()` 后 `CaptureRunnable.run()` → `emits == []`  
2. 将 `_capture_in_flight=True` 后调用 `stop()` 路径：位仍为 True（本轮最小 app 上观察到 `after stop capture_in_flight True`）  
3. `start()` 会复位（缓解），但 stop 期间/非 start 路径若读该位会误判 busy  

- **根因分析**：BUG-V2-002 补了异常 `failed` 信号，未覆盖「stopping 早退」与 stop 对称清理。  
- **最小修复建议**：stopping 早退改为 `failed.emit("capture_aborted_stopping")` 或 stop() 显式 `_capture_in_flight=False`。  
- **是否建议本次自动修复**：**是**（小范围）  
- **需要补充的测试**：`tests/test_capture_worker_failure_release.py` 增加 stopping 早退释放用例  

---

### BUG-006：Overlay `paintEvent` 对缺失 pixmap 同步 `prepare_item_pixmap`，无每帧预算

- **严重等级**：P2（性能/掉帧）  
- **影响功能**：场景切换后大量弹幕同时进入可视区时的主线程帧时间  
- **证据文件**：`app/overlay.py`  
- **证据代码**：

```654:659:app/overlay.py
        for track in self.engine.tracks:
            for item in track.items:
                if not self._item_in_paint_band(item):
                    continue
                if item._pixmap is None:
                    self.prepare_item_pixmap(item)
```

- **复现路径**：构造多轨道、多条目且 `_pixmap is None` 的引擎状态，单次 `paintEvent` 统计同步 `prepare_item_pixmap` 调用次数与 wall ms（真机 Profiler 更佳）。  
- **根因分析**：预渲染兜底放在 paint 热路径，无每帧数量/时间片上限。  
- **最小修复建议**：每帧最多 N 个（如 2）同步渲染，其余 `update()` 下一帧；与 `KNOWN-BUG-B-001-OVERLAY-PAINT-PIXMAP-BUDGET` 一致。  
- **是否建议本次自动修复**：**否**（需帧率手验）  
- **需要补充的测试**：单元级断言 paint 路径调用 `prepare` 次数 ≤ budget（mock）  

---

### BUG-007：`test_history_writer_logs_flush_failures` 用 `RuntimeError`，生产只捕 `sqlite3.Error` → 单测失败

- **严重等级**：P2（测试可信度 / CI 门禁噪声）  
- **影响功能**：历史写失败日志回归测试  
- **证据文件**：`tests/test_history_writer.py`、`app/history_writer.py`  
- **证据代码**：测试侧 `config.conn.executemany.side_effect = RuntimeError("db locked")`；生产 `except sqlite3.Error`。  
- **复现路径**：

```powershell
python -m pytest tests/test_history_writer.py::test_history_writer_logs_flush_failures -q -x
```

实测（2026-07-14，Python 3.14）：`RuntimeError: db locked` 未被捕获，用例 **FAILED**。

- **根因分析**：测试契约与实现 except 类型不一致。  
- **最小修复建议**：测试改为 `sqlite3.OperationalError`；或实现捕获更广异常（需评估）。优先改测试以匹配「仅 SQLite 错误可恢复」设计。  
- **是否建议本次自动修复**：**是**  
- **需要补充的测试**：修复后原用例通过；并加 commit 阶段 `OperationalError` 用例（并入 BUG-002）  

---

## 3. 高风险但未确认问题

| ID | 现象与本地事实 | 证明缺口 | 建议确认方式 |
|----|----------------|----------|--------------|
| RISK-001 | 工作区高度 dirty（bililive 移除等），`publish` 仅记 `git rev-parse`，不记 dirty | 脏树打包产物是否与 tag 0.3.9 行为一致 | 干净 commit 上跑 `publish_windows_release.ps1 -DryRun` + frozen smoke |
| RISK-002 | Overlay 置顶/全屏游戏内遮挡依赖 Win32 exstyle + 真机驱动 | 独占全屏、多 DPI、竖屏 | 真机矩阵（KNOWN RISK-V2-006） |
| RISK-003 | 麦克风无独立 inflight 看门狗（仅视觉 45s/48s） | 卡死 mic 槽是否可被视觉恢复间接覆盖 | 注入挂起 mic 请求 60s+ 观察 |
| RISK-004 | `project-prompts/` 整目录 gitignore；本地 `genetic_pareto_optimizer.py` 仍含明文 `API_KEY` | 是否曾入库、是否已在供应商侧吊销 | `git log --all -- project-prompts`；负责人轮换（KNOWN-PROMPT-OPTIMIZER-CREDENTIAL-001） |
| RISK-005 | 历史 Supabase anon 曾入 git（KNOWN-SUPABASE-ANON-ROTATE） | Dashboard 是否已轮换 | 负责人控制台确认 |
| RISK-006 | 裸 JWT（无 `Authorization`/`api_key=` 上下文）`sanitize_log_message` 不脱敏 | 生产错误串是否会出现裸 JWT | 对真实 provider 400 body 抽样 |
| RISK-007 | Python 3.14 跑测出现子进程 GBK `UnicodeDecodeError` warning | 3.12 CI 是否复现、是否影响 frozen | 在 3.12 复跑同批 |

---

## 4. 性能与卡顿风险

| 区域 | 风险 | 证据/说明 |
|------|------|-----------|
| 启动 | 中 | pywebview 握手超时走 browser fallback（已修短路）；WebView2 冷启动文档允许 ~25s |
| 截图 | 低–中 | worker 异常已释放 in-flight；stopping 早退仍有缝隙（BUG-005） |
| Overlay 渲染 | 中 | paint 内同步 pixmap（BUG-006） |
| 轨道 | 低 | `_pick_track` 加权随机 + 满载 tail 排队，无屏内错误 clamp |
| SQLite | 高 | 双锁 + 不对称 rollback（BUG-001/002/003） |
| 自定义弹幕库 2 万 | 中 | 分页迭代已有；`set_custom_danmu_pool` 仍全表 `SELECT text ... LIMIT 20000` 一次载入做 diff |
| 外部接口/烂梗 | 低–中 | teardown 先 `wait_all_worker_pools_done` 再 `close_meme_client`（BUG-G-008 已修） |
| 模型请求 | 中 | empty_parse 白烧（BUG-004）；视觉看门狗 45/48s 在位 |

---

## 5. 兼容性与环境风险

- **Windows / 会话**：单实例 server 名含 `USERNAME|APPDATA|session_id`，多会话隔离合理；竞态仍有 3×500ms 重试。  
- **PowerShell / UTF-8**：审计与脚本应 `-Encoding UTF8`；本地 3.14 子进程默认编码 warning 提示开发机与 CI 3.12 差异。  
- **中文路径**：未做专项注入；ConfigStore 使用 APPDATA，通常 ASCII 安全，中文用户名路径待手验。  
- **显卡/层级**：Overlay `Tool | TopMost` + `WS_EX_LAYERED|TRANSPARENT` 需真机全屏确认（RISK-002）。

---

## 6. 发布与更新风险

| 项 | 状态 | 说明 |
|----|------|------|
| 主入口 | Setup.exe + Portable.zip（MSI 非当前主链） | 见 `docs/operations/PACKAGING_WINDOWS.md` |
| Feed | R2 `releases/win/stable` | 本轮**未**做线上 HTTP 探活 |
| 内容校验 | Setup MZ / Portable ZIP magic | `scripts/check_release_endpoints.ps1` 已有；相关单测 30p 中含 content validation |
| 版本 | `0.3.9` | 与 `app/version.py` 一致 |
| Dirty 构建 | **风险** | `publish_windows_release.ps1` 只写 `Git: $shortSha`，无 porcelain/dirty 后缀（BUG-V2-012 仍开放） |
| 用户数据 | 设计保留 `%APPDATA%/DanmuAI` | 本轮未做安装/卸载真机 |
| 签名 | 默认关 | SmartScreen 风险仍在 |
| 锁文件 | `requirements-release-win-lock.txt` 可选 | 未设 `DANMU_BUILD_USE_RELEASE_LOCK=1` 时仍用范围依赖 |
| 当前工作区 | **不建议直接发布** | bililive 移除等大量未提交变更；应先干净提交 + DryRun + frozen smoke |

---

## 7. 安全与隐私风险

| 项 | 等级 | 说明 |
|----|------|------|
| 打包 supabase-config | 已加固 | `DanmuAI.spec` default-deny 含 `supabase-config` 变体 |
| API key 日志 | 基本 OK | `sk-` / `Authorization Bearer` / `api_key=` 可脱敏；**裸 JWT 仍可能泄漏**（RISK-006） |
| 诊断 SSE | 改善 | `diagnostics.js` 注释标明改用 fetch + Bearer header（非 query token） |
| 历史 anon JWT | P0 流程 | KNOWN-SUPABASE-ANON-ROTATE 待负责人轮换 |
| 本地优化脚本密钥 | 本地 | `project-prompts/` gitignore；磁盘仍可能有明文 key，勿提交、应轮换 |
| Web 控制台 | loopback + Bearer | 本机任意进程仍可在已知 token 时调用；属本机信任模型 |

**I 节社区 Worker/Supabase RLS**：本轮按任务说明跳过。

---

## 8. 建议新增的测试

| 测试文件 | 目标 | 关键断言 |
|----------|------|----------|
| `tests/test_config_store_cross_domain_transactions.py` | 双锁事务隔离 | pool rollback 后未 commit 的 config 行不得消失；成功 set 后 DB==cache |
| `tests/test_history_writer.py`（扩展） | commit 失败 rollback | `not in_transaction`；二次 flush 无重复 content |
| `tests/test_danmu_pool_commit_rollback.py` | insert/delete 对称 rollback | commit 失败后连接可继续写且无半成品 |
| `tests/test_capture_worker_failure_release.py`（扩展） | stopping 早退 | `_capture_in_flight is False` 且可再次 schedule |
| `tests/test_empty_parse_failure_backoff.py`（扩展） | 成本策略（待产品） | 连续 empty N 次 → paused 或独立计数告警 |
| `tests/test_publish_metadata_dirty.py` | 发布元数据 | dirty 树时 VERSION 含 `-dirty` 或 DryRun 拒绝 |

---

## 9. 本次可自动修复项

满足「证据充分 / 范围小 / 不改产品设计 / 可补测」：

1. **BUG-002** HistoryWriter：`except` 内 `rollback` 后再回填  
2. **BUG-003** danmu_pool insert/delete：对称 `rollback`  
3. **BUG-005** `stop()` 清 `_capture_in_flight` 或 stopping 发 `failed`  
4. **BUG-007** 单测 side_effect 改为 `sqlite3.OperationalError`  

**本次不建议自动修复**：BUG-001（架构级锁/连接）、BUG-004（产品策略）、BUG-006（需帧率手验）、发布 dirty 策略（流程决策）。

**本轮实际未改代码**（审计默认边界）。

---

## 10. 最终建议（Top 3）

1. **P1 — 统一 SQLite 写事务边界（BUG-001 / V2-005）**  
   理由：可导致配置「假保存」与跨域数据丢失，影响核心可信度；应先定方案（单锁 vs 多连接）再实现，并加交叉事务测试。  

2. **P2 — 历史/弹幕库 commit 失败 rollback 批（BUG-002/003/007）**  
   理由：PoC 已证 HistoryWriter 重复插入；修复局部、可测、可与失败单测一并收口，性价比高。  

3. **发布前冻结 — 干净工作区 + DryRun + 线上探活**  
   理由：当前树含 bililive 移除等未提交变更；在未冻结源码快照前不应上传 R2/GitHub。同时推进 Supabase anon 轮换确认（流程 P0）。

---

## 附录 A. 本轮命令与结果

| 命令 | 结果 |
|------|------|
| `python scripts/boundary_guard.py` | PASS |
| `pytest tests/test_empty_parse_failure_backoff.py tests/test_capture_worker_failure_release.py tests/test_mic_prepend_queue_preservation.py -q -x` | **14 passed** |
| `pytest tests/test_webview_shell_final_fallback.py tests/test_release_endpoint_content_validation.py tests/test_p1_log_sanitization.py -q -x` | **30 passed** |
| `pytest tests/test_ai_pipeline.py tests/test_inflight_recovery.py tests/test_danmu_engine.py -q -x` | **50 passed**（20 encoding warnings） |
| `pytest tests/test_history_writer.py::test_history_writer_logs_flush_failures -q -x` | **FAILED** `RuntimeError: db locked` |
| HistoryWriter PoC | `rows=[c1,c1,c2]` 重复确认 |
| SQLite dual-lock PoC | config 行被 rollback 清空确认 |
| Capture stopping PoC | `emits=[]` 确认 |

---

## 附录 B. 相对 2026-07-12 v2 审计的状态同步

| v2 ID | 本轮状态 |
|-------|----------|
| BUG-V2-001 WebView fallback | 代码含 `allow_failed_state_fallback`；相关单测通过 → **已修** |
| BUG-V2-002 capture failed | `failed.emit` + 主线程槽；单测通过 → **已修** |
| BUG-V2-003 mic prepend | `preserve_existing=None`；单测通过 → **已修** |
| BUG-V2-004 empty 复位退避 | 仅 `enqueued` 时 reset；单测通过 → **部分**（累加失败仍开放=本轮 BUG-004） |
| BUG-V2-005 双锁 | **仍开放** = BUG-001 |
| BUG-V2-006/007 pool/history rollback | **仍开放** = BUG-002/003 |
| BUG-V2-008 Token 脱敏 | Authorization/api_key 路径 OK；裸 JWT 残余 = RISK-006 |
| BUG-V2-010 发布内容校验 | magic 校验 + 单测通过 → **已修** |
| BUG-V2-012 dirty 元数据 | **仍开放** |
| bililive 桥接无鉴权等 | 模块已删除（工作区进行中）→ 不再适用 |

---

## 附录 C. 自检评分

| 维度 | 分（0–2） | 说明 |
|------|-----------|------|
| 证据完整性 | 2 | 文件路径 + 代码 + PoC/测试命令 |
| 严重度判定 | 2 | P1 仅数据一致性假保存；无夸大无法启动 |
| 已确认 vs 待确认 | 2 | §2 / §3 分离 |
| 发布更新链路 | 2 | §6 覆盖 spec/Velopack/dirty/签名/锁文件 |
| 可执行测试建议 | 2 | §8 文件名 + 断言 |
| **总分** | **10** | ≥7，可输出 |

---

*报告结束。修复请按工单驱动（AGENTS.md），勿在无工单授权下做架构级改动。*
