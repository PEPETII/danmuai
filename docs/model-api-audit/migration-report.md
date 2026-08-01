# Batch0–6 模型 API 迁移报告

> 报告日期：2026-08-01。
> 范围：只记录模型 API 审计链、Batch0–5 已提交实现、Batch6 离线证据和待补门禁。
> 结论：架构迁移已形成可测试链路，但“全平台官方规则已完成”**不成立**；21 个 provider 加 MiniMax 隐式分支仍有 unknown/停止条件。

## 1. 迁移前后边界

基线导出以 `3b555b7`/`574e6da` 审计链为锚点：旧实现把平台压缩为 Doubao Responses 与 OpenAI-compatible Chat 两种 transport，能力、价格、目录和前端存在重复事实源；MiniMax 还是隐式 endpoint 分支。当前已提交实现形成了：

```text
Provider/Model registry
  → exact hostname + API family
  → capability resolver
  → AuthProfile + protocol adapter
  → RequestPlanner
  → discovery/probe/stream/usage
  → model resolve route + settings integration
```

已确认的架构行为：

- registry 导出 21 个 provider；catalog 导出 19 个平台；两个 custom provider 无静态 catalog；
- endpoint resolver 使用 hostname 解析和 API family path join；
- request planner 被主请求、探活和知识整理路径复用；
- auth resolution 和导出/API metadata 对 secret 做隔离；
- discovery 默认无网络，失败回退 curated catalog，账号 discovery 结果标注来源/时间；
- probe 具备 `local`、`auth_model`、`text`、`vision`、`audio`、`stream` 分层；
- Hunyuan 当前 preset 为 `/v1` 并暴露迁移状态，StepFun 当前 preset 为 `/v1`，OpenRouter 静态 ID 使用 `author/model` 形状。

这些是代码/测试链已观察到的行为，不等于每个平台的官方模型目录、价格或账号可用性已确认。

## 2. Batch0–5 提交记录

| 批次 | commit | 范围 | 当前迁移判断 |
|---|---|---|---|
| Batch0 | `574e6da` | 审计快照目录 `batch0_current_574e6da/` 和基线资料。 | 作为旧事实源/差异矩阵，不是运行时完成证据。 |
| Batch1 | `82991d5` | 初始模型 API 相关实现及紧急数据修正：Hunyuan、StepFun、OpenRouter、provider/planner 初始链路等。 | 已进入主线；commit 内容还包含非本报告范围的其他改动。 |
| Batch2 | `72de9a3` | registry v2 schema、provider/model 定义及兼容迁移测试。 | 统一视图已落地，但官方 source/ID/price 不自动成立。 |
| Batch3 | `55a0c81` | exact endpoint、capability、auth、planner、adapter、stream/usage。 | 请求规划链已可离线验证；全平台专属 golden 未齐。 |
| Batch4 | `964fc13` | account discovery、TTL cache、curated fallback、discovery route。 | 能力未知时仍需保持 unknown；账号 discovery 未在 CI 默认执行。 |
| Batch5 | `fee89de` | 分层 probe、知识整理统一配置、resolve route、UI 配置接入。 | local/mock 链已有证据；真实网络/UI 未验收。 |

## 3. Batch6 测试证据

主代理提供的三批定向结果如下；本次文档校正未重新执行：

```text
python -m pytest tests/model_api/test_platform_schema_contract.py tests/model_api/test_registry_security_contract.py -q -x  → 7 passed
python -m pytest tests/model_api/test_capability_contract.py tests/model_api/test_golden_request_contract.py -q -x  → 24 passed
python -m pytest tests/model_api/test_stream_usage_contract.py tests/model_api/test_probe_contract.py -q -x  → 27 passed
ruff check tests/model_api  → 通过
```

合计 **58 passed**。Batch6 新测试证明的是离线 schema/registry/security/capability/golden-plan/stream-usage/probe 合同，不是全量 CI、真实 API 或浏览器验收。

Batch6 门禁补充证据：

- `ruff check app main.py tests scripts` 已真实执行，退出码 **1**，报告 **243 errors**；主代理说明新增 `tests/model_api` 未命中该输出。Batch6 定向 `ruff check tests/model_api` 仍保持通过，不能抵消全量 Ruff 失败。
- `python -m pytest tests/ -v --tb=short` 已真实启动；600045ms 后工具退出码 **124**，底层 pytest 无输出且无退出，主代理随后只终止了本次启动的 PID。结论是 **attempted/timeout/hung，未通过**，不是“未运行”或“pending”。
- `tests/test_web_routes.py` 定向回归先 **11 passed**，随后在 `tests/test_web_routes.py::test_user_nickname_round_trip_via_config_service` 因 `ConfigStore._decrypted_secret_cache` `AttributeError` 失败；确认是本批前已知/无关问题，不修。
- `tests/test_web_server.py` 定向回归先 **11 passed**，随后在 `test_web_content_page_field_hints_wired` 因 `petScale` 缺失失败；确认是本批前已知/无关问题，不修。
- 真实 API、账号 `/models`、费用/限流、完整 API 联调和 Windows package 均未验证；Batch5 Browser 静态检查仅确认 shell/partial 控件。

## 4. 21 个 provider + MiniMax 规则审计表

状态含义：

- **已落实**：当前代码/离线契约已落实该条架构或固定 endpoint 规则；不代表模型 ID/价格已核验。
- **未确认**：需要官方 exact model page、官方 API 返回或账号 discovery；当前不能写入确定值。
- **停止条件**：遇到该条件不得继续扩大目录/adapter 实现，应保留 unknown 并报告。

| provider | 官方 URL（索引） | 核验日 | 当前规则状态 | 停止条件 |
|---|---|---:|---|---|
| doubao | https://www.volcengine.com/docs/82379/1795150 | 2026-08-01 | endpoint/Responses/request plan 已落实；Seed 2.1 exact ID 未确认 | 无官方 exact ID/视觉能力证据，不更新 curated model |
| dashscope | https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope | 2026-08-01 | Chat 兼容路径与 planner 已有；Chat/Responses/区域差异未完全确认 | 官方区域/workspace 文档无法确认时停止新增 profile |
| openai | https://platform.openai.com/docs/api-reference/models | 2026-08-01 | Chat plan 已有；独立 Responses profile 和新模型 exact slug 未确认 | 不把市场名称写成 API ID，不猜价格 |
| google_gemini | https://ai.google.dev/gemini-api/docs/openai | 2026-08-01 | endpoint/Chat plan 已有；reasoning_effort 模型级规则未确认 | 无 exact model/API family 证据不改 provider 默认 |
| xai | https://docs.x.ai/developers/models | 2026-08-01 | endpoint/通用 plan 已有；Grok 4.5 exact ID/always-on 仍未确认 | 无官方或账号证据不写 Grok 4.5 slug |
| mistral | https://docs.mistral.ai/api/endpoint/models | 2026-08-01 | endpoint/vision plan 已有；`/models` capability 与 reasoning 未 live 核验 | 静态目录不覆盖账号模型能力 |
| together | https://docs.together.ai/docs/inference/openai-compatibility | 2026-08-01 | 通用 Chat plan 已有；当前推荐 ID/reasoning 未确认 | 不按固定五模型或营销名扩目录 |
| fireworks | https://docs.fireworks.ai/api-reference/list-models | 2026-08-01 | 通用 plan 已有；inference/deployment model ID 未确认 | serverless 与 deployment 未分清时停止 |
| dashscope_intl | https://help.aliyun.com/zh/model-studio/getting-started/what-is-model-studio | 2026-08-01 | legacy endpoint/通用 plan 已有；区域账号能力未确认 | 无区域/workspace 证据不复制 CN 规则 |
| zai | https://docs.z.ai/guides/overview/overview | 2026-08-01 | registry/plan 已有；GLM exact multimodal/reasoning 未确认 | 不把 Z.AI 与智谱 CN 混用 ID/价格 |
| zhipu | https://open.bigmodel.cn/dev/api | 2026-08-01 | CN endpoint/plan 已有；model-specific thinking 未确认 | 无 CN exact model 页面/账号证据停止 |
| moonshot | https://platform.moonshot.cn/docs | 2026-08-01 | endpoint/plan 已有；当前 Kimi multimodal ID 未确认 | 不把产品名称猜成 API ID |
| siliconflow | https://docs.siliconflow.cn/en/api-reference/models/get-model-list | 2026-08-01 | discovery/fallback/plan 已有；模型级 thinking budget 未确认 | 未有官方支持清单不发送 thinking 字段 |
| mimo | https://platform.xiaomimimo.com/docs | 2026-08-01 | 专属 adapter、图片/音频离线形状已落实；官方 auth/audio curl 未确认 | 未确认 header/data URI 时不扩大变体支持 |
| hunyuan | https://cloud.tencent.com/document/product/1729/131925 | 2026-08-01 | `/v1`、migrating、2026-09-30 warning 已落实；TokenHub 迁移 profile 未确认 | 新 endpoint/替代模型无官方稳定文档即停止 |
| stepfun | https://platform.stepfun.com/docs/zh/api-reference/chat/chat-completion-create | 2026-08-01 | `/v1`、Chat plan 已落实；Step 3 exact vision/Step Plan 未确认 | 不把 Step Plan 与公共 Chat endpoint 混用 |
| baidu_cloud | https://cloud.baidu.com/doc/WENXINWORKSHOP/ | 2026-08-01 | endpoint/通用 image plan 已有；两类 thinking schema 未完全确认 | 无 exact ERNIE model 证据不选 schema |
| openrouter | https://openrouter.ai/docs/api/api-reference/models/get-models | 2026-08-01 | `author/model`、exact host attribution、discovery fallback 已落实；账号 `/models` 未取 | 静态目录不代替账号目录；不猜上游能力 |
| modelscope | https://www.modelscope.cn/docs/model-service/API-Inference/intro | 2026-08-01 | custom/curated plan 已有；托管 API 的 `/models`、参数和可用性未确认 | 模型页与托管层不一致时保留 unknown |
| custom_openai | 无单一官方平台 URL；由用户 endpoint/profile 定义 | — | unknown provider schema/保守 capability 已落实 | 无用户显式 override 不声明视觉/音频/思考 |
| custom_doubao | 无单一官方平台 URL；旧 ID 保持兼容 | — | 兼容入口存在；不能自动假定完整 Doubao Responses 合约 | 无用户显式 profile 不发送平台特有字段 |
| MiniMax 隐式分支 | 当前官方 URL 未登记于 08 索引 | — | **unknown；未正式注册为 provider**；旧审计记录存在 endpoint 特判 | 必须先选择“正式注册并补来源/adapter/tests”或“移除隐式分支”，否则停止继续扩展 |

这里的“未确认”是有意保守状态，不是“平台不可用”。需要账号 API Key 才能决定的事项只可记录为 account discovery，不得写成全球固定事实。

## 5. 官方来源口径

上表 URL 来自同目录 `08_官方资料索引.md`，索引核验日期为 **2026-08-01**。本批没有重新打开外部页面；官方 URL 只作为审计入口，不为未验证的 model ID、价格、上下文或账号状态背书。MiniMax 未在该索引中登记可用于本报告的稳定官方来源，因此保留 unknown。

## 6. Final gate 与停止条件

final gate 当前为 **未通过，未关闭**：全量 Ruff 失败，且全量 pytest attempted 后 timeout/hung。不得把 58 个离线通过写成全量门禁通过。

1. 若要宣称 live，通过默认关闭、单 provider、低预算、脱敏输出和真实结果审计；
2. 若要宣称 UI/API 联调完成，通过浏览器关键路径和真实后端交互，不以 Batch5 shell/partial 静态检查代替；
3. 若要宣称某平台规则完成，必须有官方 URL + 核验日，并为 exact model ID/价格/账号能力分别提供证据；
4. 遇到官方文档无法确认精确 ID、必须依赖真实 API Key、迁移 endpoint 无稳定公开文档、或出现未提交冲突改动时，停止扩大范围并保留 unknown。

## 7. 工作区边界

Batch6 交付范围包含：

- 本批新增的 6 个 `tests/model_api/` 契约测试文件；
- `docs/model-api-audit/` 下四份审计文档。

Batch6 未修改运行时代码；工作区原有三份 Web UI 改动（`web/static/index.html`、`web/static/partials/style-generator.html`、`web/static/warm-tokens-pages-stylegen.css`）不纳入 Batch6。6 个测试文件由总控随后暂存并提交；本报告不写入未知 commit hash。本次文档校正只修改上述四份审计文档，不改代码、测试文件、README、用户文件、CI、密钥或生产数据。
