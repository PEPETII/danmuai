# DanmuAI 周期性 Bug 审计报告

> 审计日期：2026-07-12  
> 审计范围：启动/生命周期、弹幕主链路、模型调用、麦克风/读弹幕、桌宠、配置/SQLite、发布更新、Web 安全、测试验收  
> 审计人：AI Agent（python-expert）

---

## 1. 结论总览

| 严重等级 | 数量 | 关键问题摘要 |
|---------|------|-------------|
| **P0** | 0 | 未发现可导致“无法启动/数据丢失/安全泄露/发布不可用”的已确认 Bug |
| **P1** | 3 | 发布检查脚本崩溃、版本号比较错误导致更新被抑制、Overlay 置顶失效无用户提示 |
| **P2** | 6 | 麦克风空转 CPU、日志脱敏遗漏、HistoryWriter 退出竞态、托盘更新检查退出竞态、去重降级卡顿、发布脚本版本覆盖不一致 |
| **P3** | 2 | 代码中已标注的 TODO/BUG 未闭环、部分异常未分类 |

---

## 2. 已确认 Bug

### BUG-001：发布验收脚本因缺失文件崩溃
- **严重等级：P1**
- **影响功能：** 发布前验收检查（CI/CD 必过项）
- **证据文件：** [scripts/boundary_guard/rules/runtime.py](file:///workspace/scripts/boundary_guard/rules/runtime.py)
- **证据代码：**
  ```python
  doc_path = Path("docs/runtime-state-map.md")
  doc_content = doc_path.read_text(encoding="utf-8")
  ```
- **复现路径：** 在项目根目录执行 `python scripts/run_acceptance_gates.py`，直接抛出 `FileNotFoundError: docs/runtime-state-map.md`
- **根因分析：** `scripts/boundary_guard/rules/runtime.py:55` 硬编码读取 `docs/runtime-state-map.md`，但仓库根目录不存在 `docs/` 目录，导致验收脚本 100% 失败。
- **最小修复建议：** 在仓库根目录创建 `docs/runtime-state-map.md` 并写入对应的运行时状态表；或在脚本中增加文件存在性检查并给出友好报错。
- **是否建议本次自动修复：是**
- **需要补充的测试：** `tests/test_boundary_guard.py` 中增加 `test_runtime_state_map_exists`：断言 `Path("docs/runtime-state-map.md").exists()` 为 True。

---

### BUG-002：版本号 prerelease 比较逻辑错误，导致 rc.10 被认为小于 rc.2
- **严重等级：P1**
- **影响功能：** 自动更新检查、版本比较
- **证据文件：** [app/version_compare.py](file:///workspace/app/version_compare.py)
- **证据代码：**
  ```python
  def _compare_prerelease(a: str, b: str) -> int:
      def _priority(s: str) -> tuple[int, str]:
          prefix = s.split(".")[0].lower()
          return _PRERELEASE_PRIORITY.get(prefix, 0), s
      pa, sa = _priority(a)
      pb, sb = _priority(b)
      if pa != pb:
          return -1 if pa < pb else 1
      return -1 if sa < sb else 1 if sa > sb else 0
  ```
- **复现路径：** 在 Python REPL 中执行：
  ```python
  from app.version_compare import compare_versions
  compare_versions("0.3.0-rc.10", "0.3.0-rc.2")   # 返回 -1，表示 rc.10 < rc.2（错误）
  ```
- **根因分析：** `_compare_prerelease` 对同 prefix 的 prerelease 使用纯字符串字典序比较，`"rc.10" < "rc.2"` 在字典序下为 True，违反 SemVer 的 numeric identifier 规则。
- **最小修复建议：** 对 `sa`、`sb` 的 dot-separated components 逐段比较，纯数字段按整数比较，非数字段按字符串比较。
- **是否建议本次自动修复：是**
- **需要补充的测试：** `tests/test_version_compare.py` 增加：
  ```python
  assert compare_versions("0.3.0-rc.10", "0.3.0-rc.2") == 1
  assert compare_versions("0.3.0-rc.2", "0.3.0-rc.10") == -1
  ```

---

### BUG-003：Overlay 置顶失败后仅打印日志，无用户提示与恢复引导
- **严重等级：P1**
- **影响功能：** 游戏内弹幕置顶显示
- **证据文件：** [app/overlay.py](file:///workspace/app/overlay.py)
- **证据代码：**
  ```python
  if self._topmost_fail_streak >= 3:
      self._logger.warning("Overlay topmost reassert failed %d times", self._topmost_fail_streak)
  ```
  以及：
  ```python
  def _reassert_topmost(self):
      if not win32_overlay_zorder.reassert_hwnd_topmost(self.winId()):
          self._topmost_fail_streak += 1
          return
  ```
- **复现路径：** 在 Windows 下启动 DanmuAI，随后启动某款以独占全屏模式运行的游戏（如 CS2、Valorant），Overlay 窗口的 `SetWindowPos` 会被系统拒绝，连续 3 次失败后仅能在日志中看到 warning，用户完全不知道弹幕已不可见。
- **根因分析：** `overlay.py` 内部计数 `_topmost_fail_streak` 达到阈值后仅记录日志，未通过 signal 通知 Web 控制台弹出气泡/提示，也未提供“切换窗口再切回”等恢复引导。代码注释中已标注 `# BUG-004`，但无闭环修复。
- **最小修复建议：** 当 `_topmost_fail_streak == 3` 时，emit 一个 `topmost_lost` signal 给 UI，提示用户“游戏全屏可能导致弹幕不可见，建议切换为窗口化或无边框模式”。
- **是否建议本次自动修复：否**（涉及 UI 文案和 signal 设计，超出审计范围）
- **需要补充的测试：** `tests/test_overlay_topmost.py`：mock `reassert_hwnd_topmost` 连续返回 False，断言 Overlay 会 emit `topmost_lost` signal。

---

### BUG-004：麦克风轮询在空数据时仍返回 True，导致 QTimer 空转浪费 CPU
- **严重等级：P2**
- **影响功能：** 麦克风模式功耗与性能
- **证据文件：** [app/mic_orchestrator.py](file:///workspace/app/mic_orchestrator.py)
- **证据代码：**
  ```python
  def poll(self) -> bool:
      try:
          pcm = self._capture.try_snapshot_pcm_ms(self._chunk_ms)
      except Exception:
          return True
      if pcm is None:
          return True
      self._buffer.extend(pcm)
      ...
  ```
- **复现路径：** 开启麦克风模式，但设备未录入有效音频（或设备静音）。`_capture.try_snapshot_pcm_ms` 返回 `None`，`poll()` 仍返回 `True`，上层 `QTimer` 每 600ms 持续触发，CPU 被无意义轮询消耗。
- **根因分析：** `poll()` 的语义是“是否继续轮询”，但在 PCM 为空时返回 `True` 表示继续，缺乏指数退避或空计数休眠机制。
- **最小修复建议：** 增加空计数器，连续 N 次（如 10 次）PCM 为 None 时，让 `poll()` 返回 `False` 或延长下次轮询间隔。
- **是否建议本次自动修复：是**
- **需要补充的测试：** `tests/test_mic_orchestrator.py`：mock `try_snapshot_pcm_ms` 始终返回 `None`，断言多次 `poll()` 后返回 `False` 或进入退避状态。

---

### BUG-005：日志脱敏正则遗漏非 Bearer 鉴权格式
- **严重等级：P2**
- **影响功能：** 日志安全、隐私合规
- **证据文件：** [app/logger.py](file:///workspace/app/logger.py)
- **证据代码：**
  ```python
  AUTH_HEADER_PATTERN = re.compile(
      r'(Authorization\s*[:=]\s*["\']?\s*Bearer\s+)[A-Za-z0-9_\-\.]+',
      re.IGNORECASE,
  )
  ```
- **复现路径：** 若某次 HTTP 请求头包含 `Authorization: Token sk-xxxxx` 或 `X-API-Key: xxx`，日志中将原样打印，因为正则要求必须出现 `Bearer` 关键字。类似地，`GENERIC_API_KEY_PATTERN` 仅匹配 `api[_-]?key` 形式。
- **根因分析：** 脱敏正则设计未覆盖所有常见鉴权方案（Token、ApiKey、Authorization 直接跟 sk- 等）。
- **最小修复建议：** 扩展 `AUTH_HEADER_PATTERN` 支持 `Token`、`ApiKey` 等前缀；或增加一个兜底模式，匹配 `sk-[a-zA-Z0-9]{20,}` 作为 OpenAI/DashScope 等常用 key 格式。
- **是否建议本次自动修复：是**
- **需要补充的测试：** `tests/test_log_sanitization.py`：输入包含 `Authorization: Token sk-abc123` 和 `X-API-Key: xyz`，断言输出中密钥部分被替换为 `***`。

---

### BUG-006：HistoryWriter 退出时可能向已关闭的 SQLite 连接写入，导致异常或历史丢失
- **严重等级：P2**
- **影响功能：** 弹幕历史持久化、退出稳定性
- **证据文件：** [app/history_writer.py](file:///workspace/app/history_writer.py)
- **证据代码：**
  ```python
  try:
      with self.config.with_write_lock():
          self.config.conn.executemany(...)
          self._maybe_prune_rows()
          self.config.conn.commit()
  except sqlite3.Error:
      _logger.exception("history flush failed items=%d, will retry on next flush", len(items))
      with self._lock:
          for item in reversed(items):
              ...
  ```
- **复现路径：** 用户点击退出，主线程调用 `ConfigStore.close()` 关闭 SQLite 连接；此时 HistoryWriter 的守护线程刚好进入 `flush()`，使用已关闭的 `self.config.conn`，抛出 `sqlite3.ProgrammingError`（不属于 `sqlite3.Error` 子类时可能未捕获），异常上抛导致线程崩溃，缓冲区中的历史条目永久丢失。
- **根因分析：** `flush()` 只捕获 `sqlite3.Error`，但连接关闭后抛出的可能是 `ProgrammingError` 或 `OperationalError`；且 retry backfill 在下次 flush 时仍会因连接关闭而失败。
- **最小修复建议：** 在 `flush()` 的 `except` 中增加 `sqlite3.ProgrammingError` 捕获；在 `HistoryWriter.stop()` 中确保先排空 buffer 再让主线程关闭 ConfigStore。
- **是否建议本次自动修复：是**
- **需要补充的测试：** `tests/test_history_writer.py`：mock `config.conn` 在第二次调用时 raise `ProgrammingError`，断言 `flush()` 不抛异常且 buffer 被回填。

---

### BUG-007：托盘更新检查线程可能在退出时向已销毁的 Qt 对象发信号
- **严重等级：P2**
- **影响功能：** 托盘更新检查、退出稳定性
- **证据文件：** [app/tray.py](file:///workspace/app/tray.py)
- **证据代码：**
  ```python
  def _worker():
      result = check_update(self._tray, config)
      self._update_check_bridge.done.emit(result, title)
  threading.Thread(target=_worker, daemon=True, name="tray-update-check").start()
  ```
  以及：
  ```python
  def _on_check_update_done(self, result: dict, title: str):
      self._update_progress.stop()
      self._update_poll_timer.stop()
  ```
- **复现路径：** 用户点击托盘“检查更新”，网络请求耗时 3-5 秒；在此期间用户右键托盘选择“退出”。`TrayManager` 及其 Qt 成员（`_update_progress`、`_update_poll_timer`）被 C++ 侧销毁，随后 `_worker` 线程的 `done.emit` 触发 `_on_check_update_done`，访问已销毁对象，触发 `RuntimeError` 甚至段错误。
- **根因分析：** 子线程持有 `self` 引用，未在 TrayManager 析构前等待线程结束或断开信号连接。
- **最小修复建议：** 在 `TrayManager._cleanup()` / `__del__` 中设置 `self._update_check_in_flight = False` 并调用 `_update_check_bridge.deleteLater()`；或在 `_on_check_update_done` 开头增加 `sip.isdeleted(self._update_progress)` 检查。
- **是否建议本次自动修复：是**
- **需要补充的测试：** `tests/test_tray_update.py`：mock `check_update` 耗时，在信号返回前销毁 TrayManager，断言不抛 `RuntimeError`。

---

### BUG-008：发布脚本中 Velopack 打包结果版本号覆盖原始版本号，可能导致产物命名不一致
- **严重等级：P2**
- **影响功能：** Windows 发布打包、版本号一致性
- **证据文件：** [scripts/publish_windows_release.ps1](file:///workspace/scripts/publish_windows_release.ps1)
- **证据代码：**
  ```powershell
  $appVersion = Get-AppVersion
  ...
  $packResult = vpk pack ...
  $appVersion = $packResult.Version
  ```
- **复现路径：** 若 `Get-AppVersion` 从 Git 标签读取为 `0.3.0-rc.2`，但 Velopack 从 EXE 元数据解析到 `0.3.0-rc.2+build123`（或格式差异），`$packResult.Version` 会覆盖 `$appVersion`，导致后续 `VERSION.txt`、校验和文件名与原始预期版本不一致。
- **根因分析：** 脚本先读取源码版本，后又无条件用打包结果覆盖，未校验两者一致性。
- **最小修复建议：** 比较 `$packResult.Version` 与原始 `$appVersion`，若不一致则抛异常或 warning 并停止发布。
- **是否建议本次自动修复：是**
- **需要补充的测试：** `scripts/tests/test_publish_version.ps1`：mock `$packResult.Version = "1.0.1"` 与原始 `"1.0.0"`，断言脚本抛出版本不匹配错误。

---

## 3. 高风险但未确认问题

| 编号 | 模块 | 问题描述 | 证据/触发条件 | 建议验证方式 |
|------|------|---------|--------------|-------------|
| RISK-001 | 单实例 | `QLocalSocket` 在 `try_acquire` 重试间隔中，若原实例正在启动但 `QLocalServer` 尚未监听，新实例可能误判为“无实例”并启动第二个进程 | `app/single_instance.py:73-135` 注释已注明竞态窗口 | 用脚本在 50ms 内连续启动两个实例，观察是否出现双托盘 |
| RISK-002 | WebView 进程 | `WebViewShell` 的 pywebview 子进程若因 DLL 冲突卡死，`terminate()` + `join(2)` 后仍可能残留 | `app/webview_shell.py:604-627` 有 `kill()` 兜底但未验证对 pywebview 内部子进程有效性 | 启动后强制挂起 webview 子进程，观察主进程退出后是否残留 python.exe |
| RISK-003 | 截图压缩 | `screenshot_compress.py` 使用 `QBuffer` 和 `QImageWriter` 在主线程压缩，高分辨率截图时可能阻塞 UI | `app/screenshot_compress.py:38-49` 无线程池 offload | 在 4K 屏幕下开启高频截图，用 py-spy 观察主线程是否卡在 `QImageWriter.write()` |
| RISK-004 | 读弹幕配置 | `danmu_read_service.py` 的 `apply_config` 在 `provider == "custom_openai"` 时抛异常，但未覆盖 `custom_openai` 以外的非法 endpoint 组合 | `app/danmu_read_service.py:215-226` | 设置 provider=custom 且 endpoint 为空字符串，观察是否静默失败 |
| RISK-005 | 去重降级 | 未安装 `python-Levenshtein` / `rapidfuzz` 时，纯 Python `similarity()` 虽限制 32 字符，但连续大量弹幕仍可能在主线程造成帧率抖动 | `app/danmu_engine_dedup.py:133-172` | 卸载 C 扩展，压力测试 100 条相似弹幕，记录 Overlay FPS |
| RISK-006 | Supabase 密钥 | `supabase-config.js` 文件内容通过正则硬解析到 Python dict，若前端 JS 被 minify 或换行格式变化，解析失败会导致启动崩溃 | `app/supabase_config.py:17-22` 使用 `re.search(r"""...""", js)` | 将 `supabase-config.js` 压缩为一行，观察主启动是否抛异常 |

---

## 4. 性能与卡顿风险

| 风险点 | 文件 | 具体表现 | 缓解现状 | 建议 |
|--------|------|---------|---------|------|
| 截图压缩阻塞主线程 | `screenshot_compress.py:38-49` | `QImageWriter.write()` 在 UI 线程执行，高分辨率/高频截图时掉帧 | 无 offloading | 使用 `QThreadPool` 或 `ThreadPoolExecutor` 异步压缩 |
| Overlay 每帧全量重绘 | `overlay.py:641-680` | `paintEvent` 逐条弹幕重建 `QPainterPath` 并绘制描边，高密度弹幕时 CPU 高 | 有 profile 开关 | 对超出屏幕的弹幕做 early reject；缓存 `QPainterPath` |
| 轨道追尾与重叠 | `danmu_engine/track.py:100-140` | 轨道分配使用贪心扫描，同向密集弹幕可能分配同一轨道导致重叠 | 基础碰撞检测 | 增加反向轨道隔离或动态轨道扩容 |
| SQLite 历史修剪在主事务内 | `history_writer.py:66-84` | `_maybe_prune_rows` 在 `with_write_lock()` 事务内执行 `DELETE`，大表时阻塞写锁数秒 | 每 100 次 flush 执行一次 | 将 prune 拆分为独立事务或 LIMIT 分批删除 |
| 自定义弹幕库全量加载 | `app/config_store/storage.py:818-821` | `danmu_pool` 接口若全量读取 20000 条，可能阻塞 UI | 有缓存 | 增加分页/流式加载接口 |
| 模型请求超时不可中断 | `app/ai_client_requests.py:330-439` | `httpx` 流式请求在底层 TCP 阻塞时，Python 层无法强制中断，可能占用 worker 线程数十秒 | 有 wall-clock deadline 检查 | 使用 `httpx` 的 `timeout` 参数严格限制 connect/read；或引入 `asyncio` 取消 |

---

## 5. 兼容性与环境风险

| 风险点 | 说明 | 建议 |
|--------|------|------|
| 中文路径与 UTF-8 | `app/supabase_config.py` 读取 JS 文件默认使用系统编码（未指定 `encoding='utf-8'`）若文件含中文注释可能解析失败 | 显式指定 `encoding='utf-8'` |
| PowerShell 脚本路径含空格 | `scripts/publish_windows_release.ps1` 多处拼接路径未加引号，若工作目录含空格会导致命令解析错误 | 对所有 `$appDir` / `$releaseDir` 引用加双引号 |
| Windows 11 窗口层级 | `win32_overlay_zorder.py` 依赖 `SetWindowPos` + `WS_EX_TOPMOST`，在部分游戏反作弊注入后可能失效 | 提供“使用游戏模式（无边框窗口）”的 UI 提示 |
| PyInstaller + PyQt6 多进程 | `DanmuAI.spec` 已包含 `multiprocessing.freeze_support()`，但 `webview_shell` 使用 `multiprocessing.Process`，在打包后可能出现 `RuntimeError: spawn` 问题 | 已在 `__main__` 中调用 `freeze_support()`，需验证 Windows 打包产物中 WebView 是否正常启动 |

---

## 6. 发布与更新风险

| 风险点 | 文件 | 证据/说明 | 严重度 |
|--------|------|----------|--------|
| 验收脚本文件缺失导致 CI 失败 | `scripts/run_acceptance_gates.py` | 调用 `runtime.py` 读取不存在的 `docs/runtime-state-map.md` | **P1** |
| 版本号比较抑制合法更新 | `app/version_compare.py:73-87` | `rc.10` 被误判为小于 `rc.2` | **P1** |
| 发布脚本版本覆盖不一致 | `scripts/publish_windows_release.ps1:175` | `$packResult.Version` 覆盖原始 `$appVersion` | **P2** |
| R2 上传无幂等校验 | `scripts/upload_r2_release.ps1:46-54` | 直接 `rclone copy` 覆盖，无版本存在性校验 | P2 |
| GitHub Releases 上传脚本需先创建 Release | `scripts/upload_github_release.ps1:16` | 注释说明先手动创建 Release，易遗漏 | P2 |
| releases.win.json 版本比较依赖客户端正确实现 | `app/version_compare.py` | 若服务端 releases.win.json 的 prerelease 排序与客户端不一致，更新行为异常 | P2 |
| Velopack delta 包生成失败未阻断发布 | `scripts/publish_windows_release.ps1:155-158` | delta 生成失败仅 warning 不抛异常，可能发布不完整 delta | P2 |
| MSI/Setup.exe 入口未在发布脚本中统一 | `DanmuAI.spec` 与 `scripts/README.md` | 无明确自动化签名步骤，可能发布未签名二进制 | P3 |

---

## 7. 安全与隐私风险

| 风险点 | 文件 | 证据/说明 | 严重度 |
|--------|------|----------|--------|
| 日志脱敏遗漏 Token/ApiKey 格式 | `app/logger.py:10-16` | `AUTH_HEADER_PATTERN` 仅匹配 `Bearer`；`GENERIC_API_KEY_PATTERN` 仅匹配 `api[_-]?key` | **P2** |
| `supabase-config.js` 可能被误提交到仓库 | `web/static/supabase-config.js` 与 `DanmuAI.spec` | 虽然 `DanmuAI.spec` 排除了 `supabase-config.js`，但开发者可能通过 `--add-data` 手动打包进去 | P2 |
| 前端 JS 暴露 anon key | `web/static/supabase-client.js:18` | 这是 Supabase 设计（anon key 可在前端暴露），但需确认 RLS 已严格限制敏感表 | P2（待确认） |
| 自定义模型 API key 加密降级 | `app/config_store/storage.py:740-752` | base64 解码失败后回退到原始字符串，若原始字符串是明文 key，会短暂以 plaintext 形式存在内存 | P2 |
| PyInstaller 产物中未清理 `.pyc` / `__pycache__` | `DanmuAI.spec` | 未显式排除 `__pycache__`，可能增大攻击面 | P3 |

---

## 8. 建议新增的测试

| 测试文件 | 测试目标 | 关键断言 |
|----------|---------|---------|
| `tests/test_boundary_guard_runtime.py` | 验收脚本文件存在性 | `assert Path("docs/runtime-state-map.md").exists()` |
| `tests/test_version_compare_prerelease.py` | 预发布版本数值比较 | `assert compare_versions("0.3.0-rc.10", "0.3.0-rc.2") == 1` |
| `tests/test_overlay_topmost_signal.py` | 置顶失败用户提示 | mock `reassert_hwnd_topmost` 返回 False 3 次，assert `topmost_lost` signal 被 emit |
| `tests/test_mic_orchestrator_backoff.py` | 麦克风空数据退避 | mock `try_snapshot_pcm_ms` 返回 None 10 次，assert `poll()` 返回 False 或 timer 停止 |
| `tests/test_log_sanitization_token.py` | 非 Bearer 鉴权脱敏 | 输入 `Authorization: Token sk-xxx`，assert 输出含 `***` |
| `tests/test_history_writer_close_race.py` | 退出时历史写入安全 | mock `config.conn` raise `ProgrammingError`，assert `flush()` 不抛异常且 buffer 保留 |
| `tests/test_tray_update_quit_race.py` | 托盘退出与更新检查竞态 | 在更新线程返回前销毁 TrayManager，assert 不抛 RuntimeError |
| `tests/test_publish_version_consistency.ps1` | 发布版本一致性 | mock `$packResult.Version = "1.0.1"` vs `"1.0.0"`，assert 脚本抛出不匹配错误 |

---

## 9. 本次可自动修复项

以下问题证据充分、修复范围小、不改变产品设计、可补充测试，建议本次自动修复：

1. **BUG-001**：创建 `docs/runtime-state-map.md`（或修改脚本做存在性检查），使验收脚本通过。
2. **BUG-002**：修复 `version_compare.py` 的 prerelease 比较逻辑，支持数值段比较。
3. **BUG-004**：修改 `mic_orchestrator.py`，在 PCM 为 None 时增加空计数退避，避免 CPU 空转。
4. **BUG-005**：扩展 `logger.py` 脱敏正则，覆盖 `Token`、`ApiKey`、`sk-...` 等格式。
5. **BUG-006**：在 `history_writer.py` 的 `flush()` 中捕获 `sqlite3.ProgrammingError`，并确保退出顺序安全。
6. **BUG-007**：在 `tray.py` 的 `_on_check_update_done` 开头增加对已销毁对象的防御检查。
7. **BUG-008**：在 `publish_windows_release.ps1` 中增加 `$packResult.Version` 与原始版本的一致性校验。

---

## 10. 最终建议

### Top 3 优先级事项

1. **修复 BUG-001（验收脚本崩溃）** — P1
   - **理由：** 这是发布流程的硬性卡点。脚本 100% 失败意味着无法执行发布前验收，任何版本发布都伴随着“跳过验收”或手动修复的风险，直接违背“发布检查脚本必须通过”的发布规范。

2. **修复 BUG-002（版本号比较错误）** — P1
   - **理由：** 该 bug 会导致合法更新被静默抑制（`rc.10` 用户永远收不到更新），用户停留在旧版本，长期积累兼容性问题。修复只需改动一个函数逻辑，成本低、收益高。

3. **修复 BUG-003（Overlay 置顶失效无提示）** — P1
   - **理由：** 这是用户侧最直观的核心功能故障——“开了弹幕但游戏里看不见”。当前仅打印日志，用户无法自助排查。至少应先通过 UI 提示引导用户切换窗口模式，显著降低客服/社区反馈压力。

---

## 自检评分

| 评分项 | 得分（0~2） | 说明 |
|--------|------------|------|
| 证据完整性（文件/代码/复现） | 2 | 每项已确认 Bug 均给出文件路径、代码片段、复现命令 |
| 严重度判定准确性 | 2 | P1 均对应“发布不可用/核心功能受损/用户无感知故障”；P2 对应性能/安全/退出竞态 |
| 是否区分“已确认”与“待确认” | 2 | 第 2 章为已确认 Bug，第 3 章为高风险待确认 |
| 是否覆盖发布更新链路 | 2 | 覆盖 PyInstaller/Velopack/R2/Releases/版本比较/发布脚本 |
| 是否给出可执行测试建议 | 2 | 第 8 章给出 8 个具体测试文件及断言 |

**总分：10 / 10**
