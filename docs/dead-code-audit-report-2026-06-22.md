# DanmuAI 死代码深度审计报告（2026-06-22）

> **历史审计快照**：候选死代码只对 2026-06-22 的入口点与引用图有效，不能据此直接删除现行代码。当前 Mixin、配置存储和弹幕引擎已拆分；执行清理前必须重新跑引用搜索并建立定向测试基线。
>
> **历史路径说明**：文中的 `app/config_store.py`、`app/danmu_engine.py` 与 8 Mixin 装配是当时结构，现行入口见 [docs/README.md](README.md) 顶部的三份登记表。
>
> **安全红线**：本报告为只读文档产物，未修改任何业务代码。所有清理建议均需用户明确确认后方可执行。
>
> **扫描范围**：`e:\test\danmu` 仓库，排除 `.local-ai/`（历史归档）、`docs/`（文档）、`output/_bililive_dm_repo/`（第三方仓库）。
>
> **生效入口点**：`main.py:main()` → `DanmuApp.__init__`（8 个 mixin）；`app/web_api/routes.py:register_web_routes`（≈40 条路由）；`app/web_console.py` FastAPI app；`tests/conftest.py:bind_minimal_danmu_app`；`scripts/boundary_guard.py`（薄壳 → `scripts/boundary_guard/` 子包）。
>
> **构建工具链**：Velopack（运行时 `velopack>=1.2.0,<2`）+ PyInstaller（构建时 `pyinstaller>=6.10,<7`，混合架构）。

---

## 步骤 1：架构与打包迁移遗迹（Migration Artifacts）

### 1.1 已移除子系统的残留引用

#### 🟢 `app/reply_queue.py:45,47` — `scene_memory` 注释残留
- **内容摘要**：`QueuedReply` 数据类字段注释引用已移除的 `scene_memory` 子系统：
  - 第 45 行：`source: str = "ai"  # ai | fallback | mic；mic 跳过去重、fallback 不写 scene_memory`
  - 第 47 行：`memory_eligible: bool = True  # False 时不上报 scene_memory（兜底通常 False）`
- **确认依据**：全局 Grep `scene_memory` 在 `app/` 下仅此 2 处注释残留；`app/memory/` 目录与 `app/scene_memory.py` 文件均不存在（Glob 确认）。`memory_eligible` 字段全局无任何读取/写入点（仅定义处）。`scene_memory` 子系统已于 2026-06 删除（`W-SCENEBRIEF-REMOVE-*`）。
- **建议**：清理注释；`memory_eligible` 字段可一并移除（无引用）。

#### 🟢 `DanmuAI.spec:16` — `app/memory/` 注释残留
- **内容摘要**：hiddenimports 组织注释写道 `hiddenimports 按分区组织：第三方包 → app 顶层 → app.application / memory / meme_barrage / pet / providers / web_api 子包`，其中 `memory` 引用已移除的 `app/memory/` 子包。
- **确认依据**：Grep `app\.memory|app\.scene_memory` 在 `DanmuAI.spec` 中无匹配（实际 hiddenimports 列表未列入），仅注释残留。
- **建议**：清理注释中的 `memory` 引用。

### 1.2 旧版 reason 字符串未同步

#### 🟡 `main.py:282` — `reason=invalid_pixmap`（旧版字符串）
- **内容摘要**：`_apply_capture_result` 中截图无效时记录 `reason=invalid_pixmap`。
- **确认依据**：AGENTS.md §A.7 明确标注 `invalid_pixmap` 为"历史 reason，已被上面的实现替换"；当前实现应使用 `null_pixmap`。`app/snipper.py:187,227` 已使用新字符串 `reason = "null_pixmap"`，但 `main.py:282` 未同步更新。
- **关联测试**：`tests/test_capture_flow.py:259-270` 断言 `assert any("invalid_pixmap" in msg for msg in app.logger.warning_messages)`，与旧字符串绑定。
- **建议**：人工复核 — 确认是否应统一为 `null_pixmap`；若统一，需同步更新 `main.py:282` 与 `tests/test_capture_flow.py`。

#### 🟡 `main.py:383` — `reason=inflight_watchdog`（旧版字符串）
- **内容摘要**：`_on_normal_capture_tick` 中 45s 警告分支记录 `reason=inflight_watchdog`。
- **确认依据**：AGENTS.md §A.7 将 `inflight_watchdog` 列为"历史 reason，已被替换"；当前实现使用 `inflight_watchdog_recover`（48s 强制恢复，`app/main_request_context_mixin.py:139`）。但 45s 警告与 48s 恢复是不同事件，`inflight_watchdog_recover` 仅用于 48s 恢复，不适用于 45s 警告。
- **建议**：人工复核 — 确认 45s 警告分支应使用的 reason 字符串（可能需新增 `inflight_watchdog_warn` 或保留 `inflight_watchdog` 并更新文档）。

### 1.3 PyInstaller 混合架构（迁移未完成？）

#### 🔴 PyInstaller + Velopack 混合架构 — 需确认是否为预期最终状态
- **涉及文件**：
  - `DanmuAI.spec`（约 283 行）— 完整 PyInstaller spec 文件
  - `scripts/build_exe.ps1`（71 行）— PyInstaller onedir 构建脚本
  - `requirements-dev.txt:5-6` — `pyinstaller>=6.10,<7` + `pyinstaller-hooks-contrib`
  - `.github/workflows/ci.yml:60-61` — `pack-windows` job 执行 `.\scripts\build_exe.ps1`
  - `app/bundle_paths.py:1,12,17,35` — `sys.frozen` / `sys._MEIPASS`（PyInstaller 特有）检测
- **确认依据**：任务背景描述"PyInstaller → Velopack 打包"，但实际流水线是 PyInstaller + Velopack 串联（PyInstaller 构建 onedir → Velopack 包装为自动更新包）。`requirements.txt` 仅 pin velopack（运行时），`requirements-dev.txt` 仍 pin pyinstaller（构建时）。
- **风险说明**：无法静态判定这是否为预期架构，还是迁移未完成。若计划完全改用 `vpk build` 从源码直接构建，则上述文件均为迁移遗迹；若混合架构为最终状态，则均为活跃代码。
- **建议**：**严禁盲目删除** — 需项目负责人确认打包架构规划。

### 1.4 实时弹幕模式移除后的兼容残留

#### 🟡 `app/live_freshness.py:12-13` — docstring 与实际用途不符
- **内容摘要**：模块 docstring 写道 `历史兼容：实时模式 TTL/节奏预触发已移除；保留本模块仅为防旧 config 报错。`
- **确认依据**：`build_local_fallback_batch` 和 `is_model_slow` 仍被 `main.py:38-39, 238, 244` 实际调用，并非纯历史兼容。docstring 描述与实际用途不符。
- **建议**：更新 docstring，明确说明该模块当前职责（模型缓慢检测 + 本地兜底批次）。

#### 🟡 `app/application/config_service.py:119-123` 与 `app/config_store.py:126-134` — `normalize_legacy_display_mode` 迁移 shim
- **内容摘要**：`normalize_legacy_display_mode` 函数将 `danmu_display_mode == "realtime"` 映射为 `"normal"`，在启动时调用。
- **确认依据**：实时弹幕模式已于 2026-05-27 移除（CHANGELOG.md:143）。`danmu_display_mode` 已不在 `WEB_CONFIG_KEYS` 白名单中（`test_web_auth.py:221` 显式断言）。属于合理的向后兼容，但引用了已移除的实时模式。
- **建议**：保留作为向后兼容；在确认无旧版用户后可移除。

---

## 步骤 2：调用链追踪与孤立代码识别

### 2.1 明确孤立代码

#### 🟢 `app/danmu_engine.py:161-168` — `is_normalized_danmu_overlay_safe` 函数完全孤立
- **内容摘要**：`def is_normalized_danmu_overlay_safe(content: str, config, *, lang: str | None = None) -> bool:` 对已 normalize 的弹幕做 overlay 校验。
- **确认依据**：全局 Grep `is_normalized_danmu_overlay_safe` 仅命中定义处（1 行），无任何调用点（`app/`、`main.py`、`tests/`、`scripts/` 均无引用）。无动态调用特征（未出现在 `__all__`、未被 `getattr` 反射、未被信号槽字符串连接）。与同文件 `resolve_danmu_display_text`（line 144，被 `main.py:30` 引用）相邻，疑似重构遗留。
- **建议**：可直接清理。

### 2.2 方法覆盖导致死代码（高风险）

#### 🔴 `app/main_request_context_mixin.py:300-328` vs `main.py:163-221` — 方法覆盖导致行为分歧
- **内容摘要**：`DanmuApp` 在 `main.py` 与 `app/main_request_context_mixin.py` 中均定义了 `_maybe_pool_topup` 与 `_maybe_duplicate_loss_topup`，Python MRO 中 `DanmuApp` 自身方法优先于 mixin，mixin 版本永不执行。
- **行为差异**：
  - `main.py` 版本（实际执行）：调用 `plan_pool_topup` / `plan_duplicate_loss_topup` 返回 texts，手动 `engine.add_text()` 并 `self._broadcast_live_overlay_item()` 广播 live-overlay 事件。
  - `mixin` 版本（死代码）：调用 `maybe_pool_topup` / `maybe_duplicate_loss_topup` 封装版（内部 add_text，**不广播** live-overlay）。
- **确认依据**：
  - `main.py:804,831,868,901,1035` 调用 `self._maybe_pool_topup()`；`main.py:996` 调用 `self._maybe_duplicate_loss_topup()` — 全部命中 `main.py` 版本。
  - `tests/test_reply_enqueue.py:114` monkeypatch `app.main_request_context_mixin.maybe_duplicate_loss_topup` — 暗示测试作者期望 mixin 版本被调用，但实际 `main.py` 版本被调用（monkeypatch 无效）。
- **风险说明**：若未来删除 `main.py` 版本（让 mixin 生效），live-overlay 推送会静默丢失。`maybe_pool_topup` / `maybe_duplicate_loss_topup` 封装版仅被死代码与测试调用。
- **建议**：**严禁盲目删除任一版本** — 需先确认预期行为（是否应广播 live-overlay），再统一到一个实现。

### 2.3 后端注册但前端无调用的路由

#### 🟡 9 条后端冗余路由（需人工复核外部契约）

| 路由 | 方法 | 注册位置 | 前端调用 | 风险说明 |
|------|------|----------|----------|----------|
| `/api/toggle` | POST | `app/web_console_runtime.py:209` | 无 | 可能对应热键路径或外部工具 |
| `/api/meta` | GET | `app/web_console_runtime.py:144` | 无 | 前端分别调 `/api/status`、`/api/screens` |
| `/api/test/danmu` | POST | `app/web_api/routes.py:371` | 无 | 可能为测试用接口 |
| `/api/mic/test-send` | POST | `app/web_api/routes.py:515` | 无 | 前端仅调 `/api/mic/test` |
| `/api/pet/show` | POST | `app/web_api/routes.py:652` | 无 | 可能为 Qt 桌宠上下文菜单调用 |
| `/api/pet/hide` | POST | `app/web_api/routes.py:657` | 无 | 同上 |
| `/api/pet/close` | POST | `app/web_api/routes.py:662` | 无 | 同上 |
| `/api/pet/status` | GET | `app/web_api/routes.py:675` | 无 | 同上 |
| `/api/personae/{name}/versions` | GET | `app/web_api/routes.py:271` | 无 | 可能为预留功能（版本历史 UI 未实现） |

- **确认依据**：Grep `apiFetch\(['"\`]/api/...` + `fetch\(['"\`]/api/...` 覆盖 `web/static/**/*.js` + `web/static/**/*.html`，上述路由均无命中。
- **建议**：人工确认是否有外部契约（bililive_dm 插件、测试脚本、curl 调用、Qt 上下文菜单 HTTP 调用）后再决定清理。

### 2.4 向后兼容门面

#### 🟡 `app/danmu_tts.py:40-69` — `synthesize_mimo_tts` 向后兼容门面
- **内容摘要**：`def synthesize_mimo_tts(api_key, text, *, style_prompt="", voice=..., ...) -> bytes:` 为老接口符号。
- **确认依据**：Grep `synthesize_mimo_tts` 命中定义处 + `__all__` 导出 + `tests/test_danmu_tts.py:20,76,107,154,159,197`（仅测试调用）。生产代码（`app/`、`main.py`）无引用 — 实际合成走 `app.tts_providers.synthesize_tts`。文件 docstring 明确说明"本文件**仅**作为 re-export 兼容层"。
- **建议**：保留，但标注"向后兼容"；未来可考虑移除。

---

## 步骤 3：微观层面冗余（Micro-level Redundancy）

### 3.1 未使用导入

#### 🟢 `app/main_meme_mixin.py:14` — `ai_worker_pool` 未使用导入
- **内容摘要**：`from app.worker_pools import ai_worker_pool, meme_ai_pool` 中 `ai_worker_pool` 被导入但从未在文件中使用（仅 `meme_ai_pool` 和 `meme_fetch_pool` 被调用）。
- **确认依据**：Grep `ai_worker_pool` 在该文件中仅出现在 import 行（第 14 行），文件其余部分无任何引用。
- **建议**：清理 — 将 import 改为 `from app.worker_pools import meme_ai_pool`。

### 3.2 空 TYPE_CHECKING 块

#### 🟢 `app/main_meme_mixin.py:16-17` — 空 `if TYPE_CHECKING: pass` 块
- **内容摘要**：`if TYPE_CHECKING: pass` 空块，`TYPE_CHECKING` 导入后仅用于此空 pass 块，无任何类型导入。
- **确认依据**：多行正则 `if TYPE_CHECKING:\s*\n\s*pass` 匹配；Read 工具确认块内仅有 `pass`。
- **建议**：清理 — 移除空块与 `TYPE_CHECKING` 导入（若文件无其他类型注解用途）。

#### 🟢 `app/reply_parser.py:20-21` — 空 `if TYPE_CHECKING: pass` 块
- **内容摘要**：`if TYPE_CHECKING: pass` 空块，`TYPE_CHECKING`（第 16 行导入）仅用于此空 pass 块。
- **确认依据**：多行正则匹配；Read 工具确认块内仅有 `pass`。
- **建议**：清理 — 移除空块与 `TYPE_CHECKING` 导入。

### 3.3 未使用变量与方法

#### 🟢 `main.py:90` — `_DEPRECATED_LAUNCH_MSG` 未使用变量
- **内容摘要**：`_DEPRECATED_LAUNCH_MSG = DEPRECATED_LAUNCH_MSG` 注释标注"Re-export for scripts/tests that import from main"，但全仓库（含 `tests/`、`scripts/`）无任何引用。
- **确认依据**：Grep `_DEPRECATED_LAUNCH_MSG` 全仓库仅返回 `main.py:90` 赋值行，`tests/` 目录无匹配。
- **建议**：清理 — 移除该赋值行。

#### 🟢 `main.py:122-124` — `_normalize_legacy_display_mode_config` 未使用方法
- **内容摘要**：`def _normalize_legacy_display_mode_config(self) -> None:` 方法 docstring 标注"Deprecated: normalization runs in ConfigStore.__init__"，仅委托 `self.config._normalize_legacy_display_mode()`，全仓库无调用。
- **确认依据**：Grep `_normalize_legacy_display_mode_config` 全仓库仅返回 `main.py:122` 定义行，无任何调用点。
- **建议**：清理 — 移除该方法。

#### 🟢 `main.py:150-151` — 注释代码（不足 ≥10 行阈值，但确属注释代码）
- **内容摘要**：两行被注释的可执行代码：
  ```python
  # attach_web_console(self)
  # self.config_changed.connect(self._on_config_changed)
  ```
- **确认依据**：Read 工具读取确认；位于 `DanmuApp.__init__` 内。
- **建议**：清理 — 移除注释代码（不足 ≥10 行阈值，但确属注释代码）。

### 3.4 未发现的项目

- **大段注释代码块（≥10 行）**：在 `app/` 下所有 .py 文件、`web/static/app.js`、`main.py`、`scripts/` 下所有 .py 文件中，使用多种 Grep 模式（含 multiline 模式）均未发现 ≥10 行连续注释代码块。
- **不可达代码（`if False:` / `if 0:` / `while False:`）**：Grep 搜索全仓库（排除 `.local-ai/`、`docs/`）无任何匹配。
- **DANMU_QT_UI / DANMU_WEB_CONSOLE 死分支**：所有引用均位于 `app/main_launch.py:check_deprecated_launch_args()` 内或 `tests/test_deprecated_launch_flags.py` 与 `docs/` 中。未发现在 `check_deprecated_launch_args` 之外的死分支。

---

## 步骤 4：预存缺陷（Pre-existing Flaws）

### 4.1 确认的预存缺陷

#### Pre-existing Flaw #1：`app/reply_parser.py:25` — `scene_brief` 过滤项永不命中
- **缺陷类型**：旧版字段解析 / 死代码
- **内容摘要**：`_HEURISTIC_SKIP = frozenset({"comments", "scene_brief", ":", ""})` 中保留 `scene_brief` 作为过滤项。
- **根因**：`W-SCENEBRIEF-REMOVE-*` 系列工单删除了 `app/memory/`、`scene_memory_interval_sec`、`prompt_dedup_window` 等场景记忆能力，但遗漏了 `reply_parser.py` 中 `_HEURISTIC_SKIP` 集合里的 `scene_brief` 字符串。
- **影响**：不会导致功能降级，仅为冗余过滤项；`scene_brief` 永远不会出现在 AI 回复中，该过滤分支永远不命中。
- **建议处理方式**：清理 — 从 `_HEURISTIC_SKIP` 中移除 `"scene_brief"`。

#### Pre-existing Flaw #2：`app/main_helpers.py:6` — docstring 引用不存在的 `memory_tone_hint`
- **缺陷类型**：配置默认值失效 / 文档与代码不一致
- **内容摘要**：模块 docstring 第 6 行声明"纯函数辅助（reply_request_id、density_right_target、memory_tone_hint 等）"，但 `memory_tone_hint` 函数在整个 `app/` 目录中不存在。
- **根因**：`W-SCENEBRIEF-REMOVE-*` 删除了 `app/memory/` 子包及 `memory_tone_hint` 等辅助函数，但 `main_helpers.py` 的 docstring 未同步更新。
- **影响**：不影响运行时行为，仅为文档误导；Codex/Agent 阅读 docstring 时可能误以为该函数存在并尝试调用。
- **建议处理方式**：清理 — 从 docstring 中移除 `memory_tone_hint` 引用。

#### Pre-existing Flaw #3：`app/config_defaults.py:56` — `use_thinking` 配置键失效
- **缺陷类型**：配置默认值失效 / 静默失败
- **内容摘要**：`CONFIG_DEFAULTS` 中仍保留 `"use_thinking": "0"`，并在 docstring 第 14 行将 `use_thinking` 列为 API 配置项。但运行时 `ai_client_requests.py:205` 固定调用 `resolve_danmu_max_output_tokens(configured_max, use_thinking=False)`，`ai_client_requests.py:243` 固定注入 `data["thinking"] = dict(THINKING_DISABLED)`，`use_thinking` 配置值从未被读取。
- **根因**：项目决定运行时固定关闭 thinking（`THINKING_DISABLED` 常量），但未清理 `CONFIG_DEFAULTS` 中的 `use_thinking` 键。
- **影响**：**用户在 Web 控制台设置 `use_thinking=1` 不会产生任何效果（静默失败）**；`test_ai_client.py:340` 的测试用例也仅验证 `thinking` payload 仍为 `{"type": "disabled"}`，证明配置键已失效。
- **建议处理方式**：清理 — 从 `CONFIG_DEFAULTS` 移除 `use_thinking`，并从 docstring 中移除引用；或在 Web UI 隐藏该选项。

#### Pre-existing Flaw #4：`app/danmu_tts_playback.py:96-99` — 文档标记已修复的跨线程违规
- **缺陷类型**：文档与代码不一致 / 已修复的跨线程违规
- **内容摘要**：AGENTS.md §9 第 1 条、§A.5.4 多处标记 `_play_worker` 在 `threading.Thread` 中发 `playback_finished` Qt 信号为"已知跨线程违规"，要求改为 `QTimer.singleShot(0, ...)`。但实际代码已使用 `QMetaObject.invokeMethod(self, "playback_finished", Qt.ConnectionType.QueuedConnection)` 投递到主线程，这是 Qt 推荐的跨线程信号投递方式，等价于 `QTimer.singleShot(0, ...)`。
- **根因**：代码已修复（使用 `QMetaObject.invokeMethod` + `QueuedConnection`），但 AGENTS.md 与 `docs/bug-audit-report-2026-06-21.md` 仍标记为"已知违规"。
- **影响**：文档误导 Codex/Agent 修改已正确的代码；`docs/bug-audit-report-2026-06-21.md:479` 引用的代码 `self.playback_finished.emit()` 已不存在。
- **建议处理方式**：清理 — 更新 AGENTS.md §9 第 1 条、§A.5.4 与 `bug-audit-report-2026-06-21.md`，标记此问题已修复。

### 4.2 高风险预存缺陷

#### 🔴 Pre-existing Flaw #5：`app/application/config_service.py:202-208` — Web API 绕过白名单写入废弃键
- **缺陷类型**：配置默认值失效 / 废弃键仍可写入
- **内容摘要**：`danmu_display_mode` 不在 `WEB_CONFIG_KEYS` 白名单中，但 `ConfigService.apply_web_payload` 第 202-208 行仍特殊处理 `payload.get("danmu_display_mode")`，将其规范化后写入 `items["danmu_display_mode"]`。
- **根因**：`apply_web_payload` 第 198-200 行 `for key in WEB_CONFIG_KEYS: if key in payload` 会跳过非白名单键，但第 202-208 行又特殊处理 `danmu_display_mode`，绕过了白名单检查。
- **影响**：**Web API 可写入废弃的 `danmu_display_mode` 键，但运行时不再读取该键**（`resolve_danmu_render_mode` 只读 `danmu_render_mode`）。写入的值会被 `_normalize_legacy_display_mode` 规范化为 `normal`，但 `normal` 不影响任何运行时行为。这是"静默失败"——用户通过 Web API 设置 `danmu_display_mode` 不会产生任何效果。
- **建议处理方式**：修复 — 移除 `apply_web_payload` 中对 `danmu_display_mode` 的特殊处理（第 202-208 行），让白名单机制生效；或将其加入白名单并明确废弃说明。

### 4.3 中风险疑似缺陷

#### 🟡 `app/ai_client_requests.py:612-623` 与 `app/doubao_responses_stream.py:141-155` — 诊断死代码
- **缺陷类型**：旧版字段解析 / 诊断死代码
- **内容摘要**：`stream_openai` 中 `reasoning = delta.get("reasoning_content", "")` 与 `doubao_responses_stream.py` 中处理 `response.reasoning_summary_text.delta` / `response.reasoning_text.delta` 事件。项目固定发送 `thinking: {"type":"disabled"}`，理论上模型不应返回 `reasoning_content`。
- **根因**：`thinking:disabled` 是固定注入，但部分模型（如 MiMo）可能不严格遵守，因此保留诊断收集。
- **影响**：如果模型遵守 `thinking:disabled`，`reasoning_parts` 永远为空，`reasoning_only` 永远为 False，相关 warning 日志永远不触发；如果模型不遵守，reasoning 内容会被收集但不会作为弹幕上屏（正确行为）。这是"诊断死代码"——在正常情况下不触发，但保留用于异常排查。
- **建议处理方式**：保留 — 作为诊断辅助；但应在注释中明确说明"thinking:disabled 生效时此分支理论上不触发"。

#### 🟡 `app/danmu_engine.py:169-176` — Levenshtein 全局变量双向同步
- **缺陷类型**：检查逻辑失效 / 疑似冗余全局变量同步
- **内容摘要**：`_LEVENSHTEIN_UNAVAILABLE = dedup_profile._LEVENSHTEIN_UNAVAILABLE`、`_LEVENSHTEIN_RATIO = dedup_profile._LEVENSHTEIN_RATIO`，并在 `_get_levenshtein_ratio` 中通过 `dedup_profile._LEVENSHTEIN_RATIO = _LEVENSHTEIN_RATIO` 双向同步全局变量。
- **根因**：`danmu_engine.py` 从 `danmu_engine_dedup` re-export 了 `is_duplicate_in_recent` 等函数，但 `danmu_engine_dedup` 内部使用模块级全局变量 `_LEVENSHTEIN_RATIO` 缓存 Levenshtein 函数引用。
- **影响**：这种双向同步容易导致状态不一致；如果 `danmu_engine_dedup._get_levenshtein_ratio` 被直接调用，`danmu_engine._LEVENSHTEIN_RATIO` 不会同步更新。但实际调用路径都经过 `danmu_engine_dedup.is_duplicate_in_recent`，因此不会触发问题。
- **建议处理方式**：人工复核 — 考虑移除 `danmu_engine.py` 中的全局变量同步，直接委托 `dedup_profile._get_levenshtein_ratio()`。

### 4.4 未确认问题

#### `app/live_freshness.py:12-13` — docstring 与实际用途不符
- **内容摘要**：模块 docstring 声明"历史兼容：实时模式 TTL/节奏预触发已移除；保留本模块仅为防旧 config 报错"。但 `build_local_fallback_batch` 和 `is_model_slow` 仍被 `main.py:38-39, 238, 244` 实际调用，并非纯历史兼容。
- **建议**：人工复核 — 更新 docstring，明确说明该模块当前职责（模型缓慢检测 + 本地兜底批次），而非"仅为防旧 config 报错"。

#### `app/config_store.py:97-98` — 两个不同的遗留键？
- **内容摘要**：`_migrate_legacy_display_mode_to_render_mode` 在 `__init__` 中调用，处理 `display_mode` → `danmu_render_mode` 迁移。但 `display_mode`（无 `danmu_` 前缀）与 `danmu_display_mode`（有前缀）是两个不同的键。
- **建议**：人工复核 — 确认是否存在两个不同的遗留键，还是文档/代码命名不一致。

#### `app/reply_parser.py:33-46` — MiniMax `<think>` 标签剥离逻辑
- **内容摘要**：`_REASONING_OPEN = "<think>"`、`_REASONING_CLOSE = "</think>"`、`_REASONING_BLOCK_RE` 等正则用于剥离 MiniMax 风格的 `<think>...</think>` 块。项目固定发送 `thinking: {"type":"disabled"}`，理论上不应收到 `<think>` 标签。但 `is_minimax_endpoint` 时还会设置 `reasoning_split: True`。
- **建议**：人工复核 — 确认 MiniMax 端点在 `thinking:disabled` + `reasoning_split:True` 下是否仍可能泄漏 `<think>` 标签；如不可能，则为死代码。

---

## 风险等级汇总

### 🟢 低风险/明确冗余（建议清理）— 共 9 项

| # | 文件:行号 | 类型 | 内容摘要 |
|---|----------|------|----------|
| 1 | `app/reply_queue.py:45,47` | 迁移遗迹 | `scene_memory` 注释残留 + `memory_eligible` 字段无引用 |
| 2 | `DanmuAI.spec:16` | 迁移遗迹 | `app/memory/` 注释残留 |
| 3 | `app/danmu_engine.py:161-168` | 孤立代码 | `is_normalized_danmu_overlay_safe` 函数完全孤立 |
| 4 | `app/main_meme_mixin.py:14` | 未使用导入 | `ai_worker_pool` 未使用 |
| 5 | `app/main_meme_mixin.py:16-17` | 空 TYPE_CHECKING 块 | 空 `if TYPE_CHECKING: pass` |
| 6 | `app/reply_parser.py:20-21` | 空 TYPE_CHECKING 块 | 空 `if TYPE_CHECKING: pass` |
| 7 | `main.py:90` | 未使用变量 | `_DEPRECATED_LAUNCH_MSG` 无引用 |
| 8 | `main.py:122-124` | 未使用方法 | `_normalize_legacy_display_mode_config` 无调用 |
| 9 | `main.py:150-151` | 注释代码 | 2 行注释代码（不足 ≥10 行阈值） |

**预存缺陷（低风险）— 共 4 项**

| # | 文件:行号 | 缺陷类型 | 内容摘要 |
|---|----------|----------|----------|
| P1 | `app/reply_parser.py:25` | 旧版字段解析 | `scene_brief` 过滤项永不命中 |
| P2 | `app/main_helpers.py:6` | 文档不一致 | docstring 引用不存在的 `memory_tone_hint` |
| P3 | `app/config_defaults.py:56` | 配置键失效 | `use_thinking` 配置键失效（静默失败） |
| P4 | `app/danmu_tts_playback.py:96-99` | 文档不一致 | 文档标记已修复的跨线程违规 |

### 🟡 中风险/疑似废弃（需人工复核）— 共 14 项

| # | 文件:行号 | 类型 | 内容摘要 |
|---|----------|------|----------|
| 1 | `main.py:282` | 旧版 reason | `reason=invalid_pixmap`（应同步为 `null_pixmap`） |
| 2 | `main.py:383` | 旧版 reason | `reason=inflight_watchdog`（45s 警告分支） |
| 3 | `tests/test_capture_flow.py:259-270` | 测试绑定旧字符串 | 断言 `invalid_pixmap` |
| 4 | `scripts/split_t008_tests.py:67` | 测试配置 | 引用旧测试名 `test_invalid_pixmap` |
| 5 | `app/live_freshness.py:12-13` | docstring 不符 | 实际仍被调用，非纯历史兼容 |
| 6 | `app/application/config_service.py:119-123` | 迁移 shim | `normalize_legacy_display_mode` 向后兼容 |
| 7-15 | `app/web_api/routes.py` 等 | 后端冗余路由 | 9 条后端注册但前端无调用的路由 |
| 16 | `app/danmu_tts.py:40-69` | 兼容门面 | `synthesize_mimo_tts` 向后兼容 |
| 17 | `app/ai_client_requests.py:612-623` | 诊断死代码 | `reasoning_content` 解析（thinking:disabled） |
| 18 | `app/doubao_responses_stream.py:141-155` | 诊断死代码 | `reasoning_summary_text` 事件处理 |
| 19 | `app/danmu_engine.py:169-176` | 全局变量同步 | Levenshtein 双向同步 |

### 🔴 高风险/需验证动态引用与外部契约 — 共 3 项

| # | 文件:行号 | 类型 | 风险说明 |
|---|----------|------|----------|
| 1 | `DanmuAI.spec` + `scripts/build_exe.ps1` + `requirements-dev.txt:5-6` + `.github/workflows/ci.yml:60-61` + `app/bundle_paths.py` | PyInstaller 混合架构 | 需确认是否为预期最终状态，还是迁移未完成 |
| 2 | `app/main_request_context_mixin.py:300-328` vs `main.py:163-221` | 方法覆盖分歧 | mixin 版本永不执行；若删除 main.py 版本，live-overlay 推送会静默丢失 |
| 3 | `app/application/config_service.py:202-208` | 白名单绕过 | Web API 可写入废弃的 `danmu_display_mode` 键（静默失败） |

---

## Git 操作与回归测试指南

### 1. 分批清理策略

按风险等级分批，每批独立 commit，便于 `git revert`：

#### 批次 1：🟢 低风险明确冗余（建议优先清理）

**Commit 1.1：迁移遗迹注释清理**
- `app/reply_queue.py:45,47` — 移除 `scene_memory` 注释 + `memory_eligible` 字段
- `DanmuAI.spec:16` — 移除 `memory` 注释引用
- `app/main_helpers.py:6` — 移除 docstring 中 `memory_tone_hint` 引用

**Commit 1.2：孤立函数清理**
- `app/danmu_engine.py:161-168` — 移除 `is_normalized_danmu_overlay_safe`

**Commit 1.3：未使用导入与空块清理**
- `app/main_meme_mixin.py:14` — 移除 `ai_worker_pool` 导入
- `app/main_meme_mixin.py:16-17` — 移除空 `TYPE_CHECKING` 块
- `app/reply_parser.py:20-21` — 移除空 `TYPE_CHECKING` 块

**Commit 1.4：未使用变量与方法清理**
- `main.py:90` — 移除 `_DEPRECATED_LAUNCH_MSG`
- `main.py:122-124` — 移除 `_normalize_legacy_display_mode_config`
- `main.py:150-151` — 移除注释代码

**Commit 1.5：预存缺陷清理（低风险）**
- `app/reply_parser.py:25` — 从 `_HEURISTIC_SKIP` 移除 `"scene_brief"`
- `app/config_defaults.py:56` — 移除 `use_thinking` 默认值（**需同步检查 Web UI 是否有该选项**）
- `app/danmu_tts_playback.py` — 更新文档（AGENTS.md §9 第 1 条、§A.5.4）

#### 批次 2：🟡 中风险疑似废弃（需人工复核后清理）

**Commit 2.1：旧版 reason 字符串同步**（需确认后）
- `main.py:282` — `invalid_pixmap` → `null_pixmap`
- `main.py:383` — `inflight_watchdog` → 确认新字符串
- `tests/test_capture_flow.py:259-270` — 同步更新断言
- `scripts/split_t008_tests.py:67` — 同步更新测试名模式

**Commit 2.2：后端冗余路由清理**（需确认无外部契约后）
- 逐条确认 9 条路由是否有外部调用
- 确认后移除未使用的路由处理器

**Commit 2.3：docstring 更新**
- `app/live_freshness.py:12-13` — 更新 docstring

#### 批次 3：🔴 高风险（需验证后清理）

**Commit 3.1：方法覆盖分歧修复**（需确认预期行为后）
- 统一 `_maybe_pool_topup` / `_maybe_duplicate_loss_topup` 到一个实现
- 确认是否应广播 live-overlay 事件
- 同步更新 `tests/test_reply_enqueue.py`

**Commit 3.2：白名单绕过修复**（需确认后）
- `app/application/config_service.py:202-208` — 移除 `danmu_display_mode` 特殊处理

**Commit 3.3：PyInstaller 混合架构**（需项目负责人确认后）
- 若完全迁移到 Velopack：移除 `DanmuAI.spec`、`scripts/build_exe.ps1`、`requirements-dev.txt` 中 pyinstaller、CI 中 PyInstaller 步骤
- 若保留混合架构：无需清理

### 2. 每批清理后的回归测试命令

遵守 IDE_AGENT_RULES §10 分批低内存策略（禁止 `python -m pytest tests/`）：

```bash
# 批次 1（低风险清理）后
python -m pytest tests/test_reply_parser.py tests/test_reply_queue.py tests/test_reply_contract.py -q -x
python -m pytest tests/test_danmu_engine.py tests/test_danmu_engine_dedup.py -q -x
python -m pytest tests/test_p0_main_flow.py tests/test_capture_flow.py -q -x
python -m pytest tests/test_danmu_tts.py -q -x

# 批次 2（中风险清理）后
python -m pytest tests/test_capture_flow.py tests/test_p0_main_flow.py -q -x
python -m pytest tests/test_web_console.py tests/test_web_auth.py -q -x
python -m pytest tests/test_reply_enqueue.py tests/test_pool_topup.py -q -x

# 批次 3（高风险清理）后
python -m pytest tests/test_reply_enqueue.py tests/test_pool_topup.py tests/test_danmu_pool.py -q -x
python -m pytest tests/test_p0_main_flow.py tests/test_web_console.py -q -x
python -m pytest tests/test_request_timing_service.py tests/test_request_scheduling.py -q -x
```

### 3. boundary_guard 运行时机

触达编排、Web API、`DanmuApp` 主链路时必须运行：

```bash
python scripts/boundary_guard.py
```

**触发时机**：
- 批次 1 中 Commit 1.2（孤立函数清理，涉及 `danmu_engine.py`）
- 批次 1 中 Commit 1.4（未使用变量与方法清理，涉及 `main.py`）
- 批次 2 中 Commit 2.2（后端冗余路由清理，涉及 `app/web_api/`）
- 批次 3 中所有 commit（涉及主链路与配置服务）

### 4. 回滚策略

- 每批一个 commit，commit message 标注清理批次与风险等级
- 示例 commit message：
  ```
  refactor: 清理死代码批次 1.1 — 迁移遗迹注释（🟢 低风险）

  - app/reply_queue.py: 移除 scene_memory 注释残留与 memory_eligible 字段
  - DanmuAI.spec: 移除 app/memory/ 注释引用
  - app/main_helpers.py: 移除 docstring 中 memory_tone_hint 引用

  依据: docs/dead-code-audit-report-2026-06-22.md
  ```
- 若回归测试失败：`git revert <commit-hash>`
- 若 boundary_guard 报警：检查是否触达禁止修改区域

### 5. 手动验收检查点

每批清理后，启动应用并验证关键路径：

```bash
python main.py
```

**验收检查点**：
1. **启动**：应用正常启动，Web 控制台（http://127.0.0.1:18765）可访问
2. **Overlay**：Qt 透明置顶弹幕窗口正常显示
3. **截图链路**：截图定时器正常工作，AI 回复正常上屏
4. **Web 控制台**：设置页、人格页、模型页、公式化弹幕库页正常加载
5. **麦克风**（若启用）：麦克风自检正常
6. **TTS / 读弹幕**（若启用）：TTS 播放正常
7. **桌宠**（若启用）：桌宠窗口正常显示与交互
8. **烂梗弹幕**（若启用）：烂梗采集与展示正常
9. **托盘**：系统托盘菜单正常
10. **热键**：暂停/恢复热键正常

**关键日志检查**：
- 搜索 `reason=null_pixmap`（应替换 `invalid_pixmap`）
- 搜索 `reason=inflight_watchdog_recover`（48s 恢复）
- 搜索 `reason=scene_generation_lagged`（场景代际淘汰）
- 确认无 `scene_memory`、`scene_brief`、`memory_tone_hint` 相关错误

---

## 附录：扫描覆盖范围确认

| 扫描维度 | 覆盖情况 |
|----------|----------|
| 迁移遗迹（scene_brief / memory / PyInstaller / 旧版 reason / 实时模式） | ✅ 全覆盖 |
| 调用链孤立代码（app/ 公开函数/类、路由注册、适配器 registry、façade 调用链、fetch 路由匹配、动态调用特征） | ✅ 全覆盖 |
| 微观冗余（注释代码块、未使用导入、未使用变量、不可达代码、死分支） | ✅ 全覆盖 |
| 预存缺陷（旧版字段解析、检查逻辑失效、异常处理死代码、配置默认值失效） | ✅ 全覆盖 |
| 动态调用特征检查（getattr / emit / signal.connect / __all__ / entry_points / fetch 路由匹配） | ✅ 全覆盖 |

**未覆盖项**（需后续审计）：
- `scripts/audit_hiddenimports.py` 与 `scripts/velopack_poc.ps1` 未深入审查
- `web/static/modules/` 下各 JS 模块的未使用导出未逐一检查
- `tests/` 目录中仅用于反向验证未使用符号的测试用例未标记为冗余
