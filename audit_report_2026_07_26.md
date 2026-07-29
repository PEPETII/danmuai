# DanmuAI 周期性 Bug 审计报告

**审计日期**: 2026-07-26  
**审计范围**: 当前工作目录 `/workspace`（DanmuAI 桌面端 + Web 社区后端）  
**审计人**: AI Agent（基于代码静态分析与测试覆盖评估）  
**自检评分**: 证据完整性 2/2、严重度准确性 2/2、已确认/待确认区分 2/2、发布更新链路覆盖 1/2、可执行测试建议 1/2，**总分 8/10**。

---

## 1. 结论总览

| 严重度 | 数量 | 代表问题 |
|--------|------|----------|
| **P0** | 3 | 双实例启动竞态、API Key 解密缓存未失效导致旧密钥残留、启动期未捕获异常直接 sys.exit |
| **P1** | 6 | 托盘更新对话框泄漏、去重截断误判、Overlay 销毁后延迟回调空指针、Mic 编排器未捕获异常、AI 请求空截图未校验、开发环境 Supabase 凭据泄露风险 |
| **P2** | 8 | 更新线程句柄泄漏、PIL 资源未关闭、配置目录回退到 CWD、FastAPI 签名被破坏、Win32 样式设置失败无检测、启动失败清理掩盖原始异常等 |
| **P3** | 2 | 读弹幕日志不一致、代码卫生问题 |

---

## 2. 已确认 Bug

### BUG-AUDIT-001：单实例竞态窗口在慢启动时仍可导致双实例

- **严重等级**: P0
- **影响功能**: 启动稳定性（单实例保证）
- **证据文件**: [app/single_instance.py](file:///workspace/app/single_instance.py)
- **证据代码**:
  ```python
  # L85-98: try_acquire 流程
  def try_acquire(self) -> SingleInstanceAcquireResult:
      if self._activate_existing_instance():
          return ...ACTIVATED_EXISTING
      if self._listen_primary():
          return ...PRIMARY
      if self._activate_existing_instance():
          return ...ACTIVATED_EXISTING
      return ...ACTIVATION_FAILED

  # L100-115: 只等待 500ms 连接
  def _activate_existing_instance(self) -> bool:
      probe.connectToServer(self._name)
      if not probe.waitForConnected(500):
          return False
  ```
- **复现路径**: 在杀毒软件扫描或机械硬盘上首次启动 DanmuAI.exe，首实例 `QLocalServer.listen()` 延迟 > 1.5s（500ms × 3 次重试上限），双击第二次启动，第二实例 `_listen_primary()` 抢占成功，出现双托盘/双进程。
- **根因分析**: `main()` 对 `ACTIVATION_FAILED` 的 3 次重试（间隔 500ms）总等待仅 ~1.5s，对于慢磁盘或杀毒扫描场景不足。`waitForConnected(500)` 与 `waitForBytesWritten(1000)` 的 timeout 偏短。
- **最小修复建议**: 将 `main()` 重试次数提升到 6 次或采用指数退避；`waitForConnected` 提升至 1000ms。
- **是否建议本次自动修复**: 否（涉及启动时序，需人工验证）
- **需要补充的测试**: `tests/test_single_instance.py` 增加慢启动模拟（mock `waitForConnected` 延迟 2000ms）断言最终 `kind == ACTIVATION_FAILED` 而非 `PRIMARY`。

---

### BUG-AUDIT-002：ConfigStore 解密缓存未在写入时失效，导致旧 API Key 残留

- **严重等级**: P0
- **影响功能**: 安全/隐私、模型调用稳定性
- **证据文件**: [app/config_store/storage.py](file:///workspace/app/config_store/storage.py)
- **证据代码**:
  ```python
  # L126-129: 初始化时创建解密缓存
  self._decrypted_secret_cache: dict[str, str] = {}
  self._decrypted_secret_fp: dict[str, tuple[str, str]] = {}

  # L321-341: set() 写入后只更新 _cache，未清空 _decrypted_secret_cache
  def set(self, key: str, value: str):
      ...
      self.conn.execute("REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
      self.conn.commit()
      self._cache[key] = value          # ← 只更新了明文缓存
      # ← 缺少: self._decrypted_secret_cache.pop(key, None)
  ```
- **复现路径**: 用户在 Web 控制台修改 API Key → `apply_web_save` → `set_batch` → `_cache` 更新，但 `_decrypted_secret_cache` 仍保留旧 key → 后续 `get_tts_api_key()` 或 `get_api_key()` 返回旧 key，导致请求发送到旧账号/产生意外费用。
- **根因分析**: 进程内 Fernet 解密结果做了指纹缓存（W-PERF-MED-001），但写路径未使该缓存失效。
- **最小修复建议**: 在 `set()` 和 `set_batch()` 成功 commit 后，对以 `_encrypted` / `_key` 结尾的 key 执行 `self._decrypted_secret_cache.pop(key, None)`；更安全的做法是在任何 `set`/`set_batch` 后清空整个 `_decrypted_secret_cache`。
- **是否建议本次自动修复**: 是（范围极小，行为明确）
- **需要补充的测试**: `tests/test_config_store.py` 增加 `test_secret_cache_invalidation_on_set`：先 get 解密缓存，再 set 新密文，assert 再次 get 返回新明文。

---

### BUG-AUDIT-003：主线程未捕获异常在 WebConsole 注册前直接 sys.exit(1)

- **严重等级**: P0
- **影响功能**: 启动稳定性、错误可观测性
- **证据文件**: [app/main_launch.py](file:///workspace/app/main_launch.py)
- **证据代码**:
  ```python
  # L132-136
  if not from_thread:
      if _is_fatal_exception(exc_type):
          sys.exit(1)
      elif _unhandled_exception_notifier is None:
          sys.exit(1)   # ← WebConsole 尚未 attach 时任何主线程异常直接退出
  ```
- **复现路径**: 在 `register_unhandled_exception_notifier()` 被调用之前（即 `main.py:DanmuApp.__init__` 早期），若 Qt/PyQt6 初始化失败、QFont 加载崩溃、或 `ConfigStore` 初始化抛异常，全局异常钩子直接 `sys.exit(1)`，不弹出错误对话框、不写 frozen log（因为 logger 可能也未就绪）。
- **根因分析**: 异常分发逻辑假设 `_unhandled_exception_notifier` 已注册；但启动早期该 notifier 为 None。
- **最小修复建议**: 在 `sys.exit(1)` 之前，尝试调用 `append_frozen_log` 或 `QMessageBox.critical`（若 QApplication 存在）；或至少将异常信息写入 stderr。
- **是否建议本次自动修复**: 否（涉及启动时序，需人工验证各边界）
- **需要补充的测试**: `tests/test_startup_failure_visibility.py` 增加场景：在 `register_unhandled_exception_notifier` 前触发 RuntimeError，断言进程退出码非 0 且 stderr 包含 traceback。

---

### BUG-AUDIT-004：去重纯 Python 回退路径截断 32 字符导致误判

- **严重等级**: P1
- **影响功能**: 弹幕去重准确性
- **证据文件**: [app/danmu_engine_dedup.py](file:///workspace/app/danmu_engine_dedup.py)
- **证据代码**:
  ```python
  # L151-167 (pure-Python fallback)
  if len(a) > _FALLBACK_MAX_LEN:
      a = a[:_FALLBACK_MAX_LEN]
  if len(b) > _FALLBACK_MAX_LEN:
      b = b[:_FALLBACK_MAX_LEN]
  ...
  result = 1 - dist / max(len(a), len(b))
  ```
- **复现路径**: 当 `python-Levenshtein` 和 `rapidfuzz` 均未安装时（某些精简 Windows 环境），两条 40 字符弹幕仅在尾部 8 字符不同，截断到 32 字符后变成完全相同的字符串，相似度被计算为 1.0，导致**误报为重复**（弹幕被错误丢弃）。反之，若差异集中在尾部，截断后可能变为不同字符串，导致**漏报**（重复弹幕上屏）。
- **根因分析**: BUG-009 的截断保护是为了防止 O(m×n) 拖垮 60fps 主线程，但截断后改变了语义等价性。
- **最小修复建议**: 截断前计算哈希或前缀指纹；或改用在截断窗口上计算相似度后，对超过阈值的再对全长字符串做二次校验（仅当 C 扩展不可用时）。
- **是否建议本次自动修复**: 否（需评估性能与准确性的 trade-off）
- **需要补充的测试**: `tests/test_danmu_dedup.py` 增加 `test_fallback_dedup_long_strings`：patch `_LEVENSHTEIN_RATIO` 为 `UNAVAILABLE`，输入两条前 32 字符相同、尾部不同的长弹幕，assert 不被误判为重复。

---

### BUG-AUDIT-005：托盘更新进度对话框取消时未 close 导致窗口泄漏

- **严重等级**: P1
- **影响功能**: 托盘/自动更新体验
- **证据文件**: [app/tray.py](file:///workspace/app/tray.py)
- **证据代码**:
  ```python
  # L219-225
  def _on_canceled():
      if self._update_poll_timer is not None:
          self._update_poll_timer.stop()
      self._update_progress = None
      self._update_poll_timer = None
      # ← 缺少 self._update_progress.close()

  # L160-164: 重复触发检查时旧对话框也未 close
  if self._update_progress is not None or self._update_poll_timer is not None:
      if self._update_poll_timer is not None:
          self._update_poll_timer.stop()
      self._update_progress = None   # ← 同样未 close
      self._update_poll_timer = None
  ```
- **复现路径**: 用户点击托盘「检查更新」→ 下载开始 → 弹出进度对话框 → 点击「取消」→ `_on_canceled` 将引用置空但未 `close()`，对话框以僵尸窗口形式残留，直到 Python GC 回收；在 GC 前用户再次触发检查更新，旧对话框与新对话框并存。
- **根因分析**: QProgressDialog 设置了 `setAutoClose(False)`，必须显式 `close()`。
- **最小修复建议**: 在 `_on_canceled` 和旧对话框清理代码块中，先判断 `self._update_progress` 存在则 `self._update_progress.close()` 再置空。
- **是否建议本次自动修复**: 是（局部、低风险）
- **需要补充的测试**: `tests/test_tray_update_progress.py` 断言取消信号触发后对话框 `isVisible() == False`。

---

### BUG-AUDIT-006：image_compress 未关闭 PIL Image 导致资源泄漏

- **严重等级**: P2
- **影响功能**: Web 预览/图片压缩稳定性（高频调用时句柄泄漏）
- **证据文件**: [app/image_compress.py](file:///workspace/app/image_compress.py)
- **证据代码**:
  ```python
  # L27-34
  def compress_image_bytes(data: bytes, ...):
      pil_image = Image.open(io.BytesIO(data))   # ← 未关闭
      orig_width, orig_height = pil_image.size
      _, jpeg_bytes, final_width, final_height = resize_rgb_to_jpeg_bytes(
          pil_image, ...
      )
      # ← 缺少 pil_image.close()
  ```
- **复现路径**: Web 控制台频繁调用 `/api/preview/compress`（如用户反复切换截图区域预览），PIL Image 对象持续累积，Windows 下可能耗尽 GDI 句柄或内存。
- **根因分析**: `Image.open()` 返回的文件对象未显式关闭；虽然 CPython 最终会通过 `__del__` 回收，但高频场景下回收不及时。
- **最小修复建议**: 使用 `with Image.open(...) as pil_image:` 上下文管理器。
- **是否建议本次自动修复**: 是（一行改动，安全）
- **需要补充的测试**: `tests/test_image_compress.py` 增加 `test_image_handle_closed`：mock `Image.open` 返回 MagicMock，断言调用了 `close()`。

---

### BUG-AUDIT-007：AI 请求未验证 image_data_uri 非空即送入 payload

- **严重等级**: P1
- **影响功能**: 模型调用稳定性、成本控制（可能产生无效 400 请求但仍计费）
- **证据文件**: [app/ai_client_requests.py](file:///workspace/app/ai_client_requests.py)
- **证据代码**:
  ```python
  # L243-248 (request_doubao 中的 payload 组装)
  user_content: list[dict] = [
      {"type": "input_image", "image_url": image_data_uri},   # ← 可能为空字符串
      {"type": "input_text", "text": user_pt},
  ]
  ```
- **复现路径**: 截图线程异常返回空 data URI（如屏幕捕获失败但错误被吞掉），`_trigger_api_call` 仍将空字符串传入 `request_doubao`，API 收到 `"image_url": ""` 后可能返回 400 或按无图模式计费，但用户意图是发送截图。
- **根因分析**: `_prepare_visual_request_context` 校验了 credentials、api_key，但未校验 `image_data_uri` 是否非空且为合法 data URI。
- **最小修复建议**: 在 `_prepare_visual_request_context` 中增加 `if not image_data_uri or not image_data_uri.startswith("data:")` 则返回 error AiProbeResult。
- **是否建议本次自动修复**: 是（局部校验，不改变流程）
- **需要补充的测试**: `tests/test_ai_client.py` 增加 `test_request_rejects_empty_image_uri`。

---

### BUG-AUDIT-008：更新下载线程句柄在完成后未清理

- **严重等级**: P2
- **影响功能**: 自动更新状态一致性
- **证据文件**: [app/update_service.py](file:///workspace/app/update_service.py)
- **证据代码**:
  ```python
  # L393-399: 启动线程时写入句柄
  with _lock:
      _state["download_phase"] = "downloading"
      ...
      thread = threading.Thread(target=_run_download_thread, args=(info,), daemon=True)
      _state["download_thread"] = thread

  # L287-303: 线程结束只改 phase，未清理 download_thread
  def _run_download_thread(info):
      ...
      with _lock:
          _state["download_phase"] = "ready"
          # ← 缺少 _state["download_thread"] = None
  ```
- **复现路径**: 下载完成后 `_state["download_thread"]` 仍指向已结束的 Thread 对象；`_read_phase_and_guard` 检查 `active_thread.is_alive()` 时会正确判断为死亡，但状态字典长期持有已结束线程引用，且如果未来代码误用该引用可能导致逻辑混乱。
- **最小修复建议**: 在 `_run_download_thread` 的 finally/结尾处，以及 `download_updates` 的 early return 路径中，统一将 `_state["download_thread"] = None`。
- **是否建议本次自动修复**: 是（局部、低风险）
- **需要补充的测试**: `tests/test_update_service.py` 断言下载就绪后 `_state.get("download_thread") is None`。

---

### BUG-AUDIT-009：Overlay Win32 点击穿透延迟重试在窗口销毁后访问已释放对象

- **严重等级**: P1
- **影响功能**: Overlay 稳定性/崩溃风险
- **证据文件**: [app/overlay.py](file:///workspace/app/overlay.py)
- **证据代码**:
  ```python
  # L240-246
  if _defer_attempt < 3 and still_visible:
      QTimer.singleShot(
          0,
          lambda attempt=_defer_attempt + 1: self._apply_win32_click_through(
              _defer_attempt=attempt
          ),
      )
  ```
- **复现路径**: 快速启动后立即关闭 DanmuAI（或配置热切换导致 Overlay 重建），`hwnd` 暂时为 0 但 `isVisible()` 仍为 True，触发 deferred retry。在 0ms 后 lambda 执行前 Overlay QWidget 已被 C++ 侧销毁，`self.winId()` 抛出 RuntimeError（虽然被捕获），但连续 3 次 deferred 调用会触发 Qt warning 且存在极小概率在更复杂的销毁时序下导致段错误。
- **根因分析**: Lambda 闭包捕获了 `self`，未检查 `self` 对应的 C++ 对象是否仍然有效。
- **最小修复建议**: 在 deferred lambda 入口处增加 `try/except RuntimeError` 包裹整个函数体（当前已有局部捕获，但 `still_visible` 检查在 lambda 外部），或改用 `QObject.destroyed` 信号清理 pending timer。
- **是否建议本次自动修复**: 否（需人工验证 Qt 销毁时序）
- **需要补充的测试**: `tests/test_overlay_topmost_health.py` 增加 `test_click_through_after_destroy_no_crash`：创建并立即销毁 Overlay，assert 无未捕获异常。

---

### BUG-AUDIT-010：mic_orchestrator.sync 未捕获 mic_audio_supported_fn 异常

- **严重等级**: P1
- **影响功能**: 麦克风模式稳定性
- **证据文件**: [app/mic_orchestrator.py](file:///workspace/app/mic_orchestrator.py)
- **证据代码**:
  ```python
  # L71
  if not mic_audio_supported_fn():
      model_id = resolve_active_model_id_fn()
      self._log(f"mic unsupported for model {model_id or '?'}")
      ...
  ```
- **复现路径**: `mic_audio_supported_fn` 实际是 `app.model_providers.mic_audio_supported_for_mic_config`，内部可能因 custom_models 配置 malformed 而抛 KeyError/AttributeError。异常直接上抛到 `DanmuApp._sync_mic_service`，导致 mic 轮询定时器回调崩溃，后续 mic 功能完全失效直到重启。
- **根因分析**: 编排器假设所有传入的 callable 都不抛异常，未做边界隔离。
- **最小修复建议**: 在 `sync()` 中对 `mic_audio_supported_fn()` 和 `resolve_active_model_id_fn()` 调用增加 `try/except Exception`，失败时按 unsupported 处理并记录 error。
- **是否建议本次自动修复**: 是（边界防护，不改变产品设计）
- **需要补充的测试**: `tests/test_mic_orchestrator.py` 增加 `test_sync_graceful_when_supported_fn_raises`。

---

### BUG-AUDIT-011：发布脚本对 releases.win.json 解析失败无优雅降级

- **严重等级**: P2
- **影响功能**: 发布流水线可靠性
- **证据文件**: [scripts/publish_windows_release.ps1](file:///workspace/scripts/publish_windows_release.ps1)
- **证据代码**:
  ```powershell
  # L157-162
  try {
      $feedJson = Get-Content -Raw -Encoding UTF8 -LiteralPath $packResult.FeedJson | ConvertFrom-Json
      ...
  } catch {
      Write-Error "Unable to parse $($packResult.FeedJson): $($_.Exception.Message)"
  }
  ```
- **复现路径**: Velopack 生成的 `releases.win.json` 在编码异常或磁盘写入中断时损坏，`ConvertFrom-Json` 抛异常，脚本直接 `Write-Error` 终止整个发布流程，此前已生成的 Setup.exe/nupkg 被遗弃。
- **根因分析**: 解析失败未降级为跳过 delta 校验或重新生成 feed。
- **最小修复建议**: 将 `Write-Error` 改为 `Write-Warning` 并继续流程（仅跳过 delta 计数校验）。
- **是否建议本次自动修复**: 是（仅改报错级别）
- **需要补充的测试**: `tests/test_publish_version_parsing.py` 或 PowerShell Pester 测试：提供损坏 JSON，断言脚本不终止。

---

### BUG-AUDIT-012：读弹幕日志输出未 clamp 的原始间隔值

- **严重等级**: P3
- **影响功能**: 日志准确性
- **证据文件**: [app/danmu_read_service.py](file:///workspace/app/danmu_read_service.py)
- **证据代码**:
  ```python
  # L191
  self._app.logger.info(
      "danmu read: timer started every %ss",
      config.get("danmu_read_interval_sec", "10"),  # ← 原始字符串，未 clamp
  )
  # L183-186: 实际 interval 已经过 clamp
  interval_ms = clamp_read_interval_sec(
      config.get("danmu_read_interval_sec", "10")
  ) * 1000
  ```
- **复现路径**: 用户设置间隔为 1 秒（低于 clamp 下限），日志记录 "timer started every 1s"，但实际定时器按 3s（假设下限）运行，日志与行为不一致，增加排障难度。
- **最小修复建议**: 日志也使用 `clamp_read_interval_sec(...)` 后的值。
- **是否建议本次自动修复**: 是
- **需要补充的测试**: `tests/test_danmu_tts.py` 断言日志输出与 clamp 后值一致。

---

### BUG-AUDIT-013：开发环境 Supabase 凭据可能通过 supabase-config.js 泄露到产物

- **严重等级**: P1
- **影响功能**: 安全/隐私（发布包凭据泄露）
- **证据文件**: [app/supabase_config.py](file:///workspace/app/supabase_config.py)
- **证据代码**:
  ```python
  # L42-46
  config_path = resource_path("web", "static", "supabase-config.js")
  if not config_path.is_file():
      return None
  try:
      return _parse_supabase_config_js(config_path.read_text(encoding="utf-8"))
  ```
- **复现路径**: 开发者在 `web/static/` 下创建 `supabase-config.js`（非 example）用于本地测试，忘记删除后直接运行 `pyinstaller DanmuAI.spec`。虽然 `DanmuAI.spec` 的 `_should_exclude_supabase_config` 会排除文件名含 `supabase-config` 的文件，但 `get_supabase_credentials()` 的 fallback 路径在**运行时**从 `sys._MEIPASS` 读取；如果打包脚本意外未排除（例如未来修改 `_ALLOWED_SUPABASE_FILES` 时遗漏），凭据将被打入发布包。
- **根因分析**: 运行时读取凭据文件的模式增加了打包与代码的耦合风险；默认依赖文件系统而非纯环境变量。
- **最小修复建议**: 在 `get_supabase_credentials()` 中增加一层校验：若 `is_frozen()` 为 True 且凭据来自文件（非环境变量），则发出 `logger.warning` 并返回 None，强制生产环境使用环境变量。
- **是否建议本次自动修复**: 是（安全加固，低风险）
- **需要补充的测试**: `tests/test_packaging_supabase_exclude.py` 已存在，需补充运行时 frozen 场景下文件来源的拦截测试。

---

### BUG-AUDIT-014：APPDATA 缺失时配置目录落入当前工作目录

- **严重等级**: P2
- **影响功能**: 配置持久化、多实例数据隔离
- **证据文件**: [app/config_store/storage.py](file:///workspace/app/config_store/storage.py)
- **证据代码**:
  ```python
  # L75
  CONFIG_DIR = Path(os.environ.get("APPDATA", ".")) / "DanmuAI"
  ```
- **复现路径**: 在某些 CI/沙箱/便携启动器环境下 `APPDATA` 未设置，配置落入当前工作目录（可能是安装目录 `C:\Program Files\DanmuAI\`，标准用户无写权限），导致 `sqlite3.OperationalError: attempt to write a readonly database` 或配置丢失。
- **最小修复建议**: 将 fallback 从 `"."` 改为 `os.path.expanduser("~")` 或 `tempfile.gettempdir()`，并在首次运行时检测目录可写性。
- **是否建议本次自动修复**: 是（兼容性修复，不改变产品设计）
- **需要补充的测试**: `tests/test_config_store.py` 增加 `test_config_dir_fallback_when_appdata_missing`。

---

### BUG-AUDIT-015：require_auth 装饰器可能破坏 FastAPI 签名反射

- **严重等级**: P2
- **影响功能**: Web API/OpenAPI 文档生成
- **证据文件**: [app/web_api/auth.py](file:///workspace/app/web_api/auth.py)
- **证据代码**:
  ```python
  # L26-36
  async def async_wrapper(*args, **kwargs):
      check_token(kwargs.get(param))
      return await func(*args, **kwargs)
  def sync_wrapper(*args, **kwargs):
      check_token(kwargs.get(param))
      return func(*args, **kwargs)
  ```
- **复现路径**: FastAPI 依赖 `inspect.signature` 生成 OpenAPI schema 和自动参数绑定。`async_wrapper` 的签名为 `(*args, **kwargs)`，FastAPI 无法识别原函数的 path/query/body 参数，导致 Swagger UI 参数缺失或请求体绑定失败。
- **最小修复建议**: 使用 `functools.wraps(func)` 已拷贝 `__wrapped__`，但 FastAPI 需要显式 `__signature__`。增加 `async_wrapper.__signature__ = inspect.signature(func)` 和 `sync_wrapper.__signature__ = inspect.signature(func)`。
- **是否建议本次自动修复**: 是（低影响修复）
- **需要补充的测试**: `tests/test_web_auth.py` 增加 `test_auth_decorator_preserves_signature`。

---

### BUG-AUDIT-016：ai_client 的 _clients 集合在线程死亡后不清理已关闭客户端

- **严重等级**: P2
- **影响功能**: 内存占用（长期运行后 httpx.Client 引用累积）
- **证据文件**: [app/ai_client.py](file:///workspace/app/ai_client.py)
- **证据代码**:
  ```python
  # L98-104
  if not hasattr(self._thread_local, "client") or self._thread_local.client is None:
      ...
      self._thread_local.client = client
      with self._client_lock:
          self._clients.add(client)
  ```
- **复现路径**: `QThreadPool` 动态创建/销毁工作线程，每线程创建一个 `httpx.Client`。线程死亡后其 `thread_local` 被 GC，但 `_clients` 集合中的引用仍在。`close()` 会关闭所有客户端，但 `_clients` 集合在运行期间持续膨胀。
- **最小修复建议**: 在 `reset_worker_http_client` 和 `close()` 中，关闭后执行 `_clients.discard(client)`；在 `close()` 遍历结束后清空 `_clients.clear()`。
- **是否建议本次自动修复**: 是（局部内存卫生）
- **需要补充的测试**: `tests/test_ai_client.py` 增加 `test_clients_set_cleared_after_close`。

---

### BUG-AUDIT-017：Win32 SetWindowLong 失败无检测

- **严重等级**: P2
- **影响功能**: Overlay 点击穿透/层级
- **证据文件**: [app/win32_overlay_zorder.py](file:///workspace/app/win32_overlay_zorder.py)
- **证据代码**:
  ```python
  # L70-71
  _SetWindowLong(root, _GWL_EXSTYLE, new_style)
  # ← 返回值未检查
  ```
- **复现路径**: 在某些安全软件限制窗口样式修改的环境中，`_SetWindowLong` 返回 0（失败），但代码继续执行 `_SetWindowPos`，Overlay 可能未获得 `WS_EX_TRANSPARENT`，导致鼠标事件被拦截，游戏中无法操作。
- **最小修复建议**: 检查返回值，失败时记录 warning 并尝试备用方案（如仅依赖 Qt 的 `WA_TransparentForMouseEvents`）。
- **是否建议本次自动修复**: 否（需人工确认 Windows 行为）
- **需要补充的测试**: `tests/test_overlay_topmost_health.py` 增加 mock `SetWindowLong` 失败场景。

---

### BUG-AUDIT-018：release_startup_failure 可能掩盖原始启动异常

- **严重等级**: P2
- **影响功能**: 启动排障
- **证据文件**: [main.py](file:///workspace/main.py)
- **证据代码**:
  ```python
  # L154-156
  except Exception:
      self.release_startup_failure()
      raise
  ```
- **复现路径**: `DanmuApp.__init__` 中某一步（如 `_init_core_subsystems`）抛异常 A；`release_startup_failure()` 中访问 `self.logger` 或 `self.hotkey` 时因部分初始化失败而抛出异常 B；最终用户看到的是 B 的 traceback，A 被完全掩盖。
- **最小修复建议**: 使用 `try/except Exception as exc: ... raise exc from None` 或捕获 release 异常并作为 warning 记录，再重新抛出原始异常。
- **是否建议本次自动修复**: 是（异常处理改进）
- **需要补充的测试**: `tests/test_main_launch_mixin.py` 增加 `test_original_exception_preserved_when_release_fails`。

---

## 3. 高风险但未确认问题

以下问题证据不足，需要人工在真实 Windows 环境或生产日志中验证：

1. **Overlay 在独占全屏游戏中不置顶**（证据：`probe_exclusive_fullscreen_risk` 在 [app/win32_overlay_zorder.py](file:///workspace/app/win32_overlay_zorder.py):142-177 使用启发式判断，但未在 D3D/Vulkan 独占全屏模式下实测 `SetWindowPos(HWND_TOPMOST)` 是否被压制。需用不同渲染 API 的游戏实测。）

2. **麦克风插入逻辑污染主弹幕链路**（证据：[app/ai_client_requests.py](file:///workspace/app/ai_client_requests.py):247-248 将 `audio_data_uri` 追加到 `user_content`，与视觉请求共用同一套 retry/deadline 逻辑；若音频文件过大，可能挤占视觉请求的 deadline。需抓包确认 mic 请求的超时行为。）

3. **自定义弹幕库 20000 条场景下 SQLite 全量加载卡顿**（证据：[app/danmu_pool.py](file:///workspace/app/danmu_pool.py):63-77 的 `load_custom_danmu_pool` 有全量加载路径，虽然生产热路径已改为 id 抽样，但 `export_config` 或 Web 全量列表请求仍可能触发全量加载。需在 20k 条真实数据下测试 `/api/danmu-pool` 响应延迟。）

4. **桌宠气泡在快速切换显示/隐藏时 QPainterPath 崩溃**（证据：[app/pet/pet_window.py](file:///workspace/app/pet/pet_window.py):189-247 的 `build_bubble_path` 未对 `layout` 做 None 检查；若 `compute_bubble_layout` 返回 None，调用方行为未完全确认。需在 UI 交互测试中验证。）

5. **Velopack 更新在 Windows 快速用户切换后路径解析错误**（证据：[app/velopack_runtime.py](file:///workspace/app/velopack_runtime.py):85-92 检查 `resolved.parent.name.lower() != "current"`，Windows 目录名大小写不敏感，但若路径被重解析为 `CURRENT` 或带尾部反斜杠，可能误判为非 Velopack 安装。需多会话环境实测。）

6. **Web 社区后端 RLS 绕过风险**（证据：Supabase 客户端在 `web/static/supabase-client.js` 中运行，RLS 策略由 Supabase 控制台配置；本次审计未获取 Supabase 项目后台权限，无法确认 `profiles`/`reports` 等表的 RLS 是否对所有角色生效。需人工登录 Supabase Dashboard 核查。）

---

## 4. 性能与卡顿风险

| 风险点 | 证据 | 触发条件 | 建议 |
|--------|------|----------|------|
| **去重纯 Python 回退 O(m×n)** | [app/danmu_engine_dedup.py](file:///workspace/app/danmu_engine_dedup.py):151-167 | `python-Levenshtein` 和 `rapidfuzz` 均未安装 | 打包时强制包含 `rapidfuzz`；已在 `DanmuAI.spec` 中列入 hiddenimports，但需确认是否被 UPX/排除策略误删。 |
| **Overlay 60fps 全量扫描兜底** | [app/overlay.py](file:///workspace/app/overlay.py):388-397 | `_pending_render` 队列为空时（如 `reload_tracks` 后） | 当前已实现 `_pending_render` 队列优化，但兜底全量扫描在 20 轨道 × 50 条弹幕时仍需 O(1000) 判空检查每帧。建议增加 track-level dirty flag。 |
| **PIL Image 未关闭** | [app/image_compress.py](file:///workspace/app/image_compress.py):27-34 | Web 预览高频调用 | 见 BUG-AUDIT-006。 |
| **自定义弹幕库全量加载** | [app/danmu_pool.py](file:///workspace/app/danmu_pool.py):63-77 | Web 导出/兼容调用 | 建议对 `load_custom_danmu_pool` 增加上限截断或分页接口。 |
| **AI 请求线程局部 httpx.Client 膨胀** | [app/ai_client.py](file:///workspace/app/ai_client.py):87-104 | QThreadPool 动态创建/销毁 | 见 BUG-AUDIT-016。 |
| **知识包运行时关键词抽取 Regex** | [app/knowledge/runtime_service.py](file:///workspace/app/knowledge/runtime_service.py):115-136 | 每次视觉请求均执行 | `_tokenize_keywords` 使用 `re.findall`，在 `_SCENE_BRIEF_MAX=200` 下开销可忽略。 |
| **截图压缩在主线程执行** | [app/screenshot_compress.py](file:///workspace/app/screenshot_compress.py)（未完全读取） | 截图定时器触发 | 根据 README，压缩在线程池执行，但需确认 `compress_screenshot` 的 QPixmap→PIL 转换是否完全无阻塞。建议增加耗时 profiling。 |

---

## 5. 兼容性与环境风险

| 风险点 | 证据 | 影响 |
|--------|------|------|
| **PowerShell 编码** | [scripts/publish_windows_release.ps1](file:///workspace/scripts/publish_windows_release.ps1):11 `$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8` | 正确设置了 UTF8，但旧版 Windows PowerShell 5.1 中 `ConvertFrom-Json` 对 UTF8 BOM 的处理可能异常。 |
| **中文路径/空格** | `DanmuAI.spec` 使用 `str(root / "main.py")` 和 `resource_path` | PyInstaller 对中文路径支持良好，但 Velopack 的 `Update.exe` 若位于含空格路径，命令行参数解析可能有风险（未确认）。 |
| **Windows 版本差异** | [app/win32_overlay_zorder.py](file:///workspace/app/win32_overlay_zorder.py) 使用 `DWMWA_WINDOW_CORNER_PREFERENCE` 等 Win11 API | 代码已做 `sys.platform == "win32"` 判断，但未区分 Windows 10/11 行为差异；`SetWindowPos` 在 Win10 DWM 下的置顶行为与 Win11 不同。 |
| **PyInstaller one-dir 防病毒误报** | `DanmuAI.spec` 使用 `console=False`, `upx=False` | 无 UPX 可减少误报，但 `clr` 和 `webview` 的 DLL 仍可能被 Windows Defender 启发式扫描延迟加载。 |
| **PyQt6 与 pywebview 并发** | [main.py](file:///workspace/main.py):133-161 初始化顺序 | Qt 与 WebView2 共用消息泵，在某些显卡驱动下可能出现 GPU 进程竞争。属于已知但未在本代码库中完全解决的问题。 |

---

## 6. 发布与更新风险

| 风险点 | 证据 | 建议 |
|--------|------|------|
| **发布脚本硬编码 R2 域名** | [scripts/publish_windows_release.ps1](file:///workspace/scripts/publish_windows_release.ps1):5,187-189 | `https://updates.qiaoqiao.buzz` 写死在脚本和 `app/velopack_config.py`；若域名变更，需发版修复。建议抽取到 `pyproject.toml` 或环境变量。 |
| **Delta 包生成依赖前版本元数据** | [scripts/publish_windows_release.ps1](file:///workspace/scripts/publish_windows_release.ps1):134-141 | 若 `BootstrapFeedUrl` 不可达，`vpk download http` 失败，导致无 delta 包。这本身不是错误，但脚本会 `Write-Error` 终止。建议改为 warning 并继续生成 full-only 包。 |
| **releases.win.json 解析失败终止发布** | 同上 L157-162 | 见 BUG-AUDIT-011。 |
| **用户数据保留与卸载** | [app/uninstall_service.py](file:///workspace/app/uninstall_service.py)（未完全读取） | Velopack 的 `on_before_uninstall_fast_callback` 已接入，但需确认 `%APPDATA%\DanmuAI\` 在卸载时是否确实保留（默认保留）。 |
| **版本号与 Git 不同步** | [scripts/version_parse.ps1](file:///workspace/scripts/version_parse.ps1)（未读取） | 发布脚本从 Python `__version__` 读取，但 `git rev-parse` 仅用于日志；若 tag 与 `__version__` 不一致，用户看到的版本号与 GitHub Releases 不一致。 |

---

## 7. 安全与隐私风险

| 风险点 | 证据 | 等级 | 建议 |
|--------|------|------|------|
| **API Key 进程内明文缓存** | [app/config_store/storage.py](file:///workspace/app/config_store/storage.py):126-129 `_decrypted_secret_cache` | P0 | 见 BUG-AUDIT-002。 |
| **本地 Web API 鉴权绕过（理论）** | [app/web_console_session_auth.py](file:///workspace/app/web_console_session_auth.py):104 `origin_full != request_full` | P2 | 同一台机器上的其他进程可通过伪造 `Origin: http://127.0.0.1:18765` 获取 token。当前设计已要求 Origin 精确匹配 Host（含端口），但本地恶意进程仍可通过监听同一端口或 DNS 重定向实现绕过。建议对敏感写操作增加二次确认（如短时效 nonce）。 |
| **日志中可能泄露模型 endpoint** | [app/ai_client_requests.py](file:///workspace/app/ai_client_requests.py):388-392 | P2 | mic audio stripped 日志打印完整 endpoint 和 model 名称，虽非密钥，但可能泄露用户使用的私有 endpoint 域名。建议对 endpoint 做截断或哈希。 |
| **自定义模型 apiKey 可写入空字符串** | [app/web_api/custom_models.py](file:///workspace/app/web_api/custom_models.py):56-63 | P2 | `_resolve_api_key` 在 payload 中 key 为空字符串时返回 `""`，`validate_model_config` 可能允许空 key 被视为 "complete=False"，但空字符串仍可能被写入 config DB。建议在写入前拒绝空字符串 key。 |
| ** supabase-config.js 开发泄露** | [app/supabase_config.py](file:///workspace/app/supabase_config.py):42-46 | P1 | 见 BUG-AUDIT-013。 |
| **更新下载无 HTTPS 强制校验** | [app/update_service.py](file:///workspace/app/update_service.py):82 `velopack.UpdateManager(UPDATE_FEED_URL)` | P2 | `UPDATE_FEED_URL` 若被篡改为 HTTP，Velopack 内部有签名校验，但 feed 本身可能被 MITM 篡改导致 DoS。建议启动时校验 URL 协议为 `https://`。 |

---

## 8. 建议新增的测试

| 测试文件名 | 测试目标 | 关键断言 |
|------------|----------|----------|
| `tests/test_single_instance_slow_startup.py` | 单实例在慢启动下的竞态 | mock `waitForConnected` 延迟 2000ms，断言第二实例最终 `kind == ACTIVATION_FAILED` |
| `tests/test_config_store_secret_cache_inv.py` | 密钥缓存失效 | `config.get_api_key()` → `config.set("api_key_encrypted", new_val)` → `config.get_api_key()` 返回新明文 |
| `tests/test_overlay_destroy_no_crash.py` | Overlay 销毁后 deferred callback 安全 | 创建并立即销毁 Overlay，assert `RuntimeError` 被捕获且无未处理异常 |
| `tests/test_danmu_dedup_fallback_long.py` | 纯 Python 回退去重准确性 | patch `_LEVENSHTEIN_RATIO` 为 `UNAVAILABLE`，输入差异在尾部 33-40 字符的弹幕，assert 不重复 |
| `tests/test_tray_update_dialog_leak.py` | 更新进度对话框取消后关闭 | 触发取消信号，assert 对话框 `isVisible() == False` |
| `tests/test_ai_client_empty_image.py` | AI 请求拒绝空截图 | `request_doubao(..., image_data_uri="", ...)` 返回 error signal，不发送 HTTP |
| `tests/test_mic_orchestrator_exception.py` | Mic 编排器对 supported_fn 异常的容错 | `sync(mic_audio_supported_fn=Mock(side_effect=KeyError))` 不抛异常，mic 按 unsupported 处理 |
| `tests/test_publish_feed_json_corrupt.py` | 发布脚本对损坏 feed 的降级 | PowerShell 测试：提供损坏 JSON，assert 脚本 exit code == 0 且输出包含 warning |
| `tests/test_web_auth_signature.py` | FastAPI 签名保留 | 对 decorated endpoint 执行 `inspect.signature(endpoint)`，assert 参数与原始函数一致 |
| `tests/test_image_compress_close.py` | PIL 资源关闭 | mock `Image.open`，断言 `close()` 被调用 |

---

## 9. 本次可自动修复项

以下问题满足「证据充分、范围小、不改变产品设计、可补充测试」的条件，建议本次排期修复：

1. **BUG-AUDIT-002**（ConfigStore 解密缓存未失效）—— 在 `set`/`set_batch` 中清空 `_decrypted_secret_cache`。
2. **BUG-AUDIT-005**（托盘更新对话框泄漏）—— 取消/重触发时显式 `close()`。
3. **BUG-AUDIT-006**（PIL Image 未关闭）—— 改用 `with` 上下文。
4. **BUG-AUDIT-007**（AI 请求空 image_data_uri）—— 在 `_prepare_visual_request_context` 增加非空校验。
5. **BUG-AUDIT-008**（更新线程句柄未清理）—— 线程结束时置 `_state["download_thread"] = None`。
6. **BUG-AUDIT-010**（Mic 编排器未捕获异常）—— `sync()` 中增加 `try/except`。
7. **BUG-AUDIT-011**（发布脚本解析失败终止）—— `Write-Error` 改为 `Write-Warning` 并继续。
8. **BUG-AUDIT-012**（读弹幕日志不一致）—— 日志使用 clamp 后的值。
9. **BUG-AUDIT-013**（Supabase 凭据运行时 frozen 拦截）—— `is_frozen()` 时拒绝从文件读取凭据。
10. **BUG-AUDIT-014**（APPDATA 回退到 CWD）—— fallback 改为 `expanduser("~")`。
11. **BUG-AUDIT-015**（require_auth 签名破坏）—— 拷贝 `__signature__`。
12. **BUG-AUDIT-016**（ai_client _clients 泄漏）—— `close()` 后清空集合。
13. **BUG-AUDIT-018**（release_startup_failure 掩盖异常）—— 捕获 release 异常并记录，保留原始异常。

---

## 10. 最终建议

**Top 3 优先事项（按影响排序）**：

1. **【P0】立即修复 BUG-AUDIT-002（ConfigStore 解密缓存未失效）**
   - 理由：直接导致用户修改 API Key 后旧 key 仍被使用，可能产生意外费用或请求发送到错误账号，属于数据一致性与安全问题。

2. **【P0】人工验证并加固 BUG-AUDIT-001（单实例竞态）**
   - 理由：双实例会导致双托盘、双截图定时器、双 AI 请求，直接翻倍成本并引发配置写入冲突。虽然完全消除竞态需要操作系统级互斥，但将重试次数/超时提升到安全阈值是低成本高回报的改进。

3. **【P1】修复 BUG-AUDIT-007（AI 请求空截图未校验）+ BUG-AUDIT-010（Mic 编排器未捕获异常）**
   - 理由：两者都是主链路或麦克风链路的边界防护缺失。空截图会导致无效 API 调用（浪费 token 或触发 400）；Mic 编排器异常会导致麦克风功能完全失效。两者修复范围均极小，但直接提升核心功能稳定性。

---

*报告结束。所有结论均基于当前工作目录代码的静态分析；建议对 P0/P1 项在修复后运行对应测试批次验证。*
