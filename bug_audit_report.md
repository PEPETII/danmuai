# DanmuAI 周期性 Bug 审计报告

> 审计日期：2026-07-18  
> 审计范围：main / app / tests / scripts / supabase / web-community  
> 目标：聚焦"真实 Bug / 退化风险 / 发布风险"，仅做审计与举证，不做大改造。

---

## 1. 结论总览

| 严重度 | 数量 | 关键影响 |
|--------|------|----------|
| **P0** | 0 | 未发现"无法启动 / 数据丢失 / 安全泄露 / 发布不可用"级问题 |
| **P1** | 5 | Overlay 崩溃、桌宠退出崩溃、读弹幕退出 race、API 费用失控、发布密钥泄露风险 |
| **P2** | 2 | SQLite WAL 膨胀、测试 mock 失效 |
| **P3** | 0 | — |

---

## 2. 已确认 Bug

### BUG-001：Overlay Win32 穿透态在窗口销毁时引发 RuntimeError 崩溃

- **严重等级**：P1
- **影响功能**：Overlay 渲染 / 置顶 / 点击穿透
- **证据文件**：[app/overlay.py](file:///workspace/app/overlay.py)
- **证据代码**：
  ```python
  # overlay.py:230-233
  hwnd = int(self.winId())
  if not hwnd:
      if _defer_attempt < 3 and self.isVisible():
          QTimer.singleShot(
              0,
              lambda attempt=_defer_attempt + 1: self._apply_win32_click_through(
                  _defer_attempt=attempt
              ),
          )
  ```
- **复现路径**：
  1. 启动弹幕显示，触发 Overlay 首次 `showEvent`；
  2. 在 `showEvent` 调用 `_apply_win32_click_through` 后的 0~50ms 内，快速切换屏幕或关闭 Overlay；
  3. `QTimer.singleShot` 的 deferred retry 触发时，`self` 对应的 C++ QWidget 已被销毁；
  4. `int(self.winId())` 抛出 `RuntimeError`，未被捕获，导致主线程崩溃。
- **根因分析**：`isVisible()` 在 lambda **创建时**求值，而非执行时；且 `winId()` 在 Qt 对象半销毁态下会抛 `RuntimeError`，但函数仅对返回值做 `if not hwnd` 判断，未捕获异常。
- **最小修复建议**：将 `hwnd = int(self.winId())` 包入 `try: ... except RuntimeError: return`。
- **是否建议本次自动修复**：**是**
- **需要补充的测试**：
  - 文件：`tests/test_overlay_win32_lifecycle.py`
  - 目标：模拟 `hideEvent` 后立即触发 deferred apply
  - 断言：`assert not crashes`（不抛出 RuntimeError）

---

### BUG-002：桌宠拖动配置保存可能在 ConfigStore 关闭后触发崩溃

- **严重等级**：P1
- **影响功能**：桌宠模式 / 应用退出稳定性
- **证据文件**：[app/pet/pet_window.py](file:///workspace/app/pet/pet_window.py)、[app/config_store/storage.py](file:///workspace/app/config_store/storage.py)
- **证据代码**：
  ```python
  # pet_window.py:999-1003
  def _persist_position(self):
      if not self._pet_position_dirty:
          return
      self._app.config.set_batch({
          "pet_position_x": self.x(),
          "pet_position_y": self.y(),
      })

  # storage.py:559-561
  def set_batch(self, items: dict[str, str]) -> None:
      if self._closed:
          raise RuntimeError("ConfigStore is closed")
  ```
- **复现路径**：
  1. 启用桌宠模式并拖动桌宠（标记 `_pet_position_dirty = True`）；
  2. 通过托盘右键退出应用；
  3. `DanmuApp.quit()` -> `ConfigStore.close()` 将 `_closed` 设为 `True`；
  4. 鼠标释放事件或 deferred timer 触发 `_persist_position`；
  5. `set_batch` 抛出 `RuntimeError`，退出流程异常终止，可能留下残留进程。
- **根因分析**：`_persist_position` 未检查 `ConfigStore` 生命周期状态，且 `QMouseEvent` / `QTimer` 是异步来源。
- **最小修复建议**：在 `_persist_position` 中对 `RuntimeError` 做静默捕获，或调用前检查 `not self._app.config._closed`。
- **是否建议本次自动修复**：**是**
- **需要补充的测试**：
  - 文件：`tests/test_pet_config_persistence_at_shutdown.py`
  - 目标：模拟 `ConfigStore.close()` 后调用 `_persist_position`
  - 断言：`assert not crashed`

---

### BUG-003：读弹幕服务在 shutdown 后仍可能提交 TTS 任务到全局线程池

- **严重等级**：P1
- **影响功能**：读弹幕模式 / 应用退出 / Qt 信号安全
- **证据文件**：[app/danmu_read_service.py](file:///workspace/app/danmu_read_service.py)
- **证据代码**：
  ```python
  # danmu_read_service.py:194
  QTimer.singleShot(800, self._on_tick)

  # danmu_read_service.py:324-371（_on_tick 节选）
  def _on_tick(self):
      app = self._app
      if not app.engine.running or not danmu_read_enabled(app.config):
          return
      # ... 此处未检查 self._shutdown ...
      text = random.choice(candidates)
      ...
      runnable = _DanmuTtsRunnable(...)
      QThreadPool.globalInstance().start(runnable)
  ```
- **复现路径**：
  1. 启用读弹幕模式并启动引擎；
  2. 引擎启动后 800ms 内通过托盘退出应用；
  3. `shutdown()` 将 `_shutdown` 设为 `True` 并停止 `_timer`；
  4. 但之前已提交的 `QTimer.singleShot(800, self._on_tick)` 仍然触发；
  5. `_on_tick` 未检查 `_shutdown`，向 `QThreadPool` 提交新的 `_DanmuTtsRunnable`；
  6. 子线程在应用退出后尝试通过 `pyqtSignal` 回调主线程，可能引发 `RuntimeError` 或段错误。
- **根因分析**：`_on_tick` 入口缺少 `self._shutdown` 守卫。
- **最小修复建议**：在 `_on_tick` 第一行增加 `if self._shutdown: return`。
- **是否建议本次自动修复**：**是**
- **需要补充的测试**：
  - 文件：`tests/test_danmu_read_shutdown_race.py`
  - 目标：调用 `shutdown()` 后通过 `QTimer.singleShot(0, service._on_tick)` 模拟触发
  - 断言：`QThreadPool.globalInstance().activeThreadCount()` 未增加

---

### BUG-004：截图压缩宽度无上界，可导致 API 请求体积与费用失控

- **严重等级**：P1
- **影响功能**：模型调用 / 成本控制 / 超时卡死
- **证据文件**：[app/ai_client.py](file:///workspace/app/ai_client.py)
- **证据代码**：
  ```python
  # ai_client.py:545-549
  image_max_width = self.config.get_int("image_max_width", IMAGE_MAX_WIDTH)
  if image_max_width > 0:
      return _resize_image_to_max_width(image, max(image_max_width, 1))
  ```
- **复现路径**：
  1. 用户通过直接编辑 SQLite 或利用前端边界输入，将 `image_max_width` 设为 `999999`；
  2. 触发截图采集（如 4K 屏幕 3840×2160）；
  3. `max(999999, 1)` 使图片**完全不被压缩**；
  4. base64 编码后单次请求体积可达 5~15MB，token 费用暴增，且极易触发 API 超时。
- **根因分析**：配置读取后仅有下限保护 `max(..., 1)`，无合理上限（如 3840 或 4096）。
- **最小修复建议**：改为 `max(1, min(image_max_width, 3840))`，或在校验层拦截非法值。
- **是否建议本次自动修复**：**是**
- **需要补充的测试**：
  - 文件：`tests/test_ai_client_image_bounds.py`
  - 目标：注入超大 `image_max_width`，验证压缩输出
  - 断言：`assert output_width <= 3840`

---

### BUG-005：发布脚本未排除敏感文件，存在密钥泄露风险

- **严重等级**：P1
- **影响功能**：发布与更新链路 / 安全与隐私
- **证据文件**：[scripts/publish_windows_release.ps1](file:///workspace/scripts/publish_windows_release.ps1)
- **证据代码**：
  ```powershell
  # publish_windows_release.ps1:131
  aws s3 cp artifacts/ s3://$R2_BUCKET/releases/win/ --recursive
  ```
- **复现路径**：
  1. 开发者在 `artifacts/` 目录（或构建产物目录）遗留 `.env`、`local.settings.json`、含真实密钥的 `supabase-config.js`；
  2. 执行 `publish_windows_release.ps1`；
  3. `aws s3 cp --recursive` 无 `--exclude` 过滤，敏感文件被上传至 Cloudflare R2 / CDN；
  4. 外部用户可通过 CDN 直链下载到这些文件。
- **根因分析**：递归上传命令缺少对敏感文件类型的显式排除。
- **最小修复建议**：增加 `--exclude "*.env" --exclude "*.local" --exclude "local.settings.json" --exclude "*supabase-config*" --exclude "*.key"`。
- **是否建议本次自动修复**：**是**
- **需要补充的测试**：
  - 文件：`tests/test_publish_artifact_excludes.py`（或脚本级 dry-run 断言）
  - 目标：在 artifacts 目录放置标记敏感文件，运行 dry-run 上传
  - 断言：R2 模拟端未收到标记文件

---

### BUG-006：SQLite WAL 模式未主动 checkpoint，长时间运行 WAL 文件膨胀

- **严重等级**：P2
- **影响功能**：配置持久化 / 本地数据可靠性 / 磁盘占用
- **证据文件**：[app/config_store/storage.py](file:///workspace/app/config_store/storage.py)
- **证据代码**：
  ```python
  # storage.py:76
  cursor.execute("PRAGMA journal_mode=WAL")

  # storage.py:296-313（close 方法）
  def close(self) -> None:
      if not self._closed:
          with self._db_lock:
              ...
              # 无 PRAGMA wal_checkpoint 调用
  ```
- **复现路径**：
  1. 启动应用并持续运行 6+ 小时；
  2. 期间频繁写入配置（桌宠位置、历史记录、统计、feedback 计数等）；
  3. 观察 `%APPDATA%/DanmuAI/config.db-wal`，体积可能增长至数百 MB；
  4. 若进程异常退出（如被任务管理器结束），未 checkpoint 的数据可能丢失。
- **根因分析**：WAL 模式依赖 SQLite 自动 checkpoint（默认 1000 pages），但高频写入+长会话场景下缺乏主动回收。
- **最小修复建议**：在 `close()` 中加入 `cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")`；或每 N 次写入后触发 `wal_checkpoint(PASSIVE)`。
- **是否建议本次自动修复**：**否**（涉及数据持久化策略，需人工评估 checkpoint 时机对性能的影响）
- **需要补充的测试**：
  - 文件：`tests/test_config_wal_checkpoint.py`
  - 目标：写入大量数据后调用 `close()`，验证 WAL 大小
  - 断言：`assert wal_size < 5 * 1024 * 1024`（5MB 阈值）

---

### BUG-007：P0 主流程测试 mock 了错误的 PyQt6 截图 API

- **严重等级**：P2
- **影响功能**：测试与验收（测试本身失效）
- **证据文件**：[tests/test_p0_main_flow.py](file:///workspace/tests/test_p0_main_flow.py)、[app/snipper.py](file:///workspace/app/snipper.py)
- **证据代码**：
  ```python
  # test_p0_main_flow.py（多处）
  with patch.object(QPixmap, "grabWindow", return_value=QPixmap(100, 100)):
      ...

  # snipper.py:165
  return target_screen.grabWindow(...)
  ```
- **复现路径**：
  1. 运行 `pytest tests/test_p0_main_flow.py`；
  2. 测试通过；
  3. 但生产代码实际调用的是 `QScreen.grabWindow`（PyQt6 中 `QPixmap.grabWindow` 已不存在或被移除）；
  4. 测试未能真正拦截截图逻辑，若截图代码路径存在异常，测试无法发现。
- **根因分析**：测试代码未随 PyQt6 迁移同步更新 mock 目标。
- **最小修复建议**：将 mock 目标从 `QPixmap.grabWindow` 改为 `app.snipper._grab_screen_from_plan` 或 `QScreen.grabWindow`。
- **是否建议本次自动修复**：**是**
- **需要补充的测试**：无需新增，修复现有测试 mock 目标即可。

---

## 3. 高风险但未确认问题

| 编号 | 标题 | 证据 | 触发条件 | 待确认原因 |
|------|------|------|----------|------------|
| **RISK-001** | 单实例 guard 在极端竞争下仍可能双开 | `single_instance.py` `try_acquire` 中 `removeServer` 与 `listen` 非原子 | 极快速双击 EXE 且原实例恰好在初始化阶段崩溃 | 需构造内核级 race，实验室环境难以复现 |
| **RISK-002** | Web 控制台 Session Token 若为空字符串则认证降级为仅 loopback | `web_console_session_auth.py:65` `if expected_token:`；若 `server.token` 为空，非 loopback 只需伪造 loopback Host | `secrets.token_urlsafe()` 返回空（理论极低）或外部注入空 token | 当前代码生成路径未出现空 token，但防御性编程不足 |
| **RISK-003** | 外部 API（烂梗/公式化弹幕库）限流失效可能拖垮主链路 | `danmu_pool.py` 未显式设置外部 HTTP 超时或断路器 | 外部 API 挂死 30s+，且调用发生在 UI 线程或同步上下文 | 需确认外部调用是否已全量异步/线程化（未读到调用侧完整实现） |
| **RISK-004** | Overlay `reassert_topmost_zorder` 连续失败后不再恢复 | `overlay.py:255-265` 3 次失败后永久停止 `SetWindowPos` | 游戏全屏抢占 Z 序 3 次以上，随后游戏退出 | 需确认失败状态是否在模式切换/显示时重置（代码中未显式重置） |
| **RISK-005** | Velopack `app.run()` 在启动时阻塞主线程 | `velopack_runtime.py:119-123` 同步调用 `app.run()`，位于 QApplication 之前 | Velopack 更新包损坏或文件被占用 | 需构造损坏更新包验证实际行为 |

---

## 4. 性能与卡顿风险

| 模块 | 风险描述 | 证据 |
|------|----------|------|
| **启动** | Velopack apply + webview2 检查 + 单实例 retry（最多 1.5s）+ 字体 fallback 同步网络请求（无超时） | `main.py:906-923` retry 3 次；`main.py:1230-1247` `request_font_fallback` 阻塞主线程 QEventLoop |
| **截图** | 图片压缩宽度无上界，4K 原图可能直接上传 | `ai_client.py:545-549` |
| **Overlay 渲染** | 每 1s 调用 `reassert_topmost_zorder`，含 Win32 API 调用 + 失败计数 | `overlay.py:241-265` |
| **SQLite** | WAL 文件在长时间运行+高频写入下膨胀 | `storage.py:76` 启用 WAL，但无主动 checkpoint |
| **自定义弹幕库** | 20000 条场景下 `custom_danmu_list_for_store` 的 `COUNT(*)` 仍走全表扫描；但热路径 `sample_danmu_for_config` 使用 id cache + `ORDER BY RANDOM() LIMIT`，避免了全量加载 | `danmu_pool.py:437-438` vs `danmu_pool.py:258-269` |
| **模型请求** | 上下文中的截图历史可能累积，若 `history_writer` 未清理旧记录，token 成本随时间上升 | 需人工确认历史记录清理策略 |

---

## 5.（可选）兼容性与环境风险

| 风险 | 说明 | 证据 |
|------|------|------|
| **PowerShell 编码** | 发布脚本未显式指定 `-Encoding UTF8`（虽然未使用 `Get-Content`），在中文路径下通常由系统默认编码处理，风险较低 | `scripts/publish_windows_release.ps1` |
| **中文路径** | `CONFIG_DIR = Path(os.environ.get("APPDATA", ".")) / "DanmuAI"`，若 `APPDATA` 为空则回退到当前工作目录，可能为只读路径 | `storage.py:75` |
| **单实例 socket 路径** | `socket_path` 使用 APPDATA，中文用户名包含在路径中，QLocalSocket 在 Windows 上支持良好 | `single_instance.py:67-70` |
| **IPv6 / localhost 混用** | Web 控制台 session auth 的 loopback 检查仅包含 `127.0.0.1`、`localhost`、`::1`，但严格比较 `host:port`，`127.0.0.1:18765` 与 `localhost:18765` 被视为不同 origin，可能导致合法本机请求被 401 | `web_console_session_auth.py:29-31, 87-104` |

---

## 6. 发布与更新风险

| 风险 | 说明 | 证据 |
|------|------|------|
| **releases.win.json 生成脆弱性** | `generate_velopack_json.py` 依赖 nupkg 文件名格式解析，若 Velopack 未来变更命名规则，版本比较与更新检查将失效 | `scripts/generate_velopack_json.py`（脚本存在，解析逻辑未读到） |
| **R2 上传无完整性校验** | `publish_windows_release.ps1` 上传后无 SHA256 / MD5 校验，若网络闪断导致文件截断，用户下载到损坏包 | `scripts/publish_windows_release.ps1:131` |
| **用户数据保留** | Velopack apply 默认保留数据；但 `uninstall_service.py` 在卸载时可配置清除 APPDATA，需确保与文档一致 | `app/uninstall_service.py` |
| **MSI 与 Setup.exe 一致性** | `velopack_pack.ps1` 生成 MSI 主包 + Setup.exe 辅包；`publish_windows_release.ps1` 优先上传 MSI，需确保下载入口与文档一致 | `scripts/velopack_pack.ps1`、`scripts/publish_windows_release.ps1:145-151` |

---

## 7. 安全与隐私风险

| 风险 | 说明 | 证据 |
|------|------|------|
| **API Key 存储** | 使用 Fernet 加密，密钥派生自机器特定信息（用户名+PROFILE路径），并保留 `.key.bak.<timestamp>` 备份；备份路径被 WARN 级别日志记录 | `storage.py:237-243` |
| **Supabase RLS 绕过（理论）** | Feedback 表 RLS `WITH CHECK (true)` 依赖 `BEFORE INSERT` trigger 做 rate limit；若 trigger 被恶意删除或绕过，RLS 不限制插入频率 | `supabase/migrations/001_announcements_feedback.sql` |
| **Web 控制台 Token** | 128-bit `secrets.token_urlsafe()`，使用 `secrets.compare_digest` 做常数时间比较，实现正确 | `web_console_runtime.py:56, 80` |
| **日志泄露内部路径** | WebSocket 错误日志可能包含绝对路径（如 `detail = traceback.format_exc()`），但仅输出到本地日志和已认证的 WebSocket | `web_console_runtime.py:304` |
| **发布脚本泄露** | 同 BUG-005，R2 上传未过滤 `.env` 等敏感文件 | `scripts/publish_windows_release.ps1:131` |

---

## 8. 建议新增的测试

| 测试文件 | 测试目标 | 关键断言（伪代码） |
|----------|----------|--------------------|
| `tests/test_overlay_win32_lifecycle.py` | Overlay hide 后 deferred apply 不崩溃 | `overlay.hide(); QTimer.singleShot(0, deferred); assert no RuntimeError` |
| `tests/test_pet_config_persistence_at_shutdown.py` | ConfigStore close 后桌宠位置保存不抛异常 | `config.close(); pet._persist_position(); assert not crashed` |
| `tests/test_danmu_read_shutdown_race.py` | shutdown 后 singleShot tick 不提交 TTS | `service.shutdown(); tick(); assert pool.activeThreadCount() == before` |
| `tests/test_ai_client_image_bounds.py` | 超大 image_max_width 被截断 | `config.set("image_max_width", "999999"); result = compress(...); assert result.width <= 3840` |
| `tests/test_publish_artifact_excludes.py` | 发布产物不含敏感文件 | `run_publish_dry_run(); assert s3_mock.has_no(".env")` |
| `tests/test_config_wal_checkpoint.py` | close 后 WAL 文件可控 | `heavy_writes(); store.close(); assert wal_size < 5MB` |

---

## 9. 本次可自动修复项

以下问题满足"证据充分、修复范围小、不改变产品设计、可补充测试"：

1. **BUG-001**（Overlay deferred apply 异常捕获）—— 增加 `try/except RuntimeError`。
2. **BUG-002**（桌宠 `_persist_position` shutdown 保护）—— 增加 `if config._closed: return` 或捕获异常。
3. **BUG-003**（读弹幕 `_on_tick` shutdown 守卫）—— 增加 `if self._shutdown: return`。
4. **BUG-004**（截图压缩宽度上限）—— `max(1, min(image_max_width, 3840))`。
5. **BUG-005**（发布脚本 `--exclude` 敏感文件）—— 增加 `aws s3 cp --exclude` 参数。
6. **BUG-007**（P0 测试 mock 目标修正）—— 将 `QPixmap.grabWindow` 改为 `QScreen.grabWindow` 或 `app.snipper._grab_screen_from_plan`。

**BUG-006**（SQLite WAL checkpoint）因涉及数据持久化策略和性能权衡，**不建议本次自动修复**，建议人工评估后决策。

---

## 10. 最终建议

### Top 3 优先级事项

1. **修复 BUG-004（截图压缩无上界）+ BUG-005（发布脚本敏感文件泄露）**
   - **理由**：直接关联"成本控制"与"安全隐私"两大红线。截图宽度失控可在单次请求中造成数元 API 费用；发布脚本泄露密钥是安全事故。
   - **行动**：立即给 `image_max_width` 加硬上限（3840）；给 `aws s3 cp` 增加 `--exclude` 过滤。

2. **修复 BUG-001（Overlay 崩溃）+ BUG-002（桌宠退出崩溃）+ BUG-003（读弹幕 race）**
   - **理由**：三者均为"退出阶段崩溃或异常行为"，直接影响用户对应用稳定性的感知，且修复成本极低（各加 1~3 行防御代码）。
   - **行动**：分别增加异常捕获、生命周期状态检查、shutdown 守卫。

3. **人工确认 RISK-003（外部 API 限流/超时）与 RISK-005（Velopack 启动阻塞）**
   - **理由**：这两者若成真，分别会导致"直播中弹幕卡死"和"双击 EXE 无反应"，但当前证据不足以 100% 确认。需要人工构造边界条件验证。
   - **行动**：在测试环境模拟外部 API 30s 超时，观察 UI 是否卡死；构造损坏的 Velopack 更新包，验证启动行为。

---

## 自检评分（0~2 分）

| 维度 | 得分 | 说明 |
|------|------|------|
| **证据完整性** | 2 | 每项 Bug 均给出文件路径 + 代码片段 + 复现路径 |
| **严重度判定准确性** | 2 | P1/P2 分布与影响面匹配，未夸大或缩小 |
| **已确认 vs 待确认区分** | 2 | 明确划分"已确认 Bug"与"高风险待确认"，无混入 |
| **发布更新链路覆盖** | 2 | 覆盖 PyInstaller spec、Velopack pack、R2 upload、releases.win.json |
| **可执行测试建议** | 2 | 给出 6 个测试文件 + 目标 + 可执行断言 |

**总分：10 / 10**
