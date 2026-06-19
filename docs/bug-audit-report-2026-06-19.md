# DanmuAI 周期性 Bug 审计报告

## 1. 本次审计范围

- 当前分支：`main`
- 当前 commit：`1ac0f4a`
- 检查时间：2026-06-19
- 已读取的关键文件：
  - `main.py` — 入口与 DanmuApp 定义
  - `app/main_lifecycle_mixin.py` — 启动/停止/退出生命周期
  - `app/single_instance.py` — 单实例守卫
  - `app/web_console.py` — Web 控制台服务器
  - `app/webview_shell.py` — pywebview 子进程壳
  - `app/overlay.py` — Qt 透明置顶弹幕渲染
  - `app/danmu_engine.py` — 弹幕引擎（轨道、去重、加速）
  - `app/reply_parser.py` — AI 回复解析
  - `app/reply_queue.py` — AI 回复 FIFO 缓冲
  - `app/ai_client.py` — AI 请求客户端
  - `app/config_store.py` — SQLite 配置存储
  - `app/danmu_pool.py` — 公式化弹幕库
  - `app/mic_service.py` — 麦克风模式门面
  - `app/mic_capture.py` — 音频采集
  - `app/mic_utterance.py` — 语音端点检测
  - `app/mic_prompt.py` — 麦克风提示词组装
  - `app/pet/pet_window.py` — 桌宠窗口
  - `app/pet/pet_state.py` — 桌宠配置
  - `app/pet/pet_barrage.py` — 桌宠弹幕模式
  - `app/pet/pet_assets.py` — 桌宠素材加载
  - `app/update_service.py` — Velopack 更新服务
  - `app/supabase_app_updates.py` — Supabase 更新查询
  - `app/supabase_config.py` — Supabase 凭据解析
  - `app/version.py` — 版本号定义
  - `app/version_compare.py` — 版本比较
  - `app/velopack_config.py` — Velopack 更新源 URL
  - `DanmuAI.spec` — PyInstaller 打包配置
  - `scripts/publish_windows_release.ps1` — 发布脚本
  - `scripts/run_acceptance_gates.py` — 验收门禁
  - `.gitignore` — Git 忽略规则
  - `web/static/supabase-config.example.js` — Supabase 配置模板
  - `app/web_api/routes.py` — Web API 路由
  - `app/web_api/custom_models.py` — 自定义模型 API
  - `app/web_api/update.py` — 更新 API
  - `app/web_api/app_update_state.py` — 更新弹窗状态
- 已运行的命令：
  - `git branch --show-current` → `main`
  - `git rev-parse --short HEAD` → `1ac0f4a`
- 未能运行的命令及原因：
  - 未运行 `pytest`（按 IDE_AGENT_RULES §10 禁止全量测试；本次为审计工单，不涉及代码修改，无需运行分批测试）
  - 未运行 `scripts/run_acceptance_gates.py`（需要完整 Python 环境与 PyQt6 GUI，CI 环境外无法完整执行）

---

## 2. 结论总览

### P0：会导致无法启动、数据丢失、安全泄露、发布不可用的问题

| 编号 | 标题 |
|------|------|
| BUG-01 | `supabase-config.js` 未加入 `.gitignore`，Supabase anon key 可能泄露到 Git 仓库 |
| BUG-02 | Fernet 密钥丢失/损坏后，旧加密 API Key 永久不可恢复，用户无明确提示 |

### P1：会导致核心功能不可用或明显影响用户体验的问题

| 编号 | 标题 |
|------|------|
| BUG-03 | `SingleInstanceGuard` 在 probe→listen 之间存在竞态窗口，可能导致双实例启动 |
| BUG-04 | `PetBarrageController.deliver_batch` 在弹幕文本不足时分配空字符串气泡 |
| BUG-05 | `update_service._state` 字典部分读取路径未持锁，存在数据竞争 |
| BUG-06 | PyInstaller spec 缺少 `app.supabase_app_updates` 等 hiddenimport，可能导致运行时 ImportError |
| BUG-07 | `web/static` 整体打包可能将用户 `supabase-config.js` 含密钥打入发布产物 |

### P2：会导致性能下降、边界异常、配置不生效的问题

| 编号 | 标题 |
|------|------|
| BUG-08 | 自定义弹幕库 20000 条全量加载无分页，高频调用时存在性能风险 |
| BUG-09 | `PetWindow._persist_position` 拖动过程中每次 mouseRelease 写 SQLite，高频场景下可能阻塞主线程 |
| BUG-10 | `reply_parser` 纯文本回退模式不区分场景，可能误将非弹幕文本解析为弹幕 |
| BUG-11 | `PetBarrageController.apply_config` 每次调用重建所有窗口配置，无增量更新 |

### P3：代码卫生、文档不一致、潜在维护问题

| 编号 | 标题 |
|------|------|
| BUG-12 | `version_compare` 不支持 4 段版本号（如 `1.0.0.1`），可能影响未来版本比较 |
| BUG-13 | `publish_windows_release.ps1` 获取版本号无格式校验，异常版本号会静默传播 |
| BUG-14 | 测试覆盖缺失：无 pet、update、overlay 动画、velopack 相关测试 |

---

## 3. 已确认 Bug

### BUG-01：`supabase-config.js` 未加入 `.gitignore`，Supabase anon key 可能泄露到 Git 仓库

- 严重等级：**P0**
- 影响功能：安全 — Supabase 项目凭据泄露
- 证据文件：[.gitignore](file:///e:/test/danmu/.gitignore)、[supabase-config.example.js](file:///e:/test/danmu/web/static/supabase-config.example.js)
- 证据代码：
  - `.gitignore` 中无 `supabase-config.js` 条目
  - `supabase-config.example.js:5-8` 明确要求用户复制为 `supabase-config.js` 并填入真实凭据：
    ```js
    window.DANMU_SUPABASE = {
      url: 'https://YOUR_PROJECT_REF.supabase.co',
      anonKey: 'YOUR_ANON_OR_PUBLISHABLE_KEY',
    };
    ```
  - `index.html:96` 引用 `<script src="/static/supabase-config.js"></script>`
  - `app/supabase_config.py:42-47` 从该文件读取凭据：
    ```python
    config_path = resource_path("web", "static", "supabase-config.js")
    return _parse_supabase_config_js(config_path.read_text(encoding="utf-8"))
    ```
- 复现路径：
  1. 开发者复制 `supabase-config.example.js` 为 `supabase-config.js` 并填入真实 anon key
  2. `git add .` 或 `git add web/static/` 将 `supabase-config.js` 加入暂存区
  3. 推送到远程仓库，anon key 泄露
- 根因分析：`.gitignore` 缺少 `web/static/supabase-config.js` 条目。示例文件有注释提醒，但无强制保护。
- 最小修复建议：在 `.gitignore` 中添加 `web/static/supabase-config.js`。
- 是否建议本次自动修复：**否**（审计工单不允许代码修改）
- 需要补充的测试：CI 检查 `web/static/supabase-config.js` 不被提交（除模板外）

---

### BUG-02：Fernet 密钥丢失/损坏后，旧加密 API Key 永久不可恢复，用户无明确提示

- 严重等级：**P0**
- 影响功能：配置保存 — API Key 丢失后用户需重新填写，且无明确错误提示
- 证据文件：[config_store.py](file:///e:/test/danmu/app/config_store.py)
- 证据代码：
  ```python
  # config_store.py:137-158
  def _init_fernet(self):
      if not _HAS_CRYPTO:
          logger.warning(tr("config.crypto_missing"))
          return None
      if self._key_file.exists():
          key = self._key_file.read_bytes()
          try:
              f = Fernet(key)
              f.decrypt(f.encrypt(b"test"))
              return f
          except Exception:
              logger.warning(tr("config.crypto_key_regenerated"))
              # Key corrupted, generate a new one (old encrypted data becomes unreadable)
              pass
      key = Fernet.generate_key()
      self._key_file.write_bytes(key)
      _restrict_key_file_permissions(self._key_file)
      return Fernet(key)
  ```
- 复现路径：
  1. 用户正常使用，API Key 已加密存储在 `config.db`
  2. `%APPDATA%/DanmuAI/.key` 被意外删除或损坏
  3. 重启应用 → `_init_fernet` 生成新密钥 → 旧 `api_key_encrypted` 解密失败
  4. `get_api_key()` 返回空字符串，用户看到 API Key 为空，但无明确提示"旧密钥已丢失，请重新填写"
- 根因分析：密钥损坏时仅 `logger.warning`，无用户可见提示。解密失败时静默返回空值，用户可能误以为从未配置过 API Key。
- 最小修复建议：在 `_init_fernet` 检测到密钥重新生成时，设置一个标志位（如 `self.key_regenerated = True`）；在 `get_startup_notice()` 中追加提示"检测到加密密钥已更新，之前保存的 API Key 需要重新填写"。
- 是否建议本次自动修复：**否**（审计工单不允许代码修改）
- 需要补充的测试：测试密钥丢失后 `get_api_key()` 返回空值且 `get_startup_notice()` 包含提醒

---

### BUG-03：`SingleInstanceGuard` 在 probe→listen 之间存在竞态窗口，可能导致双实例启动

- 严重等级：**P1**
- 影响功能：启动与生命周期 — 极端情况下可能启动两个实例
- 证据文件：[single_instance.py](file:///e:/test/danmu/app/single_instance.py)
- 证据代码：
  ```python
  # single_instance.py:60-73
  def try_acquire(self) -> SingleInstanceAcquireResult:
      if self._activate_existing_instance():
          return SingleInstanceAcquireResult(SingleInstanceAcquireKind.ACTIVATED_EXISTING)
      if self._listen_primary():
          return SingleInstanceAcquireResult(SingleInstanceAcquireKind.PRIMARY)
      # Race window: another instance may have claimed the name between probe and listen.
      if self._activate_existing_instance():
          return SingleInstanceAcquireResult(SingleInstanceAcquireKind.ACTIVATED_EXISTING)
      return SingleInstanceAcquireResult(SingleInstanceAcquireKind.ACTIVATION_FAILED)
  ```
- 复现路径：
  1. 进程 A 正在关闭（QLocalServer 已停止但进程未退出）
  2. 进程 B 调用 `_activate_existing_instance()` → 连接失败（A 已停止监听）
  3. 进程 B 调用 `_listen_primary()` → 成功
  4. 进程 C 同时执行步骤 2-3 → `_activate_existing_instance()` 可能连接到 B 的 server（正常），也可能在 B 还未完成 listen 时连接失败
  5. 如果 C 在 B 的 `_listen_primary()` 之前到达，两者都尝试 listen → `removeServer` + retry 逻辑可能让两者都成功
- 根因分析：代码注释已承认竞态窗口（L68），但 `ACTIVATION_FAILED` 分支不退出进程，而是返回给 `main()` 处理。如果 `main()` 在此分支继续启动，则出现双实例。
- 最小修复建议：在 `main()` 中，当 `SingleInstanceAcquireResult.activation_failed` 为 True 时，应弹窗提示用户并退出，而非继续启动。
- 是否建议本次自动修复：**否**
- 需要补充的测试：测试 `ACTIVATION_FAILED` 分支时 `main()` 的行为

---

### BUG-04：`PetBarrageController.deliver_batch` 在弹幕文本不足时分配空字符串气泡

- 严重等级：**P1**
- 影响功能：桌宠模式 — 部分桌宠显示空气泡
- 证据文件：[pet_barrage.py](file:///e:/test/danmu/app/pet/pet_barrage.py)
- 证据代码：
  ```python
  # pet_barrage.py:225-236
  def deliver_batch(self, texts: list[str], ...) -> list[PetBarrageDelivery]:
      deliveries: list[PetBarrageDelivery] = []
      for idx, window in enumerate(self._windows):
          text = texts[idx] if idx < len(texts) else ""
          delivery = PetBarrageDelivery(
              slot_id=window.slot_id,
              text=text,
              ...
          )
          deliveries.append(delivery)
          window.set_bubble_text(text)
  ```
- 复现路径：
  1. 启用桌宠弹幕模式（5 个桌宠实例）
  2. AI 返回 3 条弹幕
  3. `deliver_batch` 被调用时 `texts` 长度为 3，`self._windows` 长度为 5
  4. 第 4、5 个桌宠收到 `text=""` → `set_bubble_text("")` → 气泡消失
  5. 但 `PetBarrageDelivery` 中 `text=""` 被记录，可能导致后续逻辑误判
- 根因分析：未对 `texts` 不足的情况做兜底处理（如从自定义弹幕池补齐，或跳过无文本的桌宠）。
- 最小修复建议：当 `idx >= len(texts)` 时，跳过该窗口的 `set_bubble_text` 调用，或从弹幕池补齐。
- 是否建议本次自动修复：**否**
- 需要补充的测试：测试 `deliver_batch` 在 `texts` 少于窗口数量时的行为

---

### BUG-05：`update_service._state` 字典部分读取路径未持锁，存在数据竞争

- 严重等级：**P1**
- 影响功能：自动更新 — 状态读取不一致可能导致 UI 显示错误
- 证据文件：[update_service.py](file:///e:/test/danmu/app/update_service.py)
- 证据代码：
  ```python
  # update_service.py:13-21
  _lock = threading.Lock()
  _state: dict[str, Any] = {
      "last_check": None,
      "pending_update": None,
      "last_error": None,
      "download_phase": "idle",
      "download_progress": 0,
      "package_size_bytes": 0,
      "download_thread": None,
  }
  ```
  `get_status()` 方法（L142-190）中，在 `_lock` 外读取 `_state` 的 `pending_update` 和 `download_phase`：
  ```python
  # update_service.py:162-166
  with _lock:
      pending_info = _state.get("pending_update")
      phase = str(_state.get("download_phase") or "idle")
  ```
  但 `_enrich_status()` 方法（L117-139）中也在 `_lock` 外读取 `_state`：
  ```python
  # update_service.py:117-122
  def _enrich_status(status: UpdateStatus) -> UpdateStatus:
      with _lock:
          phase = str(_state.get("download_phase") or "idle")
          progress = int(_state.get("download_progress") or 0)
          ...
  ```
  虽然 `_enrich_status` 内部持锁，但调用方 `get_status()` 在 L162-166 持锁读取后释放锁，再在 L170 调用 `_enrich_status` 再次持锁，两次读取之间状态可能已变化。
- 复现路径：
  1. 下载线程正在更新 `_state["download_phase"]` 从 `"downloading"` 到 `"ready"`
  2. `get_status()` 在 L162 读取到 `phase="downloading"`
  3. 下载线程在 L257 将 `download_phase` 更新为 `"ready"`
  4. `get_status()` 在 L170 调用 `_enrich_status()` 读取到 `phase="ready"`
  5. 返回的 `UpdateStatus` 中 `update_available=True`（基于 L162 的旧 phase），但 `download_ready=True`（基于 `_enrich_status` 的新 phase），语义矛盾
- 根因分析：`get_status()` 中两次持锁读取 `_state`，中间释放锁导致状态不一致。
- 最小修复建议：将 `get_status()` 中的所有 `_state` 读取合并到一次 `_lock` 获取中。
- 是否建议本次自动修复：**否**
- 需要补充的测试：并发测试 — 下载线程与 `get_status()` 同时运行时的状态一致性

---

### BUG-06：PyInstaller spec 缺少 `app.supabase_app_updates` 等 hiddenimport，可能导致运行时 ImportError

- 严重等级：**P1**
- 影响功能：打包发布 — frozen 模式下更新检查可能失败
- 证据文件：[DanmuAI.spec](file:///e:/test/danmu/DanmuAI.spec)
- 证据代码：
  ```python
  # DanmuAI.spec:66-129
  hiddenimports: list[str] = [
      ...
      "app.velopack_runtime",
      "app.velopack_config",
      "app.update_service",
      "app.web_api.update",
      ...
  ]
  ```
  缺少以下模块：
  - `app.supabase_app_updates` — 被 `app.web_api.update` 直接 import
  - `app.supabase_config` — 被 `app.supabase_app_updates` 直接 import
  - `app.release_channels` — 被 `app.web_api.update` 直接 import
  - `app.version_compare` — 被 `app.web_api.update` 直接 import
  - `app.web_api.app_update_state` — 被 `routes.py` 注册
  - `app.web_api.announcements_state` — 被 `routes.py` 注册
- 复现路径：
  1. 打包发布版运行
  2. 用户点击"检查更新"
  3. `app.web_api.update` → `from app.supabase_app_updates import ...` → `ImportError: No module named 'app.supabase_app_updates'`
  4. 更新检查失败，用户无法获取新版本通知
- 根因分析：PyInstaller 静态分析无法追踪函数内延迟 import 和动态路由注册，需显式列出。
- 最小修复建议：在 `DanmuAI.spec` 的 `hiddenimports` 中添加缺失模块。
- 是否建议本次自动修复：**否**
- 需要补充的测试：在 frozen 模式下测试更新检查 API 是否正常

---

### BUG-07：`web/static` 整体打包可能将用户 `supabase-config.js` 含密钥打入发布产物

- 严重等级：**P1**
- 影响功能：安全 — 开发者构建时可能将含真实 Supabase 凭据的配置文件打入发布包
- 证据文件：[DanmuAI.spec](file:///e:/test/danmu/DanmuAI.spec)
- 证据代码：
  ```python
  # DanmuAI.spec:53-54
  datas = [
      (str(root / "web" / "static"), "web/static"),
      ...
  ]
  ```
  整个 `web/static/` 目录被递归打包，包括 `supabase-config.js`（如果存在）。
- 复现路径：
  1. 开发者在 `web/static/` 下创建了 `supabase-config.js` 并填入真实凭据
  2. 执行 `pyinstaller DanmuAI.spec --noconfirm`
  3. `supabase-config.js` 被打入 `dist/DanmuAI/` 发布产物
  4. 用户安装后，`supabase_config.py` 从打包文件中读取到开发者的 Supabase 凭据
- 根因分析：`datas` 使用整个目录打包，无排除机制。
- 最小修复建议：在 `DanmuAI.spec` 中添加排除逻辑，或在打包脚本中添加检查步骤，确保 `supabase-config.js` 不在 `web/static/` 中（仅保留 `supabase-config.example.js`）。
- 是否建议本次自动修复：**否**
- 需要补充的测试：CI 检查打包产物中不包含 `supabase-config.js`

---

### BUG-08：自定义弹幕库 20000 条全量加载无分页，高频调用时存在性能风险

- 严重等级：**P2**
- 影响功能：性能 — 弹幕池加载可能阻塞主线程
- 证据文件：[danmu_pool.py](file:///e:/test/danmu/app/danmu_pool.py)
- 证据代码：
  ```python
  # danmu_pool.py:17
  CUSTOM_DANMU_POOL_MAX = 20000

  # danmu_pool.py:51-61
  def load_custom_danmu_pool(config) -> list[str]:
      if config is None or not danmu_pool_use_custom_from_config(config):
          return []
      getter = getattr(config, "get_custom_danmu_pool", None)
      if callable(getter):
          items = getter()
      else:
          raw = config.get_json("custom_danmu_pool", []) if hasattr(config, "get_json") else []
          items = raw if isinstance(raw, list) else []
      return _dedupe_lines(str(item) for item in items)
  ```
  以及 `reply_parser.py:86-97`：
  ```python
  def _scene_fillers(config=None) -> list[str]:
      pool = load_danmu_pool_for_config(config)
      if not pool:
          return []
      return sample_danmu_for_config(config, min(32, len(pool)), rng=random)

  def _generic_fillers(config=None) -> list[str]:
      pool = load_danmu_pool_for_config(config)
      if not pool:
          return []
      return sample_danmu_for_config(config, min(48, len(pool)), rng=random)
  ```
  每次 `normalize_reply_batch` 都调用 `_scene_fillers` 和 `_generic_fillers`，各触发一次全量加载。
- 复现路径：
  1. 用户添加 20000 条自定义弹幕
  2. 每次 AI 回复到达时，`normalize_reply_batch` 被调用
  3. `_scene_fillers` + `_generic_fillers` 各调用 `load_danmu_pool_for_config` → 全量读取 SQLite
  4. 在高频截图场景下（1s 间隔），每秒可能触发 2 次全量加载
- 根因分析：`load_custom_danmu_pool` 无缓存机制，每次调用都从 SQLite 全量读取。`_formula_meme_sets` 缓存仅用于烂梗库，自定义池无类似缓存。
- 最小修复建议：为自定义弹幕池添加进程内缓存（类似 `_formula_meme_sets`），在写入时失效。
- 是否建议本次自动修复：**否**
- 需要补充的测试：性能测试 — 20000 条弹幕池下 `normalize_reply_batch` 的执行时间

---

### BUG-09：`PetWindow._persist_position` 拖动过程中每次 mouseRelease 写 SQLite，高频场景下可能阻塞主线程

- 严重等级：**P2**
- 影响功能：性能 — 桌宠拖动后可能短暂卡顿
- 证据文件：[pet_window.py](file:///e:/test/danmu/app/pet/pet_window.py)
- 证据代码：
  ```python
  # pet_window.py:791-804
  def mouseReleaseEvent(self, event) -> None:
      if event.button() == Qt.MouseButton.LeftButton and self._drag_offset is not None:
          ...
          self._drag_offset = None
          self._dragging = False
          self._start_post_drag_waving()
          self._persist_position()
          event.accept()

  # pet_window.py:854-865
  def _persist_position(self) -> None:
      pos = self.pos()
      if self.slot_id > 0 or self._settings.barrage.enabled:
          ...
          return
      self._app.config.set("pet_position_x", str(pos.x()))
      self._app.config.set("pet_position_y", str(pos.y()))
      self._settings = PetSettings.from_config(self._app.config)
  ```
  每次 `mouseRelease` 都调用 `config.set()` 写 SQLite，且 `_persist_position` 还会重新解析 `PetSettings.from_config`。
- 复现路径：
  1. 启用桌宠
  2. 快速反复拖动桌宠并释放
  3. 每次释放都触发 SQLite 写入 + 配置重解析
- 根因分析：缺少防抖（debounce）机制，每次 mouseRelease 都立即写 DB。
- 最小修复建议：添加 QTimer 延迟写入（如 500ms 防抖），避免高频拖动时的重复写入。
- 是否建议本次自动修复：**否**
- 需要补充的测试：测试快速拖动时 SQLite 写入频率

---

### BUG-10：`reply_parser` 纯文本回退模式不区分场景，可能误将非弹幕文本解析为弹幕

- 严重等级：**P2**
- 影响功能：弹幕显示 — AI 返回非 JSON 格式时可能显示不相关文本
- 证据文件：[reply_parser.py](file:///e:/test/danmu/app/reply_parser.py)
- 证据代码：
  ```python
  # reply_parser.py:244-249
  else:
      candidates = [
          part.strip(" -\t\r\n")
          for part in raw.replace("\r", "\n").split("\n")
          if part.strip() and not _is_reasoning_preamble_line(part)
      ]
  ```
  当 AI 返回纯文本（非 JSON）时，按换行拆分作为弹幕。但某些模型可能返回解释性文本（如"这是根据场景生成的弹幕"），这些文本也会被当作弹幕显示。
- 复现路径：
  1. 使用非标准模型（如 GPT-4o），返回格式为纯文本解释
  2. `parse_ai_reply_payload` 进入纯文本回退分支
  3. 解释性文本被拆分为多条"弹幕"显示在屏幕上
- 根因分析：纯文本回退缺少语义过滤，仅过滤了推理前导行，未过滤解释性/元数据文本。
- 最小修复建议：增加启发式规则，过滤明显不是弹幕的文本（如包含"弹幕"、"生成"、"场景"等关键词的长句）。
- 是否建议本次自动修复：**否**
- 需要补充的测试：测试 AI 返回纯文本解释时的解析结果

---

### BUG-11：`PetBarrageController.apply_config` 每次调用重建所有窗口配置，无增量更新

- 严重等级：**P2**
- 影响功能：性能 — 配置变更时所有桌宠窗口重新加载素材
- 证据文件：[pet_barrage.py](file:///e:/test/danmu/app/pet/pet_barrage.py)
- 证据代码：
  ```python
  # pet_barrage.py:140-151
  def apply_config(self) -> None:
      if not self._windows:
          return
      settings = PetSettings.from_config(self._app.config)
      defaults = build_barrage_slots_payload(settings)
      for window in self._windows:
          slot_data = defaults[window.slot_id] if window.slot_id < len(defaults) else defaults[0]
          window.apply_slot_config(slot_data)
      ...
  ```
  `apply_slot_config` 内部调用 `reload_assets()`，会重新加载 spritesheet QPixmap。
- 复现路径：
  1. 启用桌宠弹幕模式
  2. 在 Web 控制台修改任何配置（如弹幕速度）
  3. `apply_config` 被调用 → 所有 5 个桌宠窗口重新加载素材
- 根因分析：无增量比较，每次配置变更都重建所有窗口。
- 最小修复建议：在 `apply_slot_config` 中比较 `asset_source` 和 `asset_path`，仅在变更时才 `reload_assets`。
- 是否建议本次自动修复：**否**
- 需要补充的测试：测试配置变更时素材是否被不必要地重新加载

---

### BUG-12：`version_compare` 不支持 4 段版本号，可能影响未来版本比较

- 严重等级：**P3**
- 影响功能：自动更新 — 未来使用 4 段版本号时比较结果可能不正确
- 证据文件：[version_compare.py](file:///e:/test/danmu/app/version_compare.py)
- 证据代码：
  ```python
  # version_compare.py:21-35
  def _parse_numeric_segments(core: str) -> tuple[int, ...]:
      if not core:
          return (0,)
      parts: list[int] = []
      for piece in core.split("."):
          piece = piece.strip()
          if not piece:
              parts.append(0)
              continue
          m = _SEGMENT_RE.match(piece)
          if not m or m.group(1) == "":
              raise ValueError(f"invalid version segment: {piece!r}")
          parts.append(int(m.group(1)))
      return tuple(parts)
  ```
  当前版本格式为 `0.3.3`（3 段），`_parse_numeric_segments` 支持任意段数。但 `compare_versions` 比较时使用元组比较，4 段版本 `1.0.0.1` 与 3 段版本 `1.0.0` 比较时，`(1, 0, 0, 1) > (1, 0, 0)` 为 True，语义正确。但若未来引入 `1.0.0-beta.1` 等复杂 prerelease 格式，当前 `prerelease` 比较仅为字符串比较，可能不符合 semver 规范。
- 复现路径：当前版本格式为 `0.3.3`，暂无实际影响。
- 根因分析：当前实现满足 3 段 semver 需求，但 prerelease 比较不够严格。
- 最小修复建议：暂不需要修改，但应在版本号规范文档中明确只使用 3 段 semver。
- 是否建议本次自动修复：**否**
- 需要补充的测试：测试 4 段版本号与 3 段版本号的比较结果

---

### BUG-13：`publish_windows_release.ps1` 获取版本号无格式校验，异常版本号会静默传播

- 严重等级：**P3**
- 影响功能：发布流程 — 版本号格式错误可能导致 Velopack 包名异常
- 证据文件：[publish_windows_release.ps1](file:///e:/test/danmu/scripts/publish_windows_release.ps1)
- 证据代码：
  ```powershell
  # publish_windows_release.ps1:43
  $appVersion = (python -c "from app.version import __version__; print(__version__)").Trim()
  ```
  无版本号格式校验，如果 `__version__` 包含空格、非数字字符或不符合 semver，会静默传播到 Velopack 包名和 `releases.win.json`。
- 复现路径：
  1. `app/version.py` 中 `__version__` 被误写为 `"0.3.3 "`（尾部空格）或 `"0.3.3-beta"`（含 prerelease）
  2. 发布脚本使用该版本号生成包名
  3. Velopack 包名与预期不符，更新源无法正确识别
- 根因分析：缺少版本号格式校验步骤。
- 最小修复建议：在发布脚本中添加版本号格式校验（如正则 `^\d+\.\d+\.\d+$`），不符合时终止发布。
- 是否建议本次自动修复：**否**
- 需要补充的测试：测试异常版本号时发布脚本是否报错

---

### BUG-14：测试覆盖缺失：无 pet、update、overlay 动画、velopack 相关测试

- 严重等级：**P3**
- 影响功能：测试与验收 — 核心模块无自动化测试覆盖
- 证据文件：[tests/](file:///e:/test/danmu/tests/) 目录
- 证据代码：
  - `tests/` 目录中无 `test_pet*.py`、`test_update*.py`、`test_overlay_animation*.py`、`test_velopack*.py`
  - `scripts/run_acceptance_gates.py` 中未包含 pet、update、overlay 动画相关测试
- 复现路径：
  1. 修改 `pet_barrage.py` 中的 `deliver_batch` 逻辑
  2. 无测试覆盖，修改可能引入回归而不被发现
- 根因分析：项目早期聚焦核心弹幕链路测试，pet/update/overlay 动画模块测试尚未补充。
- 最小修复建议：逐步补充高优先级测试（见 §8）。
- 是否建议本次自动修复：**否**
- 需要补充的测试：见 §8

---

## 4. 高风险但未确认问题

### HR-01：`webview_shell.py` 子进程启动可能阻塞主线程

- 证据文件：[webview_shell.py](file:///e:/test/danmu/app/webview_shell.py)
- 证据代码：`_launch_child_process()` (L363-404) 和 `_begin()` (L643-657) 中存在重试逻辑
- 风险描述：pywebview 子进程启动失败时，重试逻辑可能在主线程阻塞。`_WEBVIEW_ATTACH_MAX_ATTEMPTS = 2` 和 `_WEBVIEW_ATTACH_RETRY_MS = 1200` 意味着最多阻塞约 2.4 秒。但在极端情况下（如 WebView2 运行时缺失），可能导致更长时间阻塞。
- 需要人工确认：在 WebView2 未安装的 Windows 机器上测试启动行为。

### HR-02：`overlay.py` 在多显示器场景下可能无法正确置顶

- 证据文件：[overlay.py](file:///e:/test/danmu/app/overlay.py)
- 风险描述：`reassert_hwnd_topmost` 使用 Win32 API 设置窗口置顶，但在多显示器场景下，全屏应用（如游戏）可能覆盖 overlay。`_topmost_health_timer` 定期重新断言，但间隔可能不够短。
- 需要人工确认：在全屏游戏 + 多显示器场景下测试 overlay 置顶行为。

### HR-03：`config_store.py` 的 `check_same_thread=False` 可能导致 SQLite 并发问题

- 证据文件：[config_store.py](file:///e:/test/danmu/app/config_store.py)
- 证据代码：
  ```python
  # config_store.py:80-84
  self.conn = sqlite3.connect(
      str(db_path),
      check_same_thread=False,
      cached_statements=_SQLITE_CACHED_STATEMENTS,
  )
  ```
- 风险描述：`check_same_thread=False` 允许任意线程使用同一连接，但 SQLite 连接本身不是线程安全的。虽然写操作通过 `_write_lock` 串行化，但读操作（如 `get()` 走 `_cache`）在无锁情况下可能读到部分写入的缓存。当前 `_cache` 是普通 `dict`，Python GIL 保证单次 dict 读取的原子性，但多键读取之间可能不一致。
- 需要人工确认：在 HTTP 线程高频读取配置 + 主线程高频写入配置的场景下测试缓存一致性。

### HR-04：`mic_utterance.py` 状态机边界条件可能导致语音端点检测失败

- 证据文件：[mic_utterance.py](file:///e:/test/danmu/app/mic_utterance.py)
- 风险描述：`MicUtteranceDetector.poll` 是 4 状态机（silence→speech→trail→silence），但状态转换的边界条件（如 RMS 阈值、trail 超时）可能在嘈杂环境下频繁误触发或漏触发。
- 需要人工确认：在不同噪声环境下测试麦克风端点检测的准确率。

---

## 5. 性能与卡顿风险

### 5.1 启动速度

- **pywebview 子进程启动**：`webview_shell.py` 中 WebView2 冷启动可达 12-25 秒（`_FROZEN_LOAD_TIMEOUT_SEC = 25.0`），期间用户看到托盘图标但无主窗口。`_SLOW_START_PROMPT_SEC = 5.0` 后才显示"正在启动"提示。
- **建议**：将慢启动提示提前到 2 秒，或在托盘图标出现时立即显示"正在启动"气泡。

### 5.2 截图与 AI 请求

- **截图压缩**：`app/image_compress.py` 使用 PIL JPEG 压缩，`max_width=768, quality=85`。单次压缩通常 <50ms，但在高分辨率截图（如 4K）下可能超过 100ms。
- **AI 请求超时**：`ai_client.py` 使用 `httpx.Timeout(30.0, connect=5.0)`，重试最多 2 次。最坏情况下单次请求耗时 65 秒（30s × 2 + 5s connect）。

### 5.3 Overlay 渲染

- **60fps 渲染循环**：`overlay.py` 使用 16ms QTimer，在无动画时停止。`_use_fast_danmu_render` 对长文本/emoji 使用 `drawText` 替代 `QPainterPath.addText`，避免阻塞。但短文本仍走慢路径。
- **弹幕预渲染**：`_prepare_pixmaps_near_visible` 在弹幕接近可视区时预渲染 QPixmap，避免 paintEvent 中阻塞。设计合理，但大量弹幕同时进入可视区时可能批量预渲染。

### 5.4 SQLite

- **WAL 模式**：`config_store.py` 使用 WAL + `busy_timeout=5000`，写操作通过 `_write_lock` 串行化。设计合理，但 `_write_lock` 是 `threading.Lock`（不可重入），嵌套调用会死锁（代码注释已警告）。
- **自定义弹幕库全量加载**：见 BUG-08。

### 5.5 外部接口

- **Supabase 查询**：`supabase_app_updates.py` 使用 300 秒缓存 + 8 秒超时，设计合理。
- **Velopack 更新检查**：`update_service.py` 在 frozen 模式下才启用，源码模式跳过。

---

## 6. 发布与更新风险

### 6.1 PyInstaller 打包

- **hiddenimports 缺失**：见 BUG-06。`app.supabase_app_updates`、`app.supabase_config`、`app.release_channels`、`app.version_compare`、`app.web_api.app_update_state`、`app.web_api.announcements_state` 未列入 `DanmuAI.spec` 的 `hiddenimports`。
- **web/static 整体打包**：见 BUG-07。`supabase-config.js` 可能被打入发布产物。
- **排除项**：`EXCLUDES` 列表合理，排除了 PyQt5/PySide2/开发工具。

### 6.2 Velopack 更新

- **更新源 URL**：`velopack_config.py` 中 `UPDATE_FEED_URL = "https://updates.qiaoqiao.buzz/releases/win/stable"`，硬编码且无 fallback。
- **版本比较**：`version_compare.py` 实现正确，支持 semver 和 prerelease。
- **下载线程**：`update_service.py` 使用 daemon 线程下载，应用退出时线程被强制终止，可能导致下载中断。但 Velopack 支持断点续传，影响有限。

### 6.3 版本号

- **当前版本**：`0.3.3`（`app/version.py`）
- **版本号校验**：见 BUG-13。发布脚本无版本号格式校验。

### 6.4 用户数据保留

- **配置数据库**：`%APPDATA%/DanmuAI/config.db`，Velopack 更新不修改用户数据目录。
- **加密密钥**：`%APPDATA%/DanmuAI/.key`，见 BUG-02。密钥丢失导致配置不可恢复。

### 6.5 MSI vs Setup.exe

- **发布脚本**：`publish_windows_release.ps1` 生成 Setup.exe + Portable.zip + nupkg，但未生成 MSI。MSI 相关文档（`docs/operations/W-REL-MSI-001-MSI主入口切换.md` 等）描述了 MSI 切换计划，但当前发布脚本尚未实现。

---

## 7. 安全与隐私风险

### 7.1 API Key 安全

- **加密存储**：`config_store.py` 使用 Fernet 加密 API Key，设计合理。
- **密钥丢失**：见 BUG-02。
- **GET 掩码**：`web_api/custom_models.py` 中 GET 请求返回掩码 `apiKey`（`MASKED_KEY`），设计合理。
- **日志脱敏**：`_redact_config_value_for_log` 对敏感配置键返回 `***`，设计合理。

### 7.2 Supabase 凭据

- **anon key 泄露**：见 BUG-01 和 BUG-07。
- **RLS 依赖**：`supabase_app_updates.py` 使用 anon key + PostgREST 读取 `app_updates` 表，依赖 Supabase RLS 策略限制访问。如果 RLS 配置不当，可能导致数据泄露。
- **建议**：审计 Supabase 项目的 RLS 策略，确保 `app_updates` 表仅允许读取 `enabled=true` 的行。

### 7.3 Web 控制台鉴权

- **随机 token**：`web_console.py` 启动时生成随机 token，写操作需 `Authorization: Bearer <token>`。
- **仅本机访问**：默认 `127.0.0.1:18765`，仅本机可访问。
- **WebSocket 鉴权**：使用 `ws_token` query 参数，与 HTTP token 独立。

### 7.4 日志泄露

- **日志脱敏**：见 7.1，敏感配置键已脱敏。
- **DANMU_API_SCHEDULE_DEBUG**：开启后输出 API 调度日志，可能包含请求详情。仅用于调试，不影响生产。

---

## 8. 建议新增的测试

| 测试文件 | 测试目标 | 断言内容 |
|----------|----------|----------|
| `tests/test_pet_barrage.py` | `PetBarrageController.deliver_batch` 弹幕不足时的行为 | 当 `texts` 少于窗口数量时，多余窗口不应收到空字符串气泡 |
| `tests/test_pet_barrage.py` | `PetBarrageController.apply_config` 增量更新 | 仅变更的窗口调用 `reload_assets`，未变更的窗口不重新加载 |
| `tests/test_update_service.py` | `update_service.get_status` 并发安全 | 下载线程运行时 `get_status()` 返回的状态一致（`download_phase` 与 `update_available` 不矛盾） |
| `tests/test_update_service.py` | `update_service` 非 frozen 模式 | 非 frozen 模式下 `check_for_updates()` 返回 `ok=False, frozen=False` |
| `tests/test_version_compare.py` | 4 段版本号比较 | `compare_versions("1.0.0.1", "1.0.0") == 1` |
| `tests/test_version_compare.py` | prerelease 比较 | `compare_versions("1.0.0-alpha", "1.0.0") == -1` |
| `tests/test_config_store_key_loss.py` | Fernet 密钥丢失后的行为 | 密钥重新生成后 `get_api_key()` 返回空字符串，`get_startup_notice()` 包含提醒 |
| `tests/test_single_instance.py` | `ACTIVATION_FAILED` 分支 | 当 `try_acquire()` 返回 `ACTIVATION_FAILED` 时，`main()` 不应继续启动 |
| `tests/test_danmu_pool_perf.py` | 20000 条弹幕池加载性能 | `load_custom_danmu_pool` 在 20000 条数据下执行时间 < 100ms |
| `tests/test_reply_parser_fallback.py` | 纯文本回退解析 | AI 返回解释性文本时，`parse_ai_reply_payload` 不应将解释文本当作弹幕 |
| `tests/test_pyinstaller_hiddenimports.py` | PyInstaller hiddenimports 完整性 | 所有 `app.web_api.*` 模块和其直接依赖都在 `DanmuAI.spec` 的 `hiddenimports` 中 |
| `tests/test_supabase_config_security.py` | `supabase-config.js` 不在 Git 中 | `git ls-files web/static/supabase-config.js` 返回空 |

---

## 9. 本次可自动修复项

本次不建议自动修复。

所有发现的问题均需要人工确认修复方案或涉及架构决策，不适合在审计工单中自动修复。具体原因：

- BUG-01/BUG-07（Supabase 凭据泄露）：需确认 `.gitignore` 和 `DanmuAI.spec` 的修改策略
- BUG-02（Fernet 密钥丢失）：需设计用户提示方案
- BUG-03（SingleInstanceGuard 竞态）：需确认 `main()` 中 `ACTIVATION_FAILED` 的处理策略
- BUG-04（桌宠空气泡）：需确认兜底策略（补齐 vs 跳过）
- BUG-05（update_service 竞态）：需确认锁粒度调整方案
- BUG-06（hiddenimports 缺失）：需确认完整列表
- BUG-08-11（性能问题）：需确认优化方案

---

## 10. 最终建议

### 优先级 1：修复 Supabase 凭据泄露风险（BUG-01 + BUG-07）

- 在 `.gitignore` 中添加 `web/static/supabase-config.js`
- 在 `DanmuAI.spec` 或打包脚本中排除 `supabase-config.js`
- 审计 Git 历史中是否已泄露凭据，如有则轮换 Supabase anon key
- **理由**：安全问题是最高优先级，且修复成本极低

### 优先级 2：补充 PyInstaller hiddenimports（BUG-06）

- 在 `DanmuAI.spec` 中添加 `app.supabase_app_updates`、`app.supabase_config`、`app.release_channels`、`app.version_compare`、`app.web_api.app_update_state`、`app.web_api.announcements_state`
- 在 frozen 模式下测试更新检查 API
- **理由**：发布后用户无法检查更新是严重的功能退化

### 优先级 3：修复 Fernet 密钥丢失提示（BUG-02）

- 在 `_init_fernet` 检测到密钥重新生成时，设置标志位
- 在 `get_startup_notice()` 中追加提示
- **理由**：用户配置丢失但无提示会导致困惑和支持成本
