# Batch6 最终测试矩阵

> 状态：Batch6 final gate **未通过，未关闭**。
> 审计/文档日期：2026-08-01。
> 本文件只记录当前仓库和主代理提供的可核验证据，不把失败、超时、真实 API 或 UI 未验收写成通过。

## 1. 已提交批次范围

以下是按当前 `main` 提交链整理的 Batch0–5。提交说明是实际 commit 内容的摘要，不代表每个 commit 只包含单一工单。

| 批次 | commit | 已提交范围 | 证据边界 |
|---|---|---|---|
| Batch0 | `574e6da` | Batch0 基线快照；对应 `docs/model-api-audit/batch0_current_574e6da/` 导出物。 | 这是审计/基线锚点，不宣称完成运行时迁移。 |
| Batch1 | `82991d5` | 初始模型 API 链路落地；包含 StepFun/Hunyuan endpoint 修正、OpenRouter ID 修正、Hunyuan 生命周期字段，以及 provider/request 相关初始抽象。 | commit 同时含有其他应用/UI 改动；本表只归档模型 API 相关范围。 |
| Batch2 | `72de9a3` | Provider/Model registry v2、schema、兼容映射和 registry/migration 测试。 | 仍以现有 legacy 数据派生 v2 视图，不能据此证明官方目录已全部核验。 |
| Batch3 | `55a0c81` | endpoint/API family、capability resolver、auth、request planner、adapter、stream/usage facade。 | 已有离线代表 fixture；全平台专属 golden 仍不是本批已证明事实。 |
| Batch4 | `964fc13` | `/models` 发现、缓存、curated fallback 及对应 API route。 | 发现结果依赖账号；没有账号 discovery 就不能证明模型对所有用户可用。 |
| Batch5 | `fee89de` | 分级探活、知识整理/统一 planner 接入、model resolve route 和设置页配置接入。 | 真实网络、真实账号、浏览器 UI 均未由本批文档任务验证。 |

Batch0 基线导出明确记录了 21 个 provider、19 个 catalog 平台，以及旧的固定数量/模型 ID/价格/能力假设。当前代码快照仍应以运行时和测试为准，不能把基线文档中的旧值当作官方现状。

## 2. Batch6 离线证据

以下结果由主代理提供，本次文档任务未重新执行测试：

| 分层 | 命令 | 结果 |
|---|---|---:|
| platform schema + registry security | `python -m pytest tests/model_api/test_platform_schema_contract.py tests/model_api/test_registry_security_contract.py -q -x` | **7 passed** |
| capability + golden request | `python -m pytest tests/model_api/test_capability_contract.py tests/model_api/test_golden_request_contract.py -q -x` | **24 passed** |
| stream/usage + probe | `python -m pytest tests/model_api/test_stream_usage_contract.py tests/model_api/test_probe_contract.py -q -x` | **27 passed** |
| Batch6 Ruff | `ruff check tests/model_api` | **通过** |

合计：**58 passed**。这些测试是本地、离线、契约/请求规划测试；测试中的凭据只应是测试内部占位输入，不得进入文档、日志或提交内容。

已覆盖的行为包括：

- 19 个当前 catalog 平台的确定性离线 request plan 形状；
- provider/catalog registry 连接、source metadata 可序列化和 custom provider unknown 语义；
- exact hostname、OpenRouter host-scoped attribution 和 secret 不进入导出/API metadata；
- unknown custom model 的保守 capability；
- Doubao Responses、MiMo 图片/音频 content part 顺序及 token 字段；
- Chat/Responses stream parser、reasoning-only/usage、DashScope/OpenAI usage normalization；
- local probe 不发网络、模型发现/探活结果的脱敏字段。

## 3. 项目 CI 实际门禁

依据当前 `.github/workflows/ci.yml` 与 `pyproject.toml`，CI 不是本地 Batch6 三批测试的同义词：

| CI job/步骤 | 实际命令或配置 | 本批状态 |
|---|---|---|
| Python | Windows runner，Python `3.12` | 未在本地复跑 CI runner |
| 安装 | `pip install -r requirements.txt -r requirements-dev.txt --dry-run`，随后分别/合并安装 | 未在本地复跑 CI job |
| Ruff | `ruff check app main.py tests scripts` | **退出码 1；243 errors**。主代理说明本次输出未命中新增 `tests/model_api`。 |
| Python tests | `python -m pytest tests/ -v --tb=short` | **已尝试；600045ms 后工具退出码 124**。底层 pytest 无输出且无退出；主代理仅终止了本次启动的 PID。判定：**timeout/hung，未通过**。 |
| Windows package | publish dry-run、PyInstaller、Velopack pack、artifact verify | **未验证；不属于本批文档可声称范围** |

`pyproject.toml` 的 Ruff 约束为 target `py312`、选择 `E/F/I/W`、忽略 `E501`，测试文件允许 `F841`。Batch6 新测试目录的 Ruff 通过不能抵消全量命令的 243 errors；且主代理明确说明该全量输出未命中新增 `tests/model_api`。

## 4. 已知未决项与 final gate

| 项目 | 状态 | 说明 |
|---|---|---|
| CI 全量 pytest | **已尝试但未通过：timeout/hung** | `python -m pytest tests/ -v --tb=short` 启动后 600045ms 工具退出码 124；pytest 无输出/无退出，随后只终止本次启动 PID。 |
| CI 全量 Ruff | **失败** | `ruff check app main.py tests scripts` 退出码 1，243 errors；新增 `tests/model_api` 未命中。 |
| web routes 类既有失败 | **已确认既有/无关，不修** | 定向回归先 11 passed，随后在 `tests/test_web_routes.py::test_user_nickname_round_trip_via_config_service` 因 `ConfigStore._decrypted_secret_cache` `AttributeError` 失败；不归因于 Batch6。 |
| web server 类既有失败 | **已确认既有/无关，不修** | 定向回归先 11 passed，随后在 `test_web_content_page_field_hints_wired` 因 `petScale` 缺失失败；不归因于 Batch6。 |
| 真实 API / live smoke | **未验证** | 没有密钥、真实请求、费用或账号可用性证据。 |
| 浏览器/UI 手动验收 | **部分静态检查，完整联调未验证** | Batch5 Browser 静态检查仅确认 shell/partial 控件；完整 API 联调、视觉交互和真实后端路径未验证。 |
| Windows 打包/运行 | **未验证** | CI pack job 尚未由本批执行。 |

final gate 当前状态：**未通过，未关闭**。原因是全量 Ruff 243 errors，以及全量 pytest 已尝试但在 600045ms 后 timeout/hung（工具退出码 124、pytest 无输出/无退出）。web routes/web server 两项失败已确认是本批前已知/无关项，不在本批修复。仍待补的是 live 真实证据、完整 API 联调和 Windows package（如需要发布结论），但这些不能把全量门禁改写为通过。

## 5. 非目标

本次文档校正没有修改运行时代码、Batch6 测试文件、README、用户文件或 CI；没有运行真实外部请求；没有声称所有平台规则、官方 model ID、价格或账号可用性已完成核验。Batch6 交付范围本身包含本批新增的 6 个 `tests/model_api/` 契约测试和本目录四份审计文档。
