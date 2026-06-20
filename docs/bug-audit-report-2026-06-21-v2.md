# DanmuAI 周期性 Bug 审计报告（v2）

## 1. 本次审计范围

- 当前分支：`main`
- 当前 commit：`32ee87a`（feat: update core modules, pet system, meme barrage, tests and build scripts）
- 版本号：`0.3.4`
- 检查时间：2026-06-21
- 已读取的关键文件：
  - `main.py` — 入口与 DanmuApp 定义
  - `app/main_lifecycle_mixin.py` — 启动/停止/退出生命周期
  - `app/main_launch.py` — 启动辅助
  - `app/single_instance.py` — 单实例守卫
  - `app/web_console.py` — Web 控制台服务器
  - `app/overlay.py` — Qt 透明置顶弹幕渲染
  - `app/danmu_engine.py` — 弹幕引擎（轨道、去重、加速）
  - `app/danmu_engine_dedup.py` — 去重逻辑
  - `app/reply_parser.py` — AI 回复解析
  - `app/reply_queue.py` — AI 回复 FIFO 缓冲
  - `app/ai_client.py` — AI 请求客户端
  - `app/ai_client_requests.py` — AI 请求构建与流式解析
  - `app/config_store.py` — SQLite 配置存储
  - `app/danmu_pool.py` — 公式化弹幕库
  - `app/version_compare.py` — 版本比较
  - `app/update_service.py` — Velopack 更新服务
  - `app/velopack_runtime.py` — Velopack 启动钩子
  - `app/uninstall_service.py` — 卸载服务
  - `app/supabase_config.py` — Supabase 凭据
  - `DanmuAI.spec` — PyInstaller 打包配置
  - `app/version.py` — 版本号
- 已运行的命令：
  - `git branch --show-current` → `main`
  - `git log --oneline -5` → `32ee87a ...`
- 未能运行的命令及原因：
  - 未运行 pytest 全量测试（按 AGENTS.md §10 规定，IDE Agent 禁止本地全量 pytest）
  - 未运行 `scripts/boundary_guard.py`（需完整运行环境）

---

## 2. 结论总览

### P0：会导致无法启动、数据丢失、安全泄露、发布不可用的问题

（无新发现 P0 级问题）

### P1：会导致核心功能不可用或明显影响用户体验的问题

1. **BUG-A01**：`get_custom_danmu_pool` 全量加载 20000 条弹幕到内存，可导致 UI 卡顿
2. **BUG-A02**：`custom_danmu_list_for_store` 读操作持 `_write_lock`，高并发下阻塞主线程写操作
3. **BUG-A03**：`_load_recent_from_history` 在 `DanmuEngine.__init__` 中直接读 `config.conn`，绕过 `_write_lock`
4. **BUG-A04**：`is_formula_danmu_text` 每次调用都执行 SQLite 查询，热路径上可导致帧延迟

### P2：会导致性能下降、边界异常、配置不生效的问题

5. **BUG-A05**：`_use_fast_danmu_render` 对含 CJK 的短字符串仍走慢 QPainterPath 路径
6. **BUG-A06**：`uninstall_service.delete_user_data_if_requested` 路径安全检查仅验证 `data_dir.name`，未验证父路径
7. **BUG-A07**：`version_compare` 不支持 `+build` 元数据，可能误判版本新旧
8. **BUG-A08**：`ai_client_requests.stream_openai` 中 `json.JSONDecodeError` 被静默吞掉，丢失诊断信息
9. **BUG-A09**：`SingleInstanceGuard._activate_existing_instance` 在 `waitForConnected(500)` 超时后新进程不退出，导致双实例运行
10. **BUG-A10**：`config_store.get_json` 对非法 JSON 无异常处理，可导致启动崩溃

### P3：代码卫生、文档不一致、潜在维护问题

11. **BUG-A11**：`DanmuAI.spec` hiddenimports 列表缺少 `app.mic_buffer` 等新增模块
12. **BUG-A12**：`danmu_engine_dedup.similarity` 纯 Python 回退的 O(mn) 复杂度在长文本下可阻塞主线程
13. **BUG-A13**：`reply_parser._heuristic_comments_from_malformed_json` 递归深度无限制，畸形输入可导致栈溢出

---

## 3. 已确认 Bug

### BUG-A01：`get_custom_danmu_pool` 全量加载 20000 条弹幕可导致 UI 卡顿

- 严重等级：**P1**
- 影响功能：自定义弹幕库管理、弹幕补池、回复解析填充
- 证据文件：[danmu_pool.py](file:///e:/test/danmu/app/danmu_pool.py)
- 证据代码：
  ```python
  # L472-482
  def get_custom_danmu_pool_for_store(store) -> list[str]:
      if not store._conn_usable():
          return []
      try:
          with store._write_lock:
              rows = store.conn.execute(
                  "SELECT text FROM custom_danmu_pool_entries ORDER BY id ASC"
              ).fetchall()
      except sqlite3.ProgrammingError:
          return []
      return [str(row[0]).strip() for row in rows if row and row[0] and str(row[0]).strip()]
  ```
- 复现路径：用户导入 20000 条自定义弹幕 → 任何调用 `load_danmu_pool_for_config` 的路径（补池、回复解析填充）都会全量加载 → 主线程阻塞
- 根因分析：`CUSTOM_DANMU_POOL_MAX = 20000`，但 `get_custom_danmu_pool_for_store` 无分页、无 LIMIT，全量 `fetchall()` 到 Python 列表。`load_danmu_pool_for_config` → `get_custom_danmu_pool` → 此函数。`_scene_fillers` / `_generic_fillers` 在每次 `normalize_reply_batch` 时调用，频率极高。
- 最小修复建议：`get_custom_danmu_pool_for_store` 加 `LIMIT 20000`；热路径 `sample_danmu_for_config` 已走 `custom_danmu_random_sample`（SQL RANDOM()），但 `load_danmu_pool_for_config` 仍全量加载，应改为按需抽样或缓存。
- 是否建议本次自动修复：否（需确认所有调用方语义）
- 需要补充的测试：`test_danmu_pool.py` 中添加 20000 条数据的性能回归测试

### BUG-A02：`custom_danmu_list_for_store` 等读操作持 `_write_lock`，阻塞主线程

- 严重等级：**P1**
- 影响功能：Web API 弹幕库列表查询、自定义弹幕计数
- 证据文件：[danmu_pool.py](file:///e:/test/danmu/app/danmu_pool.py)
- 证据代码：
  ```python
  # L317-324
  def custom_danmu_count_for_store(store, source: str | None = None) -> int:
      if not store._conn_usable():
          return 0
      try:
          with store._write_lock:  # ← 读操作持写锁
              return _custom_danmu_count_locked(store, source)
      except sqlite3.ProgrammingError:
          return 0
  ```
  同样问题存在于 `custom_danmu_list_for_store`（L350）、`custom_danmu_random_sample_for_store`（L449）、`custom_danmu_contains_text_for_store`（L464）、`get_custom_danmu_pool_for_store`（L476）。
- 复现路径：HTTP 线程调用弹幕库列表 API → 持 `_write_lock` → 主线程 `config.set()` 等待 → UI 卡顿
- 根因分析：所有 `danmu_pool` 函数使用 `store._write_lock` 保护 SQLite 读操作，但 WAL 模式下读不阻塞写。这些读操作只需保证连接可用，不需要与写操作串行化。`_write_lock` 的设计初衷是"写路径串行化保证 cache/DB 一致"，但被误用于读路径。
- 最小修复建议：读操作移除 `_write_lock`，仅保留 `store._conn_usable()` 检查；或引入 `_read_lock`（WAL 模式下读不互斥）。
- 是否建议本次自动修复：否（需确认 WAL 模式下无脏读风险）
- 需要补充的测试：`test_p1_sqlite_concurrency.py` 中添加读操作与写操作并发测试

### BUG-A03：`_load_recent_from_history` 绕过 `_write_lock` 直接读 `config.conn`

- 严重等级：**P1**
- 影响功能：弹幕引擎初始化
- 证据文件：[danmu_engine.py](file:///e:/test/danmu/app/danmu_engine.py)
- 证据代码：
  ```python
  # L216-224
  def _load_recent_from_history(self):
      try:
          rows = self.config.conn.execute(
              "SELECT content FROM history ORDER BY id DESC LIMIT 30"
          ).fetchall()
          for row in reversed(rows):
              self._remember_content(row[0])
      except Exception:
          pass
  ```
- 复现路径：启动时 `DanmuEngine.__init__` → `_load_recent_from_history` → 直接用 `self.config.conn` 无锁读 → 若此时 HTTP 线程正在写 config → SQLite `ProgrammingError` 或脏读
- 根因分析：`DanmuEngine.__init__` 在主线程构造，此时 HTTP 线程尚未启动，实际风险较低。但代码模式不一致——其他地方都通过 `config` 门面或 `_write_lock` 访问 `conn`，此处直接访问 `conn` 违反了 `ConfigStore` 的封装边界。
- 最小修复建议：改为 `self.config.meme_barrage_library_all_texts()` 类似的门面方法，或在 `ConfigStore` 中添加 `get_recent_history(limit)` 方法。
- 是否建议本次自动修复：否（启动时竞态风险低，但需统一访问模式）
- 需要补充的测试：无

### BUG-A04：`is_formula_danmu_text` 热路径上每次调用执行 SQLite 查询

- 严重等级：**P1**
- 影响功能：弹幕截断判断、去重判断
- 证据文件：[danmu_pool.py](file:///e:/test/danmu/app/danmu_pool.py)
- 证据代码：
  ```python
  # L165-169
  def is_formula_danmu_text(config, content: str) -> bool:
      """True when content is from formula sources (custom pool or meme barrage)."""
      return is_stored_custom_pool_text(config, content) or is_stored_meme_barrage_text(
          config, content
      )
  ```
  `is_stored_custom_pool_text` → `config.custom_danmu_contains_text` → SQLite `SELECT 1 ... LIMIT 1`（L460-469）。
  `is_stored_meme_barrage_text` → `_meme_barrage_text_set` → 有缓存但首次全量加载。
- 复现路径：每条弹幕上屏时 `normalize_danmu_display_text` → `is_formula_danmu_text` → SQLite 查询。高频弹幕场景下每秒可触发数十次。
- 根因分析：`is_stored_custom_pool_text` 没有缓存机制，每次都走 SQLite 查询。`_meme_barrage_text_set` 有 `id(config)` 为 key 的缓存，但 `is_stored_custom_pool_text` 没有。
- 最小修复建议：为 `is_stored_custom_pool_text` 添加类似 `_meme_barrage_text_set` 的内存缓存（`set[str]`），在弹幕库写入时 `invalidate_formula_text_cache`。
- 是否建议本次自动修复：否（需确认缓存失效时机）
- 需要补充的测试：`test_danmu_pool.py` 中添加缓存命中/失效测试

---

### BUG-A05：`_use_fast_danmu_render` 对含 CJK 的短字符串仍走慢 QPainterPath 路径

- 严重等级：**P2**
- 影响功能：弹幕渲染性能
- 证据文件：[overlay.py](file:///e:/test/danmu/app/overlay.py)
- 证据代码：
  ```python
  # L69-74
  def _use_fast_danmu_render(content: str) -> bool:
      if len(content) >= _FAST_DANMU_RENDER_MIN_LEN:  # 36
          return True
      return any(ord(ch) > 127 for ch in content)
  ```
- 复现路径：短弹幕（<36 字符）含 CJK → `any(ord(ch) > 127)` 返回 True → 走 `fast=True` 的 `drawText` 描边。但注释说"长文本/emoji 走 drawText 描边，避免 QPainterPath.addText 阻塞主线程数秒"，实际对短 CJK 也走 fast 路径，这是**正确行为**（CJK 字符的 QPainterPath.addText 同样慢），但函数名和注释有误导性。
- 根因分析：函数名 `_use_fast_danmu_render` 和注释暗示只有长文本才走 fast，但实际 CJK 短文本也走 fast。这是**正确的设计选择**但文档不一致。
- 最小修复建议：更新函数注释，明确说明 CJK/emoji 始终走 fast 路径。
- 是否建议本次自动修复：是（仅改注释）
- 需要补充的测试：无

### BUG-A06：`delete_user_data_if_requested` 路径安全检查不充分

- 严重等级：**P2**
- 影响功能：卸载时用户数据删除
- 证据文件：[uninstall_service.py](file:///e:/test/danmu/app/uninstall_service.py)
- 证据代码：
  ```python
  # L81-94
  def delete_user_data_if_requested() -> None:
      marker = _delete_marker_path()
      if not marker.exists():
          return
      try:
          content = marker.read_text(encoding="utf-8").strip()
      except OSError:
          return
      if "delete-user-data=1" not in content:
          return
      data_dir = _appdata_dir()
      if data_dir.name != APPDATA_DIR_NAME:  # ← 仅检查最后一级目录名
          return
      shutil.rmtree(data_dir, ignore_errors=True)
  ```
- 复现路径：若 `%APPDATA%` 环境变量被篡改为非标准路径（如 `C:\`），`_appdata_dir()` 返回 `C:\DanmuAI`，`data_dir.name == "DanmuAI"` 检查通过 → `shutil.rmtree("C:\DanmuAI")` 删除意外目录。
- 根因分析：仅检查 `data_dir.name != APPDATA_DIR_NAME`，未验证 `data_dir.parent` 是否为 `%APPDATA%` 或 `AppData\Roaming`。理论上 `%APPDATA%` 不会指向根目录，但安全关键代码应做更严格的路径验证。
- 最小修复建议：增加 `data_dir.parent` 是否为 `%APPDATA%` 的验证：
  ```python
  appdata = os.environ.get("APPDATA", "")
  if appdata and str(data_dir.parent).lower() != Path(appdata).resolve().lower():
      return
  ```
- 是否建议本次自动修复：否（安全关键代码需人工确认）
- 需要补充的测试：`test_uninstall_service.py` 中添加路径安全边界测试

### BUG-A07：`version_compare` 不支持 `+build` 元数据

- 严重等级：**P2**
- 影响功能：自动更新版本比较
- 证据文件：[version_compare.py](file:///e:/test/danmu/app/version_compare.py)
- 证据代码：
  ```python
  # L38-43
  def _split_core_prerelease(normalized: str) -> tuple[str, str | None]:
      if "-" not in normalized:
          return normalized, None
      core, prerelease = normalized.split("-", 1)
      prerelease = prerelease.strip() or None
      return core, prerelease
  ```
- 复现路径：若 Supabase `app_updates` 表中 `latest_version` 为 `0.3.4+build.1`，`_split_core_prerelease` 会将 `+build.1` 作为 core 的一部分传入 `_parse_numeric_segments`，导致 `+` 后的内容解析失败（`ValueError: invalid version segment`）。
- 根因分析：Semver 规范中 `+build` 为构建元数据，应被忽略。当前实现仅处理 `-prerelease`，未剥离 `+build`。
- 最小修复建议：在 `_split_core_prerelease` 之前或其中剥离 `+build`：
  ```python
  if "+" in normalized:
      normalized = normalized.split("+", 1)[0]
  ```
- 是否建议本次自动修复：是（改动小、风险低）
- 需要补充的测试：`test_version_compare.py` 中添加 `+build` 元数据测试

### BUG-A08：`stream_openai` 中 JSON 解析错误被静默吞掉

- 严重等级：**P2**
- 影响功能：AI 回复流式解析诊断
- 证据文件：[ai_client_requests.py](file:///e:/test/danmu/app/ai_client_requests.py)
- 证据代码：
  ```python
  # L583-605
  try:
      chunk = json.loads(payload)
      # ...
  except (json.JSONDecodeError, IndexError, KeyError):
      continue  # ← 静默吞掉所有解析错误
  ```
- 复现路径：模型返回非标准 SSE 数据（如 `data: {"choices":[{}]}`）→ `json.JSONDecodeError` → 静默跳过 → 无日志、无诊断信息 → 用户看到"AI 返回为空"但无法排查原因。
- 根因分析：流式解析中 `continue` 是合理的（避免单行错误中断整个流），但完全无日志会导致问题排查困难。
- 最小修复建议：添加 `logger.debug` 记录解析失败：
  ```python
  except (json.JSONDecodeError, IndexError, KeyError) as exc:
      logger.debug("stream chunk parse skipped: %r payload=%.80s", exc, payload)
      continue
  ```
- 是否建议本次自动修复：是（仅添加 debug 日志）
- 需要补充的测试：无

### BUG-A09：`SingleInstanceGuard` 激活超时后新进程不退出

- 严重等级：**P2**
- 影响功能：单实例守卫
- 证据文件：[single_instance.py](file:///e:/test/danmu/app/single_instance.py)
- 证据代码：
  ```python
  # L60-73
  def try_acquire(self) -> SingleInstanceAcquireResult:
      if self._activate_existing_instance():
          return SingleInstanceAcquireResult(
              SingleInstanceAcquireKind.ACTIVATED_EXISTING
          )
      if self._listen_primary():
          return SingleInstanceAcquireResult(SingleInstanceAcquireKind.PRIMARY)
      if self._activate_existing_instance():
          return SingleInstanceAcquireResult(
              SingleInstanceAcquireKind.ACTIVATED_EXISTING
          )
      return SingleInstanceAcquireResult(SingleInstanceAcquireKind.ACTIVATION_FAILED)
  ```
  以及 `_activate_existing_instance`（L75-90）中 `waitForConnected(500)` 超时返回 `False`。
- 复现路径：原实例正在启动但 `QLocalServer` 尚未就绪 → 新进程 `_activate_existing_instance` 返回 `False` → `_listen_primary` 成功（原实例 server 名尚未注册）→ 新进程成为主实例 → 原实例也继续启动 → 双实例运行。
- 根因分析：`try_acquire` 的竞态窗口在注释中已承认（L68），但 `ACTIVATION_FAILED` 返回后 `main()` 仍继续启动（见 `main.py` 中的调用逻辑），不会 exit。这是一个已知的低概率竞态，设计上选择了"不阻塞"而非"严格互斥"。
- 最小修复建议：在 `main()` 中对 `ACTIVATION_FAILED` 结果添加短暂等待重试，或在文档中明确说明此竞态窗口。
- 是否建议本次自动修复：否（需确认 main() 中的处理逻辑）
- 需要补充的测试：`test_single_instance.py` 中添加竞态场景测试

### BUG-A10：`config_store.get_json` 对非法 JSON 无异常处理

- 严重等级：**P2**
- 影响功能：配置读取
- 证据文件：[config_store.py](file:///e:/test/danmu/app/config_store.py)
- 证据代码：
  ```python
  # L436-438
  def get_json(self, key: str, default: list | dict | None = None) -> list | dict:
      val = self.get(key)
      return json.loads(val) if val else (default or {})
  ```
- 复现路径：`config.db` 中某 key 的 value 为非法 JSON（如手动编辑、迁移损坏）→ `json.loads(val)` 抛出 `json.JSONDecodeError` → 调用方未捕获 → 启动崩溃。
- 根因分析：`get_json` 假设数据库中的 JSON 值始终合法，但未做防御性处理。`set_json` 写入时是合法的，但数据库文件可能被外部工具修改或损坏。
- 最小修复建议：添加 try-except：
  ```python
  def get_json(self, key: str, default: list | dict | None = None) -> list | dict:
      val = self.get(key)
      if not val:
          return default or {}
      try:
          return json.loads(val)
      except (json.JSONDecodeError, TypeError):
          logger.warning("config key=%s has invalid JSON, returning default", key)
          return default or {}
  ```
- 是否建议本次自动修复：是（改动小、防御性编程）
- 需要补充的测试：`test_config_store.py` 中添加非法 JSON 测试

---

## 4. 高风险但未确认问题

### H-01：`_prepare_capacity_for_new_item` 中淘汰循环可能阻塞主线程

- 证据文件：[danmu_engine.py](file:///e:/test/danmu/app/danmu_engine.py) L601-617
- 描述：`_prepare_capacity_for_new_item` 中 `for _ in range(safety)` 循环的 `safety` 上限为 `max(current_display_count(), pending_cap, retention_cap, 1) + 8`。若 `retention_cap=9999` 且轨道中有大量屏外 pending，循环可能执行数千次 `_evict_furthest_offscreen_pending`，每次都遍历所有轨道。在弹幕密集场景下可能导致帧延迟。
- 需要人工确认：实际使用中 `retention_cap` 默认 600，是否会出现极端场景。

### H-02：`reply_parser._heuristic_comments_from_malformed_json` 递归深度无限制

- 证据文件：[reply_parser.py](file:///e:/test/danmu/app/reply_parser.py) L130-173
- 描述：`}{` 拼接时递归调用自身，若模型返回大量 `}{` 拼接（如 `}{` 重复 1000 次），递归深度可达 1000 层，触发 `RecursionError`。
- 需要人工确认：实际模型输出是否可能包含大量 `}{` 拼接。

### H-03：`WebConsoleBridge.invoke_on_main` 超时后 HTTP 请求挂起

- 证据文件：[web_console.py](file:///e:/test/danmu/app/web_console.py) L186-231
- 描述：`invoke_on_main` 超时后抛出 `MainThreadInvokeTimeout`，但 HTTP 路由中可能未统一捕获此异常，导致 500 错误返回给前端。
- 需要人工确认：FastAPI 的全局异常处理器是否覆盖 `MainThreadInvokeTimeout`。

### H-04：`config_store._init_fernet` 中 `.key` 文件权限 `0o600` 在 Windows 上无效

- 证据文件：[config_store.py](file:///e:/test/danmu/app/config_store.py) L62-67
- 描述：`os.chmod(path, 0o600)` 在 Windows 上仅影响只读属性，不提供真正的文件权限控制。加密密钥文件的实际安全性依赖 NTFS ACL 和 `%APPDATA%` 的用户隔离。
- 需要人工确认：是否需要在 Windows 上显式设置 DACL。

---

## 5. 性能与卡顿风险

### 5.1 启动速度

- **ConfigStore 初始化**（[config_store.py](file:///e:/test/danmu/app/config_store.py) L73-113）：`__init__` 中执行 `_init_db`、`_load_cache`、`_migrate_legacy_display_mode_to_render_mode`、`seed_config_defaults`、`_init_fernet`、`_repair_stale_region_if_needed`、`_normalize_legacy_display_mode`、`migrate_custom_danmu_pool_json`。这些操作在主线程同步执行，若 `config.db` 较大或迁移数据量多，可导致启动延迟。
- **DanmuEngine._load_recent_from_history**（[danmu_engine.py](file:///e:/test/danmu/app/danmu_engine.py) L216-224）：启动时读取最近 30 条历史记录，正常情况下很快。

### 5.2 截图与 AI 请求

- **httpx 超时**（[ai_client.py](file:///e:/test/danmu/app/ai_client.py) L100）：`httpx.Timeout(30.0, connect=5.0)`，30 秒总超时合理。但流式响应中无总超时限制（`stream_openai` 仅检查 `_request_wall_clock_exceeded`），若模型持续返回 SSE 事件但内容为空，可能长时间不超时。
- **重试策略**：最多 2 次重试（L252, L460），超时重试、异常重试（重建 httpx 客户端），HTTP 状态错误不重试。设计合理。

### 5.3 Overlay 渲染

- **QPainterPath.addText 性能**（[overlay.py](file:///e:/test/danmu/app/overlay.py) L96-106）：对 CJK/emoji 已走 fast 路径（`drawText` 描边），性能可接受。但 `_FAST_DANMU_RENDER_MIN_LEN = 36` 对纯 ASCII 短文本仍走慢路径，若弹幕内容为纯英文短句（如 "lol"），仍可能触发 `QPainterPath.addText`。实际影响取决于弹幕频率。
- **pixmap 预渲染**（L328-342）：`_prepare_pixmaps_near_visible` 每帧检查所有轨道的未渲染 item，O(n) 复杂度。弹幕密集时可能有性能影响。

### 5.4 SQLite

- **WAL + busy_timeout=5000**（[config_store.py](file:///e:/test/danmu/app/config_store.py) L86-88）：设计合理，5 秒等待足够覆盖正常写操作。
- **_write_lock 粒度**：所有写操作共享同一把锁，包括 `set`、`set_batch`、`apply_web_save`、`_encrypted_set`、以及 `danmu_pool` 的所有操作。高并发场景下可能成为瓶颈。
- **custom_danmu_pool_entries 无分页全量查询**：见 BUG-A01。

### 5.5 自定义弹幕库

- **20000 条上限**（[danmu_pool.py](file:///e:/test/danmu/app/danmu_pool.py) L17）：`CUSTOM_DANMU_POOL_MAX = 20000`。`custom_danmu_random_sample_for_store` 使用 `ORDER BY RANDOM() LIMIT ?`，对 20000 条数据性能可接受（SQLite RANDOM() 不需要全表排序）。
- **`set_custom_danmu_pool_for_store`**（L485-505）：先 `DELETE FROM custom_danmu_pool_entries`（全表删除），再 `INSERT`。20000 条数据的全量替换会导致短暂的表锁和 WAL 膨胀。

---

## 6. 发布与更新风险

### 6.1 PyInstaller

- **DanmuAI.spec**（[DanmuAI.spec](file:///e:/test/danmu/DanmuAI.spec)）：hiddenimports 列表较完整，覆盖了 `app.*` 的所有子包。但以下新增模块可能遗漏：
  - `app.mic_buffer`（在 `main_lifecycle_mixin.py` 中被引用但未在 hiddenimports 中）
  - `app.worker_pools`（已在 hiddenimports 中）
  - `app.web_console_session_auth`（已在 hiddenimports 中）
- **supabase-config.js 排除**（L66-70）：正确排除了含凭据的配置文件。
- **console=False**（L317）：发布为 GUI 应用，`sys.stderr` 可能为 None，已通过 `_prepare_stdio_for_uvicorn` 处理。

### 6.2 Velopack

- **velopack_runtime.py**（[velopack_runtime.py](file:///e:/test/danmu/app/velopack_runtime.py)）：启动钩子在 `QApplication` 之前执行，异常处理合理（L32-33 捕获所有异常并日志记录，不阻塞启动）。
- **update_service.py**（[update_service.py](file:///e:/test/danmu/app/update_service.py)）：`_manager()` 缓存 `UpdateManager` 实例，线程安全通过 `_lock` 保护。`download_updates` 中的线程管理合理。
- **版本比较**：见 BUG-A07（`+build` 元数据不支持）。

### 6.3 用户数据保留

- **uninstall_service.py**：默认保留用户数据，opt-in 删除。见 BUG-A06（路径安全检查不充分）。
- **config.db 迁移**：`ConfigStore.__init__` 中执行迁移，无版本号管理。若未来需要破坏性迁移（如改表结构），需添加迁移版本号。

---

## 7. 安全与隐私风险

### 7.1 API Key

- **加密存储**（[config_store.py](file:///e:/test/danmu/app/config_store.py) L139-170）：Fernet 加密，密钥文件 `.key` 在 `%APPDATA%/DanmuAI/`。密钥丢失后旧密文不可恢复，设计合理。
- **日志脱敏**（L46-51）：`_redact_config_value_for_log` 对敏感 key 返回 `***`，对长值截断。覆盖了 `api_key_encrypted`、`mic_api_key_encrypted`、`tts_api_key_encrypted`、`custom_models`、`api_key`。
- **自定义模型 apiKey**：`get_custom_models` 返回解密后的明文 apiKey（L618-645），通过 Web API 返回时需确认前端是否做掩码处理。

### 7.2 Supabase

- **凭据来源**（[supabase_config.py](file:///e:/test/danmu/app/supabase_config.py)）：环境变量优先，回退到 `web/static/supabase-config.js`。打包时已排除此文件（DanmuAI.spec L69）。
- **anon_key 安全性**：Supabase anon key 设计上可公开，安全性依赖 RLS 策略。需确认 Supabase 项目中所有表都配置了正确的 RLS。

### 7.3 Web API 认证

- **Bearer token**（[web_console.py](file:///e:/test/danmu/app/web_console.py) L402）：启动时生成 `secrets.token_urlsafe(24)`，仅绑定 `127.0.0.1`。设计合理。
- **WebSocket 认证**：使用 `ws_token` query 参数，与 HTTP token 一致。

### 7.4 潜在风险

- **`SanitizedLogger`**：日志脱敏机制需确认是否覆盖所有 API key 泄露路径（如 AI 请求 URL 中的 key 参数）。
- **`supabase-config.js` 在源码仓库中**：若仓库公开，anon key 会暴露。需确认仓库可见性。

---

## 8. 建议新增的测试

### 8.1 `test_danmu_pool_performance.py`

- 测试目标：验证 20000 条自定义弹幕下各操作的性能
- 断言内容：
  - `custom_danmu_random_sample_for_store(store, 10)` 在 100ms 内完成
  - `get_custom_danmu_pool_for_store(store)` 在 500ms 内完成
  - `custom_danmu_list_for_store(store, page=1, page_size=100)` 在 50ms 内完成

### 8.2 `test_config_store_json_safety.py`

- 测试目标：验证 `get_json` 对非法 JSON 的容错
- 断言内容：
  - `config.get_json("bad_key")` 在 value 为 `"{invalid"` 时返回 `{}`（不抛异常）
  - `config.get_json("bad_key", default=[])` 在 value 为 `"not json"` 时返回 `[]`

### 8.3 `test_version_compare_build_metadata.py`

- 测试目标：验证 `+build` 元数据的处理
- 断言内容：
  - `compare_versions("0.3.4", "0.3.4+build.1") == 0`
  - `compare_versions("0.3.4+build.1", "0.3.4+build.2") == 0`
  - `is_version_newer("0.3.5", "0.3.4+build.1") == True`

### 8.4 `test_uninstall_path_safety.py`

- 测试目标：验证卸载路径安全检查
- 断言内容：
  - `delete_user_data_if_requested()` 在 `%APPDATA%` 指向非标准路径时不删除
  - `delete_user_data_if_requested()` 在 marker 文件不存在时不删除

### 8.5 `test_danmu_engine_dedup_cache.py`

- 测试目标：验证 `is_formula_danmu_text` 的缓存机制
- 断言内容：
  - 连续调用 `is_formula_danmu_text` 不触发重复 SQLite 查询
  - `invalidate_formula_text_cache` 后缓存失效

---

## 9. 本次可自动修复项

| 编号 | 修复内容 | 风险 | 范围 |
|------|---------|------|------|
| BUG-A07 | `version_compare.py` 中剥离 `+build` 元数据 | 低 | 1 行代码 + 测试 |
| BUG-A08 | `ai_client_requests.py` 中流式解析错误添加 debug 日志 | 低 | 2 行代码 |
| BUG-A10 | `config_store.py` 中 `get_json` 添加 try-except | 低 | 5 行代码 + 测试 |
| BUG-A05 | `overlay.py` 中 `_use_fast_danmu_render` 注释更新 | 无 | 仅注释 |

---

## 10. 最终建议

按优先级排序：

1. **BUG-A01 + BUG-A04**：自定义弹幕库 20000 条全量加载 + 热路径 SQLite 查询无缓存。这是当前最可能影响用户体验的性能问题，在高弹幕密度场景下可导致主线程卡顿。建议：为 `is_stored_custom_pool_text` 添加内存缓存；`load_danmu_pool_for_config` 改为按需抽样。

2. **BUG-A02**：读操作持 `_write_lock` 阻塞主线程。这是架构层面的问题，影响所有使用自定义弹幕库的 Web API 调用。建议：引入读写锁或移除读操作的 `_write_lock`。

3. **BUG-A07 + BUG-A10**：版本比较不支持 `+build` 元数据 + `get_json` 无异常处理。这两个是低风险但修复成本极低的问题，建议立即修复。
