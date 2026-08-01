# Batch6 Golden Payload 摘要

> 审计/文档日期：2026-08-01。
> 结论口径：`已覆盖` 仅表示当前离线 planner/adapter 契约有证据；不表示官方 model ID、价格、账号可用性或真实 HTTP 已确认。
> 本文件不记录任何 API Key 或凭据值。

## 1. 证据范围

主代理提供的 Batch6 golden 相关命令为：

```text
python -m pytest tests/model_api/test_capability_contract.py tests/model_api/test_golden_request_contract.py -q -x  → 24 passed
ruff check tests/model_api  → 通过
```

`test_golden_request_contract.py` 参数化遍历当前 `PLATFORM_CATALOGS` 的 19 个平台，并另测 Doubao Responses 和 MiMo 图片+音频形状。仓库已有的专属离线 fixture 仍是 `tests/fixtures/model_api/openai_chat.json` 与 `tests/fixtures/model_api/doubao_responses.json`；不能把参数化计划检查误写成 19 个官方专属 fixture 已齐全。

## 2. 19 类 golden 状态

| # | golden 类别 | 当前状态 | 证据/缺口 |
|---:|---|---|---|
| 1 | OpenAI Responses + image | **unknown** | 当前有 Responses family/adapter 契约，但没有独立 OpenAI Responses provider/model 的专属 golden；不得猜精确 model ID。 |
| 2 | OpenAI Chat legacy + image | **已覆盖（离线契约）** | 19 平台参数化 plan 覆盖 OpenAI Chat；另有 `openai_chat.json` 代表 fixture。未做真实请求。 |
| 3 | Gemini OpenAI compatibility + reasoning effort | **unknown** | Gemini 平台 plan 有覆盖，但当前未形成已核验 exact model 的 `reasoning_effort` 专属 golden。 |
| 4 | xAI Grok 4.5 | **unknown** | 通用 catalog plan 有覆盖；Grok 4.5 exact API ID、always-on reasoning 和参数组合未由账号/官方 exact ID 证实。 |
| 5 | Mistral vision | **已覆盖（离线契约）** | 参数化 catalog plan 带图片输入；模型级 vision/reasoning 仍需官方/账号证据。 |
| 6 | Doubao Responses + image | **已覆盖（专属形状）** | 专项测试断言 `input_image` 在 `input_text` 前、无误加 `thinking`/`stream_options`；另有 `doubao_responses.json`。 |
| 7 | DashScope vision + thinking disabled | **已覆盖（离线契约）** | 参数化 plan 覆盖平台；thinking/schema 与区域/workspace 规则未做 live 核验。 |
| 8 | Z.AI visual model | **已覆盖（离线契约）** | 参数化 plan 覆盖平台；精确视觉模型 ID 和多模态字段仍 unknown。 |
| 9 | Zhipu visual model | **已覆盖（离线契约）** | 参数化 plan 覆盖平台；CN 账号可用 ID 与模型级 thinking 未确认。 |
| 10 | Moonshot/Kimi image | **已覆盖（离线契约）** | 参数化 plan 覆盖平台；当前 Kimi image/video exact API ID 未确认。 |
| 11 | SiliconFlow vision | **已覆盖（离线契约）** | 参数化 plan 覆盖平台；`enable_thinking`/budget 仅可按 exact model 确认。 |
| 12 | MiMo image | **已覆盖（专属形状）** | 专项测试断言图片在文本前、`max_completion_tokens`、关闭 thinking 且不发 `stream_options`。 |
| 13 | MiMo image + audio | **已覆盖（专属形状）** | 专项测试断言 `image_url`、`text`、`input_audio` 顺序和音频 data URI 形状；官方 HTTP 认证/音频契约仍需 live/官方 curl 证据。 |
| 14 | Hunyuan vision | **已覆盖（离线契约）** | 参数化 plan 覆盖当前 Hunyuan catalog；迁移后 TokenHub endpoint/model 仍未确认。 |
| 15 | StepFun vision | **已覆盖（离线契约）** | 参数化 plan 覆盖当前 catalog；精确 Step 3 vision ID 和 Step Plan profile 未确认。 |
| 16 | Baidu vision | **已覆盖（离线契约）** | 参数化 plan 覆盖平台；`thinking.type`/`enable_thinking` 的 exact model override 未完全核验。 |
| 17 | OpenRouter vision | **已覆盖（离线契约）** | 参数化 plan + host-scoped attribution/security contract；动态 `/models` 的实际账号数据未获取。 |
| 18 | ModelScope custom discovered model | **unknown** | 当前测试使用静态 catalog model 的离线 plan，不等于真实 `/models` discovered model；托管 API 可用性未确认。 |
| 19 | custom OpenAI explicit override | **unknown** | unknown capability 的保守行为有测试，但没有独立 custom override golden 断言；用户 endpoint/schema 仍需显式配置。 |

本 19 类均属于工单 05 的范围，因此本表没有将某一类标为“不适用”。“不适用”只可用于未来明确不支持的协议/模态，不能用来掩盖尚未形成 golden 的类别。

## 3. 统一断言与安全边界

当前已由离线测试锁定或覆盖的通用断言：

- method、API family、URL join、model 字段和 parser ID；
- Chat 的 `messages` 与 Responses 的 `input` 结构；
- content part 顺序、max token 字段、reasoning/optional 字段是否省略；
- unknown model 不自动宣称视觉/音频/思考；
- 计划请求的 repr、URL 和导出 metadata 不包含凭据值；
- stream/usage parser 使用独立的本地事件行，不发外网。

仍未形成 final-gate 证据的项目：

- 每个平台一个可维护的官方 HTTP golden fixture；
- OpenAI Responses 独立 profile；
- Gemini/xAI/Mistral/Together 等模型级 reasoning exact profile；
- MiMo 官方 curl 对认证头、音频 data 和 thinking 的核验；
- 真实 provider response、错误分类和 account discovery；
- UI 实际展示 golden payload 后的浏览器交互。

## 4. 官方来源与核验日

官方 URL 以 `docs/danmuai_model_api_audit_2026-08-01/.../08_官方资料索引.md` 为来源，索引核验日统一记为 **2026-08-01**。本批没有重新打开外部页面，也没有用这些 URL 猜测 model ID 或价格。平台级来源包括：

| 范围 | 官方 URL | 索引核验日 |
|---|---|---|
| OpenAI | https://platform.openai.com/docs/api-reference/responses | 2026-08-01 |
| Gemini | https://ai.google.dev/gemini-api/docs/openai | 2026-08-01 |
| xAI | https://docs.x.ai/developers/model-capabilities/text/reasoning | 2026-08-01 |
| Mistral | https://docs.mistral.ai/api/endpoint/models | 2026-08-01 |
| 火山方舟 | https://www.volcengine.com/docs/82379/1795150 | 2026-08-01 |
| DashScope | https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope | 2026-08-01 |
| Z.AI | https://docs.z.ai/api-reference/llm/chat-completion | 2026-08-01 |
| 智谱 CN | https://open.bigmodel.cn/dev/api | 2026-08-01 |
| 硅基流动 | https://docs.siliconflow.cn/en/api-reference/models/get-model-list | 2026-08-01 |
| MiMo | https://platform.xiaomimimo.com/docs | 2026-08-01 |
| 腾讯混元 | https://cloud.tencent.com/document/product/1729/111007 | 2026-08-01 |
| StepFun | https://platform.stepfun.com/docs/zh/api-reference/chat/chat-completion-create | 2026-08-01 |
| 百度千帆 | https://cloud.baidu.com/doc/WENXINWORKSHOP/ | 2026-08-01 |
| OpenRouter | https://openrouter.ai/docs/api/api-reference/models/get-models | 2026-08-01 |
| ModelScope | https://www.modelscope.cn/docs/model-service/API-Inference/intro | 2026-08-01 |
| Together | https://docs.together.ai/docs/inference/openai-compatibility | 2026-08-01 |
| Fireworks | https://docs.fireworks.ai/api-reference/list-models | 2026-08-01 |
| Moonshot/Kimi | https://platform.moonshot.cn/docs | 2026-08-01 |

价格、账号 `/models` 结果和精确 model ID 仍按 unknown 处理，直到有对应官方页面或用户账号返回的证据。
