---
description: 
alwaysApply: true
---

# AGENTS.md — DanmuAI

> **对话式 AI / Codex / IDE Agent：** 先读本文件 **§1–§10**（协作与边界），再读 [ai-project-context.md](ai-project-context.md)（技术上下文与阅读顺序）。附录 A 为 DanmuAI 技术速查。

> **链接与目录说明（2026-06-21 校正）**：
>
> - 本文件中标记「**待 workorders/ 目录补建**」的链接（`../workorders/...` 5 处）当前在仓库根未创建 `workorders/`；Codex 暂时改为读 `reports/` 内工单报告。
> - 标记「**待 templates/ 目录补建**」的链接（`templates/...` 4 处）当前未创建。
> - 标记「**待根级协作文档补建**」的链接（`ai-project-context.md`、`IDE_AGENT_RULES.md`、`手动验收指南.md`、`Codex提示词手册.md`、`Codex工单交接模板.md`、`提示词上下文包.md` 6 处）当前未在仓库根创建；这些链接引用保留作为工单治理流程恢复后的回填占位。
> - 所有 `../../docs/...` 路径已校正为 `../docs/...`（AGENTS.md 位于仓库根）。
> - 本节为注脚，Codex 可忽略其内容做无副作用阅读。

---

## 1. 项目协作原则

- **一次只做一个小工单**：每个工单应在 5–10 分钟内可手动验收；范围过大时必须由负责人拆单。
- **工单驱动**：开工前必须能从 [../workorders/工单列表.md](../workorders/工单列表.md)（待 workorders/ 目录补建）或工单交接文档中读到工单 ID、目标、允许区、禁止区、验收标准。
- **文档与代码分工**：技术细节以 `main.py` 与 `app/` 源码为准；协作流程以本文件与 [../workorders/README.md](../workorders/README.md)（待 workorders/ 目录补建）为准。
- **不自由发挥架构**：不得在未获工单授权的情况下引入新分层、新包结构或大规模重构。
- **负责人补充优先**：标有「待项目负责人补充」的字段不得由 Codex 根据猜测填写业务需求。

---

## 2. Codex 执行边界

Codex / IDE Agent **只执行当前工单**，不得：

1. 实现未来工单或 [../docs/operations/ROADMAP.md](../docs/operations/ROADMAP.md) 中尚未拆单的功能
2. 顺手重构与工单无关的模块
3. 自行决定新架构或新依赖
4. 修改工单「禁止修改的区域」所列路径
5. 把 `.local-ai/` 内历史归档当作当前行为

开工前**必须阅读**（按工单类型选读）：

| 优先级 | 文件 |
|--------|------|
| P0 | 本文件 §1–§10、[../workorders/当前仓库状态.md](../workorders/当前仓库状态.md)（待 workorders/ 目录补建）、当前工单正文 |
| P0 技术 | [ai-project-context.md](ai-project-context.md)（待根级协作文档补建） |
| P1 改代码 | [../docs/CONTRIBUTING_ARCHITECTURE.md](../docs/CONTRIBUTING_ARCHITECTURE.md)、[../docs/core/MAIN_PIPELINE.md](../docs/core/MAIN_PIPELINE.md) |
| P1 改 Web/API | [../docs/features/WEB_CONSOLE.md](../docs/features/WEB_CONSOLE.md) |

---

## 3. 单工单规则

每个工单必须包含（见 [templates/工单/工单模板.md](templates/工单/工单模板.md)（待 templates/ 目录补建））：

- 工单 ID、标题、背景、目标
- **允许修改的区域**（路径列表，宜小）
- **禁止修改的区域**（路径列表，宜全）
- 需求、**非目标**（明确不包含什么）
- **验收标准**（可检查、可判定通过/不通过）
- **手动验证步骤**（5–10 分钟可完成）
- 完成后必须更新的文档列表

工单完成后必须：

1. 按 [templates/Codex完成报告/Codex完成报告模板.md](templates/Codex完成报告/Codex完成报告模板.md)（待 templates/ 目录补建）输出完成报告
2. 更新 [../workorders/当前仓库状态.md](../workorders/当前仓库状态.md)（待 workorders/ 目录补建）
3. 在 [../workorders/工单列表.md](../workorders/工单列表.md)（待 workorders/ 目录补建）中将该工单标为已完成（或交由负责人更新）

---

## 4. 允许与禁止行为

### 允许（须与工单一致）

- 仅修改工单「允许修改的区域」内的文件
- 为通过验收而添加**必要**的测试（若工单允许修改 `tests/`）
- 运行构建/测试/boundary_guard（见 §7）
- 更新工单列出的文档

### 禁止（无工单明确授权则一律禁止）

- 修改 `app/`、`web/`、`main.py`、`tests/`、`scripts/`、锁文件、`package.json`、构建与 CI 配置（**文档类工单除外**）
- 添加 `requirements.txt` 中未要求的依赖
- 重命名 Boundary Guard 维护者登记表：`runtime-state-map.md`、`main-pipeline-sequence.md`、`final-architecture-baseline.md`
- 在 HTTP 线程直接修改 Qt 对象
- 顺手修复范围外 bug 或「顺便」改架构

### 本仓库默认功能落点（有代码工单时）

| 类型 | 落点 |
|------|------|
| 新控制台功能 | `web/static/` + `app/web_api/routes.py` |
| 弹幕显示/轨道 | `app/overlay.py`、`app/danmu_engine.py` |
| 主链路/截图/AI 调度 | `main.py`（高风险，工单须单独授权） |
| 麦克风 | `app/mic_*.py` |
| 桌宠 | `app/pet/` + `app/main_state_mixin.py` + `app/web_api/pet.py` + `web/static/` |
| TTS / 读弹幕 | `app/danmu_tts.py`、`app/danmu_tts_playback.py`、`app/tts_providers.py`、`app/tts_catalog.py`、`app/tts_audio_utils.py`、`app/danmu_read_service.py` + `app/web_api/danmu_read.py` |
| 浮动面板 | `app/floating_panel_engine.py`、`app/floating_panel_overlay.py` |
| 烂梗弹幕 | `app/meme_barrage/` + `app/main_meme_mixin.py` + `app/web_api/meme_barrage.py` |
| 模型适配器 | `app/providers/`（base / adapters / registry / capabilities / constants） |
| 新业务子包 | 见附录 A「核心模块速查」 |

---

## 5. 文档更新规则

| 时机 | 更新 |
|------|------|
| 每个工单完成 | [../workorders/当前仓库状态.md](../workorders/当前仓库状态.md)（待 workorders/ 目录补建） |
| 发现范围外问题 | [../workorders/已知问题与后续事项.md](../workorders/已知问题与后续事项.md)（待 workorders/ 目录补建；只记录，不修） |
| 设计决策变更 | [../workorders/设计更新说明.md](../workorders/设计更新说明.md)（待 workorders/ 目录补建） |
| 新工单登记 | [../workorders/工单列表.md](../workorders/工单列表.md)（待 workorders/ 目录补建） |
| 交接给 Codex | 复制 [templates/Codex执行提示词/Codex执行提示词模板.md](templates/Codex执行提示词/Codex执行提示词模板.md)（待 templates/ 目录补建）或 [Codex工单交接模板.md](Codex工单交接模板.md)（待根级协作文档补建） |

模板目录：[templates/](templates/)（待 templates/ 目录补建；复制填空，勿直接当正式状态用）。

---

## 6. 完成报告规则

工单结束时**必须**提交完成报告，结构见 [templates/Codex完成报告/Codex完成报告模板.md](templates/Codex完成报告/Codex完成报告模板.md)（待 templates/ 目录补建），至少包含：

1. 修改摘要  
2. **修改的文件列表**（完整路径）  
3. 未修改的关键区域（证明未越界）  
4. 运行的命令  
5. 构建/测试结果  
6. 手动验证步骤与结果  
7. 风险与注意事项  
8. **发现但未处理的问题**（应已写入已知问题文档）  
9. 已更新的文档  
10. 建议下一个工单（可选，不擅自实现）

---

## 7. 验证规则

- **构建/测试通过 ≠ 功能可用**：必须按工单「手动验证步骤」在真实环境检查关键路径（见 [手动验收指南.md](手动验收指南.md)（待根级协作文档补建））。
- 能运行则必须运行（工单涉及代码时）：

```bash
pip install -r requirements.txt
```

**IDE / Agent 本地验证**：必须遵守 [IDE_AGENT_RULES.md](IDE_AGENT_RULES.md)（待根级协作文档补建）§10 分批低内存测试策略。**禁止**本地全量 pytest（`pytest`、`pytest tests`、`python -m pytest` 无文件参数、`python -m pytest tests/`）：全库 700+ 用例会占用大量内存，易导致 Windows 开发机卡顿。只跑与工单相关的 `tests/test_*.py`，每批 `-q -x`，失败即停；完成报告须含分批测试报告。

触达编排、Web API、`DanmuApp` 主链路时另跑：

```bash
python scripts/boundary_guard.py
```

> `scripts/boundary_guard.py` 是薄壳（仅 1 行 import），真实实现在 `scripts/boundary_guard/` 子包：`cli.py`、`runner.py`、`reporters.py`、`git_diff.py`、`source_parse.py`、`models.py`、`constants.py` + `rules/`（`web.py` / `request.py` / `pipeline.py` / `diagnostics.py` / `config.py` / `runtime.py` / `baseline.py` / `status.py`）。

- 提交前可参考附录 A 中的可选扩大批次（仍须 `-x`、逐批执行，不能替代全量）。
- **CI / 维护者全量**（Agent 禁止自动执行）：`python -m pytest tests/ -q`
- 纯文档工单：用 `git diff --name-only` 确认未改动业务代码；本项目**无** markdownlint / docs 专用检查命令。

---

## 8. 范围外问题处理

发现**不在当前工单范围内**的问题时：

1. **不要修复**（即使改动很小）  
2. **不要**在当次 PR 中「顺便」重构  
3. 使用 [templates/已知问题记录/已知问题记录模板.md](templates/已知问题记录/已知问题记录模板.md)（待 templates/ 目录补建）记入 [../workorders/已知问题与后续事项.md](../workorders/已知问题与后续事项.md)（待 workorders/ 目录补建）  
4. 在完成报告 §8 中引用问题 ID  
5. 由负责人在 [../workorders/工单列表.md](../workorders/工单列表.md)（待 workorders/ 目录补建）中**单独开后续工单**

需求不清楚时：**停止实现并向负责人提问**，禁止猜测业务逻辑或配置默认值。

文档与代码冲突时：**以 `main.py` 与 `app/` 为准**，并在已知问题或当前仓库状态中标注「文档待复核」。

---

## 9. 项目特定架构边界

以下约束**优先于** Agent 自行推断；详情见 [ai-project-context.md](ai-project-context.md)（待根级协作文档补建）与 [../docs/CONTRIBUTING_ARCHITECTURE.md](../docs/CONTRIBUTING_ARCHITECTURE.md)。

1. **线程**：截图、回复出队、Qt 对象在主线程；AI HTTP 在 `QThreadPool`；HTTP 写 Qt **必须**经 `WebConsoleBridge` 或 `QTimer.singleShot(0, ...)`。  
   - 截图 tick 间隔由 `_normal_recognition_interval_ms()` 决定（常见默认 **5s**，非硬编码 1s）。
   - `keyboard` 热键回调经 `_ToggleBridge` 到主线程。
   - 麦克风：`sounddevice.InputStream` 回调在 PortAudio 线程，通过 `app/mic_buffer.py:MicRingBuffer` 互传，主线程 `_poll_mic_utterance()` 消费。
   - TTS：`app/danmu_tts_playback.py` 的 `_play_worker` 在 `threading.Thread` 中发 `playback_finished` Qt 信号 — **跨线程**，违反本条；Codex 工单若触碰该文件，须改为 `QTimer.singleShot(0, ...)` 投递到主线程。

2. **主链路**：`_on_screenshot_timer` → … → `_consume_reply_queue` 不得随意改序或旁路；新增定时器/线程须同步 [../docs/main-pipeline-sequence.md](../docs/main-pipeline-sequence.md)。  

3. **场景代际 `scene_generation` 处理**：`_visual_reply_stale_reason()`（`app/main_request_context_mixin.py`）会丢弃 `scene_generation < current._scene_generation` 的回复，reason = `scene_generation_lagged`。新工单**不得**擅自关闭该检查。  

4. **Web API**：禁止在 `app/web_api/*` 中直接读 `danmu_app._…` 私有字段；使用 `DanmuApp` 公开 façade。  

5. **历史文档**：`.local-ai/` 内归档（`scratch/archive-phases/`、`reports/archive/`）仅作背景，**非**当前行为（含已移除 Qt 主窗、实时弹幕模式）。  

6. **UI 事实**：默认 `python main.py` → Web + pywebview + Overlay；`--qt-ui` / `--legacy-ui` / `DANMU_QT_UI=1` / `DANMU_WEB_CONSOLE=0` → `sys.exit(2)`。启动参数拒绝由 `app/main_launch.py:check_deprecated_launch_args()` 统一处理。  

7. **Overlay 窗口标志**：`app/overlay.py` 当前代码使用 `FramelessWindowHint | WindowStaysOnTopHint | Tool | BypassWindowManagerHint`（含 `Tool`）；Win32 扩展样式由 `app/win32_overlay_zorder.py:apply_overlay_exstyles` 应用 `WS_EX_LAYERED | WS_EX_TRANSPARENT`。修改前请读 `app/overlay.py:124-130` 当前代码确认。  

8. **视觉请求看门狗**：`VISUAL_INFLIGHT_WARN_SEC=45`、`VISUAL_INFLIGHT_RECOVER_SEC=48`、`REQUEST_WALL_CLOCK_SEC=45`、`MAX_IN_FLIGHT=1`、`MAX_MIC_IN_FLIGHT=1`、`CAPTURE_FAIL_WARN_THRESHOLD=3` 均定义在 `app/main_helpers.py`（非 `main.py`），由 `main.py` 通过 `from app.main_helpers import ...` 引入。`reason=inflight_watchdog_recover` 由 `_try_recover_stale_visual_inflight()` 触发；仅告警，不自动复位应用层 `ai_in_flight`。  

9. **场景简述已移除**：`scene_brief`、`app/memory/`、`scene_memory_interval_sec`、`prompt_dedup_window`（`memory_window` 别名）已于 2026-06 删除（`W-SCENEBRIEF-REMOVE-*`）。写文档/工单时**勿**把它们当作现行能力或配置键。  

10. **维护者登记表位置**：`docs/runtime-state-map.md`、`docs/main-pipeline-sequence.md`、`docs/final-architecture-baseline.md` 位于仓库 **`docs/` 根**（**不**在 `docs/core/`）；`boundary_guard` 依赖其路径，禁止移动。

---

## 10. 给 Codex 的最终提醒

- 你只执行**当前工单**，不是整个 ROADMAP。  
- 小步提交、小步验收；宁可少做，不可多做。  
- 完成报告 + 更新当前仓库状态是**交付的一部分**，不是可选项。  
- 范围外问题只记录，不修。  
- 不确定就停，就问。

### Codex 工作流文档索引

| 文档 | 用途 |
|------|------|
| [../workorders/README.md](../workorders/README.md)（待 workorders/ 目录补建） | 工作流目录说明 |
| [../workorders/工单列表.md](../workorders/工单列表.md)（待 workorders/ 目录补建） | 可执行小工单 backlog |
| [../workorders/当前仓库状态.md](../workorders/当前仓库状态.md)（待 workorders/ 目录补建） | 分支、测试、最近变更 |
| [手动验收指南.md](手动验收指南.md)（待根级协作文档补建） | 通用手动验收 |
| [Codex提示词手册.md](Codex提示词手册.md)（待根级协作文档补建） | 提示词与常见错误 |
| [Codex工单交接模板.md](Codex工单交接模板.md)（待根级协作文档补建） | 交接示例 |
| [../workorders/已知问题与后续事项.md](../workorders/已知问题与后续事项.md)（待 workorders/ 目录补建） | 范围外问题沉淀 |
| [../workorders/设计更新说明.md](../workorders/设计更新说明.md)（待 workorders/ 目录补建） | 设计变更记录 |
| [提示词上下文包.md](提示词上下文包.md)（待根级协作文档补建） | 复制给 AI 的上下文 |
| [templates/](templates/)（待 templates/ 目录补建） | 各类空白模板 |

---

## 附录 A. DanmuAI 技术速查

> 模块表、陷阱、环境变量；与 [ai-project-context.md](ai-project-context.md)（待根级协作文档补建）互补。  
> 本附录于 2026-06-21 全面校正，事实对齐 `app/` 源码、`requirements.txt`、`docs/` 实际目录。

### A.1 当前 UI 事实

- 默认 `python main.py` → Web 控制台 + pywebview + Qt Overlay/托盘
- **新功能仅加在** `web/static/` 与 `app/web_api/`（`routes.py` 注册）
- 已移除遗留 Qt 主窗；`--qt-ui` / `--legacy-ui` / `DANMU_QT_UI=1` / `DANMU_WEB_CONSOLE=0` → `sys.exit(2)`（由 `app/main_launch.py:check_deprecated_launch_args` 拒绝）
- Overlay (`app/overlay.py` + `app/danmu_engine.py`) 始终运行，与控制台 UI 无关
- pywebview 桌面壳由 `app/webview_shell.py` 拉起到**子进程**，与 Qt 主线程不在同一进程

### A.2 架构

```text
python main.py
├─ DanmuApp（main.py + app/main_*mixin.py，共 8 个 mixin）
│  └─ 单例 QObject，主链路、生命周期、Web façade、运行态宿主
├─ uvicorn 线程                 — app/web_console.py（127.0.0.1:18765）
├─ pywebview 子进程             — app/webview_shell.py（桌面壳）
├─ web/static/                  — 默认控制台 UI（index.html、app.js、warm-tokens.css）
├─ app/web_api/                 — 人格/模型/池/TTS/麦/桌宠/浮动面板/烂梗/更新/诊断 SSE 路由（routes.py 注册）
├─ app/providers/               — 模型适配器（doubao / openai / mimo / dashscope 等）
├─ app/pet/                     — 桌宠（窗口 + 状态 + 动画 + 弹幕，共 9 文件）
├─ TTS 子系统                   — app/danmu_tts.py + danmu_tts_playback.py + tts_providers.py + tts_catalog.py + tts_audio_utils.py + danmu_read_service.py
├─ app/meme_barrage/            — 烂梗弹幕（client / service / store / config / ai_select / runnable）
└─ DanmuOverlay（app/overlay.py）— Qt 透明置顶弹幕（始终启用）
```

**线程模型**（agent 容易搞错）：

- 截图在**主线程** `QTimer`（间隔由 `_normal_recognition_interval_ms()` 决定，常见默认 **5s**，非硬编码 1s）
- AI 请求在 `QThreadPool`（`MAX_IN_FLIGHT=1`，定义在 `app/main_helpers.py`）
- HTTP 线程写 Qt 对象**必须**走 `WebConsoleBridge` 信号或 `QTimer.singleShot(0, ...)` 到主线程
- pywebview 由 `app/webview_shell.py` 拉起到**子进程**，不是 Qt 主线程内的第二个 UI 线程
- `keyboard` 回调经 `_ToggleBridge` 到主线程
- 麦克风：`sounddevice.InputStream` 回调在 PortAudio 线程，通过 `app/mic_buffer.py:MicRingBuffer` 互传，主线程 `_poll_mic_utterance()` 消费
- TTS：`app/danmu_tts_playback._play_worker` 在 `threading.Thread` 中发 `playback_finished` Qt 信号（已知跨线程违规，详见 §9）

**扩展 API**：`app/web_api/routes.py` 在 `web_console` 上注册；人格/模型逻辑复用 `PersonaManager`、`TemplateManager`、`validate_model_config`

### A.3 核心模块速查

> 模块按职责分组；Codex 开工单前必须先在本表确认目标路径。  
> Mixin 共 8 个；`app/mic_*.py` 共 10 个（含 `app/web_api/mic_test.py` 路由）；其他新增子包（`pet/` / `danmu_tts*` / `tts_*` / `floating_panel_*` / `meme_barrage/` / `providers/`）2026-06-21 起被纳入治理。

#### A.3.1 启动与单例

| 模块 | 职责 |
|------|------|
| `main.py` | 入口；装配 `DanmuApp`；`from app.main_helpers import ...` 引入看门狗常量；`_on_screenshot_timer` 触发主链路 |
| `app/main_helpers.py` | 纯辅助：`VISUAL_INFLIGHT_WARN_SEC=45`、`VISUAL_INFLIGHT_RECOVER_SEC=48`、`REQUEST_WALL_CLOCK_SEC=45`、`MAX_IN_FLIGHT=1`、`MAX_MIC_IN_FLIGHT=1`、`CAPTURE_FAIL_WARN_THRESHOLD=3` + `BatchTracker` + `density_right_target` / `queue_capacity` / `reply_request_id` 等纯函数 |
| `app/main_launch.py` | 启动参数解析：`check_deprecated_launch_args` / `web_launch_mode_from_argv` / `global_exception_hook` / `show_startup_notice_if_needed` |
| `app/main_launch_mixin.py` | `DanmuAppLaunchMixin`：启动编排 |
| `app/main_mic_probe.py` | 麦克风启动探测辅助 |

#### A.3.2 DanmuApp Mixin（共 8 个）

| 模块 | 职责 |
|------|------|
| `app/main_lifecycle_mixin.py` | 生命周期、错误处理、`Translator.set_language()`（行 71）、`MAX_CONSECUTIVE_FAILURES=5`、`start/stop/quit` |
| `app/main_request_context_mixin.py` | request meta、RTT、`_visual_reply_stale_reason`（`scene_generation_lagged`）、`_estimated_reply_gap_ms`（100/120/200/500/1000ms）、密度/队列辅助 |
| `app/main_display_mixin.py` | live status、overlay/floating panel/pet 显隐、测试弹幕注入 |
| `app/main_mic_mixin.py` | 麦克风链路、mic insert、读弹幕 probe/config façade（`MIC_POLL_MS=600`、`MIC_POLL_PHASE_MS=250`） |
| `app/main_meme_mixin.py` | 烂梗弹幕 Mixin |
| `app/main_state_mixin.py` | 运行态、桌宠相关 state 维护 |
| `app/main_web_facade_mixin.py` | 对外 Web façade（供 `app/web_api/*` 调用） |

#### A.3.3 视觉与弹幕

| 模块 | 职责 |
|------|------|
| `app/danmu_engine.py` | 多轨道 Track；`_pick_track` 3 段加权随机（idle → `random.choice`；acceptable → `random.choices(weights=1/(1+count))`；满载 → `tail_edge + random.uniform(50, 250)`） |
| `app/overlay.py` | Qt 透明置顶渲染；`FramelessWindowHint | WindowStaysOnTopHint | Tool | BypassWindowManagerHint`；Win32 exstyle 由 `app/win32_overlay_zorder.py` 应用 `WS_EX_LAYERED | WS_EX_TRANSPARENT` |
| `app/floating_panel_engine.py` + `app/floating_panel_overlay.py` | 浮动面板引擎与渲染（与 Overlay 并存的另一图层） |
| `app/live_freshness.py` | 截图退避、`build_local_fallback_batch`、`is_model_slow`（实时模式 TTL/节奏预触发**已移除**） |
| `app/reply_parser.py` | AI 回复 JSON 解析与标准化 |
| `app/reply_queue.py` | `AIReplyFIFOBuffer`（`max_items=8`）+ 自适应延迟 100–1000ms（由 `_estimated_reply_gap_ms` 计算） |
| `app/danmu_engine_dedup.py` | 去重：`deque(30)` + `recent_exact_set` + Levenshtein `dedup_threshold=0.5` |
| `app/image_compress.py` | PIL + JPEG + Base64，`max_width=768`、`quality=85`（运行时由 `image_max_width` / `image_quality` 配置覆盖），**无临时文件** |

#### A.3.4 持久化与运行态

| 模块 | 职责 |
|------|------|
| `app/config_store.py` | SQLite `%APPDATA%/DanmuAI/config.db` + `.key`；Fernet 加密；`PRAGMA journal_mode=WAL`、`busy_timeout=5000`；`self._write_lock = threading.Lock()`（**非** `RLock`，递归会死锁） |
| `app/danmu_pool.py` | 自定义公式化弹幕库；SQLite 表 `custom_danmu_pool_entries`（`CUSTOM_DANMU_POOL_MAX=20000`）；同屏补足与 `normalize_reply_batch` 填充 |
| `app/lifetime_stats.py` | 持久累计统计（弹幕/运行时长/Token），`stop()` 时并入 |
| `app/session_run_log.py` | 场次记录；`session_runs` 表（最近 100 条） |

#### A.3.5 模型与适配器

| 模块 | 职责 |
|------|------|
| `app/ai_client.py` | 双 API：`doubao` → `/responses` 流式；`openai` → `/chat/completions` SSE；请求固定注入 `thinking: {"type":"disabled"}`（`THINKING_DISABLED` 定义在 `app/providers/constants.py`）；流式只收集 `content` |
| `app/providers/` | `__init__.py` / `registry.py` / `capabilities.py` / `constants.py` + `adapters/{base.py, default_openai.py, mimo.py, __init__.py}` |
| `app/model_providers.py` | **9 个服务商预设**（`doubao` / `dashscope` / `zai` / `zhipu` / `moonshot` / `siliconflow` / `mimo` / `custom_openai` / `custom_doubao`）+ `guess_provider_from_endpoint` |
| `app/model_catalog.py` | **5 平台**（`doubao` / `dashscope` / `siliconflow` / `mimo` / `zai`）；定价元数据用于 Web 视觉模型选择器 |

#### A.3.6 麦克风子系统（10 个文件）

| 模块 | 职责 |
|------|------|
| `app/mic_service.py` | 模式门面；`mic_mode_enabled(config)` / `MicService` / `mic_window_sec_from_config` |
| `app/mic_buffer.py` | `MicRingBuffer`：PortAudio 线程 ↔ 主线程互传 PCM |
| `app/mic_capture.py` | `sounddevice.InputStream` 回调写入 `MicRingBuffer`；`try_snapshot_pcm_ms` 访问 buffer 内部 |
| `app/mic_encode.py` | `pcm_to_wav_data_uri` → `data:audio/wav;base64,...` |
| `app/mic_utterance.py` | RMS 语音端点检测（无 VAD 库），4 状态机（IDLE / SPEAKING / SILENCE_PENDING / COOLDOWN）；含回滞阈值 |
| `app/mic_prompt.py` | 麦克风插入提示词组装 |
| `app/mic_orchestrator.py` | 多设备/多状态编排 |
| `app/mic_test.py` | 麦克风自检（控制台调用） |
| `app/mic_test_send.py` | 麦克风自检发送路径 |
| `app/web_api/mic_test.py` | `/api/mic/test`、`/api/mic/devices`、`/api/mic/test-send` 路由 |

#### A.3.7 桌宠子系统

| 模块 | 职责 |
|------|------|
| `app/pet/pet_window.py` | 桌宠窗口（透明 / 拖拽 / 上下文菜单） |
| `app/pet/pet_state.py` | 状态机 |
| `app/pet/pet_animation_mapper.py` | 动作 → 帧序列 |
| `app/pet/pet_barrage.py` | 桌宠弹幕 |
| `app/pet/pet_prompt.py` | 桌宠指令 prompt 组装 |
| `app/pet/pet_command_service.py` | 指令派发 |
| `app/pet/pet_assets.py` | 内置资源 + 用户导入资源管理 |
| `app/pet/pet_facade.py` | 对外 façade（供 `app/web_api/pet.py` 调用） |
| `app/web_api/pet.py` | 桌宠 REST 路由（`/api/pet/*`） |

#### A.3.8 TTS / 读弹幕

| 模块 | 职责 |
|------|------|
| `app/danmu_tts.py` | TTS 文本选择 / 状态 |
| `app/danmu_tts_playback.py` | 播放 worker（**已知跨线程 Qt 信号**） |
| `app/tts_providers.py` | TTS 提供方实现（火山 / 阿里等） |
| `app/tts_catalog.py` | TTS 音色目录（Web 选择器） |
| `app/tts_audio_utils.py` | PCM/WAV 工具 |
| `app/danmu_read_service.py` | 读弹幕 probe service（**当前在主线程跑 HTTP**，慢） |
| `app/web_api/danmu_read.py` | `/api/danmu-read/*` 路由 |

#### A.3.9 烂梗子系统

| 模块 | 职责 |
|------|------|
| `app/meme_barrage/client.py` | 远端客户端（默认 `verify_ssl=False`，**仅内网**） |
| `app/meme_barrage/service.py` | 业务编排 |
| `app/meme_barrage/store.py` | 烂梗库 SQLite |
| `app/meme_barrage/config.py` | 配置 |
| `app/meme_barrage/ai_select.py` | AI 选梗 |
| `app/meme_barrage/runnable.py` | 后台 runnable |
| `app/web_api/meme_barrage.py` | `/api/meme-barrage/*` 路由 |

#### A.3.10 杂项

| 模块 | 职责 |
|------|------|
| `app/translations.py` + `app/translations_*.py` | 中英翻译表；`Translator.set_language()` 在 `DanmuApp.__init__` 通过 lifecycle mixin 调用 |
| `app/api_probe.py` | API 探活；发 `thinking: disabled` |
| `app/api_schedule.py` | API 调度节流（受 `DANMU_MIN_API_INTERVAL_MS` 控制，默认 800ms） |
| `app/snipper.py` | `resolve_capture_rect`：当 `region_w/h > 0` 按屏内相对坐标裁剪；`null_pixmap` reason 触发日志 |
| `app/single_instance.py` | 单实例锁（`SingleInstanceGuard`）；激活失败需主动 `sys.exit` |
| `app/win32_overlay_zorder.py` | Overlay Win32 exstyle 应用 |
| `app/web_console.py` | FastAPI/uvicorn 服务端（`127.0.0.1:18765`） |
| `app/webview_shell.py` | pywebview 桌面壳（`_LOAD_TIMEOUT_SEC=25`，WebView2 冷启动可能 >12s） |
| `app/web_api/routes.py` | 主路由注册（≈40 条路由） |
| `app/supabase_config.py` + `app/supabase_*` | Supabase 配置（`DANMU_SUPABASE_URL` / `DANMU_SUPABASE_ANON_KEY`） |
| `app/velopack_runtime.py` | Velopack 运行时（`reason=import_error` 处理） |
| `app/uninstall_service.py` | 卸载标记；读 `%APPDATA%` |
| `app/font_registry.py` | 字体目录 `%APPDATA%/DanmuAI/fonts` |
| `app/bundle_paths.py` | PyInstaller / Velopack 资源路径 |

### A.4 运行与测试

```bash
pip install -r requirements.txt
python main.py                         # Web + pywebview + Overlay
python main.py --web-browser           # 系统浏览器打开控制台
python main.py --web-launch=browser    # 等价于 --web-browser
```

依赖摘要（来自 `requirements.txt`，全部 pin 在 major 内）：

| 类别 | 包 |
|------|----|
| 桌面 / 网络 | `PyQt6>=6.6,<7`、`httpx[http2]>=0.27,<1`、`keyboard>=0.13,<1`、`websockets>=12.0,<14` |
| 存储 / 安全 | `cryptography>=41.0,<44`、`python-Levenshtein>=0.23,<1` |
| 图像 | `Pillow>=10.0,<12` |
| 音频 | `sounddevice>=0.4.6,<1`、`numpy>=1.24,<3` |
| Web / ASGI | `fastapi>=0.115.0,<1`、`python-multipart>=0.0.20,<0.1`、`uvicorn[standard]>=0.32.0,<1`、`pywebview>=5.0,<6` |
| AI SDK | `volcengine-python-sdk[ark]>=5.0,<6`、`dashscope>=1.24.6,<2` |
| 打包 | `velopack>=1.2.0,<2` |

#### A.4.1 IDE Agent 分批验证（强制，见 §10 与 IDE_AGENT_RULES §10）

- 只跑与改动相关的 `tests/test_*.py`，每批 `-q -x`；禁止 `python -m pytest tests/`。
- 原因与映射表：[IDE_AGENT_RULES.md](IDE_AGENT_RULES.md)（待根级协作文档补建）§10（**禁止本地全量**，避免内存耗尽与机器卡顿）。

#### A.4.2 可选扩大批次（逐批 `-x` 执行，不能替代全量）

```bash
python -m pytest tests/test_reply_parser.py tests/test_p0_main_flow.py tests/test_danmu_engine.py tests/test_config_store.py tests/test_ai_client.py -q -x
python -m pytest tests/test_web_console.py tests/test_web_persona_api.py tests/test_web_custom_models.py tests/test_image_compress.py tests/test_ui_mode.py -q -x
python -m pytest tests/test_reply_queue.py tests/test_reply_enqueue.py tests/test_reply_contract.py tests/test_request_timing_service.py tests/test_request_scheduling.py -q -x
python -m pytest tests/test_mic_mode.py tests/test_mic_utterance.py tests/test_mic_capture.py tests/test_mic_orchestrator.py tests/test_mic_insert.py -q -x
python -m pytest tests/test_pet_lifecycle.py tests/test_pet_window_drag.py tests/test_pet_assets.py tests/test_pet_barrage_config.py tests/test_pet_command_service.py -q -x
python -m pytest tests/test_meme_barrage_api.py tests/test_meme_barrage_runtime.py tests/test_meme_barrage_client.py tests/test_meme_ai_select_smoke.py -q -x
python -m pytest tests/test_danmu_tts.py tests/test_tts_catalog.py tests/test_danmu_read_api.py tests/test_floating_panel_engine.py tests/test_status_floating_panel.py -q -x
python -m pytest tests/test_provider_adapters.py tests/test_model_providers.py tests/test_model_catalog.py tests/test_scene_generation_version.py tests/test_inflight_recovery.py -q -x
```

#### A.4.3 CI / 维护者全量（IDE Agent 禁止自动执行）

```bash
python -m pytest tests/ -q
python -m pytest tests/ -v --tb=short
```

#### A.4.4 测试约定

- **临时目录**：项目根 `.pytest_tmp/`（`conftest.py` 重定向 `TMP`/`TEMP`，避免 `%TEMP%\pytest-of-*` 权限问题；根 `conftest.py` 先执行，`tests/conftest.py` 再细分 per-test 子目录）
- **共享假对象**：`tests/fakes.py`（`FakeTimer`、`FakeEngine`、`FakeConfig`、`FakeLogger` 等）
- **最小 DanmuApp**：`DanmuApp.__new__(DanmuApp)` + `bind_minimal_danmu_app(app, **overrides)`（`tests/conftest.py`）
- **勿** `from test_p0_main_flow import ...`（无包前缀 collection 时报 `ModuleNotFoundError`）
- **轨道选择**：`_pick_track` 为加权随机，需 `monkeypatch` `random.choices` 才能断言确定性轨道
- **Overlay 单测**：需 `QApplication` + `overlay.show()` + `processEvents()`；`_target_interval_ms()` 在不可见时返回 `0`
- **pytest `basetemp`**：`pytest.ini` 未设；实际目录取自 `tests/conftest.py` 的 `pytest_configure`

CI：`.github/workflows/ci.yml` — Python 3.12 `windows-latest`，Ruff + 全量 pytest；另有 `pack-windows` Job 跑 Velopack 打包。

### A.5 关键陷阱

#### A.5.1 存储与并发

- **加密锁死**：丢失 `%APPDATA%/DanmuAI/.key` → 已加密 Key 不可恢复
- **`ConfigStore._write_lock`** 是非可重入 `threading.Lock`（**非** `RLock`）；任何**递归回调**内再次获取会自死锁。新工单若需在锁内调用其他 store 方法，须先确认调用链无持锁递归
- **公式化弹幕库**：Web 页「公式化弹幕库」管理自定义短句；`danmu_pool_use_custom` 开启且 `min_on_screen`>0（默认 5，**0** 关闭）时同屏补足生效；AI 条数不足与本地轻量兜底从自定义池去重补齐；句库经 `/api/danmu-pool/custom`，开关与 `min_on_screen` 经 `/api/danmu-pool/settings`，**不进** `PUT /api/config`
- **`get_custom_danmu_pool_for_store`** 不分页读全表（默认上限 20000）；在主线程调用时窗口化渲染可能 hang
- **`set_custom_danmu_pool_for_store`** 当前为全 DELETE+INSERT，不分批；大批量替换需自行分块

#### A.5.2 视觉与弹幕

- **弹幕截断**：AI 上屏默认 15 中文字 / 40 英文字 + `...`；公式化弹幕（自定义库、烂梗）完整展示
- **去重**：`deque(30)` + `recent_exact_set` + Levenshtein `dedup_threshold=0.5`
- **失败退避**：连续 5 次暂停（`MAX_CONSECUTIVE_FAILURES=5`）；401/403/402 立即暂停
- **输出 token 下限**：`resolve_danmu_max_output_tokens` 下限 **512**（运行时固定关闭 thinking，忽略 `use_thinking` 开启）
- **思考模式**：豆包/OpenAI 请求均发 `thinking: {"type":"disabled"}`；勿把 `reasoning_content` 当弹幕；MiMo 未关闭时易「AI 返回为空」
- **小米 MiMo**：预设 `https://api.xiaomimimo.com/v1`（OpenAI 兼容）；目录模型仅 `mimo-v2.5`（MiMo-V2.5）；**开麦**：豆包 Responses `input_audio`+`audio_url`；MiMo **仅 mimo-v2.5** 走 Chat Completions `input_audio`+`input_audio.data`（data URI）
- **识图区域**：默认 `screen_index` 全屏；`region_w/h > 0` 时 [`app/snipper.py`](app/snipper.py) 按**屏内相对坐标**裁剪（不是绝对桌面坐标）。Web 经 `POST/GET /api/capture-region/*` 鼠标框选，**勿**把 `region_*` 写入 `PUT /api/config`
- **Overlay 窗口标志**：`FramelessWindowHint | WindowStaysOnTopHint | Tool | BypassWindowManagerHint`（含 `Tool`，当前代码保留）；Win32 exstyle 由 `app/win32_overlay_zorder.py` 应用 `WS_EX_LAYERED | WS_EX_TRANSPARENT`
- **无 Qt 主窗**：`setQuitOnLastWindowClosed(False)`；托盘退出 → `DanmuApp.quit()`
- **`scene_generation` 过时回复被丢弃**：见 §9 第 3 条

#### A.5.3 Web / 进程

- **Web 写配置**：`PUT /api/config` → bridge 信号 → 主线程 `apply_config_patch`；**勿在 HTTP 线程直接改 Qt 对象**
- **GET 自定义模型**：返回掩码 `apiKey`
- **Web Console Bearer Token**：写接口需要 `Authorization: Bearer <token>`（启动时 `secrets.token_urlsafe(24)` 生成）
- **WebView2 冷启动**：可能超过 12s；`webview_shell.py` 设 `_LOAD_TIMEOUT_SEC=25` / `_FROZEN_LOAD_TIMEOUT_SEC=25`
- **单实例**：`SingleInstanceGuard` 激活失败需在 main 中主动 `sys.exit`，否则会并发启动
- **启动参数拒绝**：`--qt-ui` / `--legacy-ui` / `DANMU_QT_UI=1` / `DANMU_WEB_CONSOLE=0` 全部由 `app/main_launch.py:check_deprecated_launch_args()` 拒绝并 `sys.exit(2)`

#### A.5.4 麦克风 / TTS

- **跨线程 Qt 信号（已知违规）**：`app/danmu_tts_playback._play_worker` 在 `threading.Thread` 中发 `playback_finished` Qt 信号 — 须改用 `QTimer.singleShot(0, ...)` 投递到主线程
- **TTS HTTP 走主线程**：`danmu_read_service.run_probe` 在主线程发起 HTTP，慢请求会卡 UI
- **`mic_capture.try_snapshot_pcm_ms`** 访问 `MicRingBuffer._lock` / `_data` 私有字段；改 buffer 内部结构时必须同步该调用点
- **PortAudio 设备不可用**：`mic_capture` 记录 `reason=preferred_device_unavailable`，启动期不抛错

#### A.5.5 模型 / 适配器

- **平台数量**：当前 **5** 个平台（doubao / dashscope / siliconflow / mimo / zai）；选择器 UI 与 pricing 元数据均按此枚举
- **预设数量**：当前 **9** 个服务商预设（含 `zai`），加 2 个自定义 = 11 项；Web 模型选择器按此渲染
- **MiMo 与 DashScope**：MiMo 是 OpenAI 兼容自定义 provider；DashScope 是阿里官方 SDK（`dashscope` 包）；`app/providers/adapters/` 当前实现 `default_openai.py` 与 `mimo.py`，其他 provider 复用 default_openai 走 OpenAI 兼容接口

### A.6 环境变量速查

| 变量 | 作用 |
|------|------|
| `DANMU_API_SCHEDULE_DEBUG=1` | API 调度日志（`app/api_schedule.py`） |
| `DANMU_MIN_API_INTERVAL_MS` | 防 API 冷启动连打（默认 800，单位 ms） |
| `DANMU_REPLY_PIPELINE_LOG=1` | 主链路 reply pipeline 日志（`app/main_request_context_mixin.py`） |
| `DANMU_IMAGE_METRICS=1` | 压缩指标 debug 日志（`app/image_metrics.py`） |
| `DANMU_DEDUP_PROFILE=1` | 去重统计 `/api/status.dedup_profile`（`app/danmu_engine_dedup.py`） |
| `DANMU_OVERLAY_PROFILE=1` | Overlay 渲染 profile 日志（`app/overlay.py`） |
| `DANMU_STARTUP_TRACE=1` | 启动链路 trace 日志（`app/startup_trace.py`） |
| `DANMU_SUPABASE_URL` / `DANMU_SUPABASE_ANON_KEY` | Supabase 配置覆盖（`app/supabase_config.py`） |
| `DANMU_QT_UI=1` | 启动即拒绝（与 `--qt-ui` 同效，`app/main_launch.py`） |
| `DANMU_WEB_CONSOLE=0` | 启动即拒绝（`app/main_launch.py`） |
| `DANMU_WEB_LAUNCH=browser` | 等同 `--web-browser`（`app/main_launch.py`） |
| `ARK_API_KEY` / `DANMU_API_KEY` | 探测脚本读取（`scripts/test_thinking_model_probe.py`） |
| `DANMU_MEMORY_SOAK=1` | 内存压力测试（`tests/test_danmu_memory_stability.py`） |
| `APPDATA` | Windows 上 `%APPDATA%` 决定配置 / 字体 / 卸载目录 |

### A.7 排障日志（`reason=`）

主链路 structured warning / info，见应用日志。`reason=` 字符串实际取值集合（grep 自 `app/`）：

| `reason` / 场景 | 含义 |
|-----------------|------|
| `null_pixmap` | 截图无效（null / `isNull()` / 零尺寸），本 tick 不递增 `screenshot_id`、不触发 API（`app/snipper.py:187,227`） |
| `scene_generation_lagged` | 回复 `scene_generation` < current，丢弃（`app/main_request_context_mixin.py:74`） |
| `request_meta_missing` | 回复到达时无 `_pending_request_meta`（`app/main_request_context_mixin.py:60`） |
| `timing_not_started` | `consume_timing` 时无对应 `mark_started`（`app/main_request_context_mixin.py:196`） |
| `inflight_watchdog_recover` | 视觉 `ai_in_flight` 超过 `VISUAL_INFLIGHT_RECOVER_SEC=48` 强制释放（`app/main_request_context_mixin.py:139`） |
| `empty_parse` | AI 有响应但解析后无弹幕（`app/meme_barrage/runnable.py:169` / `app/application/danmu_diagnostics.py:23`） |
| `import_error` | Velopack 启动 import 失败，跳过（`app/velopack_runtime.py:22`） |
| `preferred_device_unavailable` | 麦克风首选设备不可用（`app/mic_capture.py:189`） |

历史 reason（`invalid_pixmap` / `inflight_watchdog` / `_pending_request_meta`）已被上面的实现替换；查阅旧日志时可按本表回溯。

RTT / `_pending_request_meta` 键：`{request_round}:{screenshot_id}:{scene_generation}`，由 `app/main_helpers.py:reply_request_id` 组装。

### 排障日志（`reason=`）

主链路 structured warning / info，见应用日志（配合 `DANMU_API_SCHEDULE_DEBUG`）：

| `reason` / 场景 | 含义 |
|-----------------|------|
| `invalid_pixmap` | 截图无效（null / `isNull()` / 零尺寸），本 tick 不递增 `screenshot_id`、不触发 API |
| `empty_parse` | AI 有响应但解析后无弹幕 |
| `request_meta_missing` | 回复到达时无 `_pending_request_meta` |
| `timing_not_started` | `consume_timing` 时无对应 `mark_started` |
| `inflight_watchdog` | 视觉 `ai_in_flight` 超过 `VISUAL_INFLIGHT_WARN_SEC`（45s，**`main.py` 模块常量**，非 `DanmuApp` 字段）；仅告警，不自动复位 |

RTT / `_pending_request_meta` 键：`{request_round}:{screenshot_id}:{scene_generation}`。

### A.8 改动决策树

```text
配置、人格、模型、日志 UI  → web/static/ + app/web_api/
弹幕显示、轨道、性能       → app/overlay.py + app/danmu_engine.py + app/floating_panel_*.py
麦克风、语音               → app/mic_*.py（含 mic_buffer.py / mic_orchestrator.py / mic_test*.py）
桌宠                       → app/pet/ + app/main_state_mixin.py + app/web_api/pet.py + web/static/
TTS / 读弹幕               → app/danmu_tts*.py + app/tts_*.py + app/danmu_read_service.py + app/web_api/danmu_read.py
烂梗                       → app/meme_barrage/ + app/main_meme_mixin.py + app/web_api/meme_barrage.py
模型适配器                 → app/providers/
主链路/截图/AI 调度        → main.py（高风险，工单须单独授权）
视觉稿                     → prototype/Qwen_*（Web only）
```

视觉规范：`prototype/Qwen_markdown_20260525_4vyxmv819.md`、`prototype/Qwen_html_20260524_481u8vlmv.html`

### A.9 技术文档索引

> 所有路径从仓库根解析（AGENTS.md 位于仓库根）。  
> 标注「**待根级协作文档补建**」的入口尚未创建，仅作为后续恢复治理流程的占位。

- [ai-project-context.md](ai-project-context.md)（待根级协作文档补建）— 对话式 AI / Agent 统一入口（阅读顺序与边界）
- [../docs/README.md](../docs/README.md) — 文档索引
- [../docs/core/ARCHITECTURE.md](../docs/core/ARCHITECTURE.md) — 架构总览
- [../docs/CONTRIBUTING_ARCHITECTURE.md](../docs/CONTRIBUTING_ARCHITECTURE.md) — 贡献边界与 Boundary Guard
- [../docs/core/MAIN_PIPELINE.md](../docs/core/MAIN_PIPELINE.md) — 主链路（普通模式）
- [../docs/core/RUNTIME_STATE.md](../docs/core/RUNTIME_STATE.md) — 运行态与快照
- [../docs/core/BOUNDARY_GUARD.md](../docs/core/BOUNDARY_GUARD.md) — `scripts/boundary_guard.py`（+ `scripts/boundary_guard/` 子包）
- [../docs/features/WEB_CONSOLE.md](../docs/features/WEB_CONSOLE.md) — Web API 与页面地图
- [../docs/operations/ROADMAP.md](../docs/operations/ROADMAP.md) — ROADMAP（不进入工单授权即不得实现）
- 维护者登记：`docs/runtime-state-map.md`、`docs/main-pipeline-sequence.md`、`docs/final-architecture-baseline.md`（位于 **`docs/` 根**，**非** `docs/core/`；`boundary_guard` 依赖其路径，禁止移动或重命名）
- 文档与源码不一致时，以 `main.py` 与 `app/` 源码为准
