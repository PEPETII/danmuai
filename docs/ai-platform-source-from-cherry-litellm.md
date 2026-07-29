# AI 平台配置源分析报告 — Cherry Studio + LiteLLM

> **历史数据映射快照（2026-06-29）**：本文说明上游字段如何映射到 `data/ai-platforms/`；筛选规则见 [视觉/语音筛选说明](ai-model-filtering-vision-audio.md)，当次输出见 [筛选报告](ai-model-filtering-vision-audio-report.md)。
>
> **复现限制（已确认）**：文中 Cherry Studio `packages/provider-registry/...` 和 LiteLLM `model_prices_and_context_window.json` 当前不在本仓库，无法仅靠现有文件重跑同一输入。复现时需取得具有明确版本的上游快照，保留许可证与来源信息，再核对生成文件 diff；现有 `data/ai-platforms/*.json` 只能作为结果快照。
>
> 生成日期: 2026-06-29
> 数据来源: Cherry Studio (GPL-3.0) + LiteLLM (MIT)

---

## 1. Cherry Studio 中保存 Provider 配置的文件路径

**主文件**: `packages/provider-registry/data/providers.json`

- 63 个 provider，每个包含: id、name、description、defaultChatEndpoint、endpointConfigs、apiFeatures、metadata(website)
- `endpointConfigs` 按 EndpointType 组织，每个 endpoint 含 `baseUrl`、`adapterFamily`、可选 `modelsApiUrls` 和 `reasoningFormat`
- Schema 定义: `packages/provider-registry/src/schemas/provider.ts`

**运行时类型定义**: `src/shared/data/types/provider.ts`

- Provider 合并类型（用户配置 + 预设合并后的最终态）
- 关键字段: id、presetProviderId、name、endpointConfigs、defaultChatEndpoint、apiKeys、authType、apiFeatures、settings
- AuthType 枚举: `api-key` / `oauth` / `iam-aws` / `api-key-aws` / `iam-gcp` / `iam-azure`
- ProviderSettings 含: apiVersion (Azure)、cacheControl (Anthropic)、extraHeaders、serviceTier (OpenAI)、keepAliveTime (Ollama)

**配置构建逻辑**: `src/main/ai/provider/config.ts`

- 按 provider 类型构建请求配置 (ProviderConfig)
- 包含 Copilot/CherryAI/Ollama/Azure/DashScope/Bedrock/Vertex/Cherryin/NewAPI/AiHubMix 等特殊构建逻辑

---

## 2. Cherry Studio 中保存模型列表的文件路径

**主文件**: `packages/provider-registry/data/models.json`

- 模型目录基础定义，每个模型含: id、name、capabilities、contextWindow、maxOutputTokens、maxInputTokens、inputModalities、outputModalities、pricing、reasoning、ownedBy、family
- UniqueModelId 格式: `providerId::modelId`

**Provider 级别覆盖**: `packages/provider-registry/data/provider-models.json`

- 按 provider 维度覆盖模型配置（如 pricing、apiModelId 等）
- 用于 gateway/代理类 provider 的模型定价差异

**模型列表获取逻辑**: `src/main/ai/provider/listModels.ts` + `listModelsSchemas.ts`

- 不同 provider 用不同的 models API URL 获取模型列表

**运行时类型定义**: `src/shared/data/types/model.ts`

- Model 合并类型，字段: id(UniqueModelId)、providerId、apiModelId、name、capabilities、contextWindow、maxOutputTokens、maxInputTokens、endpointTypes、supportsStreaming、reasoning、parameterSupport、pricing、imageGeneration
- capabilities 枚举: function-call / reasoning / image-recognition / image-generation / audio-recognition / audio-generation / embedding / rerank / audio-transcript / video-recognition / video-generation / structured-output / file-input / web-search / code-execution / file-search / computer-use

---

## 3. Cherry Studio 中保存默认 API 地址 / apiHost / baseURL 的文件路径

**主文件**: `packages/provider-registry/data/providers.json` 中的 `endpointConfigs[endpointType].baseUrl`

关键默认 API 地址（从 providers.json 提取）:

| Provider ID | 默认 BaseURL |
|---|---|
| openai | https://api.openai.com |
| anthropic | https://api.anthropic.com |
| gemini | https://generativelanguage.googleapis.com |
| azure-openai | 无默认（用户配置） |
| ollama | http://localhost:11434 |
| deepseek | https://api.deepseek.com |
| zhipu | https://open.bigmodel.cn/api/paas/v4/ |
| dashscope | https://dashscope.aliyuncs.com/compatible-mode/v1/ |
| doubao | https://ark.cn-beijing.volces.com/api/v3/ |
| silicon | https://api.siliconflow.cn/v1 |
| openrouter | https://openrouter.ai/api/v1/ |
| moonshot | https://api.moonshot.cn |
| minimax | https://api.minimaxi.com/v1/ |
| hunyuan | https://api.hunyuan.cloud.tencent.com |
| baidu-cloud | https://qianfan.baidubce.com/v2/ |
| groq | https://api.groq.com/openai |
| mistral | https://api.mistral.ai |
| grok | https://api.x.ai/v1 |
| together | https://api.together.xyz |
| fireworks | https://api.fireworks.ai/inference |
| nvidia | https://integrate.api.nvidia.com |
| yi | https://api.lingyiwanwu.com |
| stepfun | https://api.stepfun.com |
| baichuan | https://api.baichuan-ai.com |
| ppio | https://api.ppinfra.com/v3/openai/ |
| huggingface | https://router.huggingface.co/v1/ |
| github | https://models.github.ai/inference |

**URL 格式化逻辑**: `src/main/ai/provider/config.ts` → `formatBaseURL()`

- Ollama: `formatOllamaApiHost()` 附加 `/api`
- Gemini: `formatApiHost(baseURL, appendApiVersion, 'v1beta')`
- Azure: 附加 `/openai` 后缀
- 某些 provider 不附加 API version (copilot, github, cherryai, perplexity, newapi, azure-openai)

---

## 4. Cherry Studio 中区分 Provider Type 的代码路径

### EndpointType 枚举 (`packages/provider-registry/src/schemas/enums.ts`)

```
anthropic-messages / google-generate-content / jina-rerank /
ollama-chat / ollama-generate / openai-audio-transcription /
openai-audio-translation / openai-chat-completions / openai-embeddings /
openai-image-edit / openai-image-generation / openai-responses /
openai-text-completions / openai-text-to-speech / openai-video-generation
```

### adapterFamily（在 endpointConfigs 中声明）

区分逻辑: 每个端点类型关联一个 adapterFamily，决定使用哪个 AI SDK adapter:
- `openai-compatible`: 通用 OpenAI 兼容（默认）
- `anthropic`: Anthropic 原生协议
- `google`: Gemini 原生协议
- `azure`: Azure OpenAI
- `ollama`: Ollama 原生
- `bedrock`: AWS Bedrock
- `google-vertex` / `google-vertex-anthropic`: Vertex AI
- `openrouter`: OpenRouter
- `deepseek`: DeepSeek 专用
- `groq`: Groq 专用
- `mistral`: Mistral 专用
- `xai` / `xai-responses`: xAI/Grok
- `cherryin`: CherryIN 代理
- `aihubmix`: AiHubMix 代理
- `newapi`: NewAPI 代理
- `huggingface`: Hugging Face
- `perplexity`: Perplexity
- `togetherai`: Together AI
- `voyage`: VoyageAI
- `gateway`: Vercel AI Gateway

### Factory 模式 (`src/main/ai/provider/factory.ts`)

- `getAiSdkProviderId(provider, model)`: 根据有效端点类型解析 AI SDK provider ID
- `providerToAiSdkConfig(provider, model)`: 构建请求配置，内含 ConfigBuilderEntry 匹配链

---

## 5. Cherry Studio 中与 apiKey / headers / apiVersion / authType 相关的字段

### AuthType (`src/shared/data/types/provider.ts:85`)

```typescript
type AuthType = 'api-key' | 'oauth' | 'iam-aws' | 'api-key-aws' | 'iam-gcp' | 'iam-azure'
```

### AuthConfig（鉴权配置详情）

| AuthType | 字段 |
|---|---|
| api-key | headerName?, prefix?, required? |
| oauth | clientId, refreshToken?, accessToken?, expiresAt? |
| iam-aws | region, accessKeyId?, secretAccessKey? |
| api-key-aws | region |
| iam-gcp | project, location, credentials? |
| iam-azure | apiVersion, deploymentId? |

### ApiKeyEntry (`src/shared/data/types/provider.ts:70-81`)

- id (UUID), key (实际值), label?, isEnabled

### ProviderSettings (`src/shared/data/types/provider.ts:163-208`)

- `apiVersion` (string, optional) — Azure 专用
- `extraHeaders` (Record<string, string>, optional) — 自定义请求头
- `cacheControl` (Anthropic 专用) — enabled, tokenThreshold, cacheSystemMessage, cacheLastNMessages
- `serviceTier` (OpenAI/Groq 专用)
- `streamOptions` — includeUsage
- `keepAliveTime` (Ollama/LMStudio/GPUStack 专用)

### 自定义 Headers UI

`src/renderer/pages/settings/ProviderSettings/ConnectionSettings/ProviderCustomHeaderDrawer.tsx`

### 特殊 Headers

- OpenRouter: 无内建特殊 header，但 DanmuAI 项目在 `app/providers/registry.py:provider_extra_headers()` 中为 OpenRouter 注入了 `HTTP-Referer` 和 `X-Title`
- Copilot: `COPILOT_DEFAULT_HEADERS` (constants.ts) — Copilot-Integration-Id, User-Agent, Editor-Version 等
- CherryAI: 请求签名 (`src/main/ai/provider/cherryai/`)

---

## 6. LiteLLM 中保存模型价格和上下文窗口的文件路径

**主文件**: `model_prices_and_context_window.json`

- 每个模型一条记录，key 为模型 ID
- 示例字段: litellm_provider, max_tokens, max_input_tokens, max_output_tokens, input_cost_per_token, output_cost_per_token, supports_vision, supports_function_calling, supports_parallel_function_calling, supports_audio_input, supports_audio_output, supports_reasoning, supports_prompt_caching, supports_response_schema, supports_system_messages, supports_web_search, mode, deprecation_date, supported_regions

---

## 7. LiteLLM 中保存 Provider Adapter 的目录路径

**主目录**: `litellm/llms/`

主要 provider 子目录:

| 目录 | 对应 Provider |
|---|---|
| anthropic/ | Anthropic Claude |
| openai/ | OpenAI |
| azure/ | Azure OpenAI |
| bedrock/ | AWS Bedrock |
| gemini/ | Google Gemini |
| mistral/ | Mistral AI |
| xai/ | xAI (Grok) |
| sambanova/ | SambaNova |
| cerebras/ | Cerebras |
| aiml/ | AI/ML API |
| baseten/ | Baseten |
| ovhcloud/ | OVHcloud |
| v0/ | Vercel v0 |
| wandb/ | Weights & Biases |
| zai/ | Z.AI |
| sap/ | SAP AI |
| langflow/ | Langflow |
| manuscripts/ | Manuscripts |
| e2b/ | E2B |

---

## 8. LiteLLM 中与 provider / api_base / context window / pricing 相关的字段

### 核心字段

| 字段 | 说明 |
|---|---|
| `litellm_provider` | Provider 标识 (openai / anthropic / bedrock / vertex_ai / gemini / azure / etc.) |
| `max_tokens` | 旧字段，等同于 max_output_tokens 或 max_input_tokens |
| `max_input_tokens` | 最大输入 token 数 |
| `max_output_tokens` | 最大输出 token 数 |
| `input_cost_per_token` | 输入每 token 价格（USD） |
| `output_cost_per_token` | 输出每 token 价格（USD） |
| `input_cost_per_audio_token` | 音频输入每 token 价格 |
| `output_cost_per_reasoning_token` | 推理 token 输出价格 |
| `mode` | chat / embedding / completion / image_generation / audio_transcription / audio_speech / moderation / rerank / search |
| `supports_vision` | 是否支持视觉 |
| `supports_function_calling` | 是否支持函数调用 |
| `supports_parallel_function_calling` | 是否支持并行函数调用 |
| `supports_audio_input` | 是否支持音频输入 |
| `supports_audio_output` | 是否支持音频输出 |
| `supports_reasoning` | 是否支持推理 |
| `supports_prompt_caching` | 是否支持 prompt 缓存 |
| `supports_response_schema` | 是否支持结构化输出 |
| `supports_system_messages` | 是否支持系统消息 |
| `supports_web_search` | 是否支持 Web 搜索 |
| `supported_regions` | 支持的区域列表 |
| `deprecation_date` | 废弃日期 |

---

## 9. 哪些资料可以直接转成 providers.json

**可直接迁移**（公开配置事实，无版权风险）:

1. **Cherry Studio providers.json 的 id/name/baseUrl/endpointConfigs/adapterFamily/defaultChatEndpoint** → 已转换到 `data/ai-platforms/providers.json`
2. **metadata.website（official/apiKey/docs/models 链接）** → 已转换，纯公开 URL
3. **apiFeatures（arrayContent/streamOptions/developerRole/serviceTier/verbosity）** → 已转换，纯技术特征
4. **EndpointType 枚举** → 已映射到 protocol 字段
5. **AuthType 枚举值** → 已映射到 authStyle 字段

---

## 10. 哪些资料可以直接转成 models.json

**可直接迁移**:

1. **LiteLLM model_prices_and_context_window.json 的 litellm_provider/max_tokens/max_input_tokens/max_output_tokens** → 已转换到 `data/ai-platforms/models.json` 的 contextWindow/maxInputTokens/maxOutputTokens
2. **LiteLLM 的 input_cost_per_token/output_cost_per_token** → 已转换到 pricing.inputPerMTok/outputPerMTok（×1000000）
3. **LiteLLM 的 supports_vision/supports_function_calling/supports_audio_input/supports_reasoning** → 已转换到对应布尔字段
4. **Cherry Studio models.json 的 capabilities/pricing/contextWindow/maxOutputTokens** → 已转换，补充模型能力信息
5. **Cherry Studio provider-models.json 的 provider 级别定价覆盖** → 已转换

---

## 11. 哪些资料只能作为参考，不能直接抄

**仅参考，不直接迁移**:

1. **Cherry Studio 的 AuthConfig 实现**（api-key headerName/prefix、OAuth 流程、AWS IAM 签名）→ DanmuAI 目前只支持 Bearer token，需按需集成
2. **Cherry Studio 的 ProviderSettings**（apiVersion、cacheControl、extraHeaders）→ 功能字段，需按 DanmuAI 架构适配
3. **Cherry Studio 的 ReasoningFormatType**（openai-chat/openai-responses/anthropic/gemini/openrouter/enable-thinking/thinking-type/dashscope/self-hosted）→ DanmuAI 固定禁用 thinking，不需要
4. **Cherry Studio 的自定义 provider 实现代码**（dashscopeProvider/siliconProvider/zhipuProvider 等）→ 业务代码，不能复制
5. **LiteLLM 的 provider adapter 代码**（litellm/llms/ 下各 provider 的请求构建逻辑）→ 业务代码，不能复制
6. **Cherry Studio 的 CherryIN/CherryAI 签名逻辑** → 业务代码，不能复制
7. **Cherry Studio 的 Copilot auth 流程** → 业务代码，不能复制
8. **两个项目的 UI 组件代码** → 不能复制
9. **两个项目的品牌资源/图标** → 不能复制
10. **Cherry Studio 的 ImageGenerationSupport / ImageModeDef** → DanmuAI 不做图像生成，不需要
11. **LiteLLM 的 model_prices_and_context_window.json 中的非 chat 模型**（embedding/image_generation/audio 等）→ DanmuAI 当前只需要 chat + vision 模型

---

## 附录: 生成文件清单

| 文件 | 记录数 | 来源 |
|---|---|---|
| `data/ai-platforms/providers.json` | 63 providers | Cherry Studio |
| `data/ai-platforms/models.json` | 200 models | LiteLLM + Cherry Studio |
| `data/ai-platforms/access-modes.json` | 63 accessModes | Cherry Studio (推断) |
| `data/ai-platforms/source-map.json` | 溯源映射 | - |
| `docs/ai-platform-source-from-cherry-litellm.md` | 本报告 | - |
