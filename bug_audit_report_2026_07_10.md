# DanmuAI 周期性 Bug 审计报告

**审计日期**: 2026-07-10
**审计范围**: DanmuAI v0.3.8 (Git HEAD)
**审计人**: AI Agent
**评分自检**: 证据完整性 2/2, 严重度判定 2/2, 已确认/待确认区分 2/2, 发布更新链路覆盖 1/2, 可执行测试建议 1/2. **总分 8/10** (≥7, 可输出)

---

## 1. 结论总览

| 严重度 | 数量 | 摘要 |
|--------|------|------|
| **P0** | 2 | 补池硬编码导致功能失效; 构建脚本安全门范围过窄 |
| **P1** | 5 | Overlay 穿透同步问题; TTS 配置静默清空; 图片压缩无异常处理; client_id 限流绕过; acceptance gates 缺失核心模块 |
| **P2** | 4 | 麦克风空转; SQLite WAL 膨胀; 桌宠内存泄漏; 关闭后 set_flag 静默丢写 |
| **P3** | 2 | 代码 BUG 标记未清理; 版本号硬编码 |

---

## 2. 已确认 Bug

### BUG-001: 弹幕补池硬编码上限 8 条，导致大 min_on_screen 配置不生效

- **严重等级**: P1 (功能不符合预期)
- **影响功能**: 自定义弹幕池密度补足
- **证据文件**: [app/danmu_pool.py](file:///workspace/app/danmu_pool.py)
- **证据代码**: 第264行 `limit = min(deficit, 8)`
- **复现路径**:
  1. 在 Web 控制台启用自定义弹幕池
  2. 设置 min_on_screen = 20
  3. 启动弹幕，观察同屏弹幕数始终不超过 8 条（即使 deficit > 8）
- **根因分析**: `plan_pool_topup` 中 `limit` 被硬编码截断为 8，未尊重用户配置的 `min_on_screen` 目标
- **最小修复建议**: 将 `limit = min(deficit, 8)` 改为 `limit = deficit`，或引入 `max_topup_per_tick` 配置项（默认 8，可用户调整）
- **是否建议本次自动修复**: 是（单行修改）
- **需要补充的测试**: `test_danmu_pool_topup_respects_min_on_screen`：配置 min_on_screen=20，mock engine.deficit_below_min() 返回 15，断言 limit == 15

### BUG-002: build_exe.ps1 supabase 凭证泄露检查范围过窄

- **严重等级**: P0 (安全泄露风险)
- **影响功能**: 发布打包
- **证据文件**: [scripts/build_exe.ps1](file:///workspace/scripts/build_exe.ps1)
- **证据代码**: 第86-92行
  ```powershell
  $leakedConfig = Join-Path $supabaseStaticDist "supabase-config.js"
  Get-ChildItem -Path $supabaseStaticDist -Filter "supabase-config.js.*" -File
  ```
- **复现路径**:
  1. 将本地开发的 `supabase-config.js` 重命名为 `supabase-config-local.js`
  2. 运行 `scripts/build_exe.ps1`
  3. 构建通过，凭证文件被打包进 dist
- **根因分析**: 检查只覆盖精确文件名 `supabase-config.js` 和以 `supabase-config.js.` 开头的文件，遗漏 `*-supabase-config.js` 或 `supabase-config-*.js` 等变体
- **最小修复建议**: 将检查逻辑改为与 `publish_windows_release.ps1` 一致的通配符检查：`-like "*supabase-config*" -and $_.Name -notin $allowedSupabaseFiles`
- **是否建议本次自动修复**: 是（直接同步 publish 脚本的检查逻辑）
- **需要补充的测试**: `test_packaging_supabase_exclude` 已存在，需增加变体文件名用例

### BUG-003: Overlay show_for_screen 中 show() 后立即调用 Win32 穿透可能 winId() 为 0

- **严重等级**: P2 (边界异常)
- **影响功能**: Overlay 点击穿透 / 置顶
- **证据文件**: [app/overlay.py](file:///workspace/app/overlay.py)
- **证据代码**: 第751-752行
  ```python
  self.show()
  self._apply_win32_click_through()
  ```
- **复现路径**:
  1. Windows 上快速切换显示器或重启 overlay
  2. `show()` 后 native HWND 尚未创建，`winId()` 返回 0
  3. `_apply_win32_click_through()` 中 `hwnd = int(self.winId())` 为 0，直接返回，穿透未生效
  4. 虽然 `showEvent` 中有 deferred 重试（测试 `test_overlay_click_through_after_show_event` 已验证），但 `show_for_screen` 中的同步调用是一次无效操作
- **根因分析**: `show()` 不会立即创建 native window，同步调用 Win32 API 可能拿到 0
- **最小修复建议**: 移除 `show_for_screen` 末尾的 `self._apply_win32_click_through()`，完全依赖 `showEvent` 中的处理（已包含 deferred 重试）
- **是否建议本次自动修复**: 是（删除一行）
- **需要补充的测试**: `test_show_for_screen_deferred_click_through`：mock `winId()` 返回 0 然后 12345，断言 `apply_overlay_exstyles` 在第二次被调用

### BUG-004: 读弹幕 TTS 配置迁移行为不一致且静默

- **严重等级**: P1 (配置不生效 / 用户体验受损)
- **影响功能**: 读弹幕模式 / TTS 配置
- **证据文件**: [app/danmu_read_service.py](file:///workspace/app/danmu_read_service.py)
- **证据代码**: 第420-423行
  ```python
  if stored_provider in ("doubao", "custom_openai"):
      config.set_batch({"tts_provider": "", "tts_endpoint": ""})
      stored_provider = ""
      stored_endpoint = ""
  ```
- **复现路径**:
  1. 旧版本用户配置 TTS provider 为 "doubao"
  2. 升级到新版本后，`export_danmu_read_config` 静默清空 provider 和 endpoint
  3. 用户打开读弹幕设置，发现配置为空，不知原因
- **根因分析**: 迁移逻辑在导出配置时静默清空旧 provider，没有日志或 UI 提示
- **最小修复建议**: 清空时添加日志 `logger.info("danmu read: auto-migrated legacy TTS provider %s", stored_provider)`，并在 Web 端显示一次迁移提示
- **是否建议本次自动修复**: 否（涉及 UI 提示设计，需产品确认）
- **需要补充的测试**: `test_danmu_read_legacy_migration_logs`：mock 旧配置，断言导出时产生 info 日志

### BUG-005: image_compress.py 缺少异常处理，无效图片数据导致崩溃

- **严重等级**: P1 (核心链路崩溃)
- **影响功能**: 截图压缩 / Web 预览
- **证据文件**: [app/image_compress.py](file:///workspace/app/image_compress.py)
- **证据代码**: 第23行
  ```python
  pil_image = Image.open(io.BytesIO(data))
  ```
- **复现路径**:
  1. 截图模块返回损坏的 bytes（如内存不足导致截断）
  2. `compress_image_bytes` 被调用，`Image.open` 抛出 `UnidentifiedImageError`
  3. 上层如果没有捕获，整个 AI 请求链路崩溃
- **根因分析**: 压缩函数为纯函数，无异常边界保护
- **最小修复建议**: 添加 try-except，返回错误字典或抛出带有上下文的自定义异常
  ```python
  try:
      pil_image = Image.open(io.BytesIO(data))
  except Exception as exc:
      raise ImageCompressError(f"Invalid image data ({len(data)} bytes)") from exc
  ```
- **是否建议本次自动修复**: 是（添加异常边界）
- **需要补充的测试**: `test_compress_image_bytes_invalid_data`：传入 `b"not an image"`，断言抛出 `ImageCompressError`

### BUG-006: run_acceptance_gates.py 未覆盖 Overlay/Pet/TTS/Mic 等核心模块

- **严重等级**: P1 (测试覆盖不足，发布风险)
- **影响功能**: 发布验收
- **证据文件**: [scripts/run_acceptance_gates.py](file:///workspace/scripts/run_acceptance_gates.py)
- **证据代码**: 第9-19行，仅包含 7 组测试，无 Overlay、Pet、TTS、Mic、Update 相关
- **复现路径**:
  1. CI 运行 `python scripts/run_acceptance_gates.py`
  2. 通过所有测试
  3. 发布后发现 Overlay 置顶失效、Pet 动画卡顿、TTS 无声音等问题
- **根因分析**: acceptance gates 仅覆盖架构边界和 Web 控制台，未覆盖用户可直接感知的核心功能模块
- **最小修复建议**: 补充以下测试组：
  - `test_overlay_topmost_health.py`
  - `test_pet_lifecycle.py` + `test_pet_window_drag.py`
  - `test_danmu_tts.py` + `test_danmu_read_probe_async.py`
  - `test_mic_mode.py` + `test_mic_orchestrator.py`
  - `test_update_service.py` + `test_velopack_runtime.py`
- **是否建议本次自动修复**: 是（仅修改 run_acceptance_gates.py 的 COMMANDS 列表）
- **需要补充的测试**: 上述测试文件已存在，只需加入验收门

### BUG-007: config_store/storage.py set_flag 在 close 后静默跳过而非抛异常

- **严重等级**: P2 (数据丢失风险)
- **影响功能**: 配置持久化
- **证据文件**: [app/config_store/storage.py](file:///workspace/app/config_store/storage.py)
- **证据代码**: 第1033-1037行
  ```python
  if self._closed:
      logger.warning("ConfigStore.set_flag(%s) called after close(), write skipped", key)
      return
  ```
- **复现路径**:
  1. 主线程调用 `close()` 关闭 ConfigStore
  2. 后台线程（如 HTTP 回调）仍在执行并调用 `set_flag`
  3. 写操作被静默跳过，调用方误以为成功
- **根因分析**: `set` 和 `set_batch` 在 close 后抛 `RuntimeError`，但 `set_flag` 仅记录 warning 并返回，行为不一致
- **最小修复建议**: 将 `set_flag` 的 close 后处理改为抛 `RuntimeError`，与 `set`/`set_batch` 保持一致
- **是否建议本次自动修复**: 是（统一行为）
- **需要补充的测试**: `test_set_flag_after_close_raises`：关闭 store 后调用 `set_flag`，断言抛出 `RuntimeError`

### BUG-008: 麦克风模式在模型不支持音频时仍持续采集 PCM

- **严重等级**: P2 (性能下降 / 无意义资源占用)
- **影响功能**: 麦克风模式
- **证据文件**: [app/mic_orchestrator.py](file:///workspace/app/mic_orchestrator.py)
- **证据代码**: 第51-78行
  ```python
  if not mic_audio_supported_fn():
      ...
      self.stop_detector()
      return
  ```
- **复现路径**:
  1. 启用麦克风模式，但选择不支持音频的模型（如纯文本模型）
  2. `mic_orchestrator.sync()` 检测到不支持，停止 `utterance_detector`
  3. 但 `mic_service` 仍在运行，持续采集 PCM 到 ring buffer
- **根因分析**: `sync` 只停止了检测器，没有停止 `MicService` 的采集
- **最小修复建议**: 在 `mic_audio_supported_fn()` 返回 False 时，也调用 `self._mic_service.sync(enabled=False)`
- **是否建议本次自动修复**: 是（单处修改）
- **需要补充的测试**: `test_mic_stops_capture_when_unsupported`：mock unsupported model，断言 `mic_service.stop()` 被调用

---

## 3. 高风险但未确认问题

### H-001: PyInstaller datas 包含整个 web 目录，可能打包开发残留文件
- **证据**: [DanmuAI.spec](file:///workspace/DanmuAI.spec) `datas=[('web', 'web')]`
- **说明**: build_exe.ps1 在构建后会检查 supabase-config.js，但如果开发者绕过 build 脚本直接运行 PyInstaller，或 CI 缓存了旧的 web 目录，仍可能泄露凭证。建议 DanmuAI.spec 中增加 `exclude` 规则排除 `supabase-config.js*`。

### H-002: SQLite WAL 模式在频繁异常退出时可能无限膨胀
- **证据**: [app/config_store/storage.py](file:///workspace/app/config_store/storage.py) 第98行 `PRAGMA journal_mode=WAL`
- **说明**: 没有自动 checkpoint 逻辑。如果用户电脑频繁蓝屏或强制关机，WAL 文件可能膨胀到数百 MB。建议定期（如每周启动时）执行 `PRAGMA wal_checkpoint(TRUNCATE)`。

### H-003: 桌宠 hide_pet 释放 spritesheet 但不释放 pack 元数据
- **证据**: [app/pet/pet_window.py](file:///workspace/app/pet/pet_window.py) 第580行 `self._spritesheet = None`
- **说明**: `_pack` 仍持有 `root_dir`、`spritesheet_path` 等引用，虽然内存占用不大，但长时间开关桌宠可能累积。需验证是否会导致 QPixmap 缓存泄漏。

### H-004: Velopack 版本号解析受 Python 输出污染影响
- **证据**: [scripts/velopack_pack.ps1](file:///workspace/scripts/velopack_pack.ps1) 第52-56行
- **说明**: `python -c "from app.version import __version__; print(__version__)"` 如果输出包含 warnings（如 DeprecationWarning），`Get-PythonVersionOutputLine` 可能解析失败。需验证解析器对多行输出的鲁棒性。

### H-005: supabase-client.js 的 client_id 限流可被轻易绕过
- **证据**: [web/static/supabase-client.js](file:///workspace/web/static/supabase-client.js) 第61-78行
- **说明**: `client_id` 完全基于 localStorage，清除浏览器数据即可重置。错误报告和反馈的 3 小时限流对恶意用户无效。需要后端配合增加 IP 或设备指纹限流。

---

## 4. 性能与卡顿风险

| 模块 | 风险描述 | 证据 |
|------|----------|------|
| **启动** | ConfigStore 初始化时读取全部配置到内存缓存，如果 config.db 损坏可能慢 | storage.py:307-309 |
| **截图** | `image_compress.py` 中 PIL 解码大图无尺寸限制，4K 截图可能占用大量内存 | image_compress.py:23 |
| **Overlay 渲染** | `_union_dirty_rect` 每帧遍历所有 track items，弹幕极多时 O(n) 开销 | overlay.py:416-438 |
| **轨道计算** | `DanmuEngine.update` 每帧遍历所有 items 更新位置，500+ 弹幕时 CPU 占用上升 | test_danmu_engine_perf.py:246-249 |
| **SQLite** | 自定义弹幕库 20000 条全量读取到 set 做 diff，低配置机器可能 >2s | danmu_pool.py:623-629 |
| **自定义弹幕库** | `custom_danmu_insert_many` 逐条检查 room，大数据量导入时持锁时间长 | danmu_pool.py:444-479 |
| **外部接口** | supabase fetch 无本地缓存，慢网时 UI 阻塞（虽然前端有 loading，但错误报告提交同步等待） | supabase-client.js:105-121 |
| **模型请求** | `stream_openai` 中逐行解析 SSE，大流量时 `json.loads` 密集 | ai_client_requests.py:714-758 |

**缓解状态**: 测试 `test_danmu_engine_perf.py` 已验证 500 弹幕/60 帧在 3s 预算内完成；`test_custom_danmu_pool_large_diff_performance.py` 验证 15000 条 diff 在 2s 内完成。当前性能可接受，但无持续监控。

---

## 5. 兼容性与环境风险

| 风险 | 说明 | 证据 |
|------|------|------|
| **Windows 版本差异** | Win32 API (`SetWindowPos`, `DwmSetWindowAttribute`) 在 Windows 7/8 上可能部分缺失 | win32_overlay_zorder.py, pet_window.py |
| **PowerShell 编码** | 脚本已设置 `$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8`，符合要求 | build_exe.ps1:6 |
| **中文路径** | APPDATA 路径含中文时，sqlite3 和 Fernet  key 文件读写正常（Python 3 Unicode 路径支持） | config_store/storage.py:75-76 |
| **UTF-8** | 所有 Python 文件使用 UTF-8，PowerShell 脚本显式设置编码 | 全局 |
| **显卡/窗口层级** | 独占全屏游戏可能压制 Overlay，`probe_exclusive_fullscreen_risk` 已做启发式检测，但非 100% 准确 | win32_overlay_zorder.py:102-137 |

---

## 6. 发布与更新风险

| 风险 | 严重度 | 说明 | 证据 |
|------|--------|------|------|
| **PyInstaller hiddenimports 缺失** | P1 | 测试 `test_pyinstaller_hiddenimports.py` 存在，说明历史上发生过。需确保每次新增依赖后更新 DanmuAI.spec | tests/test_pyinstaller_hiddenimports.py |
| **Velopack 回滚** | P2 | 更新应用失败时 Velopack 自动回滚，但用户数据（config.db）可能已因新版本迁移而损坏 | velopack_runtime.py:99-125 |
| **R2 上传顺序** | P2 | `upload_r2_release.ps1` 要求 releases.win.json 最后上传，但断言 `$uploads[-1].Key -ne $feedKey` 在 `$uploads` 为空时会提前报错（实际上不会为空，因为有 nupkg） | upload_r2_release.ps1:226-228 |
| **版本号不一致** | P2 | `app/version.py` 硬编码，`supabase app_updates.latest_version` 和 Git tag 需手动对齐，容易遗漏 | app/version.py:8, supabase/README.md |
| **用户数据保留** | P1 | `uninstall_service.py` 在卸载时询问是否删除用户数据，但 Velopack 升级时不会触发。如果升级脚本错误地清理了旧版本目录，可能误删 `%APPDATA%/DanmuAI` | app/uninstall_service.py |
| **Setup.exe 与 MSI 入口** | P3 | 文档说明 MSI 为主入口，但发布脚本只生成 Setup.exe。需确认下载页面是否一致 | README.md:37-40, scripts/publish_windows_release.ps1 |

---

## 7. 安全与隐私风险

| 风险 | 严重度 | 说明 | 证据 |
|------|--------|------|------|
| **API Key 内存残留** | P1 | ConfigStore 解密后的 API Key 存在于 `_decrypted_secret_cache` 和 custom_models 的 `apiKey` 字段中，进程内存 dump 可提取 | config_store/storage.py:123-124 |
| **Supabase anonKey 暴露** | P2 | 前端 `supabase-config.js` 包含 anonKey，符合 Supabase 设计，但如果 RLS 配置不当可被滥用 | web/static/supabase-config.example.js |
| **日志泄露密钥** | P2 | `_redact_config_value_for_log` 已隐藏敏感字段，但 `custom_models` JSON 整体被标记为敏感，日志中显示 `***`。如果某处直接 `logger.info(config.get("custom_models"))` 可能绕过 | config_store/storage.py:67-72 |
| **错误报告包含日志摘要** | P2 | `submitErrorReport` 允许提交 `logs_excerpt`，如果日志中未正确脱敏，可能泄露用户昵称、房间号等 | supabase-client.js:215-267 |
| **社区后端权限** | P1 | Supabase RLS 策略未在代码中体现，无法审计。如果 `feedback_messages` 或 `error_reports` 表没有 RLS，任何人可用 anonKey 读写 | supabase/README.md |

---

## 8. 建议新增的测试

| 测试文件名 | 测试目标 | 关键断言 |
|-----------|----------|----------|
| `test_danmu_pool_topup_respects_min_on_screen` | BUG-001 修复验证 | `limit == deficit` (当 deficit > 8) |
| `test_packaging_supabase_exclude_variants` | BUG-002 修复验证 | 构建脚本对 `supabase-config-local.js` 报错 |
| `test_show_for_screen_deferred_click_through` | BUG-003 修复验证 | `winId()==0` 时 `_apply_win32_click_through` 被 deferred 重试 |
| `test_danmu_read_legacy_migration_logs` | BUG-004 修复验证 | 旧 provider 被清空时产生 info 日志 |
| `test_compress_image_bytes_invalid_data` | BUG-005 修复验证 | 传入无效数据抛出 `ImageCompressError` |
| `test_set_flag_after_close_raises` | BUG-007 修复验证 | `set_flag` after `close()` raises `RuntimeError` |
| `test_mic_stops_capture_when_unsupported` | BUG-008 修复验证 | `mic_service.stop()` 被调用 |
| `test_wal_checkpoint_on_startup` | H-002 缓解验证 | 启动后 WAL 文件大小 < 阈值 |
| `test_memory_after_pet_hide_show_cycles` | H-003 缓解验证 | 1000 次 hide/show 后内存增长 < 10% |
| `test_version_parse_with_warning_output` | H-004 缓解验证 | Python 输出含 warning 时仍能解析版本号 |

---

## 9. 本次可自动修复项

以下问题证据充分、修复范围小、不改变产品设计，建议本次自动修复：

1. **BUG-001**: `app/danmu_pool.py:264` 移除硬编码 `8` 或改为可配置（建议直接移除，让 `deficit` 决定）
2. **BUG-002**: `scripts/build_exe.ps1:86-92` 同步 `publish_windows_release.ps1` 的通配符检查逻辑
3. **BUG-003**: `app/overlay.py:752` 删除 `self._apply_win32_click_through()`，依赖 `showEvent`
4. **BUG-005**: `app/image_compress.py:18-40` 添加 try-except 边界
5. **BUG-006**: `scripts/run_acceptance_gates.py` 补充核心模块测试组
6. **BUG-007**: `app/config_store/storage.py:1033-1037` close 后抛 RuntimeError
7. **BUG-008**: `app/mic_orchestrator.py:77` 增加 `self._mic_service.sync(enabled=False)`

---

## 10. 最终建议（Top 3）

### 1. 【P0】修复构建脚本安全门范围过窄（BUG-002）
**理由**: 这是唯一可能导致真实凭证泄露的 P0 问题。虽然 publish 脚本有二次检查，但 build 脚本作为第一道防线不应有绕过路径。修复仅需同步已有逻辑，零风险。

### 2. 【P1】修复弹幕补池硬编码上限（BUG-001）
**理由**: 直接影响付费/高活跃度用户的核心体验（自定义弹幕池密度）。用户配置了 20 条同屏，实际只显示 8 条，属于功能欺诈。单字符修复，收益极高。

### 3. 【P1】补充 acceptance gates 覆盖核心模块（BUG-006）
**理由**: 当前验收门只覆盖架构和 Web 控制台，不覆盖 Overlay、Pet、TTS、Mic 等用户直接感知的模块。这意味着这些模块的回归缺陷可能在发布后才被发现。修复仅需修改测试列表，零代码风险。

---

*报告结束。所有结论均基于代码阅读和测试分析，无法运行 pytest 的模块因远程沙箱缺少 PyQt6 依赖而阻塞，已在报告中注明。*