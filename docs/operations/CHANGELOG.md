# Changelog

## Unreleased

## 0.3.4 (2026-06-20)

### Changed

- **W-REL-034-RELEASE-001**：将本地发布版本号提升到 `0.3.4`，按固定顺序核对 Windows 发布链：`scripts/build_exe.ps1` → `scripts/publish_windows_release.ps1` → 检查 `release/velopack/` → `scripts/upload_r2_release.ps1`（GitHub / Supabase 本轮延后）

### Added

- **公式化弹幕库 / 反馈 / 诊断**：自定义句库上限与去重逻辑增强；内容反馈上下文（`feedback-context.js`）；诊断快照扩展；CI workflow 补充（`82e792d`）
- **人格工坊**：完整 system/user prompt 预览（`61dd61b`）；内置人格 prompt 统一追加真人观众【风格要求】块；`active_personae_version` 升至 11，默认激活列表移除「测试2」

### Fixed

- **人格 / 读弹幕设置**：人格列表展示与读弹幕保存 handler 修复（`1c8a80c`）
- **回复契约**：恢复 plain reply contract 措辞；退役「团战解说型」内置人格（`4f35108`、`63e8495`）

### Changed（UI / 文案）

- 麦克风与 TTS 设置页文案优化（`3f4a7e9`）
- 托盘 / pywebview / Web 错误上报与反馈 UI 调整（`8bfb4e2`）
- Windows 发布脚本 `publish_windows_release.ps1` 行为更新（`82e792d`）

### Documentation

- 发布文档与工作流状态整理（`5fb8907`）

## 0.3.3 (2026-06-19)

### Changed

- **W-REL-033-RELEASE-001**：将本地发布版本号提升到 `0.3.3`，按固定顺序核对 Windows 发布链：`scripts/build_exe.ps1` → `scripts/publish_windows_release.ps1` → 检查 `release/velopack/` → `scripts/upload_r2_release.ps1` → `scripts/upload_github_release.ps1`

### Documentation

- **W-REL-033-RELEASE-001**：补充 `0.3.3` 发布准备与校验记录，明确 **R2 是主更新源**、**GitHub Releases 仅镜像**、更新 feed 为 `https://updates.qiaoqiao.buzz/releases/win/stable`、最新安装包别名为 `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe`

### Added（W-PR-INTAKE 批次，PR #20–#24 本地适配）

- **W-PR-INTAKE-020（PR #20）**：`reply_parser` 解析前剥离完整或未闭合 `...` 与常见推理前言（`让我想想` / `思考一下` / `reasoning:` 等），provider 前言后含 JSON 仍可提取；MiniMax 端点（host 含 `minimax` / `minimaxi`）请求路径补齐 `reasoning_split: true`，probe 与正式请求一致；不影响其他 OpenAI 兼容 provider
- **W-PR-INTAKE-021（PR #21）**：新增 `app/application/danmu_diagnostics.py`（`DanmuDiagnosticsRecorder`，线程安全 `threading.Lock` + `deque` + `Counter`）；`main.py` 8 个失败分支记录未上屏原因（capture failure / AI request failure / empty parse / duplicate / empty text / floating-panel spacing / entry-zone overload / layout rejection）；`diagnostic_snapshot` 暴露 `undisplayed` 摘要；`overview.html` + `diagnostics.js` 展示最近未上屏统计与原因列表
- **W-PR-INTAKE-022（PR #22）**：设置页「弹幕」标签新增「样式预览」区域（`settings-danmu-preview.js`），实时预览横向弹幕（速度、轨道数、字号、透明度、最大字数、字体、加粗）与悬浮窗（面板宽度、最大条数、速度、透明度、字号、字体、加粗）；表单 input/change 即时刷新，保存配置 / 恢复默认后同步刷新；纯前端，不接入真实 overlay，不写持久化
- **W-PR-INTAKE-023（PR #23）**：overview 页面新增首次运行设置引导（`app-setup-guide.js`），覆盖 API / 模型已配置、probe / 连通性检查、识图屏幕已设置、测试弹幕 / 启动生成进度；dismiss / probe / test 痕迹存 localStorage；不新增后端 API，不改变开始/停止主流程
- **W-PR-INTAKE-024（PR #24）**：直播输出面板内新增 setup assistant（地址已复制、overlay 已连接、测试弹幕已发送三阶段），copied / tested 存 localStorage，连接状态来自运行时状态源；不重建整块 `liveOverlayPanel` DOM，不新增后端 API

### Fixed

- **W-BUG-AUDIT-03**：从 Git 跟踪中移除误提交的 `.venv-build/`；`.gitignore` 补齐默认构建 venv 名，避免再次 `git add` 整棵 site-packages

## 0.3.2 (2026-06-14)

### Changed

- **W-DANMU-POOL-BUILTIN-REMOVE-001**：移除内置公式化弹幕库（`data/danmu_pool_zh.json`、bootstrap 数据、`danmu_pool_enabled` 配置键）；公式化补足与填充仅走自定义句库（`danmu_pool_use_custom` + `/api/danmu-pool/*`）；`/api/danmu-pool/meta` 不再返回 `builtin_enabled` / `builtin_count`
- **W-FP-V2-002**：移除 V1 悬浮窗兼容层；`/api/status` **不再**返回 `display_mode`（请改用 `danmu_render_mode`）。遗留 W-FP 配置键 `display_mode` 在 `ConfigStore` 启动时写回 `danmu_render_mode`，运行时不再读取。

### Added

- Web 概览「直播输出」新增接入助手：展示复制地址、网页源连接与测试弹幕步骤，并提供打开预览、刷新状态入口。
- 人格工坊新增「提示内容」全局直播主题输入框（`live_topic` 配置键，上限 200 字）；AI 主链路在 `system_pt` 末尾追加主题行，空值零侵入（W-LIVE-TOPIC-001）
- 助手设置新增「麦克风模式」标签：麦克风开关、窗口、测试与独立 `mic_api_*` / `mic_model` 配置；默认「与识图模型相同」保持兼容（W-mic-settings-tab）

### Fixed（P3 全量修复，W-P3-*，2026-06-03）

- **W-WEB-MIME-001**：Windows 注册表将 `.js` 映射为 `text/plain` 时 Web 控制台空白；启动 uvicorn 前强制 `application/javascript` / `text/css`（`app/web_static_mime.py`）
- 移除 `danmu_queue` 遗留别名；`_pending_request_meta` 改用 tuple 键；JPEG 压缩共享 `app/jpeg_resize.py`
- legacy `realtime` 显示模式归一化收口至 `ConfigStore.__init__`
- Web：`btnToggle` 不再切换前额外 `GET /api/status`；框选超时重置 `selection_state`；save_config 超时 10s
- 退出顺序：`history_writer.stop()` 先于 `ai_worker.close()`；`RequestTimingService` start/stop 统一 `reset_started`
- 弹幕引擎：`needs_refill` 惰性可见计数重建；诊断/ pywebview 重试等见 [bug-audit/BUGS-OVERVIEW.md](bug-audit/BUGS-OVERVIEW.md) BUG-050–089

### Documentation

- README 依赖表与 i18n 说明；WEB_CONSOLE 明确错误反馈走 Supabase 前端直连

## 2026-05-29

### Added

- **直播网页弹幕层**：`LiveOverlayHub`、`/live-overlay`、`/api/live-overlay/events`（SSE）、`POST …/test`；`main.py` 在 normalize 成功后旁路广播（视觉 AI + 开麦 AI）；控制台「运行概览 → 直播输出」
- **Provider 适配层**：`app/providers/`（registry、capabilities、Default/MiMo adapters）；`ai_client` / `api_probe` OpenAI 路径委托 adapter
- MiMo 目录：`mimo-v2.5`（MiMo-V2.5）、`mimo-v2.5-pro`（无识图）；默认可视仍为 `mimo-v2.5`
- 公告已读：`GET/PUT /api/announcements-read-state`（`config.db` 按公告 `id`）；顶栏简略条（前 30 字，独立 dismiss）
- Web 内置 `tailwindcdn.js`；`app/single_instance.py` 单实例激活已有窗口
- Web 侧栏 **公告** 页、**问题反馈** 表单（Supabase）；`supabase/migrations/001_announcements_feedback.sql`

### Removed

- `app/probe_runnable.py`（主链路未使用的库存预取探测）

### Fixed

- RTT 计时键改为 `{request_round}:{screenshot_id}:{scene_generation}`，避免麦克风与视觉请求同帧互相覆盖
- `ConfigStore.set()` 写入失败时不再污染内存缓存（与 `set_batch` 一致）
- WebSocket：Starlette `WebSocketRoute`；日志 WS 1008 时 `refreshSession()`

### Changed

- 主链路：清除 realtime/节奏模式遗留；截图 API 失败退避接入 `screenshot_interval_ms`
- 截图：拒绝 null / `isNull()` / 零尺寸 pixmap，不递增 `screenshot_id`
- 主链路可观测性：无效截图、空 AI 解析、缺失 request meta / RTT、视觉 in-flight 超时（45s）等 structured warning 日志
- MiMo：OpenAI 兼容请求与探测对齐；`HOST_ENTRIES` 合并 endpoint guess
- Web：`POST /api/personae/{name}/rollback` 需 Bearer；配置保存失败写入 Web 错误状态

### Documentation

- [WEB_CONSOLE.md](WEB_CONSOLE.md)：直播 Overlay、公告、Supabase
- [architecture/provider-adapter.md](architecture/provider-adapter.md)、[audits/token-consumption-audit.md](audits/token-consumption-audit.md)
- [main-pipeline-sequence.md](main-pipeline-sequence.md)、[runtime-state-map.md](runtime-state-map.md)、[PACKAGING_WINDOWS.md](PACKAGING_WINDOWS.md)
- GitHub Release 正文：[release/2026-05-29.md](release/2026-05-29.md)

## 2026-05-27

### Added

- Web 控制台侧栏页 **公式化弹幕库**：内置/自定义公式化短句开关、最小同屏条数、自定义句批量追加与删除
- API：`GET/PUT /api/danmu-pool/meta|settings`、`GET/POST/DELETE /api/danmu-pool/custom`；配置键 `danmu_pool_use_custom`、`custom_danmu_pool`
- 人格工坊内置人格 **+7**：傲娇型、腹黑型、中二型、治愈型、毒舌型、元气型、社恐型（默认未加入激活列表）
- Web **教程**、**问题反馈** 页（飞书教程外链、QQ 群二维码）
- 前台窗口活动追踪：`app/window_info.py`、`app/memory/activity.py` / `activity_prompt.py`（推断写代码/游戏/浏览等，拼入记忆提示）
- 运行态与调度模块 `app/application/`（`runtime_state`、`request_scheduler`、`generation_pipeline_state` 等）
- `scripts/boundary_guard.py`、`scripts/run_acceptance_gates.py`；维护者文档 `final-architecture-baseline.md`、`main-pipeline-sequence.md`、`runtime-state-map.md`
- 小米 **MiMo** 服务商预设与 `app/model_catalog.py` 目录项；视觉模型 Web 选择器优化
- Windows 打包指南 [PACKAGING_WINDOWS.md](PACKAGING_WINDOWS.md)

### Removed

- 遗留 Qt 主窗（`ui/`）及启动方式 `--qt-ui`、`--legacy-ui`、`DANMU_QT_UI`、`DANMU_WEB_CONSOLE=0`；请使用默认 Web 控制台
- 助手设置中的「内置中文短句库」「最小同屏条数」（已迁至公式化弹幕库页）
- **实时弹幕模式**（`danmu_display_mode=realtime`）：Web 表单、配置导出与节奏预触发链路已移除；仅保留普通模式（固定识图间隔 + `normal_reply_count`）
- Web 配置项：`reply_scene_count`、`reply_filler_count`、`screenshot_interval`、`freq_mode`、`capture_mode`、`freshness`、`drop_stale`、`scene_probe_size`、`memory_clear_policy`

### Changed

- Web 运行概览：**诊断面板**默认隐藏（不再轮询 `/api/diagnostics`；接口仍可供维护者调试）
- **弹幕场次记录**写入本机 `config.db`，重启后保留最近 100 条
- 公式化补足：`min_on_screen` 在 **内置库或自定义库** 任一开启时生效；自定义库开启时即使内置库关闭也可补足
- `PUT /api/config` 不再包含 `danmu_pool_enabled` / `min_on_screen`（请用 `/api/danmu-pool/settings`）
- 弹幕生成统一为普通模式间隔与批次条数；遗留 `realtime` 配置在启动/Web 保存时映射为普通模式行为
- `DanmuApp` 始终启动 Web 控制台；废弃启动参数将 `sys.exit(2)` 并打印迁移说明
- `docs/qt6_ui_redesign_plan.md` 移至 `docs/archive/`（只读历史）

### Documentation

- **开源文档治理（第二轮）**：正式文档收敛为 README / `docs/ARCHITECTURE.md` / `WEB_CONSOLE.md` / `CONTRIBUTING_ARCHITECTURE.md` / `MAIN_PIPELINE.md` / `RUNTIME_STATE.md` / `BOUNDARY_GUARD.md`；删除根目录 Phase stub、已完成 pool/display 规划、IDE 注释战役材料；`MEMORY_SYSTEM_PLAN` 迁入 [archive/planning/](archive/planning/)
- 文档治理：新增 [CONTRIBUTING_ARCHITECTURE.md](CONTRIBUTING_ARCHITECTURE.md)、[MAIN_PIPELINE.md](MAIN_PIPELINE.md)、[RUNTIME_STATE.md](RUNTIME_STATE.md)、[BOUNDARY_GUARD.md](BOUNDARY_GUARD.md)；重写 [ARCHITECTURE.md](ARCHITECTURE.md) 与 [docs/README.md](README.md)
- Phase 文档仅保留于 [archive/architecture-phases/](archive/architecture-phases/)（根目录 stub 已移除）
- 同步 [main-pipeline-sequence.md](main-pipeline-sequence.md)、[runtime-state-map.md](runtime-state-map.md)（移除 realtime/rhythm 主链路描述）
- 文档：移除对已删除 `prototype/scheme-e-*` 的当前态引用；统一默认 Web 控制台叙事
- 新增 `prototype/README.md`；更新 `AGENTS.md`、`README*.md`、`docs/ROADMAP*.md`、`docs/RELEASE_CHECKLIST*.md`、`docs/ARCHITECTURE*.md`、`CONTRIBUTING*.md`
- `docs/qt6_ui_redesign_plan.md`：标注 Phase 0 / `scheme-e` 为历史；Qt 令牌以 `ui/theme.py` 为准
- 隐私/安全/审计：`screen_index` 所选显示器全屏（修正「主屏 / screens[0]」过时表述）
- 架构：恢复场景指纹与 `live_freshness` 文档；删除「场景指纹已禁用」错误描述
- 用户文档：README / WEB_CONSOLE 补充 `DANMU_IMAGE_METRICS`、`DANMU_SCENE_DEBUG`；JPEG 压缩双入口说明；`scripts/` 索引
- 合规：`OPEN_SOURCE_AUDIT*`、`THIRD_PARTY_NOTICES.md` 补充 fastapi、uvicorn、pywebview

## 2026-05-24（Web 控制台迁入）

- **默认启动**：`python main.py` → pywebview + 本地 Web 控制台（`127.0.0.1:18765`）+ Qt Overlay/托盘，不再默认加载 Qt 主窗
- 新增 `app/web_console.py`、`app/webview_shell.py`、`web/static/`、`app/web_api/`（人格、自定义模型、`POST /api/preview/compress`）
- Web 页面：运行概览、助手设置（含节奏/截图/图像参数）、人格工坊、弹幕日记（多级别过滤/复制/自动滚动）、隐私
- `ui/main_window.py` 仅 `--qt-ui` / `DANMU_QT_UI=1` 加载，标记 **deprecated**
- 文档：`docs/WEB_CONSOLE.md`、更新 `README.md`、`AGENTS.md`、`docs/ARCHITECTURE.md`
- 测试：`test_web_persona_api.py`、`test_web_custom_models.py`、`test_image_compress.py`、`test_ui_mode.py`

## 2026-05-24（方案 E Qt UI）

- 主窗口 UI 全面切换为**方案 E（玻璃浅色）**：渐变背景、浮动侧栏、`GlassTopBar`、右下角 `LogDock`
- 新增 `ui/glass_frame.py`、`ui/glass_top_bar.py`、`ui/log_dock.py`；`ui/theme.py` 增加 `USE_LEGACY_THEME` 回退开关
- 新增 HTML 原型 `prototype/scheme-e-*.html`、`scheme-e-tokens.css`；`ui_preview.html` 指向主壳预览
- 更新 `AGENTS.md`、`docs/ARCHITECTURE.md`、`README.md` 等文档以反映 UI 结构；详见 `docs/qt6_ui_redesign_plan.md`

## 2026-05-17

- 项目许可证从 MIT 更改为 GPL-3.0+，与 PyQt6 (GPL-3.0) 和 python-Levenshtein (GPL-2.0+) 的 copyleft 要求一致
- `LICENSE` 更新为 GPL v3 摘要 + 第三方依赖许可证声明
- `README.md` 补充项目状态、环境要求（Python ≥ 3.12、Windows）、已知限制；修复所有本地绝对路径为仓库相对路径
- `CONTRIBUTING.md` 修复本地绝对路径
- `docs/OPEN_SOURCE_AUDIT.md` 补充第三方依赖许可证审计表，更新许可证口径为 GPL-3.0+
- `.env.example` 明确标注为参考模板，桌面应用不自动加载
- `.gitignore` 补齐 `.agents/`、`.trae/`、`skills-lock.json`、`test_icon.png`
- 移除 `log/`、`.coverage`、`__pycache__/`、`.pytest_cache/`、`.npmcache/`、`scratchpad.md`、`skills-lock.json`、`test_icon.png` 等无关文件
- 初始化 Git 仓库
- 整理 `docs/`：移除 9 个内部过程文档（ISSUE_TRACKER、OPTIMIZATION_PLAN、产品需求文档、技术架构文档、技术问题解决方案、测试用例文档、需求文档、项目决策框架、项目管理文档），保留 5 个公开文档
- 新增 `.github/ISSUE_TEMPLATE/bug_report.md`、`.github/ISSUE_TEMPLATE/feature_request.md`、`.github/PULL_REQUEST_TEMPLATE.md`
- 新增 `THIRD_PARTY_NOTICES.md` 第三方依赖许可证声明
- 新增 `docs/RELEASE_CHECKLIST.md` 发布检查清单

## 2026-05-16

- 新增标准 MIT `LICENSE`
- 重写 `README.md`，补齐安装、运行、隐私、FAQ、贡献和许可证说明
- 新增 `CONTRIBUTING.md`、`SECURITY.md`、`.gitignore`、`.env.example`
- 新增 `docs/PRIVACY.md`、`docs/ROADMAP.md`、`docs/ARCHITECTURE.md`、`docs/OPEN_SOURCE_AUDIT.md`
- 修复默认截图逻辑，改为使用配置区域而非全屏
- 增加首启配置提示、退出清理、截图失败重调度、暂停时队列清理
- 引入 AI 回复解析与固定 5 条标准化逻辑
- 增补 pytest 测试覆盖回复约束、首启提示、异常释放和过期丢弃
