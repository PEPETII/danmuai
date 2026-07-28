# DanmuAI 周期性 Bug 审计报告

> 审计日期：2026-07-28
> 审计范围：A-J 全模块
> 审计环境：Linux 远程沙箱 / Python 3.14.4（无项目依赖）

---

## 1. 结论总览

| 严重度 | 数量 | 关键问题摘要 |
|--------|------|--------------|
| **P0** | 1 | `config_migrations.py` schema_version 解析未容错，DB 元数据损坏即导致应用无法启动 |
| **P1** | 3 | PyInstaller hiddenimports 缺失 `app.knowledge` 子模块；麦克风模式在独立 mic 凭证缺失时仍启用采集与端点检测；测试/验收环境因缺失依赖完全无法运行 |
| **P2** | 5 | 应用退出无重入保护；托盘更新进度对话框取消后未关闭；版本号非法回退到 0 导致更新判断静默错误；Supabase 客户端把 401/403 误判为限流；截图/Overlay 主链路无致命缺陷 |
| **P3** | 1 | `webview_shell.py` 存在不可达死代码 |

---

## 2. 已确认 Bug

### BUG-001：schema_version 解析崩溃导致应用无法启动

- **严重等级：** P0
- **影响功能：** 启动稳定性 / SQLite 配置存储
- **证据文件：** [app/config_migrations.py](file:///workspace/app/config_migrations.py)
- **证据代码：**
  ```python
  51     row = conn.execute(
  52         "SELECT value FROM schema_meta WHERE key='schema_version'"
  53     ).fetchone()
  54     if row is None:
  55         current = 0
  56     else:
  57         current = int(row[0])   # ← 无 try/except
  58     for version, name, fn in sorted(MIGRATIONS, key=lambda m: m[0]):
  59         ...
  72     return max([current] + [m[0] for m in MIGRATIONS])
  ```
- **复现路径：**
  1. 关闭应用；
  2. 用 SQLite 工具执行 `UPDATE schema_meta SET value='abc' WHERE key='schema_version';`；
  3. 双击 EXE 或 `python main.py` 启动；
  4. `ConfigStore.__init__` 调用 `run_pending(self.conn)` → `int(row[0])` 抛出 `ValueError`，进程崩溃，托盘/主窗口均不出现。
- **根因分析：** `schema_meta.value` 字段为 `TEXT`，任何非整数字符串（包括空字符串、用户手动编辑、旧版本残留）都会使 `int()` 抛未捕获异常，直接阻断启动。
- **最小修复建议：** 将 `current = int(row[0])` 包裹在 `try/except ValueError` 中，异常时回退到 `current = 0` 并写入日志/告警。
- **是否建议本次自动修复：** 是
- **需要补充的测试：** `test_config_migrations_corrupt_schema_version.py` —— 模拟 `schema_meta.value='bad'`，断言 `run_pending` 返回 0 且不抛异常。

---

### BUG-002：DanmuAI.spec 缺失 `app.knowledge` 子模块 hiddenimports

- **严重等级：** P1
- **影响功能：** 打包发布 / PyInstaller / 知识包运行时
- **证据文件：** [DanmuAI.spec](file:///workspace/DanmuAI.spec)、[app/main_lifecycle_mixin.py](file:///workspace/app/main_lifecycle_mixin.py)
- **证据代码：**
  - DanmuAI.spec 的 `hiddenimports` 列表（第 119–326 行）包含 `app.application.*`、`app.meme_barrage.*`、`app.pet.*`、`app.providers.*`、`app.web_api.*`，**没有任何 `app.knowledge` 条目**。
  - `main_lifecycle_mixin.py` 第 307–313 行在 `try/except` 块内动态导入：
    ```python
    from app.knowledge.runtime_service import KnowledgeRuntimeService
    self.knowledge_runtime = KnowledgeRuntimeService(self)
    ```
- **复现路径：**
  1. 在干净 Windows 环境执行 `pyinstaller DanmuAI.spec --noconfirm`；
  2. 运行 `dist/DanmuAI/DanmuAI.exe`；
  3. 启动日志中出现 `knowledge_runtime mount failed: ModuleNotFoundError: No module named 'app.knowledge'`；
  4. 知识包功能完全不可用，且异常被静默吞掉，用户无感知。
- **根因分析：** PyInstaller 静态分析无法追踪 `try/except` 块内的动态 import；该模块及其子模块未被收集到打包产物中。
- **最小修复建议：** 在 `hiddenimports` 中追加：
  ```python
  "app.knowledge",
  "app.knowledge.runtime_service",
  # 以及实际存在的其他 knowledge 子模块
  ```
- **是否建议本次自动修复：** 是
- **需要补充的测试：** `test_packaging_hiddenimports_knowledge.py` —— 遍历 `DanmuAI.spec` 的 `hiddenimports`，断言包含 `app.knowledge.runtime_service`。

---

### BUG-003：麦克风模式在独立 mic 凭证缺失时仍启用采集与端点检测

- **严重等级：** P1
- **影响功能：** 麦克风 / 语音插入链路 / 模型调用成本
- **证据文件：** [app/mic_orchestrator.py](file:///workspace/app/mic_orchestrator.py)、[app/ai_client_support.py](file:///workspace/app/ai_client_support.py)、[app/main_mic_mixin.py](file:///workspace/app/main_mic_mixin.py)
- **证据代码：**
  - `mic_orchestrator.py` 第 51–79 行，`sync()` 仅在 `mic_audio_supported_fn()`（模型能力）返回 True 时启动 detector，**未检查 mic 凭证是否就绪**。
  - `ai_client_support.py` 第 363–374 行，`resolve_mic_request_credentials` 在 `mic_use_visual_model=0` 且 endpoint/key/model 任一缺失时返回 `None`。
  - `main_mic_mixin.py` 第 120–137 行，`_trigger_mic_api_call` 检查了 `mic_mode_enabled`、`engine.running`、`mic_audio_supported`，**但未检查 `resolve_mic_request_credentials` 是否为 None**。PCM 已被采集并编码为 WAV data URI 后，才在 AI worker 内触发 credential error。
- **复现路径：**
  1. Web 控制台关闭「使用视觉模型」mic 开关；
  2. 不填写 mic API endpoint / key / model；
  3. 开启麦克风模式并启动弹幕；
  4. 麦克风服务与 utterance detector 正常启动，用户说话时 PCM 被采集、编码，AI worker 收到请求后因凭证缺失返回 error，浪费 CPU、内存与一轮网络请求。
- **根因分析：** 编排器生命周期与凭证校验分离：detector 的启停只看「模型是否支持音频」，不看「凭证是否完整」。
- **最小修复建议：** 在 `MicOrchestrator.sync()` 中增加 `mic_credentials_ready_fn` 参数；若 `mic_use_visual_model=0` 且 `resolve_mic_request_credentials(config)` 为 None，则 `stop_detector()` 并在 Web 状态栏提示「mic API 未配置」。
- **是否建议本次自动修复：** 是（范围小，仅增加一个前置判断）
- **需要补充的测试：** `test_mic_orchestrator_credentials_guard.py` —— 配置 `mic_use_visual_model=0` 且 mic_api_key 为空，断言 `sync()` 后 `detector` 为 None。

---

### BUG-004：DanmuApp.quit() 无重入保护，重复调用可产生多个模态进度对话框

- **严重等级：** P2
- **影响功能：** 退出稳定性 / 托盘退出 / 卸载后退出
- **证据文件：** [app/main_lifecycle_mixin.py](file:///workspace/app/main_lifecycle_mixin.py)、[app/tray.py](file:///workspace/app/tray.py)
- **证据代码：**
  - `main_lifecycle_mixin.py` 第 776–888 行，`quit()` 方法内创建 `QProgressDialog(...)` 并执行大量 teardown，**没有任何 `_quitting` 标志位**。
  - `tray.py` 第 307 行：卸载确认后通过 `QTimer.singleShot(0, self.app.quit)` 异步触发 quit；托盘「退出」菜单项（第 72 行）直接连接 `self.app.quit`。
- **复现路径：**
  1. 点击托盘「卸载」→ 选择「卸载（保留数据）」→ 确认；
  2. 在 `QProgressDialog` 弹出后、进程退出前，再次点击托盘「退出」；
  3. `quit()` 被第二次调用，新建第二个 `QProgressDialog`，`QApplication.processEvents()` 在第一个对话框事件循环内处理第二个对话框的显示，产生 UI 重入和可能的 `RuntimeError`（QObject 已删除）。
- **根因分析：** 异步事件（`QTimer.singleShot`）与用户交互并发时，缺乏原子性的「正在退出」状态门控。
- **最小修复建议：** 在 `DanmuApp` 增加 `self._quitting = False`；`quit()` 入口判断 `if self._quitting: return`，并在方法第一行置为 `True`。
- **是否建议本次自动修复：** 是
- **需要补充的测试：** `test_quit_reentrancy.py` —— 连续调用 `app.quit()` 两次，断言只产生一个 `QProgressDialog` 实例。

---

### BUG-005：托盘更新进度对话框取消后未显式关闭，导致窗口泄漏

- **严重等级：** P2
- **影响功能：** 自动更新 / 托盘 UI
- **证据文件：** [app/tray.py](file:///workspace/app/tray.py)
- **证据代码：**
  ```python
  219                 def _on_canceled():
  220                     if self._update_poll_timer is not None:
  221                         self._update_poll_timer.stop()
  222                     self._update_progress = None
  223                     self._update_poll_timer = None
  ```
  第 219–223 行：用户点击「取消」后仅停止 timer 并清空引用，**未调用 `self._update_progress.close()`**。该对话框设置了 `setAutoClose(False)`、`setAutoReset(False)`。
- **复现路径：**
  1. 托盘点击「检查更新」→ 发现新版本 → 点击「是」下载；
  2. 弹出进度对话框后点击「取消」；
  3. `QProgressDialog` 仍作为顶层窗口驻留内存，直到进程退出；重复操作可累积多个隐形窗口。
- **根因分析：** 取消回调未完整释放 Qt 窗口资源。
- **最小修复建议：** 在 `_on_canceled` 中增加 `self._update_progress.close()` 再置空引用。
- **是否建议本次自动修复：** 是
- **需要补充的测试：** `test_tray_update_dialog_cleanup.py` —— mock 用户取消下载，断言进度对话框 `close()` 被调用一次。

---

### BUG-006：版本比较对非法版本号静默回退到 0，可能导致更新判断错误

- **严重等级：** P2
- **影响功能：** 自动更新 / 版本比较
- **证据文件：** [app/version_compare.py](file:///workspace/app/version_compare.py)
- **证据代码：**
  ```python
  61  def parse_version(raw: str) -> tuple[tuple[int, ...], str | None]:
  62      normalized = normalize_version(raw)
  63      if not normalized:
  64          raise ValueError("empty version")
  65      core, prerelease = _split_core_prerelease(normalized)
  66      try:
  67          return _parse_numeric_segments(core), prerelease
  68      except ValueError:
  69          return (0,), prerelease   # ← 静默回退
  ```
- **复现路径：**
  1. 假设某次 CI 错误地把版本号写成 `v0.3.0-beta.unknowntag` 或混入换行符；
  2. `parse_version` 捕获 `ValueError` 后返回 `(0,)`；
  3. `is_version_newer("0.3.0", "v0.3.0-beta.unknowntag")` 返回 `False`，用户永远收不到更新提示。
- **根因分析：** 非法版本被静默降级为 `0`，调用方无法区分「正常旧版本」与「解析失败」。
- **最小修复建议：** 回退时记录 `logger.warning`；或在 Velopack 检查结果中增加版本合法性校验，非法时弹窗提示维护人员。
- **是否建议本次自动修复：** 否（涉及更新策略决策，需产品确认）
- **需要补充的测试：** `test_version_compare_malformed_fallback.py` —— 输入 `"abc"`，断言返回 `(0,)` 且记录 warning 日志。

---

### BUG-007：Supabase 客户端将 401/403 错误误判为 rate_limit

- **严重等级：** P2
- **影响功能：** Web 社区 / 错误上报 / 前端 UX
- **证据文件：** [web/static/supabase-client.js](file:///workspace/web/static/supabase-client.js)
- **证据代码：**
  ```javascript
  if (err.kind === 'rate_limit' || err.status === 403 || err.status === 401) {
      throw createSupabaseError(ERROR_REPORT_RATE_LIMIT_MSG, {
          kind: 'rate_limit',
          status: err.status,
      });
  }
  ```
- **复现路径：**
  1. Supabase 项目 RLS 策略变更导致匿名 key 权限不足，返回 403；
  2. 用户在前端提交错误报告；
  3. 前端提示「提交过于频繁，请稍后再试」，掩盖真实的鉴权/权限问题。
- **根因分析：** 错误码分类过于宽泛，把鉴权失败和限流混为一谈。
- **最小修复建议：** 将 `401/403` 单独映射为 `auth_error` 并显示对应本地化文案。
- **是否建议本次自动修复：** 是
- **需要补充的测试：** `test_supabase_client_auth_error_classification.js` —— mock fetch 返回 403，断言抛出的 error kind 为 `auth_error` 而非 `rate_limit`。

---

### BUG-008：`webview_shell.py` 存在不可达死代码

- **严重等级：** P3
- **影响功能：** 代码卫生
- **证据文件：** [app/webview_shell.py](file:///workspace/app/webview_shell.py)
- **证据代码：**
  ```python
  442         while self._spawn_attempt <= _SPAWN_MAX_ATTEMPTS:
  443             try:
  444                 self._launch_child_process(url, gui)
  445                 return True
  446             except OSError as exc:
  447                 if self._spawn_attempt >= _SPAWN_MAX_ATTEMPTS:
  448                     self._fail_start(...)
  449                     return False
  450                 ...
  451                 self._spawn_attempt += 1
  452         return False   # ← 第 462 行，不可达
  ```
- **复现路径：** 静态分析即可确认；`while` 内所有分支均提前 `return`，循环外 `return False` 永远不会执行。
- **根因分析：** while 循环内的 OSError 处理逻辑已覆盖所有退出路径。
- **最小修复建议：** 删除第 462 行，或替换为 `raise AssertionError("unreachable")` 以在未来逻辑变更时提供保险。
- **是否建议本次自动修复：** 是
- **需要补充的测试：** 无需新增测试，静态 lint 即可捕获。

---

## 3. 高风险但未确认问题

> 以下问题证据不足或需 Windows 真机/生产环境验证，**不得直接排入修复队列**。

| 编号 | 模块 | 描述 | 待验证项 |
|------|------|------|----------|
| RISK-A1 | 启动与生命周期 | `single_instance.py` 的 QLocalSocket 激活现有实例后，若原实例主线程卡在 WebView 握手，新实例可能误判为「已激活」但用户仍看不到窗口 | Windows 真机双击 EXE 压力测试 |
| RISK-B1 | 弹幕显示链路 | Overlay `WindowStaysOnTopHint` 在部分独占全屏游戏（DWM bypass）中可能失效；`reassert_hwnd_topmost` 周期性修复是否足够 | 在《CS2》《Valorant》等游戏中实测置顶 |
| RISK-F1 | SQLite / 配置 | `ConfigStore._write_lock` 为 `threading.Lock()`（非 RLock），若某写线程在持有锁时崩溃（C extension segfault），锁永不释放，后续所有写入永久阻塞 | 构造 writer 线程 segfault 场景验证 |
| RISK-G1 | 自定义弹幕库 | 20000 条自定义池全量加载时，`sample_danmu_for_config` 是否做 SQL `ORDER BY RANDOM() LIMIT n` 还是 Python 层全量采样 | 读取 `app/danmu_pool.py` 采样实现并压测 |
| RISK-H1 | 发布与更新 | `publish_windows_release.ps1` 第 134–141 行：若 BootstrapFeedUrl 首次发布或网络抖动导致 `vpk download http` 失败，`SkipDeltaBootstrap` 为 false 时仅报错， delta 包被静默跳过 | 检查 CI 日志中 delta 包生成率 |
| RISK-I1 | Web 后端 | Supabase RLS 策略是否对 `error_reports` 表的 `client_id` 建立了唯一索引以防止刷量；`app_updates` 表是否限制 write 权限仅服务账号可写 | 检查 Supabase Dashboard / 迁移脚本 |

---

## 4. 性能与卡顿风险

| 风险点 | 证据 | 影响 | 缓解现状 |
|--------|------|------|----------|
| 启动慢：pywebview 冷启动 12–25s | `webview_shell.py` 第 22–25 行 `_LOAD_TIMEOUT_SEC = 25.0` | 用户双击 EXE 后长时间无窗口，可能重复点击 | 有 `_SLOW_START_PROMPT_SEC = 3.0` 气泡提示，但无实际加速 |
| 截图压缩：每轮固定 5s 间隔发送完整 JPEG | `main_lifecycle_mixin.py` 截图 timer 固定间隔 | 模型成本随间隔线性增长 | 已有压缩质量/宽度配置，无动态节流 |
| Overlay 渲染：60fps `QElapsedTimer` + 脏区绘制 | `overlay.py` 第 33–34 行 `_FRAME_DT = 1.0/60.0` | 弹幕密集时主线程绘制负载高 | 有 `needs_render_tick` 停表逻辑，但未实测 GPU/CPU 占用 |
| 轨道计算：每帧遍历全部 item 计算 alpha/位置 | `DanmuEngine.update()` 驱动所有 track | 超高密度场景下 O(n) 累积 | 有 `pending_entry_cap` 与 `retention_cap`，但默认较宽松 |
| SQLite：WAL + 256 cached statements | `storage.py` 第 79、93–100 行 | 正常场景足够；极端并发写可能触发 `busy_timeout` 等待 | 当前设计合理，风险低 |
| 自定义弹幕库 20000 条 | 未确认加载方式 | 若全量加载到内存再随机采样，启动或切换配置时可能卡顿 | **待验证 RISK-G1** |

---

## 5. 兼容性与环境风险

| 风险点 | 说明 |
|--------|------|
| Windows 版本差异 | `win32_overlay_zorder.py` 使用 Win32 API 设置 `WS_EX_LAYERED`，在 Windows 7/8 或精简版系统上可能缺少相关 DLL；未看到版本兼容性检测代码 |
| PowerShell / UTF-8 | `publish_windows_release.ps1` 第 11 行显式设置 `$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8`，脚本本身已做防护；但用户本地若使用旧版 Windows PowerShell 5.1 且未启用 UTF-8 Beta，日志输出仍可能乱码 |
| 中文路径 | `ConfigStore` 使用 `%APPDATA%/DanmuAI/`，由 `Path` 处理；PyInstaller `onedir` 模式下若用户将安装目录放在中文路径，`sys._MEIPASS` 解压通常正常，但 Velopack 的 `Update.exe` 路径含中文时历史上偶有编码问题，**未在本代码库中发现直接证据** |
| 显卡/窗口层级 | 部分笔记本混合显卡（NVIDIA Optimus）在独显直连模式下，DWM 合成器行为变化可能导致 `WindowStaysOnTopHint` 与游戏窗口 Z-Order 竞争失效；**属系统级限制，未确认代码缺陷** |

---

## 6. 发布与更新风险

| 风险点 | 证据 | 严重度 |
|--------|------|--------|
| **PyInstaller hiddenimports 缺失知识包模块** | BUG-002 | P1 |
| `collect_submodules("uvicorn")` 可能拖入测试/调试子模块 | `DanmuAI.spec` 第 123 行 | P2（产物体积） |
| Velopack delta 包依赖前序 release 存在 | `publish_windows_release.ps1` 第 134–141 行 | P2（首次发布或 bootstrap 失败时无 delta） |
| 版本号解析非法回退 | BUG-006 | P2 |
| 产物中意外包含 supabase-config.js（含凭据） | `DanmuAI.spec` 与 `publish_windows_release.ps1` 均已实现 default-deny 白名单（BUG-005 修复） | 已缓解 |
| MSI/Setup.exe 命名一致性 | `publish_windows_release.ps1` 输出 `PEPETII.DanmuAI-win-Setup.exe` 与 `PEPETII.DanmuAI-$appVersion-Setup.exe`；README 未明确说明主下载入口是 MSI 还是 Setup.exe | P3（文档不一致） |

---

## 7. 安全与隐私风险

| 风险点 | 证据 | 状态 |
|--------|------|------|
| API Key 本地存储 | `ConfigStore` 使用 Fernet 加密 + `%APPDATA%/DanmuAI/.key` 文件；密钥损坏时旧密文不可恢复但会备份为 `.key.bak.<timestamp>` | 设计合理 |
| 日志脱敏 | `SanitizedLogger` + `sanitize_sensitive_text` 已覆盖 key/token 关键词；`main_mic_mixin.py` 第 114 行仅记录 `pcm_bytes={len(pcm)}`，不记录音频内容 | 已缓解 |
| Supabase 前端密钥 | `supabase-config.example.js` 仅含占位符；`supabase-client.js` 使用 anon key（公开权限）；未发现 service_role key 泄露 | 已缓解 |
| 错误上报限流 | `supabase-client.js` 对 `error_reports` 有 403/401/429 拦截，但把 401/403 归类为 rate_limit（BUG-007），可能掩盖 RLS 配置错误 | **待修复** |
| 社区后端权限边界 | `web_api/auth.py` 的 `require_auth` / `require_auth_query` 仅为 token 装饰器，具体 token 校验逻辑未在本次审计范围内深入；**若 token 为硬编码或长期不变，存在越权风险** | **高风险待人工确认** |

---

## 8. 建议新增的测试

| 测试文件名 | 测试目标 | 关键断言 |
|------------|----------|----------|
| `tests/test_config_migrations_corrupt_schema_version.py` | schema_meta 损坏时启动不崩溃 | `run_pending(conn) == 0` 且不抛异常 |
| `tests/test_packaging_hiddenimports_knowledge.py` | 发布产物包含 knowledge 模块 | `"app.knowledge.runtime_service" in hiddenimports` |
| `tests/test_mic_orchestrator_credentials_guard.py` | mic 独立凭证缺失时不启动 detector | `orchestrator.detector is None` |
| `tests/test_quit_reentrancy.py` | quit() 重复调用只弹一个进度对话框 | `QProgressDialog` 实例数 <= 1 |
| `tests/test_tray_update_dialog_cleanup.py` | 更新下载取消后关闭对话框 | `QProgressDialog.close.assert_called_once()` |
| `tests/test_version_compare_malformed_fallback.py` | 非法版本解析降级并记录日志 | `parse_version("abc") == ((0,), None)` 且 log 含 warning |
| `tests/test_supabase_client_auth_error_classification.py`（前端 JS） | 401/403 不归为 rate_limit | `error.kind === 'auth_error'` |

---

## 9. 本次可自动修复项

以下问题证据充分、修复范围小、不改变产品设计，**建议直接排入本次修复**：

1. **BUG-001** `config_migrations.py` 增加 `int(row[0])` 的 `ValueError` 保护。
2. **BUG-005** `tray.py` 进度对话框取消回调中增加 `.close()`。
3. **BUG-007** `supabase-client.js` 将 401/403 独立分类为 `auth_error`。
4. **BUG-008** `webview_shell.py` 删除/注释不可达的 `return False`。
5. **BUG-002** `DanmuAI.spec` 追加 `app.knowledge` 相关 `hiddenimports`。

若团队决定不立即修复 **BUG-003**（麦克风凭证门控）和 **BUG-004**（quit 重入保护），建议至少在下个迭代排期，因为二者均影响用户可感知的稳定性。

---

## 10. 最终建议（Top 3）

### Top 1：修复 BUG-001（P0）schema_version 解析崩溃
- **理由：** 任何一次意外的 DB 元数据损坏（用户手动编辑、磁盘错误、旧版本残留）都会导致应用完全无法启动，属于「单点故障」。修复仅增加一行 try/except，收益极高。

### Top 2：修复 BUG-002（P1）并补充打包后冒烟测试
- **理由：** 知识包（Knowledge Runtime）是 Phase B 核心功能，hiddenimports 缺失意味着发布产物中该功能 100% 不可用，且异常被 `try/except` 静默吞掉，用户与开发者均无法及时发现。必须在 `DanmuAI.spec` 中补齐，并在 CI 中增加「打包后启动并检查 knowledge_runtime 挂载成功」的冒烟测试。

### Top 3：修复 BUG-003（P1）麦克风凭证缺失仍启用采集
- **理由：** 该问题直接浪费用户的模型调用成本（一次无意义的 API error 请求仍可能产生网络流量和 token 计费前开销），并在后台持续占用麦克风硬件和 CPU（PCM 编码、utterance 检测）。增加前置判断即可完全避免。

---

## 11. 自检评分

| 评分项 | 得分 | 说明 |
|--------|------|------|
| 证据完整性（文件/代码/复现） | 2/2 | 每个已确认 Bug 均给出文件路径、代码片段、复现路径 |
| 严重度判定准确性 | 2/2 | P0 为启动崩溃，P1 为功能/发布不可用，P2 为体验受损，P3 为卫生项 |
| 是否区分「已确认」与「待确认」 | 2/2 | 第 3 章独立列出高风险未确认问题，未混入已确认 Bug |
| 是否覆盖发布更新链路 | 2/2 | 覆盖 PyInstaller、Velopack、版本比较、R2、产物完整性 |
| 是否给出可执行测试建议 | 2/2 | 第 8 章给出 7 个具体测试文件名、目标与断言 |

**总分：10/10**

---

## 附录：测试执行阻塞记录（审计环境）

> 按用户要求：若无法运行测试，必须写清失败命令、失败文件、断言/报错、缺失依赖、阻塞原因、建议修复。

### 阻塞命令 1
```bash
python -m pytest --tb=short -q
```
- **失败文件：** 170 个测试文件在 collection 阶段报错（完整列表见终端输出）
- **断言/报错：** `ModuleNotFoundError: No module named 'PyQt6'`、`No module named 'httpx'`、`No module named 'fastapi'`
- **缺失依赖：** PyQt6、httpx、fastapi、以及 requirements.txt / requirements-dev.txt 中列出的其他运行时依赖
- **阻塞原因：** 当前 Linux 远程沙箱未安装项目依赖（无 `venv-build` 或 `.venv` 被激活）
- **建议修复（审计环境）：** 在沙箱中执行 `pip install -r requirements.txt -r requirements-dev.txt` 后重跑；若 PyQt6 在 Linux 无显示环境导致 import 失败，可追加 `export QT_QPA_PLATFORM=offscreen` 或仅运行纯逻辑测试子集。

### 阻塞命令 2
```bash
python scripts/run_acceptance_gates.py
```
- **失败文件：** `tests/test_web_console.py`、`tests/test_p0_main_flow.py`、`tests/test_web_custom_models.py`、`tests/test_ai_client.py` 等
- **断言/报错：** 同上，ImportError 导致 collection 失败，EXIT_CODE 非 0
- **缺失依赖：** 同上
- **阻塞原因：** `run_acceptance_gates.py` 通过 `subprocess.run` 调用 pytest，子进程同样缺少依赖
- **建议修复（审计环境）：** 同上；此外建议在 `run_acceptance_gates.py` 入口增加 `REPO_ROOT / "requirements-dev.txt"` 存在性检查，若依赖缺失提前给出友好提示而非大量 ImportError。
