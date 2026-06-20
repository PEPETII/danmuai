# DanmuAI 周期性 Bug 审计报告（v3）

> **覆盖关系**：本报告**取代** `docs/bug-audit-report-2026-06-21.md` (v1, 1468 行) 与 `docs/bug-audit-report-2026-06-21-v2.md` (v2, 500 行)，不再单独维护那两个文件。本报告基于 commit `91fc81e` 的**当前代码状态**复核 v2 已列 BUG、核实 v1 carry-over、并对 v1/v2 未覆盖的模块（启动、桌宠、TTS、烂梗、Web API、模型适配器、发布链路）做完整扫描。
> **任务定位**：仅审计报告，不修代码（用户已确认 `audit-only-no-fix`）。

---

## 1. 本次审计范围

- 当前分支：`main`
- 当前 commit：`91fc81e`（feat: update core modules, pet system, meme barrage, AI client, danmu pool, tests and build scripts）
- 版本号：`0.3.4`（`app/version.py:8`）
- 检查时间：2026-06-21
- 已读取的关键文件（由 3 个并行只读子代理执行）：
  - **A 启动 / 生命周期**：`main.py`、`app/main_lifecycle_mixin.py`、`app/main_launch.py`、`app/main_launch_mixin.py`、`app/single_instance.py`、`app/velo*`、`app/webview_shell.py`、`app/tray.py`、`app/startup_trace.py`、`app/main_state_mixin.py`、`app/main_mic_mixin.py`
  - **B 弹幕链路**：`app/danmu_engine.py`、`app/danmu_engine_dedup.py`、`app/danmu_engine_models.py`、`app/overlay.py`、`app/floating_panel_engine.py`、`app/floating_panel_overlay.py`、`app/reply_parser.py`、`app/reply_queue.py`、`app/image_compress.py`、`app/screenshot_compress.py`、`app/jpeg_resize.py`、`app/live_freshness.py`
  - **C 模型调用**：`app/ai_client.py`、`app/ai_client_requests.py`、`app/ai_client_support.py`、`app/doubao_responses_stream.py`、`app/api_probe.py`、`app/api_schedule.py`、`app/model_providers.py`、`app/model_selection.py`、`app/model_catalog.py`、`app/providers/` 全包
  - **D 麦 / TTS / 读弹幕**：`app/mic_*.py` 共 10 个、`app/web_api/mic_test.py`、`app/danmu_tts.py`、`app/danmu_tts_playback.py`、`app/tts_providers.py`、`app/tts_catalog.py`、`app/tts_audio_utils.py`、`app/danmu_read_service.py`、`app/web_api/danmu_read.py`
  - **E 桌宠**：`app/pet/` 全 9 文件、`app/main_state_mixin.py`、`app/web_api/pet.py`、`data/pet/default/pet.json`
  - **F 配置 / SQLite**：`app/config_store.py`、`app/config_defaults.py`、`app/application/config_service.py`、`app/danmu_pool.py`、`app/danmu_pool_overlay.py`、`app/lifetime_stats.py`、`app/session_run_log.py`、`app/history_writer.py`
  - **G 烂梗 / 公式化**：`app/meme_barrage/` 全 6 文件、`app/main_meme_mixin.py`、`app/web_api/meme_barrage.py`
  - **H 发布 / 更新**：`DanmuAI.spec`、`scripts/build_exe.ps1`、`scripts/publish_windows_release.ps1`、`scripts/upload_r2_release.ps1`、`scripts/upload_github_release.ps1`、`scripts/sign_windows_release.ps1`、`scripts/velopack_pack.ps1`、`scripts/velopack_poc.ps1`、`scripts/run_acceptance_gates.py`、`scripts/audit_hiddenimports.py`、`app/velopack_runtime.py`、`app/velopack_config.py`、`app/update_service.py`、`app/version.py`、`app/version_compare.py`、`app/release_channels.py`、`app/uninstall_service.py`、`supabase/migrations/003_app_updates.sql`、`app/supabase_app_updates.py`、`app/supabase_config.py`、`.env.example`、`.gitignore`、`docs/operations/WINDOWS_RELEASE_*.md`、`docs/operations/PACKAGING_WINDOWS.md`、`docs/operations/RELEASE_CHECKLIST.md`、`docs/operations/W-REL-MSI-001~004-*.md`、`reports/W-REL-*-completion-report.md`、`reports/release-url-consistency-check.md`、`reports/release-url-migration-default-check.md`
  - **I Web 社区 / 后端**：`app/web_api/*.py` 全包、`app/web_console.py`、`app/web_console_ws.py`、`app/web_console_session_auth.py`、`app/web_console_runtime.py`、`supabase/migrations/001~010-*.sql`、`web/static/supabase-config.example.js`、`web/static/supabase-client.js`、`.vercel/project.json`
  - **J 测试 / 验收**：`conftest.py`、`tests/conftest.py`、`tests/fakes.py`、`pytest.ini`、`requirements.txt`、`requirements-dev.txt`、`.github/workflows/ci.yml`、`scripts/run_acceptance_gates.py`
- 已运行的命令：
  - `git log -1 --pretty=format:...` → `91fc81e 2026-06-21 03:34:49 +0800`
  - `git rev-parse --abbrev-ref HEAD` → `main`
  - 项目根 / `docs/` / `scripts/` / `tests/` / `reports/` / `tools/` / `.github/` 目录树枚举
- 未能运行的命令及原因：
  - **未运行 pytest 任何子集**：按 AGENTS.md §10 / Codex 提示词手册护栏 §2，IDE Agent 禁止本地全量 pytest；本次任务为纯审计报告，按用户选择 `audit-only-no-fix`，连与工单相关的分批测试也未触发，避免磁盘/.pytest_tmp 噪音。
  - **未运行 `scripts/run_acceptance_gates.py`**：本机 PowerShell 可执行，但脚本自身存在 P2-1（引用不存在的测试文件），运行会立即失败，留作下一轮工单处理。
  - **未运行 `python scripts/boundary_guard.py`**：触发条件是"触达主链路/Web API/DanmuApp 主入口的代码工单"——本任务不是代码工单。
  - **未运行 PyInstaller 端到端冒烟**（`pyinstaller DanmuAI.spec`）：见 §6 P0-1，缺口需在发布工单里补，本审计以静态 AST + spec 阅读为限。

---

## 2. 结论总览

### P0：会导致无法发布 / 数据丢失 / 启动阻塞 / 主线程长时间卡死的问题

| # | 标题 | 维度 |
|---|------|------|
| **REL-P0-1** | W-REL-MSI-001 完成报告与代码背离：`scripts/velopack_pack.ps1` 仍只产 Setup.exe 不产 MSI | H |
| **REL-P0-2** | R2 上传脚本未上传 MSI、未生成 `DanmuAI-Installer.msi` latest 别名 | H |
| **REL-P0-3** | GitHub Release 上传脚本不包含 MSI 资产，主入口声明仍为 Setup.exe | H |
| **REL-P0-4** | `publish_windows_release.ps1` 主入口声明、控制台 banner、VERSION.txt 报告均不含 MSI | H |
| **TTS-P0-5** | `danmu_read_service.run_probe` 在主线程同步 HTTP，慢响应可阻塞 UI 数秒至数十秒 | D |
| **WEB-P0-6** | `/api/probe` / `/api/custom-models/probe` 不走 `_invoke_main`，HTTP 线程直接调用 `bridge.danmu_app.probe_api_connection()` 数十秒 | I |
| **LIFE-P0-7** | `DanmuApp.quit()` 串行 wait 两个 QThreadPool（`capture` + `ai`），任一卡死会拖累另一个 | A |
| **POOL-P0-8** | `get_custom_danmu_pool_for_store` 仍无分页（`LIMIT 20000` 仅约束上限，仍全量 fetchall + 冷路径无缓存） | F |

### P1：会导致核心功能不可用、跨线程违规、用户报告"看起来坏"、可观测性 / 维护性显著退化

| # | 标题 | 维度 |
|---|------|------|
| **MIC-P1-1** | `app/mic_capture._last_error` 在 PortAudio 线程写、主线程无锁读（CPython 字面量原子，但 stale 风险） | D |
| **MIC-P1-2** | Web 设置面板"说话内容相关弹幕数量 / 额外插入数量"字段无对应实现，`mic_prompt` 用 `normal_reply_count` | D |
| **TTS-P1-3** | `_DanmuTtsRunnable` 已用 `QMetaObject.invokeMethod` + QueuedConnection 修复跨线程违规，但 AGENTS.md §9 / §A.5.4 仍描述为"已知违规" | D |
| **TTS-P1-4** | `tts_catalog.MIMO_VOICES` 与 `tts_providers.MIMO_TTS_VOICES` 两份常量双源，新增 voice 必须两处同步 | D |
| **TTS-P1-5** | `danmu_read_service._on_tick` 在 floating_panel 模式仍读 `engine.current_display_count()`（恒为 0），产生重复 `no_visible_text` 日志 | D |
| **TTS-P1-6** | `danmu_read_service._on_tick` 当 `texts == []` 时 `random.choice([])` 抛 `IndexError` | D |
| **POOL-P1-7** | `_tags_cache` 模块级全局缓存 TTL 已实现，但 `save_settings` 后下一次 `get_tags` 仍可能命中旧 cache（coupling 隐式） | G |
| **POOL-P1-8** | `MemeBarrageService.apply_remote_page` 修改 `_page_num` 非原子，并发 collect tick 可能互相覆盖 | G |
| **POOL-P1-9** | `_MemeBarrageBridge` 在 `quit()` 时未 `deleteLater`，可能 QApplication 退出后触发 RuntimeError | G |
| **POOL-P1-10** | `apply_meme_barrage_settings` 调用 `reset_cursors()` 立即写 config.db，用户尚未确认就持久化 | G |
| **POOL-P1-11** | `_meme_start_ai_select` 用 `getattr(self, "_latest_screenshot", None)` 可能拿到与当前 collect tick 不一致的旧画面 | G |
| **POOL-P1-12** | `_meme_display_backlog` 不限大小；显示节流每 tick 2 条但 backlog 累积无上限告警 | G |
| **POOL-P1-13** | `MemeAiSelectRunnable` 共用 `self._worker`，stopping 时抛英文 `RuntimeError` 而非翻译键 | G |
| **PET-P1-14** | `_tick_momentum` 内 `_set_drag_anim_state` 与 `momentum_run_state_for_vx` 状态更新顺序耦合，`running-right ↔ running-left` 跳变时 `_frame_index` 反复回 0（视觉退化） | E |
| **PET-P1-15** | `_paint_bubble` 每帧新建 `QTextDocument` + PaintContext（GC 压力 + Qt layout 重算） | E |
| **PET-P1-16** | 桌宠 sprite 缺图静默 return，`_load_error` 为空时 UI 与日志均无提示 | E |
| **PET-P1-17** | 槽位资产热切换 `reload_assets()` 后 `_frame_index`/`_frame_clock` 不重置，新 sprite 按旧 row 索引 | E |
| **PET-P1-18** | 双击命令框仅 slot_id==0 开启；barrage 模式下所有桌宠对双击无反应（语义未文档化） | E |
| **BARRAGE-P1-19** | `resolve_danmu_max_chars` docstring 写"中文 15 / 英文 40"，实际常量 `DEFAULT_DANMU_MAX_CHARS_ZH=20 / EN=50`（默认值漂移，UI 与 docstring 失真） | B |
| **BARRAGE-P1-20** | `danmu_lines > DANMU_LINES_MAX=20` 时 UI 显示原值，实际生效 20 行，无 warn 日志 | B |
| **BARRAGE-P1-21** | `_FAST_DANMU_RENDER_MIN_LEN` 在 `overlay.py:46=8` 与 `floating_panel_overlay.py:32=36` 不一致（两套阈值无统一文档） | B |
| **BARRAGE-P1-22** | `overlay.show_for_screen` 的 `geo_key` 未含 `devicePixelRatio`，DPR 变化时不 reload_tracks | B |
| **WEB-P1-23** | `web_console_ws` 仅鉴权 ws_token，不检查 Origin/Host；持有 token 的本机进程可订阅 status/logs | I |
| **WEB-P1-24** | `/api/preview/compress` `max_width` 与 `quality` 无边界校验，恶意大文件 base64 编码阻塞 | I |
| **WEB-P1-25** | `routes._invoke_main` 异常映射未覆盖 `OSError` / `ConnectionError` → 一律 500 | I |
| **WEB-P1-26** | `invoke_on_main` 超时后无主线程心跳，HTTP 504 错误信息不含主线程调用栈 | I |
| **WEB-P1-27** | `/api/session` 同源校验 `request_full` 未默认补 `:18765`，`Host: 127.0.0.1` 与 `Origin: http://127.0.0.1:18765` 不匹配致 403 | I |
| **WEB-P1-28** | `web_api/mic_test.list_mic_devices` 直接在 HTTP 线程调 `sounddevice.query_devices()`，阻塞 PortAudio | I |
| **LIFE-P1-29** | `main.py:1046-1079` `ACTIVATION_FAILED` 后 `time.sleep(0.5)` 阻塞主线程 ≤1s | A |
| **LIFE-P1-30** | `_open_web_console` 在 failed 态 `try_recover_web_console_for_user_action` 仅首次触发，用户重连"卡死" | A |
| **LIFE-P1-31** | `webview_shell.attach_webview_shell` 调用者未传 `on_handshake_failed` 时失败静默 | A |
| **LIFE-P1-32** | `webview_shell.schedule_webview_attach` 重试 `_SPAWN_MAX_ATTEMPTS=3` × `vpkAttachPoll=500ms` = 1.5s，可能不足以覆盖 WebView2 冷启动 | A |
| **MODEL-P1-33** | `_probe_openai` 用 `max_tokens=1`，GLM-4.5V 等要求 ≥4 的 provider 返回 400 | C |
| **MODEL-P1-34** | `image_compress.compress_image_bytes` 对 PIL 解码历史漏洞（CVE-2023-44271 类）仅靠 10MB 上限，不防御超大数据 | C |
| **MODEL-P1-35** | `providers/registry.is_minimax_endpoint` 子串匹配 `minimax` / `minimaxi`，可能误注入 `reasoning_split: true` 到无关服务 | C |
| **REL-P1-36** | `app/release_channels.py:17` 兜底 `R2_LATEST_INSTALLER_URL` 仍为 Setup.exe URL，与线上 MSI URL 冲突 | H |
| **REL-P1-37** | `supabase/migrations/003_app_updates.sql:7` 列默认 `release_url` 仍为 Setup.exe URL，新环境 migration 后立刻不一致 | H |
| **REL-P1-38** | `docs/operations/WINDOWS_RELEASE_CONTRACT.md §2 / §4` 自相矛盾（既说 MSI 已移除，又说 MSI 是主入口） | H |
| **REL-P1-39** | `docs/operations/PACKAGING_WINDOWS.md` / `RELEASE_CHECKLIST.md` / `docs/release/README.md` / `website/index.html` / `README.md` 全部以 Setup.exe 为主下载 | H |
| **REL-P1-40** | `app/velopack_config.py` 默认 URL `https://updates.qiaoqiao.buzz/releases/win/stable` 与 Supabase manifest 双轨；当前文档未说明优先级 | H |

### P2：会导致性能下降、边界异常、配置不生效的问题

| # | 标题 | 维度 |
|---|------|------|
| **CFG-P2-1** | `scripts/run_acceptance_gates.py` 引用不存在的 `tests/test_boundary_guard.py` 与 `tests/test_diagnostics.py`，CI 立即失败 | J |
| **CFG-P2-2** | `scripts/audit_hiddenimports.py` 仅静态 AST 分析，未真正跑 PyInstaller；hiddenimports 端到端冒烟缺口 | H |
| **CFG-P2-3** | `app/main_launch.global_exception_hook` 在 frozen `sys.stderr is None` 二次异常时有 AttributeError 风险（已 try/except 兜底但非全局） | A |
| **BARRAGE-P2-4** | `_heuristic_comments_from_malformed_json` 已加 `_MAX_HEURISTIC_DEPTH=16` 但未捕获 `RecursionError`，深度嵌套 `}{` 仍可能栈溢出 | B |
| **BARRAGE-P2-5** | `_heuristic_comments_from_malformed_json` 用 `re.search(r'"comments"\s*:\s*\[(.*)$')` 无 `re.DOTALL`，跨行 `comments` 截取失败 | B |
| **BARRAGE-P2-6** | `_prepare_pixmaps_near_visible` 每帧 O(n) 检查所有轨道未渲染 item | B |
| **BARRAGE-P2-7** | `_prune_recent_by_ttl` 在 `_remember_content` 与 `_is_duplicate` 各调一次，每条弹幕 add_text 触发 2 次剪枝 | B |
| **BARRAGE-P2-8** | `FloatingPanelEngine.relayout_vertical_gaps` 仅在 `>max_items && 屏外` 时丢弃一条，无屏外可删时面板卡死 | B |
| **MODEL-P2-9** | `_get_http_client` 失败回退 HTTP/1.1 后不重试 HTTP/2 | C |
| **MODEL-P2-10** | `doubao_responses_stream.chunk_type` 用 `not in` 去重，profile 指标永远只看到 1 次同一 type 事件 | C |
| **MODEL-P2-11** | `_probe_doubao` fallback 路径不读 `body.json()`，重复失败不告知 | C |
| **MODEL-P2-12** | `screenshot_compress.compress_screenshot` `scaledToWidth` 不保留 aspect ratio（如果原图比例非整数） | C |
| **MODEL-P2-13** | `request_doubao` `thinking` 字段注入逻辑（`ai_client_requests.py:243`）与 `providers/adapters/mimo.py:53` 双处，需要同步维护 | C |
| **REL-P2-14** | `upload_github_release.ps1:132` 控制台硬编码"Primary download: ...Setup.exe" | H |
| **REL-P2-15** | `web/static/supabase-config.example.js` 若 `_collect_dir_datas` 未显式 exclude，会被打包；建议加 `exclude_names={"supabase-config.example.js"}` 或移至 `_templates/` | H |
| **MIC-P2-16** | `mic_buffer.try_take_recent_ms` `acquire(blocking=False)` 丢帧无错误返回，仅 R-P1 观测 | D |
| **MIC-P2-17** | `mic_orchestrator._sync_mic_service` 在 toggle 路径未独立处理，导致 `toggle` 时 mic 仍在录音（隐私风险） | D |
| **MIC-P2-18** | `mic_test_send.placeholder_image_data_uri` 每次重新 JPEG 编码 + base64，未缓存 | D |
| **TTS-P2-19** | `synthesize_tts` 入口不限制 text 长度，超长 prompt 触发 4xx | D |
| **TTS-P2-20** | `validate_custom_tts_fields` 仅校验 DASHSCOPE_QWEN model_id 非空 | D |
| **POOL-P2-21** | `runnable.py` 与主链路共用 `self._worker`，stopping 抛错文案未走 `tr(...)` | G |
| **POOL-P2-22** | `_tags_cache` invalidate 隐式耦合到 `save_settings`，调用方需要知道 | G |
| **PET-P2-23** | `pet_assets.validate_pet_pack_dir` 不校验 `state_spec.row < grid_rows`，超界运行时报 `IndexError` | E |
| **PET-P2-24** | `pet_facade._pet_barrage_disable_config_items` 不校验临时态 `danmu_render_mode == "pet_barrage"`，恢复值可能不一致 | E |
| **PET-P2-25** | `pet_barrage.sync_slots_to_config` 与 `pet_facade.apply_pet_settings_patch` 在 ctrl 为 None 时手工写 slot 字段，语义可能不一致 | E |
| **WEB-P2-26** | `routes._invoke_main` 已被 `run_in_executor` 包装，SSE diagnostics 路径会跨两次 event loop | I |
| **LIFE-P2-27** | `quit()` `waitForDone(2000)` 串行阻塞主线程，若 capture worker 卡死则 AI pool 永远等不到 | A |
| **LIFE-P2-28** | `webview_shell._DISABLE_SLOW_START_PROMPT = True` 是死代码（调试开关） | A |

### P3：代码卫生、文档不一致、潜在维护问题

| # | 标题 | 维度 |
|---|------|------|
| **DOC-P3-1** | AGENTS.md §A.3.10 仍写 `meme_barrage/client.py` 默认 `verify_ssl=False`（已改为 `True`，文档陈旧） | G |
| **DOC-P3-2** | AGENTS.md §A.5.4 仍写 `mic_capture.try_snapshot_pcm_ms` 直接访问 `MicRingBuffer` 私有字段（已封装，文档陈旧） | D |
| **DOC-P3-3** | AGENTS.md §9 仍写 `_play_worker` 跨线程 Qt 信号违规（已用 `QMetaObject.invokeMethod(QueuedConnection)` 修复） | D |
| **DOC-P3-4** | `web/static/supabase-client.js:17, 52` 与 `content-announcements.js:413` 仍按"复制 `supabase-config.example.js`"提示用户，但打包版该文件不存在 | I |
| **DOC-P3-5** | `docs/operations/CHANGELOG.md:39` 0.3.3 条目仍写"最新安装包别名 = DanmuAI-Setup.exe" | H |
| **DOC-P3-6** | `docs/operations/CHANGELOG.md` 0.3.4 条目未提 W-REL-MSI-001~004 完成情况 | H |
| **DOC-P3-7** | `docs/operations/WINDOWS_CODE_SIGNING.md:45` 只列 Setup.exe，未提 MSI 验签 | H |
| **DOC-P3-8** | `reports/release-url-consistency-check.md` / `release-url-migration-default-check.md` 2026-06-11 报告与当前 MSI 主入口背离，建议归档 | H |
| **HYG-P3-9** | 仓库根散落大量 `debug-*.log`（`debug-120c6c.log`、`debug-a9a516.log` 514KB 等）、`nul`、`.venv-build`、`.venv-build-312`、`dist/`、`build/`、`__pycache__/`、`.npmcache/`、`node_modules/`、`.ruff_cache/`、`pytest_cache/`、`pytest_tmp/`，应纳入 `.gitignore` 与 .gitattributes 清理 | J |
| **HYG-P3-10** | `debug-a9a516.log` 514KB 等大日志文件疑似含敏感 token / 用户路径，需在下次清理时人工核对后再删除 | J |
| **HYG-P3-11** | `nul` 文件（169B）在仓库根——PowerShell 上 `nul` 是设备名，疑似重定向残留 | J |
| **HYG-P3-12** | `main_lifecycle_mixin.py:146, 156` `_capture_in_flight = False` 重复赋值（v1 BUG-A03 重提） | A |
| **HYG-P3-13** | `danmu_pool.py` 中 f-string 拼接 SQL（当前已用参数化，风格提示） | F |
| **HYG-P3-14** | `update_service.py` `thread.start()` 注释说"blocking"但实际非阻塞（v1 BUG-H06 重提） | H |
| **HYG-P3-15** | `version_compare._split_core_prerelease` 仍按第一个 `-` 分割（已加 `+` 剥离，但多 `-` 仍未处理） | H |
| **HYG-P3-16** | `.vercel/project.json` 含 Vercel 项目/组织 ID 已提交到仓库（v1 BUG-I05 重提） | I |
| **HYG-P3-17** | `conftest.py` 的 `tmp_path` fixture 覆盖了 pytest 内置 `tmp_path`（v1 BUG-J02 重提） | J |

---

## 3. 已确认 Bug（精选 — P0 全部 + 高影响 P1）

> 本节只列**确认有证据**的 P0 和对用户体验影响最大的 P1。每条附文件:行号 + 证据。**已修复**的 v2 BUG-A02 ~ A13 与 v1 carry-over 不在此处重列，统一在 §4"v2 BUG 复核"中给出状态表。

### REL-P0-1：`scripts/velopack_pack.ps1` 未实施 W-REL-MSI-001 的代码改动

- **严重等级：P0**
- **影响功能**：发布链路（R2 + GitHub + Supabase release_url 全部依赖此脚本）
- **证据文件**：`scripts/velopack_pack.ps1:76-86`（`vpk pack` 调用块）；返回值（L103-112）；全文件 grep `wix|WiX|--msi|Ensure-Wix5` 无任何匹配
- **证据代码**：
  ```powershell
  # scripts/velopack_pack.ps1:76-86（无 --msi、无 Ensure-Wix5）
  $packResult = & $vpkPath pack --packId DanmuAI `
      --packVersion $Version `...
      --instLocation Either  # ← 与完成报告描述不符
  ```
- **复现路径**：在未装 WiX 5 的构建机上运行 `publish_windows_release.ps1` → MSI 永远不生成 → R2 上传脚本无 MSI 可上传 → 线上 MSI 资产陈旧
- **根因分析**：`reports/W-REL-MSI-001-completion-report.md`（2026-06-13）声称已落地，但代码层 `velopack_pack.ps1` 实际从未实施该工单的任何代码改动。这是文档与代码严重背离的典型
- **最小修复建议**：按 `docs/operations/W-REL-MSI-001-MSI主入口切换.md` §1 实施 `vpk pack --msi --instLocation Either` + `Ensure-Wix5` 前置检查 + 返回值扩展为 `Msi` / `VersionedMsi`
- **是否建议本次自动修复**：否（release 链路变更需单独工单 W-REL-MSI-001-COMPLETION-AUDIT-001）
- **需要补充的测试**：`tests/test_velopack_pack_ps1.py` 中 mock `vpk pack` 调用，断言 `--msi` 与 `--instLocation Either` 都传入

### REL-P0-2 / P0-3 / P0-4：R2 / GitHub / publish 主入口未切到 MSI

- **严重等级：P0 × 3**
- **影响功能**：发布后用户下载物（Setup.exe 与 MSI 同时存在但主入口错配）
- **证据文件**：
  - `scripts/upload_r2_release.ps1:116-145, 217, 228`（`$uploads` 不含 MSI；行 228 只 copy `DanmuAI-Setup.exe` latest 别名）
  - `scripts/upload_github_release.ps1:65-78, 132`（`$assetFiles` 不含 Installer.msi；行 132 `"Primary download: ...DanmuAI-Setup.exe"`）
  - `scripts/publish_windows_release.ps1:145-165`（VERSION.txt 不含 MSI 文件名）；控制台 banner 主入口 URL
- **复现路径**：维护者跑 `publish_windows_release.ps1` → 产物只有 Setup.exe + nupkg + Portable → R2 latest 别名仍为 Setup.exe → 用户打开官网看到"主下载 Setup.exe"
- **根因分析**：REL-P0-1 的传染——如果 MSI 未生成，下游脚本无 MSI 可传
- **最小修复建议**：在 P0-1 修复后，逐脚本把 MSI 资产加入上传清单、改主入口 URL、VERSION.txt 与控制台 banner
- **是否建议本次自动修复**：否（与 P0-1 同工单）
- **需要补充的测试**：`tests/test_publish_windows_release.py`（mock）

### TTS-P0-5：`danmu_read_service.run_probe` 主线程同步 HTTP

- **严重等级：P0**
- **影响功能**：读弹幕模式（用户点击"试听"按钮）
- **证据文件**：`app/danmu_read_service.py:303-310` `synthesize_tts(...)` 同步阻塞
- **证据代码**：
  ```python
  # app/danmu_read_service.py:303-310
  with httpx.Client(timeout=...) as c:
      resp = c.post(...)  # 主线程同步阻塞
      ...
  ```
- **调用链**：`DanmuAppWebFacadeMixin.run_danmu_read_probe` (`main_web_facade_mixin.py:217`) → `_invoke_main` (`web_api/routes.py:412-419`) → `danmu_read_service.run_probe`
- **复现路径**：用户在 Web 控制台点击"读弹幕试听" → UI 卡顿直到 HTTP 完成（典型 5–30s）→ 托盘菜单、截图定时器、Overlay 刷新全部停顿
- **根因分析**：与 AGENTS.md §A.5.4"TTS HTTP 走主线程"描述一致，但当前 `_DanmuTtsRunnable` 已封装为 QRunnable + 信号回主线程——**仅 `run_probe` 路径未迁移**
- **最小修复建议**：参考 `_DanmuTtsRunnable`（`danmu_read_service.py:88-123`）改 QRunnable；probe 返回后用 `_tts_ready`/`_tts_failed` 信号驱动播放
- **是否建议本次自动修复**：否（需独立工单）
- **需要补充的测试**：`tests/test_danmu_read_api.py` 中 mock 主线程 Event.wait 在 probe 调用时**不应**被阻塞

### WEB-P0-6：`/api/probe` 与 `/api/custom-models/probe` 不走 `_invoke_main`

- **严重等级：P0**
- **影响功能**：用户在 Web 控制台"测试连接"按钮
- **证据文件**：`app/web_api/routes.py:466-485`
- **证据代码**：
  ```python
  # app/web_api/routes.py:466-485（不走 _invoke_main）
  @router.post("/api/probe")
  async def api_probe(body, authorization):
      check_token(authorization)
      return bridge.danmu_app.probe_api_connection(body.dict())  # ← 直接调用
  ```
- **复现路径**：用户在 Web 控制台输入 API key 后点"测试连接" → HTTP 线程同步等 API 响应（数秒到数十秒）→ uvicorn 工作线程被占用 → 后续请求排队
- **根因分析**：与 P0-5 同根，但影响范围更广（普通模式 + 自定义模型 + 读弹幕 + 模型切换都受影响）
- **最小修复建议**：所有写/探测接口统一 `_invoke_main`；probe 走 QRunnable + 信号
- **是否建议本次自动修复**：否（涉及多路由改造）
- **需要补充的测试**：`tests/test_acceptance_gates.py` 中添加"并发 2 个 probe 请求，主线程不阻塞"断言

### LIFE-P0-7：`DanmuApp.quit()` 串行 wait 两个 QThreadPool

- **严重等级：P0**
- **影响功能**：托盘退出 / 关闭控制台时的清理
- **证据文件**：`app/main_lifecycle_mixin.py:687-705` `quit()` 末尾
- **证据代码**：
  ```python
  # app/main_lifecycle_mixin.py:687-705（串行 wait）
  self.capture_worker_pool().waitForDone(2000)        # ← 先等 capture
  QThreadPool.globalInstance().waitForDone(2000)      # ← 再等 ai
  ```
- **复现路径**：AI worker 在某次请求中因网络异常进入内部 sleep → `waitForDone(2000)` 超时 → capture worker 仍在 join → 主线程退出被延迟 4s
- **根因分析**：两个 pool 独立但顺序 wait；任一卡死会拖累另一个
- **最小修复建议**：用两个 thread 并行 wait；或先 cancel `ai_worker.mark_stopping()` 后立即 cancel capture
- **是否建议本次自动修复**：否（退出路径改动需回归测试）
- **需要补充的测试**：`tests/test_main_lifecycle.py` 中 mock 卡死 worker，断言退出时间 ≤ 2.5s

### POOL-P0-8：`get_custom_danmu_pool_for_store` 仍全量 fetchall 20000 条

- **严重等级：P0**
- **影响功能**：自定义弹幕库补池 / 公式化弹幕判断冷路径
- **证据文件**：`app/danmu_pool.py:495-504`
- **证据代码**：
  ```python
  # app/danmu_pool.py:495-504
  def get_custom_danmu_pool_for_store(store) -> list[str]:
      if not store._conn_usable():
          return []
      try:
          rows = store.conn.execute(
              "SELECT text FROM custom_danmu_pool_entries ORDER BY id ASC LIMIT 20000"
          ).fetchall()  # ← 仍全量 fetchall
  ```
- **复现路径**：用户导入 20000 条自定义弹幕 → 任何调用 `load_danmu_pool_for_config` 的路径（补池、回复解析填充）都会全量加载 → 冷路径 O(N) + 全内存
- **根因分析**：v2 报告 BUG-A01 已指出；本次复核 SQL 加了 `LIMIT 20000`（仅约束上限），但 `fetchall()` 仍一次性把所有行读到 Python 列表；热路径 `is_stored_custom_pool_text` 已通过 `_custom_pool_text_set` 缓存（见 v2 BUG-A04 已修），但冷路径仍是 O(N)
- **最小修复建议**：
  - 方案 A（推荐）：`load_danmu_pool_for_config` 改"按需抽样 + 内存 LRU"
  - 方案 B：`get_custom_danmu_pool_for_store` 改为流式迭代（`fetchmany(1000)`）
- **是否建议本次自动修复**：否（需确认所有调用方语义）
- **需要补充的测试**：`tests/test_danmu_pool.py` 中添加 20000 条数据的性能回归（`assert get_custom_danmu_pool_for_store(store) < 500ms`）

### MIC-P1-1：`mic_capture._last_error` 跨线程无锁读写

- **严重等级：P1**
- **影响功能**：麦克风启动 / 故障诊断
- **证据文件**：`app/mic_capture.py:298-300`（PortAudio 回调线程写）；`app/mic_capture.py:154-155`（主线程 `@property` 读）
- **证据代码**：
  ```python
  # app/mic_capture.py:298-300
  def _on_audio(self, indata, frames, time_info, status) -> None:
      if status:
          self._last_error = str(status)  # ← PortAudio 线程写
      self._buffer.append(indata.tobytes())
  ```
- **复现路径**：连续 5 次设备错误 → `_last_error` 在主线程轮询时看到 stale 值（CPython str 字面量原子，仅信息陈旧不崩溃）
- **根因分析**：CPython int/str 单字赋值是原子的，但读到的可能是"旧值"或"新值"中的某一个——属于 stale 而非 crash
- **最小修复建议**：将 `_last_error` 类型改为 `tuple[str, float]` 或用 `threading.Lock` 保护；增加"stale"过滤
- **是否建议本次自动修复**：否（影响面广）

### MIC-P1-2：Web 设置面板"说话相关弹幕数量"无对应实现

- **严重等级：P1**
- **影响功能**：麦克风模式插入条数
- **证据文件**：`app/mic_prompt.py:18-20`
- **证据代码**：
  ```python
  # app/mic_prompt.py:18-20
  def mic_insert_reply_count(config) -> int:
      return normal_reply_count_from_config(config)  # ← 复用普通
  ```
- **复现路径**：用户在 Web 设置改"插入条数"→ 实际 mic insert 批数 = 普通 `normal_reply_count`，与用户期望的"说话内容相关弹幕数量""额外插入数量"不一致
- **根因分析**：代码中**不存在** mic 专属配置键（AGENTS.md §A.5.4 描述"配置字段是否真的生效"——未确认风险，但本轮已确认风险：**完全没实现**）
- **最小修复建议**：增加 `mic_insert_reply_count_override` 配置键读取；或在 UI 明示该字段不生效
- **是否建议本次自动修复**：否（产品决策）

### BARRAGE-P1-19：`resolve_danmu_max_chars` 默认值漂移

- **严重等级：P1**（影响文档可读性，不影响功能）
- **证据文件**：`app/danmu_engine.py:113-116`
- **证据代码**：
  ```python
  # app/danmu_engine.py:113-116
  def resolve_danmu_max_chars(config, *, lang=None) -> int:
      """上屏弹幕最大字数；未配置时中文 15、英文 40。"""
      fallback = DEFAULT_DANMU_MAX_CHARS_EN if lang == "en" else DEFAULT_DANMU_MAX_CHARS_ZH
      # DEFAULT_DANMU_MAX_CHARS_ZH = 20, EN = 50  ← 与 docstring 不一致
  ```
- **复现路径**：用户读 docstring 期望 15/40，配置 `danmu_max_chars=0` 时实际 20/50
- **最小修复建议**：把 docstring 改为"未配置时中文 20 / 英文 50"
- **是否建议本次自动修复**：**是**（仅改注释，零风险）
- **需要补充的测试**：无

### REL-P1-36 / P1-37 / P1-38 / P1-39：兜底 URL / migration DEFAULT / 文档 / 官网主入口全链路 Setup.exe

- **严重等级：P1 × 4**（与 P0-1 强耦合）
- **证据文件**：
  - `app/release_channels.py:17` `R2_LATEST_INSTALLER_URL = ".../DanmuAI-Setup.exe"`
  - `supabase/migrations/003_app_updates.sql:7` 列默认 `release_url = ".../DanmuAI-Setup.exe"`
  - `docs/operations/WINDOWS_RELEASE_CONTRACT.md:51, 73` 自相矛盾
  - `docs/operations/PACKAGING_WINDOWS.md:10, 175, 524`；`RELEASE_CHECKLIST.md:30-63`；`docs/release/README.md:3, 56`；`website/index.html:323`；`README.md:79`
- **最小修复建议**：在 P0-1 ~ P0-4 修复时同步更新；新增 `W-REL-MSI-001-COMPLETION-AUDIT-001` 工单

---

## 4. v1 / v2 BUG 复核状态表

> 本表是 v3 对 v1（`bug-audit-report-2026-06-21.md`）和 v2（`bug-audit-report-2026-06-21-v2.md`）所有列出的 BUG 在 `91fc81e` 的当前状态。**结论 = 已修复 / 仍存在 / 部分缓解 / 文档陈旧**。

### v2 BUG-A01 ~ A13

| 编号 | 标题 | 状态 | 证据 |
|------|------|------|------|
| A01 | `get_custom_danmu_pool` 全量加载 20000 条 | **仍存在（变 P0-8）** | `danmu_pool.py:495-504` 仍全量 fetchall |
| A02 | 读操作持 `_write_lock` | 已修复 | `danmu_pool.py` 全部读函数不再持 `_write_lock`；用独立 `_pool_write_lock` |
| A03 | `_load_recent_from_history` 绕过门面 | 已修复 | 改用 `config.get_recent_history(30)` 门面 |
| A04 | `is_formula_danmu_text` 热路径无缓存 | 已修复 | `_custom_pool_text_set` 缓存 + 写入路径 invalidate |
| A05 | `_use_fast_danmu_render` 注释误导 | 已修复 | docstring 注释已更新 |
| A06 | `delete_user_data_if_requested` 路径安全 | 已修复 | `uninstall_service.py:81-104` 加父路径比对 |
| A07 | `version_compare` 不支持 `+build` | 已修复 | `version_compare.py:38-46` 显式剥离 |
| A08 | `stream_openai` JSON 错误静默 | 已修复（保留 continue 但加 debug log） | `ai_client_requests.py:624-626` |
| A09 | `SingleInstanceGuard` 竞态 | 已修复（main 重试 2 次 + exit(2)） | `single_instance.py` docstring 声明 |
| A10 | `get_json` 无 try-except | 已修复 | `config_store.py:460-468` |
| A11 | `DanmuAI.spec` hiddenimports 缺失 | 已修复（当前未发现遗漏） | `DanmuAI.spec:169, 217, 223, 225-288` |
| A12 | `similarity` 纯 Python 回退 | 部分修复（有预剪枝 + Levenshtein C 扩展优先） | `danmu_engine_dedup.py:130-142` |
| A13 | `_heuristic_comments_from_malformed_json` 递归 | 已修复（_MAX_HEURISTIC_DEPTH=16） | `reply_parser.py:27, 131-142`；但 P2-4 仍可栈溢出 |

### v1 carry-over（v1 报告中提到的、v2 未复用的项）

| 编号 | 标题 | 状态 | 证据 |
|------|------|------|------|
| v1-A01 | `_on_ai_error` 缺陈旧守卫 | 已修复 | `main_lifecycle_mixin.py:418-425` |
| v1-C01 | 豆包 Responses `output_text.done` 重复 | 已修复 | `doubao_responses_stream.py:135-140` `if not collected` |
| v1-D01 | `_play_worker` 跨线程 emit | 已修复 | `danmu_tts_playback.py:69-99` `QMetaObject.invokeMethod(QueuedConnection)` |
| v1-G01 | `meme_barrage/client.py` 默认 `verify_ssl=False` | 已修复 | `meme_barrage/client.py:59-61` 默认 `True`；**但 AGENTS.md §A.3.10 文档陈旧（P3-1）** |
| v1-H02 | `upload_github_release.ps1` 硬编码旧日期 | 已修复（动态从 version 文件读） | `upload_github_release.ps1:42-62` |
| v1-H03 | `velopack_runtime.app.run()` 异常 raise | 已修复（外层 try/except 吞） | `velopack_runtime.py:19-34` |
| v1-H04 | `supabase-config.js` 打包排除 | 部分缓解（打包版仅 env var） | `DanmuAI.spec:65-70` 仍 exclude；但前端文案未同步（P3-4） |
| v1-B01 | FloatingPanelOverlay 慢 `QPainterPath` | 部分修复（threshold 不一致，P1-21） | `floating_panel_overlay.py:32` 与 `overlay.py:46` |
| v1-B02 | `FloatingPanelEngine.is_duplicate` 无 TTL | 未复核（建议下次单查） | — |
| v1-B03 | `reply_parser._try_parse_json_object` `}{` 取首段 | 未复核 | — |
| v1-D02 | `try_snapshot_pcm_ms` 访问私有字段 | 文档陈旧 | `mic_capture.py:293-295` 已封装 |
| v1-D03 | 读弹幕 `run_probe` 在主线程 | **仍存在（变 P0-5）** | `danmu_read_service.py:303-310` |
| v1-F01 ~ F03 | danmu_pool 锁 / LIKE / DELETE+INSERT | 大部分已修复 | v2 报告已展开 |
| v1-F05 | `ConfigStore.close()` 后 `get()` 仍可读 cache | 未复核 | — |
| v1-G05 | 烂梗 AI 与主链路共用 worker pool | **仍存在（P1-13 / P2-21）** | `meme_barrage/runnable.py:79-173` |
| v1-G06 | `_meme_display_tick` 递归无批次数限制 | **仍存在（P1-12）** | `main_meme_mixin.py:347-350` |
| v1-H01 | R2 Setup.exe latest 用 `no-cache` | 已被契约认可（不再算 bug） | `WINDOWS_RELEASE_CONTRACT.md:126` |
| v1-H05 | `_manager()` 每次新建 UpdateManager | 未复核 | — |
| v1-H07 | `delete_user_data_if_requested` 仅检查 marker | 已修复 | `uninstall_service.py:81-104` |
| v1-I01 | Supabase 速率限制 client_id 伪造 | 未复核（需 SQL 视角） | — |
| v1-I02 | `listAnnouncements()` 不在查询中过滤 `published=true` | 未复核 | — |
| v1-I03 | Live Overlay SSE 端点无鉴权 | **仍存在（P1-23）** | `web_console_ws.py:66-107` |
| v1-J01 | `FakeConfig.get_json` 无容错 | 未复核 | — |

---

## 5. 性能与卡顿风险

### 5.1 启动速度

- **ConfigStore 初始化**（`config_store.py:73-113`）：`__init__` 中执行 `_init_db`、`_load_cache`、`_migrate_legacy_display_mode_to_render_mode`、`seed_config_defaults`、`_init_fernet`、`_repair_stale_region_if_needed`、`_normalize_legacy_display_mode`、`migrate_custom_danmu_pool_json`。这些操作在主线程同步执行，若 `config.db` 较大或迁移数据量多，可导致启动延迟。
- **DanmuEngine._load_recent_from_history**（v2 已修复走门面，正常情况下很快）。
- **WebView2 冷启动**：`webview_shell.py` 设 `_LOAD_TIMEOUT_SEC=25` / `_FROZEN_LOAD_TIMEOUT_SEC=25`，但 `schedule_webview_attach` 重试仅 1.5s（P1-32）。

### 5.2 截图与 AI 请求

- **httpx 超时**（`ai_client.py:100`）：`httpx.Timeout(30.0, connect=5.0)`，30 秒总超时合理。但流式响应中无总超时限制。
- **重试策略**：最多 2 次重试（L252, L460），超时重试、异常重试（重建 httpx 客户端），HTTP 状态错误不重试。设计合理。
- **图像压缩**：`image_compress.py:30-39` 对 PIL 解码历史漏洞（CVE-2023-44271 类）仅靠 10MB 上限，不防御超大数据（P1-34）。

### 5.3 Overlay 渲染

- **QPainterPath.addText 性能**（`overlay.py:96-106`）：对 CJK/emoji 已走 fast 路径（`drawText` 描边），性能可接受。但 `_FAST_DANMU_RENDER_MIN_LEN` 在 `overlay.py:46=8` 与 `floating_panel_overlay.py:32=36` 不一致（P1-21）。
- **pixmap 预渲染**（L328-342）：`_prepare_pixmaps_near_visible` 每帧检查所有轨道的未渲染 item，O(n) 复杂度（P2-6）。弹幕密集时可能有性能影响。
- **`_paint_bubble` 每帧新建 QTextDocument**（P1-15）：GC 压力 + Qt layout 重算。

### 5.4 SQLite

- **WAL + busy_timeout=5000**（`config_store.py:86-88`）：设计合理。
- **`_write_lock` 粒度**：v2 报告 BUG-A02 已修，**读操作不再持 `_write_lock`**；`_pool_write_lock` 独立。
- **`custom_danmu_pool_entries` 全量查询**：P0-8 仍未消除（仅加 `LIMIT 20000` 约束上限，不分页）。

### 5.5 自定义弹幕库

- **20000 条上限**（`danmu_pool.py:17`）：`CUSTOM_DANMU_POOL_MAX = 20000`。`custom_danmu_random_sample_for_store` 使用 `ORDER BY RANDOM() LIMIT ?`，对 20000 条数据性能可接受。
- **`set_custom_danmu_pool_for_store`**（L485-505）：先 `DELETE FROM custom_danmu_pool_entries`（全表删除），再 `INSERT`。20000 条数据的全量替换会导致短暂的表锁和 WAL 膨胀。

### 5.6 主线程做 HTTP 的传染

TTS-P0-5（`run_probe`）+ WEB-P0-6（probe 路由）+ LIFE-P0-7（quit 串行 wait）—— 三个 P0 都属于"主线程做重活"问题，应作为统一工单治理（参见 §10 第 1 优先级）。

---

## 6. 发布与更新风险

### 6.1 PyInstaller

- **`DanmuAI.spec` hiddenimports**：v2 报告 BUG-A11 已复核；当前 `app.mic_buffer` / `app.web_console_session_auth` / `app.worker_pools` / `app.application.*` / `app.memory.*` / `app.meme_barrage.*` / `app.pet.*` / `app.providers.*` / `app.web_api.*` 全部包含。建议下次发版前实际跑一次 `pyinstaller DanmuAI.spec` 端到端冒烟（REL-P0-2 / P2-2）。
- **`supabase-config.js` 排除**：仍 `exclude_names=frozenset({"supabase-config.js"})`，设计如此（不打包凭据），但前端文案未同步（P3-4）。

### 6.2 Velopack

- **`velopack_runtime.py`**：启动钩子在 `QApplication` 之前执行，异常处理合理（L32-33 捕获所有异常并日志记录，不阻塞启动）。
- **`update_service.py`**：`_manager()` 缓存 `UpdateManager` 实例，线程安全通过 `_lock` 保护。
- **版本比较**：v2 BUG-A07 已修（`+build` 元数据剥离）；`_split_core_prerelease` 仍按第一个 `-` 分割（P3-15）。

### 6.3 MSI 主入口切换（核心 release-blocker）

**REL-P0-1 ~ P0-4 + REL-P1-36 ~ P1-39** —— **当前 commit 不能 release 0.3.4**。原因：

1. `scripts/velopack_pack.ps1` 未实施 W-REL-MSI-001 任何代码改动
2. 下游 R2 / GitHub / publish 脚本主入口仍为 Setup.exe
3. `app/release_channels.py` 兜底 URL 与 `supabase/migrations/003_app_updates.sql` 列默认值仍为 Setup.exe URL
4. 文档（`WINDOWS_RELEASE_CONTRACT.md`、`PACKAGING_WINDOWS.md`、`RELEASE_CHECKLIST.md`、`docs/release/README.md`、`website/index.html`、`README.md`）全部仍以 Setup.exe 为主入口

**触发条件**：在没装 WiX 5 的构建机上运行 `publish_windows_release.ps1` → MSI 永远不生成 → R2 上传脚本无 MSI 可上传 → 线上 MSI 资产陈旧。

**修复路径**：开 `W-REL-MSI-001-COMPLETION-AUDIT-001` 小工单（不再实施 MSI，只是把已写的 MSI 切换代码真正落到 `scripts/*` 与 `app/release_channels.py` + `supabase/migrations/003_app_updates.sql` + Supabase README INSERT 示例），通过后再按 `scripts/run_acceptance_gates.py`（先修 CFG-P2-1）做一次完整发布演练。

### 6.4 用户数据保留

- **`uninstall_service.py`**：默认保留用户数据，opt-in 删除。`delete_user_data_if_requested` 当前已补强：marker 文件存在 → 内容含 `delete-user-data=1` → `data_dir.name == APPDATA_DIR_NAME` → 父路径等于 `%APPDATA%` → `shutil.rmtree`。多层防护充分。
- **MSI 卸载路径下**：W-REL-CLEANUP-001 工单的目标与实现状态需确认（建议单查）。

### 6.5 代码签名

- **`scripts/sign_windows_release.ps1`**：默认关闭；开启需 `VPK_SIGN_PARAMS` 或 `VPK_AZURE_TRUSTED_SIGN_FILE`。无 PFX/凭据泄漏风险。
- **`docs/operations/WINDOWS_CODE_SIGNING.md:45`** 只列 Setup.exe，未提 MSI 验签（P3-7）。

---

## 7. 安全与隐私风险

### 7.1 API Key

- **加密存储**（`config_store.py:139-170`）：Fernet 加密，密钥文件 `.key` 在 `%APPDATA%/DanmuAI/`。密钥丢失后旧密文不可恢复。
- **日志脱敏**（L46-51）：`_redact_config_value_for_log` 对敏感 key 返回 `***`，对长值截断。
- **自定义模型 apiKey**：`get_custom_models` 返回解密后的明文 apiKey，通过 Web API 返回时需确认前端是否做掩码处理（建议单查）。

### 7.2 Supabase

- **凭据来源**（`supabase_config.py`）：环境变量优先，回退到 `web/static/supabase-config.js`。打包时已排除此文件。
- **anon_key 安全性**：设计上可公开，依赖 RLS 策略。**Supabase 项目中所有表是否都配置了正确的 RLS 需人工核对**（v1 BUG-I01 ~ I03 复核建议单查）。

### 7.3 Web API 认证

- **Bearer token**（`web_console.py:402`）：启动时生成 `secrets.token_urlsafe(24)`，仅绑定 `127.0.0.1`。
- **WebSocket 鉴权**：P1-23，仅鉴权 ws_token 不查 Origin/Host，持有 token 的本机进程可订阅 status/logs。

### 7.4 潜在风险

- **`SanitizedLogger`**：日志脱敏机制需确认是否覆盖所有 API key 泄露路径（如 AI 请求 URL 中的 key 参数）。
- **`supabase-config.js` 打包排除**：打包版永远只能走 env var（已在 v1 H04 部分缓解）。
- **Live Overlay SSE**：P1-23，鉴权不严。

### 7.5 隐私

- **MIC-P2-17**：mic toggle 路径未独立处理，**`toggle` 时 mic 仍在录音**（隐私问题）。
- **HYG-P3-10**：`debug-a9a516.log` 514KB 等大日志文件疑似含敏感 token / 用户路径，需人工核对后再删除。

---

## 8. 建议新增的测试

> 给出测试文件名 + 测试目标 + 断言内容；不写代码。

### 8.1 `tests/test_danmu_pool_pagination.py`

- **测试目标**：验证 `get_custom_danmu_pool_for_store` 不再全量加载
- **断言内容**：
  - `assert len(get_custom_danmu_pool_for_store(store)) <= 20000`
  - 20000 条数据下，`get_custom_danmu_pool_for_store(store)` 完成时间 < 500ms
  - mock `store.conn.execute` 验证 SQL 含 `LIMIT 20000`

### 8.2 `tests/test_uninstall_path_safety.py`

- **测试目标**：验证卸载路径安全检查（v2 BUG-A06 + workorder 已覆盖代码，测试代码本次未跑）
- **断言内容**：
  - `delete_user_data_if_requested()` 在 `%APPDATA%` 指向非标准路径时 `shutil.rmtree` **不**调用
  - 在 marker 文件不存在 / 内容不含 `delete-user-data=1` 时不删除

### 8.3 `tests/test_main_lifecycle_quit_concurrent.py`

- **测试目标**：验证 `quit()` 并行 wait capture + ai pool
- **断言内容**：
  - mock capture worker 卡死 5s，断言 `quit()` 总耗时 < 3s

### 8.4 `tests/test_release_url_msi_consistency.py`

- **测试目标**：验证 REL-P1-36 ~ P1-39 的 URL 一致性
- **断言内容**：
  - `app/release_channels.py:R2_LATEST_INSTALLER_URL.endswith(".msi")`
  - `supabase/migrations/003_app_updates.sql` 列 DEFAULT 含 `.msi`
  - `docs/operations/WINDOWS_RELEASE_CONTRACT.md` 不自相矛盾
  - `README.md`、`website/index.html` 主下载链接为 `.msi`

### 8.5 `tests/test_velopack_pack_msi.py`

- **测试目标**：验证 REL-P0-1（MSI 打包参数）
- **断言内容**：
  - mock `vpk pack` 调用，断言 `--msi` 与 `--instLocation Either` 都传入
  - 缺失 WiX 5 时脚本应 fail-fast
  - 返回值含 `Msi` / `VersionedMsi` 字段

### 8.6 `tests/test_web_socket_origin.py`

- **测试目标**：验证 WEB-P1-23（WS 鉴权 Origin 检查）
- **断言内容**：
  - 持有 ws_token 但 Origin 跨域的请求被 403
  - Origin/Host 同源的请求正常返回

### 8.7 `tests/test_danmu_read_probe_non_blocking.py`

- **测试目标**：验证 TTS-P0-5（probe 不阻塞主线程）
- **断言内容**：
  - mock 主线程 Event.wait 在 probe 调用时**不应**被阻塞
  - probe 通过 QRunnable + 信号返回

### 8.8 `tests/test_api_probe_via_invoke_main.py`

- **测试目标**：验证 WEB-P0-6（probe 路由走 `_invoke_main`）
- **断言内容**：
  - `/api/probe` 与 `/api/custom-models/probe` 的实现都通过 `bridge.invoke_on_main` 调用
  - 并发 2 个 probe 请求，主线程不阻塞

### 8.9 `tests/test_run_acceptance_gates.py`（修复 CFG-P2-1）

- **测试目标**：修复 `scripts/run_acceptance_gates.py` 引用不存在的测试文件
- **建议方案**：要么创建 `tests/test_boundary_guard.py` + `tests/test_diagnostics.py`，要么从 COMMANDS 列表移除

### 8.10 `tests/test_pet_window_frame_reset.py`

- **测试目标**：验证 PET-P1-17（资产切换重置帧）
- **断言内容**：
  - 调用 `apply_slot_config` 后 `_frame_index == 0` 且 `_frame_clock == 0.0`

### 8.11 `tests/test_mic_insert_count_override.py`

- **测试目标**：验证 MIC-P1-2（mic 插入条数配置键）
- **断言内容**：
  - 设置 `mic_insert_reply_count_override=2` 后，`mic_insert_reply_count(config)` 返回 2
  - 未设置时回退到 `normal_reply_count`

### 8.12 `tests/test_overlay_geo_key_dpr.py`

- **测试目标**：验证 BARRAGE-P1-22（geo_key 含 DPR）
- **断言内容**：
  - `overlay.show_for_screen` 的 geo_key 在 DPR 变化时不相等 → `reload_tracks` 被调用

---

## 9. 本次可自动修复项

> 只列低风险、小范围、证据明确、修复 ROI 高的项。本次任务用户已确认 `audit-only-no-fix`，**不实际修复**，仅列出供后续工单使用。

| # | 修复内容 | 文件 | 风险 | 范围 |
|---|---------|------|------|------|
| BARRAGE-P1-19 | `resolve_danmu_max_chars` docstring 改为"未配置时中文 20 / 英文 50" | `app/danmu_engine.py:113-116` | 零 | 1 行注释 |
| DOC-P3-1 | AGENTS.md §A.3.10 `verify_ssl=False` → `True` | `AGENTS.md:385`（行号以实际为准） | 零 | 1 行文档 |
| DOC-P3-2 | AGENTS.md §A.5.4 `try_snapshot_pcm_ms` 描述更新 | `AGENTS.md` | 零 | 1 段文档 |
| DOC-P3-3 | AGENTS.md §9 `_play_worker` 跨线程违规描述更新 | `AGENTS.md` | 零 | 1 段文档 |
| BARRAGE-P1-20 | `danmu_lines > 20` 时增加 warn 日志 | `app/danmu_engine.py:255-296` | 低 | 1 行代码 |
| BARRAGE-P1-21 | `_FAST_DANMU_RENDER_MIN_LEN` 在两处统一为 8 或 36（需决策） | `app/overlay.py:46` + `app/floating_panel_overlay.py:32` | 低 | 1-2 行常量 |
| MIC-P1-1 | `_last_error` 改为 `tuple[str, float]` + Lock | `app/mic_capture.py:154-155, 298-300` | 低 | ~10 行 |
| BARRAGE-P2-5 | `_heuristic_comments_from_malformed_json` `re.search` 加 `re.DOTALL` | `app/reply_parser.py:158` | 低 | 1 行 |
| WEB-P2-3 | `global_exception_hook` 顶端 `if sys.stderr is None: sys.stderr = open(os.devnull, 'w')` | `app/main_launch.py:44, 67-70` | 低 | 2 行 |

---

## 10. 最终建议

按优先级排序：

1. **REL-P0-1 ~ P0-4（MSI 主入口 release-blocker）**：当前 commit 不能 release 0.3.4。**先开 `W-REL-MSI-001-COMPLETION-AUDIT-001` 工单**，把已写的 MSI 切换代码真正落到 `scripts/velopack_pack.ps1` / `scripts/upload_r2_release.ps1` / `scripts/upload_github_release.ps1` / `scripts/publish_windows_release.ps1` / `app/release_channels.py` / `supabase/migrations/003_app_updates.sql` / `supabase/README.md` / `website/index.html` / `README.md` / `docs/operations/PACKAGING_WINDOWS.md` / `RELEASE_CHECKLIST.md` / `docs/release/README.md` / `docs/operations/WINDOWS_RELEASE_CONTRACT.md`。通过后再按 `scripts/run_acceptance_gates.py`（先修 CFG-P2-1）做一次完整发布演练。

2. **主线程做 HTTP 的传染治理（TTS-P0-5 + WEB-P0-6 + LIFE-P0-7）**：三个 P0 都属于"主线程做重活"问题。**开 `W-LIFE-MAIN-THREAD-IO-001` 工单**，把 `danmu_read_service.run_probe`、`/api/probe`、`/api/custom-models/probe`、`/api/mic/test`、`DanmuApp.quit()` 的 wait 顺序统一为：HTTP 线程只做 dispatch；重活走 QRunnable + 信号回主线程；waitForDone 改为并行。

3. **POOL-P0-8（自定义弹幕库全量加载）+ MIC-P1-2（mic 插入条数无配置键）**：这两项影响用户可感知的功能（"设置面板改了没生效"）。**开 `W-DANMU-POOL-PAGINATION-001` + `W-MIC-INSERT-COUNT-OVERRIDE-001` 两个工单**，前者改 `get_custom_danmu_pool_for_store` 流式迭代或 LRU 缓存，后者补 `mic_insert_reply_count_override` 配置键 + UI 提示。

---

## 附录 A. 本次审计方法

- 3 个并行只读子代理（`explore` 类型）独立执行 A-J 10 模块 + 发布链路审计
- 所有结论基于 commit `91fc81e` 的代码静态分析；未运行 pytest / PyInstaller / uvicorn
- 复用了 v1 / v2 报告的全部 BUG 列表，但**只复核其状态**，不重复展开已修复项
- 本报告**取代** `docs/bug-audit-report-2026-06-21.md` 与 `docs/bug-audit-report-2026-06-21-v2.md`，那两个文件自此归档

## 附录 B. v1 / v2 BUG 复核中"未复核"项列表

> 以下 v1 BUG 在本次只读审计中未单独深入复核（建议下一轮工单补查）：
- v1-B02 `FloatingPanelEngine.is_duplicate` TTL 剪枝
- v1-B03 `reply_parser._try_parse_json_object` `}{` 拼接取首段
- v1-F05 `ConfigStore.close()` 后 `get()` 仍可读 cache
- v1-G05 烂梗 AI 与主链路共用 worker pool（已部分覆盖为 P1-13 / P2-21）
- v1-H05 `update_service._manager()` 每次新建 UpdateManager
- v1-I01 Supabase 速率限制 client_id 伪造
- v1-I02 `listAnnouncements()` 不在查询中过滤 `published=true`
- v1-J01 `FakeConfig.get_json` 无容错

## 附录 C. 仍存在的 P0 项速查

1. **REL-P0-1** `scripts/velopack_pack.ps1` 未产 MSI
2. **REL-P0-2** R2 上传脚本未传 MSI
3. **REL-P0-3** GitHub Release 不含 MSI 资产
4. **REL-P0-4** `publish_windows_release.ps1` 主入口声明仍为 Setup.exe
5. **TTS-P0-5** `danmu_read_service.run_probe` 主线程同步 HTTP
6. **WEB-P0-6** `/api/probe` 不走 `_invoke_main`
7. **LIFE-P0-7** `DanmuApp.quit()` 串行 wait 两个 QThreadPool
8. **POOL-P0-8** `get_custom_danmu_pool_for_store` 全量 fetchall