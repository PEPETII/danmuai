# AGENTS.md — DanmuAI

> **对话式 AI / Codex / IDE Agent：** 先读本文件 **§1–§10**（协作与边界），再读 [docs/agent/ai-project-context.md](docs/agent/ai-project-context.md)（技术上下文与阅读顺序）。附录 A 为 DanmuAI 技术速查。

---

## 1. 项目协作原则

- **一次只做一个小工单**：每个工单应在 5–10 分钟内可手动验收；范围过大时必须由负责人拆单。
- **工单驱动**：开工前必须能从 [docs/workflow/工单列表.md](docs/workflow/工单列表.md) 或工单交接文档中读到工单 ID、目标、允许区、禁止区、验收标准。
- **文档与代码分工**：技术细节以 `main.py` 与 `app/` 源码为准；协作流程以本文件与 [docs/workflow/README.md](docs/workflow/README.md) 为准。
- **不自由发挥架构**：不得在未获工单授权的情况下引入新分层、新包结构或大规模重构。
- **负责人补充优先**：标有「待项目负责人补充」的字段不得由 Codex 根据猜测填写业务需求。

---

## 2. Codex 执行边界

Codex / IDE Agent **只执行当前工单**，不得：

1. 实现未来工单或 [docs/operations/ROADMAP.md](docs/operations/ROADMAP.md) 中尚未拆单的功能
2. 顺手重构与工单无关的模块
3. 自行决定新架构或新依赖
4. 修改工单「禁止修改的区域」所列路径
5. 把 [docs/archive/](docs/archive/) 中的历史设计当作当前行为

开工前**必须阅读**（按工单类型选读）：

| 优先级 | 文件 |
|--------|------|
| P0 | 本文件 §1–§10、[docs/workflow/当前仓库状态.md](docs/workflow/当前仓库状态.md)、当前工单正文 |
| P0 技术 | [docs/agent/ai-project-context.md](docs/agent/ai-project-context.md) |
| P1 改代码 | [docs/CONTRIBUTING_ARCHITECTURE.md](docs/CONTRIBUTING_ARCHITECTURE.md)、[docs/core/MAIN_PIPELINE.md](docs/core/MAIN_PIPELINE.md) |
| P1 改 Web/API | [docs/features/WEB_CONSOLE.md](docs/features/WEB_CONSOLE.md) |

---

## 3. 单工单规则

每个工单必须包含（见 [docs/templates/工单/工单模板.md](docs/templates/工单/工单模板.md)）：

- 工单 ID、标题、背景、目标
- **允许修改的区域**（路径列表，宜小）
- **禁止修改的区域**（路径列表，宜全）
- 需求、**非目标**（明确不包含什么）
- **验收标准**（可检查、可判定通过/不通过）
- **手动验证步骤**（5–10 分钟可完成）
- 完成后必须更新的文档列表

工单完成后必须：

1. 按 [docs/templates/Codex完成报告/Codex完成报告模板.md](docs/templates/Codex完成报告/Codex完成报告模板.md) 输出完成报告
2. 更新 [docs/workflow/当前仓库状态.md](docs/workflow/当前仓库状态.md)
3. 在 [docs/workflow/工单列表.md](docs/workflow/工单列表.md) 中将该工单标为已完成（或交由负责人更新）

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

---

## 5. 文档更新规则

| 时机 | 更新 |
|------|------|
| 每个工单完成 | [docs/workflow/当前仓库状态.md](docs/workflow/当前仓库状态.md) |
| 发现范围外问题 | [docs/workflow/已知问题与后续事项.md](docs/workflow/已知问题与后续事项.md)（只记录，不修） |
| 设计决策变更 | [docs/workflow/设计更新说明.md](docs/workflow/设计更新说明.md) |
| 新工单登记 | [docs/workflow/工单列表.md](docs/workflow/工单列表.md) |
| 交接给 Codex | 复制 [docs/templates/Codex执行提示词/Codex执行提示词模板.md](docs/templates/Codex执行提示词/Codex执行提示词模板.md) 或 [docs/agent/Codex工单交接模板.md](docs/agent/Codex工单交接模板.md) |

模板目录：[docs/templates/](docs/templates/)（复制填空，勿直接当正式状态用）。

---

## 6. 完成报告规则

工单结束时**必须**提交完成报告，结构见 [docs/templates/Codex完成报告/Codex完成报告模板.md](docs/templates/Codex完成报告/Codex完成报告模板.md)，至少包含：

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

- **构建/测试通过 ≠ 功能可用**：必须按工单「手动验证步骤」在真实环境检查关键路径（见 [docs/agent/手动验收指南.md](docs/agent/手动验收指南.md)）。
- 能运行则必须运行（工单涉及代码时）：

```bash
pip install -r requirements.txt
```

**IDE / Agent 本地验证**：必须遵守 [docs/IDE_AGENT_RULES.md](docs/IDE_AGENT_RULES.md) §10 分批低内存测试策略；**禁止**本地执行 `pytest`、`pytest tests`、`python -m pytest`（无文件参数）或 `python -m pytest tests/`。每批须 `-x`，失败即停；完成报告须含分批测试报告。

触达编排、Web API、`DanmuApp` 主链路时另跑：

```bash
python scripts/boundary_guard.py
```

- 提交前可参考附录 A 中的可选扩大批次（仍须 `-x`、逐批执行，不能替代全量）。
- **CI / 维护者全量**（Agent 禁止自动执行）：`python -m pytest tests/ -q`
- 纯文档工单：用 `git diff --name-only` 确认未改动业务代码；本项目**无** markdownlint / docs 专用检查命令。

---

## 8. 范围外问题处理

发现**不在当前工单范围内**的问题时：

1. **不要修复**（即使改动很小）  
2. **不要**在当次 PR 中「顺便」重构  
3. 使用 [docs/templates/已知问题记录/已知问题记录模板.md](docs/templates/已知问题记录/已知问题记录模板.md) 记入 [docs/workflow/已知问题与后续事项.md](docs/workflow/已知问题与后续事项.md)  
4. 在完成报告 §8 中引用问题 ID  
5. 由负责人在 [docs/workflow/工单列表.md](docs/workflow/工单列表.md) 中**单独开后续工单**

需求不清楚时：**停止实现并向负责人提问**，禁止猜测业务逻辑或配置默认值。

文档与代码冲突时：**以 `main.py` 与 `app/` 为准**，并在已知问题或当前仓库状态中标注「文档待复核」。

---

## 9. 项目特定架构边界

以下约束**优先于** Agent 自行推断；详情见 [docs/agent/ai-project-context.md](docs/agent/ai-project-context.md) 与 [docs/CONTRIBUTING_ARCHITECTURE.md](docs/CONTRIBUTING_ARCHITECTURE.md)。

1. **线程**：截图、回复出队、Qt 对象在主线程；AI HTTP 在 `QThreadPool`；HTTP 写 Qt **必须**经 `WebConsoleBridge` 或 `QTimer.singleShot(0, ...)`。  
2. **主链路**：`_on_screenshot_timer` → … → `_consume_reply_queue` 不得随意改序或旁路；新增定时器/线程须同步 [docs/main-pipeline-sequence.md](docs/main-pipeline-sequence.md)。  
3. **Web API**：禁止在 `app/web_api/*` 中直接读 `danmu_app._…` 私有字段；使用 `DanmuApp` 公开 façade。  
4. **历史文档**：`docs/archive/` 仅作背景，**非**当前行为（含已移除 Qt 主窗、实时弹幕模式）。  
5. **UI 事实**：默认 `python main.py` → Web + pywebview + Overlay；`--qt-ui` / `DANMU_WEB_CONSOLE=0` → `sys.exit(2)`。

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
| [docs/workflow/README.md](docs/workflow/README.md) | 工作流目录说明 |
| [docs/workflow/工单列表.md](docs/workflow/工单列表.md) | 可执行小工单 backlog |
| [docs/workflow/当前仓库状态.md](docs/workflow/当前仓库状态.md) | 分支、测试、最近变更 |
| [docs/agent/手动验收指南.md](docs/agent/手动验收指南.md) | 通用手动验收 |
| [docs/agent/Codex提示词手册.md](docs/agent/Codex提示词手册.md) | 提示词与常见错误 |
| [docs/agent/Codex工单交接模板.md](docs/agent/Codex工单交接模板.md) | 交接示例 |
| [docs/workflow/已知问题与后续事项.md](docs/workflow/已知问题与后续事项.md) | 范围外问题沉淀 |
| [docs/workflow/设计更新说明.md](docs/workflow/设计更新说明.md) | 设计变更记录 |
| [docs/agent/提示词上下文包.md](docs/agent/提示词上下文包.md) | 复制给 AI 的上下文 |
| [docs/templates/](docs/templates/) | 各类空白模板 |

---

## 附录 A. DanmuAI 技术速查

> 模块表、陷阱、环境变量；与 [docs/agent/ai-project-context.md](docs/agent/ai-project-context.md) 互补。

### 当前 UI 事实

- 默认 `python main.py` → Web 控制台 + pywebview + Qt Overlay/托盘
- **新功能仅加在** `web/static/` 与 `app/web_api/`（`routes.py` 注册）
- 已移除遗留 Qt 主窗；`--qt-ui` / `--legacy-ui` / `DANMU_QT_UI` / `DANMU_WEB_CONSOLE=0` → `sys.exit(2)`
- Overlay (`app/overlay.py` + `app/danmu_engine.py`) 始终运行，与控制台 UI 无关

### 架构

```text
python main.py
├─ DanmuApp（main.py + app/main_*mixin.py）
│  └─ 单例 QObject，主链路、生命周期、Web façade、运行态宿主
├─ uvicorn 线程                 — app/web_console.py（127.0.0.1:18765）
├─ pywebview 子进程             — app/webview_shell.py（桌面壳）
├─ web/static/                  — 默认控制台 UI（index.html、app.js、warm-tokens.css）
├─ app/web_api/                 — 人格、自定义模型、压缩预览、麦克风测试路由
└─ DanmuOverlay（app/overlay.py）— Qt 透明置顶弹幕（始终启用）
```

**线程模型**（agent 容易搞错）：

- 截图在**主线程**（`QTimer` 1s）
- AI 请求在 `QThreadPool`（`MAX_IN_FLIGHT=1`）
- HTTP 线程写 Qt 对象**必须**走 `WebConsoleBridge` 信号或 `QTimer.singleShot(0, ...)` 到主线程
- pywebview 由 `app/webview_shell.py` 拉起到**子进程**，不是 Qt 主线程内的第二个 UI 线程
- `keyboard` 回调经 `_ToggleBridge` 到主线程

**扩展 API**：`app/web_api/routes.py` 在 `web_console` 上注册；人格/模型逻辑复用 `PersonaManager`、`TemplateManager`、`validate_model_config`

### 核心模块速查

| 模块 | 职责 |
|------|------|
| `app/ai_client.py` | 双 API：`doubao` → `/responses` 流式；`openai` → `/chat/completions` SSE；请求固定 `thinking: disabled`（`THINKING_DISABLED`），流式只收集 `content` |
| `app/main_lifecycle_mixin.py` | `DanmuApp` 生命周期、错误处理、启动编排、`start/stop/quit` |
| `app/main_request_context_mixin.py` | request meta、RTT、memory、密度/队列辅助 |
| `app/main_display_mixin.py` | live status、overlay/floating panel 显隐、测试弹幕注入 |
| `app/main_mic_mixin.py` | 麦克风链路、mic insert、读弹幕 probe/config façade |
| `app/danmu_engine.py` | 多轨道 Track；`_pick_track` 加权随机（非轮询） |
| `app/overlay.py` | Qt 透明置顶渲染；16ms QTimer 有动画时 60fps |
| `app/live_freshness.py` | 截图退避、本地兜底批次（实时模式 TTL/节奏预触发已移除） |
| `app/memory/` + `app/memory_prompt_builder.py` | 场景简述 `scene_brief` + prompt 层防重复；`scene_memory_enabled` / `scene_memory_interval_sec` / `prompt_dedup_enabled` |
| `app/scene_memory.py` | 兼容 re-export（`SceneBriefStore` / `SceneMemoryStore` 别名） |
| `app/reply_parser.py` | AI 回复 JSON 解析与标准化 |
| `app/reply_queue.py` | `AIReplyFIFOBuffer` + 自适应延迟 100–1000ms |
| `app/config_store.py` | SQLite `%APPDATA%/DanmuAI/config.db`，Fernet 加密 Key，WAL + 写锁 |
| `app/mic_service.py` | 麦克风模式门面；`mic_mode_enabled` / `MicService` |
| `app/mic_utterance.py` | RMS 语音端点检测（无 VAD 库），4 状态机 |
| `app/mic_capture.py` | `sounddevice` 录音；`mic_encode.py` → WAV data URI |
| `app/mic_prompt.py` | 麦克风插入提示词组装 |
| `app/model_providers.py` | 8 个服务商预设 + 2 个自定义（火山方舟、百炼、智谱、Moonshot、硅基流动、**小米 MiMo**、OpenAI/豆包自定义）；`guess_provider_from_endpoint` |
| `app/model_catalog.py` | 四平台模型目录（`doubao` / `dashscope` / `siliconflow` / `mimo`）与定价元数据（Web 视觉模型选择器） |
| `app/translations.py` | 中英翻译表；`Translator.set_language()` 在 `DanmuApp.__init__` 调用 |
| `app/image_compress.py` | PIL + JPEG + Base64，max_width 768 quality 85，无临时文件 |
| `app/danmu_pool.py` | 自定义公式化弹幕库（SQLite `custom_danmu_pool`）；同屏补足与 `normalize_reply_batch` 填充 |
| `app/lifetime_stats.py` | 持久累计统计（弹幕/运行时长/Token），`stop()` 时并入 |
| `app/session_run_log.py` | 场次记录（启停一轮）；`config.db` 表 `session_runs`，最近 100 条 |

### 运行与测试

```bash
pip install -r requirements.txt
python main.py                         # Web + pywebview + Overlay
python main.py --web-browser           # 系统浏览器打开控制台
```

#### IDE Agent 分批验证（强制，见 IDE_AGENT_RULES §10）

- 只跑与改动相关的 `tests/test_*.py`，每批 `-q -x`；禁止 `python -m pytest tests/`。
- 映射表与四批策略：[docs/IDE_AGENT_RULES.md](docs/IDE_AGENT_RULES.md) §10。

#### 可选扩大批次（逐批 `-x` 执行，不能替代全量）

```bash
python -m pytest tests/test_reply_parser.py tests/test_p0_main_flow.py tests/test_danmu_engine.py tests/test_config_store.py tests/test_ai_client.py -q -x
python -m pytest tests/test_web_console.py tests/test_web_persona_api.py tests/test_web_custom_models.py tests/test_image_compress.py tests/test_ui_mode.py -q -x
```

#### CI / 维护者全量（IDE Agent 禁止自动执行）

```bash
python -m pytest tests/ -q
python -m pytest tests/ -v --tb=short
```

#### 测试约定

- **临时目录**：项目根 `.pytest_tmp/`（`conftest.py` 重定向 `TMP`/`TEMP`，避免 `%TEMP%\pytest-of-*` 权限问题；根 `conftest.py` 先执行，`tests/conftest.py` 再细分 per-test 子目录）
- **共享假对象**：`tests/fakes.py`（`FakeTimer`、`FakeEngine`、`FakeConfig`、`FakeLogger` 等）
- **最小 DanmuApp**：`DanmuApp.__new__(DanmuApp)` + `bind_minimal_danmu_app(app, **overrides)`（`tests/conftest.py`）
- **勿** `from test_p0_main_flow import ...`（无包前缀 collection 时报 `ModuleNotFoundError`）
- **轨道选择**：`_pick_track` 为加权随机，需 `monkeypatch` `random.choices` 才能断言确定性轨道
- **Overlay 单测**：需 `QApplication` + `overlay.show()` + `processEvents()`；`_target_interval_ms()` 在不可见时返回 `0`
- **pytest `basetemp`**：`pytest.ini` 未设；实际目录取自 `tests/conftest.py` 的 `pytest_configure`

CI：`.github/workflows/ci.yml` — Python 3.12 `windows-latest`

### 关键陷阱

- **加密锁死**：丢失 `%APPDATA%/DanmuAI/.key` → 已加密 Key 不可恢复
- **弹幕截断**：AI 上屏默认 15 中文字 / 40 英文字 + `...`；公式化弹幕（自定义库、烂梗）完整展示
- **公式化弹幕库**：Web 页「公式化弹幕库」管理自定义短句；`danmu_pool_use_custom` 开启且 `min_on_screen`>0（默认 5，**0** 关闭）时同屏补足生效；AI 条数不足与本地轻量兜底从自定义池去重补齐；句库经 `/api/danmu-pool/custom`，开关与 `min_on_screen` 经 `/api/danmu-pool/settings`，不进 `PUT /api/config`
- **去重**：`deque(30)` + `recent_exact_set` + Levenshtein `dedup_threshold=0.5`
- **失败退避**：连续 5 次暂停；401/403/402 立即暂停
- **输出 token 下限**：`resolve_danmu_max_output_tokens` 下限 **512**（运行时固定关闭 thinking，忽略 `use_thinking` 开启）
- **思考模式**：豆包/OpenAI 请求均发 `thinking: {"type":"disabled"}`；勿把 `reasoning_content` 当弹幕；MiMo 未关闭时易「AI 返回为空」
- **小米 MiMo**：预设 `https://api.xiaomimimo.com/v1`（OpenAI 兼容）；目录模型仅 `mimo-v2.5`（MiMo-V2.5）；**开麦**：豆包 Responses `input_audio`+`audio_url`；MiMo **仅 mimo-v2.5** 走 Chat Completions `input_audio`+`input_audio.data`（data URI）
- **识图区域**：默认 `screen_index` 全屏；`region_w/h > 0` 时 [`app/snipper.py`](app/snipper.py) 按屏内相对坐标裁剪。Web 经 `POST/GET /api/capture-region/*` 鼠标框选，**勿**把 `region_*` 写入 `PUT /api/config`
- **Web 写配置**：`PUT /api/config` → bridge 信号 → 主线程 `apply_config_patch`；**勿在 HTTP 线程直接改 Qt 对象**
- **GET 自定义模型**：返回掩码 `apiKey`
- **Overlay 窗口标志**：`FramelessWindowHint | WindowStaysOnTopHint | Tool | BypassWindowManagerHint` + Win32 `WS_EX_LAYERED | WS_EX_TRANSPARENT`
- **无 Qt 主窗**：`setQuitOnLastWindowClosed(False)`；托盘退出 → `DanmuApp.quit()`

### 环境变量速查

| 变量 | 作用 |
|------|------|
| `DANMU_API_SCHEDULE_DEBUG=1` | API 调度日志 |
| `DANMU_MIN_API_INTERVAL_MS` | 防 API 冷启动连打（默认 800） |
| `DANMU_IMAGE_METRICS=1` | 压缩指标 debug 日志 |
| `DANMU_DEDUP_PROFILE=1` | 去重统计 `/api/status.dedup_profile` |
| `DANMU_WEB_LAUNCH=browser` | 等同 `--web-browser` |

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

### 改动决策树

```text
配置、人格、模型、日志 UI → web/static/ + app/web_api/
弹幕显示、轨道、性能      → app/overlay.py + app/danmu_engine.py
麦克风、语音              → app/mic_*.py
视觉稿                    → prototype/Qwen_*（Web only）
```

视觉规范：`prototype/Qwen_markdown_20260525_4vyxmv819.md`、`prototype/Qwen_html_20260524_481u8vlmv.html`

### 技术文档索引

- [docs/agent/ai-project-context.md](docs/agent/ai-project-context.md) — 对话式 AI / Agent 统一入口（阅读顺序与边界）
- [docs/README.md](docs/README.md) — 文档索引
- [docs/core/ARCHITECTURE.md](docs/core/ARCHITECTURE.md) — 架构总览
- [docs/CONTRIBUTING_ARCHITECTURE.md](docs/CONTRIBUTING_ARCHITECTURE.md) — 贡献边界与 Boundary Guard
- [docs/core/MAIN_PIPELINE.md](docs/core/MAIN_PIPELINE.md) — 主链路（普通模式）
- [docs/core/RUNTIME_STATE.md](docs/core/RUNTIME_STATE.md) — 运行态与快照
- [docs/core/BOUNDARY_GUARD.md](docs/core/BOUNDARY_GUARD.md) — `scripts/boundary_guard.py`
- [docs/features/WEB_CONSOLE.md](docs/features/WEB_CONSOLE.md) — Web API 与页面地图
- 场景简述记忆：`scene_memory_enabled` + `prompt_dedup_enabled`；见 [docs/core/ARCHITECTURE.md](docs/core/ARCHITECTURE.md)
- 维护者登记：`docs/runtime-state-map.md`、`docs/main-pipeline-sequence.md`、`docs/final-architecture-baseline.md`
- 文档与源码不一致时，以 `main.py` 与 `app/` 源码为准
