# Contributing

## 项目协作原则

- 一次只处理当前任务；不实现未授权的 Roadmap、未来工单或顺手重构。
- 先读后写：先检查工作区状态、目标文件、调用方、相关测试和适用的架构登记表，再修改。
- 保持改动集中、可审查、可回滚；不擅自引入依赖、移动文件、改名公共接口或调整架构分层。
- 发现范围外问题只记录，不修复；除非它直接阻塞当前任务或造成安全风险。
- 不把 `.local-ai/scratch/`、`.local-ai/reports/archive/` 等历史资料当作当前行为依据。
- 默认不创建/切换分支，不提交、推送、发布、部署或修改生产数据；只有明确授权时才执行。

详细原则与架构边界见根目录 [AGENTS.md](AGENTS.md)。

## 开发原则

- 默认 UI 为 **Web 控制台**（`web/static/` + `app/web_console.py` + `app/web_api/`），PyQt6 仅用于 Overlay/托盘。
- 优先修复稳定性、隐私和发布质量问题，再考虑新功能。
- 修改 Web UI 前对照 [docs/ui/DESIGN_SYSTEM.md](docs/ui/DESIGN_SYSTEM.md)、[docs/ui/UI_CHANGE_CHECKLIST.md](docs/ui/UI_CHANGE_CHECKLIST.md)，以及 [`prototype/Qwen_html_20260524_481u8vlmv.html`](prototype/Qwen_html_20260524_481u8vlmv.html)；Token 以 `web/static/warm-tokens-base.css` 为准（入口 `warm-tokens.css`）。

## 开工前检查

开始前执行只读检查：

```powershell
git status --short
git diff --stat
```

保留已有变更，不覆盖与当前任务无关的修改。若目标文件有未知改动，先区分基线和本次改动。

## 任务边界与变更纪律

任务描述若没有明确允许区，按"完成目标所需的最小文件集合"处理。以下行为必须有明确授权：

- 修改主链路、线程/进程模型、公共 API、数据库 schema、迁移、配置格式、发布链或 CI。
- 新增第三方依赖、删除依赖、批量重命名、移动目录或删除数据/资源。
- 执行正式发布、R2/GitHub 上传、代码签名、部署、回滚、提交或推送。

禁止通过以下方式制造表面成功：禁用测试、吞掉异常、删除校验、扩大容错、硬编码测试结果、把失败改报成功或只验证 UI toast。

### 默认功能落点

| 需求                | 默认落点                                                                                    |
| ----------------- | --------------------------------------------------------------------------------------- |
| Web 控制台页面、交互、样式   | `web/static/`、`web/static/modules/`、`web/static/partials/`                              |
| Web API           | `app/web_api/`，由 `app/web_api/routes.py` 注册                                             |
| 主链路、截图、视觉 AI、回复队列 | `main.py`、`app/main_*_mixin.py`、`app/application/`（高风险）                                 |
| 弹幕渲染、轨道与 Overlay  | `app/overlay.py`、`app/danmu_engine/`                                                    |
| 配置与本地存储           | `app/config_store/`、相关 `app/application/` 服务                                            |
| 知识库               | `app/knowledge/`、`app/web_api/knowledge*.py`、`web/static/modules/app-knowledge-page.js` |
| 麦克风/语音            | `app/mic_*.py`、`app/danmu_read_service.py`、相关 Web API                                   |
| 桌宠                | `app/pet/`、对应 `app/main_*_mixin.py` 和 Web API                                           |
| TTS               | `app/danmu_tts*.py`、`app/tts_*.py`                                                      |
| 烂梗弹幕              | `app/meme_barrage/`、`app/main_meme_mixin.py`、对应 Web API                                 |
| 模型适配器             | `app/providers/`、`app/ai_client.py`、`app/model_providers.py`                            |
| Windows 构建/发布     | `scripts/build_exe.ps1`、`scripts/velopack_pack.ps1` 及 `docs/operations/`                |

## 本地开发

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
python main.py
```

配置目录默认为 `%APPDATA%/DanmuAI/`。在非 Windows 且未设置 `APPDATA` 时，会落在当前工作目录下的 `./DanmuAI/`。

**Web UI 构建**：修改 `web/static/` 中的 HTML/CSS/JS 后，执行以下命令重新生成入口 HTML：

```powershell
python web/static/build_index_html.py
```

## 提交前检查

本地 **不要** 跑全量 `python -m pytest tests/`：套件 700+ 条，内存占用高，易导致机器卡顿。请按改动范围 **分批** 执行（每批 `-q -x`）；全量仅 CI 或资源充足的维护者环境执行。

分批策略与 Agent 边界以根目录 [AGENTS.md](AGENTS.md) §7 / §10 为准。可选本地补充：`.local-ai/prompts/IDE_AGENT_RULES.md` §10（该路径可能被 gitignore，克隆后不一定存在；**勿**依赖根级 `IDE_AGENT_RULES.md`）。Web UI 另见 [docs/ui/DESIGN_SYSTEM.md](docs/ui/DESIGN_SYSTEM.md)。

```bash
pip install -r requirements-dev.txt
ruff check app main.py tests scripts
# 批次 1 — 主链路、回复、引擎、配置、AI 客户端
python -m pytest tests/test_reply_parser.py tests/test_p0_main_flow.py tests/test_danmu_engine.py tests/test_config_store.py tests/test_ai_client.py -q -x
# 批次 2 — Web / UI
python -m pytest tests/test_web_console.py tests/test_web_persona_api.py tests/test_web_custom_models.py tests/test_image_compress.py tests/test_ui_mode.py -q -x
# 批次 3 — 调度与 Boundary Guard
python -m pytest tests/test_request_scheduling.py tests/test_boundary_guard_web_rules.py tests/test_boundary_guard_runtime_rules.py tests/test_boundary_guard_request_rules.py tests/test_boundary_guard_diagnostics_rules.py -q -x
# 批次 4 — 知识库
python -m pytest tests/test_knowledge_import_service.py tests/test_knowledge_database.py tests/test_knowledge_integration.py tests/test_knowledge_pipeline_integration.py tests/test_knowledge_validator.py -q -x
```

**测试对应关系**：

- `app/reply_parser.py`、`main.py`、回复队列：`test_reply_parser.py`、`test_p0_main_flow.py`、`test_reply_*.py`、`test_request_scheduling.py`。
- `app/web_api/`、`web/static/`：相关 `test_web_*.py`、`test_ui_*.py`，必要时补浏览器/手动验收。
- `app/overlay.py`、`app/danmu_engine/`：`test_overlay_*.py`、`test_danmu_*.py`。
- `app/config_store/`：`test_config_*.py`、加密/SQLite 并发相关测试。
- `app/knowledge/`：`test_knowledge_*.py`，并核对真实 `knowledge_items` 持久化计数。
- 更新/打包运行时：`test_update_api.py`、`test_update_service.py`、`test_velopack_runtime.py`；发布脚本仅按 AGENTS.md §9.8 规则验证。

与改动相关的其他 `tests/test_*.py` 请单独成批追加；**禁止**无文件参数的 `pytest` / `python -m pytest tests/`。

### 静态检查与 Boundary Guard

Python 代码改动至少运行：

```powershell
ruff check app main.py tests scripts
```

触达 `main.py` 主链路、`app/application/` 编排、`app/web_api/`、运行态、线程/定时器或三份架构登记表时，另运行：

```powershell
python scripts/boundary_guard.py
```

`boundary_guard.py` 退出码为 `0` 表示通过，`1` 表示发现问题。不要用截断输出、过滤错误或忽略退出码来宣称通过。

### 变更后的最小门禁

按触达范围执行：

1. 纯文档：`git diff --check` + 链接/章节检查。
2. Python 逻辑：`ruff` + 相关 pytest 批次。
3. 主链路/Web/API/运行态：再加 `python scripts/boundary_guard.py`。
4. UI：再做浏览器或人工关键路径验收，并保存必要截图/日志证据；不要把截图当作唯一证据。
5. 发布：仅在授权后按发布文档执行，并验证 Setup、Portable、full/delta 包及 hash/manifest。

## 提交规范

- 不要提交 API Key、日志、截图、`%APPDATA%/DanmuAI/` 下的本地数据库或 `.key` 文件。
- 不要把调试截图、缓存目录、`.coverage`、`__pycache__`、`.pytest_cache` 带入版本库。
- 新功能或可见行为变化需要同步更新：
  - `README.md`
  - [项目技术上下文](.local-ai/prompts/ai-project-context.md)（若涉及 Web API/UI）
  - [CHANGELOG](docs/operations/CHANGELOG.md)
- 新增/删除/移动定时器、线程、后台任务或主链路触发点：同步 `docs/main-pipeline-sequence.md`。
- 新增、删除或改变 `DanmuApp` 运行态字段：同步 `docs/runtime-state-map.md`。
- 所有权、边界或架构基线改变：同步 `docs/final-architecture-baseline.md`。
- Web/UI 改动：遵循 `docs/ui/*` 设计系统；新增页面状态、交互或响应式行为时，补充对应测试或手动验收记录。
- 修改根级维护文档时，请同步更新 [CHANGELOG](docs/operations/CHANGELOG.md) 与对应的 Boundary Guard 登记表（若触达线程、状态或架构边界）。

## 范围外问题处理

发现无关缺陷时：

1. 不在当前任务中修复、重构或改测试绕过它。
2. 记录文件、位置、可观察影响和复现/验证方法。
3. 若仓库已有对应工单或问题记录，引用它；否则在完成报告中列为后续事项。

文档与实现冲突时，记录冲突，不要为了让文档"看起来一致"篡改运行代码或历史报告。需求会改变数据模型、线程模型、兼容性或发布行为且未给出选择时，应停止扩展并请求明确授权。

## 安全与隐私

- 本地 Web API 默认只监听 `127.0.0.1:18765`，不是多用户网络服务；不要为方便调试改为监听公网或局域网。
- 写接口和受保护 WebSocket 使用启动期 session/Bearer token；不要绕过鉴权或把 token 写入日志、截图、测试产物。
- API Key、`Authorization`、长 base64 图片和加密串必须脱敏。不要提交 `.env`、`.key`、PFX、证书密码、R2 Token 或任何密钥。
- 截图默认在内存中压缩后发送，不要为调试把截图原文写入磁盘或日志；人工验收时避开密码、支付、聊天和企业内部页面。
- 涉及真实外部服务、上传、发布、签名、生产数据或不可逆操作时，先确认授权、影响范围和回滚方式。

详见 [SECURITY.md](SECURITY.md)。安全问题不要公开粘贴原始密钥、截图或包含隐私的日志。

## Issue 与 PR

- Bug 报告请附最小复现步骤、实际行为、期望行为和日志摘要。
- 涉及隐私、凭据或安全边界的问题，请不要公开贴出原始截图和密钥，改走 [SECURITY.md](SECURITY.md) 中的私下反馈流程。
