# AI 模型筛选报告：视觉理解与语音能力

> **阶段性结果快照**：生成日期 2026-06-29；模型能力、价格和供应商字段可能随上游变化。筛选口径见 [视觉/语音筛选说明](ai-model-filtering-vision-audio.md)，字段来源见 [数据源分析](ai-platform-source-from-cherry-litellm.md)。
>
> **复现前置条件（已确认）**：本报告列出的 Cherry Studio `packages/provider-registry/...` 与 LiteLLM 根级 JSON 当前未保留在仓库；只能确认生成产物仍位于 `data/ai-platforms/`。重新生成前须补齐并固定上游快照，记录来源 commit/版本与执行命令。

---

## 1. 筛选基于哪些文件

本次筛选的数据源如下：

| 来源 | 文件路径 | 说明 |
|------|----------|------|
| Cherry Studio | `packages/provider-registry/data/providers.json` | 服务商注册信息 |
| Cherry Studio | `packages/provider-registry/data/models.json` | 模型能力定义 |
| Cherry Studio | `packages/provider-registry/data/provider-models.json` | 服务商-模型映射 |
| LiteLLM | `model_prices_and_context_window.json` | 模型定价与上下文窗口 |
| 已生成数据 | `data/ai-platforms/providers.json` | 聚合后的服务商列表 |
| 已生成数据 | `data/ai-platforms/access-modes.json` | 访问模式定义 |
| 已生成数据 | `data/ai-platforms/models.json` | 聚合后的模型列表 |

筛选逻辑：合并 Cherry Studio 和 LiteLLM 的模型数据，按能力标签过滤，去重后得到最终候选集。

---

## 2. 筛选出多少个视觉理解模型

- **候选模型总数**：904 个（来自 Cherry Studio + LiteLLM 合并去重后）
- **被排除模型**：20 个
  - OCR-only 模型：仅有光学字符识别能力，不具备通用视觉理解
  - image-generation-only 模型：仅有图片生成能力，不具备视觉理解输入
- **最终视觉理解模型**：884 个

排除判定依据：模型的 `mode` 字段或能力标签表明其视觉功能仅限于 OCR 或图片生成，而非通用视觉理解（如场景描述、截图分析等）。

---

## 3. 筛选出多少个语音转写模型

- **语音转写模型**：17 个

典型模型包括：

| 模型 ID | 服务商 | 说明 |
|---------|--------|------|
| `whisper-1` | OpenAI | 通用语音转写 |
| `whisper-large-v3` | Groq / DeepInfra | Whisper V3 大模型 |
| `gpt-4o-transcribe` | OpenAI | GPT-4o 驱动的高质量转写 |
| `gpt-4o-mini-transcribe` | OpenAI | GPT-4o-mini 驱动的低成本转写 |

转写模型的特征：`mode` 为 `audio_transcription` 或能力标签中包含 `transcription`，输入为音频，输出为纯文本。

---

## 4. 筛选出多少个直接语音理解模型

- **直接语音理解模型（directAudioUnderstanding）**：85 个

典型模型包括：

| 模型 ID | 服务商 | 说明 |
|---------|--------|------|
| `gemini-2-5-flash` | Google | 多模态，原生音频输入 |
| `gemini-2-5-pro` | Google | 多模态，原生音频输入 |
| `qwen2-5-omni` | 阿里云 | 全模态，音频直接理解 |
| `gpt-4o-audio-preview` | OpenAI | 音频输入预览版 |
| `grok-4` | xAI | 多模态音频理解 |

直接语音理解 vs 转写的关键区别：直接语音理解模型能接收音频输入并直接在多模态上下文中理解和推理，无需先转写为文本。

---

## 5. 默认推荐候选

从 `model-selection-presets.json` 的 `visionUnderstanding.default` 列出前 10 个推荐模型：

| 序号 | 模型 ID | 服务商 | 特点 |
|------|---------|--------|------|
| 1 | `gpt-5.5` | OpenAI | 最新旗舰视觉模型 |
| 2 | `gpt-5.4` | OpenAI | 高质量视觉理解 |
| 3 | `gpt-5.4-mini` | OpenAI | 性价比平衡 |
| 4 | `gemini-2-5-pro` | Google | 多模态旗舰 |
| 5 | `gemini-2-5-flash` | Google | 多模态快速版 |
| 6 | `claude-sonnet-4.5` | Anthropic | 高质量视觉推理 |
| 7 | `claude-opus-4` | Anthropic | 顶级视觉理解 |
| 8 | `deepseek-vl` | DeepSeek | 国产视觉模型 |
| 9 | `deepseek-vl-chat` | DeepSeek | 国产视觉对话模型 |
| 10 | `qwen-vl-max` | 阿里云 | 通义千问视觉旗舰 |

这些模型覆盖了主流服务商的视觉理解能力，适合作为 DanmuAI 截图识图的默认推荐。

---

## 6. 低成本候选

适合预算有限或高频调用场景的模型：

| 模型 ID | 服务商 | 说明 |
|---------|--------|------|
| `gpt-4.1-mini` | OpenAI | 低成本 GPT-4.1 系 |
| `gpt-4.1-nano` | OpenAI | 最低成本 GPT-4.1 系 |
| `gemini-3-flash-preview` | Google | Flash 系列预览版 |
| `deepseek-vl-chat` | DeepSeek | 国产低成本视觉 |
| `qwen-vl-plus` | 阿里云 | 通义千问视觉经济版 |
| `glm-4v-flash` | 智谱 AI | GLM 视觉快速版 |

低成本模型的筛选标准：按 `model_prices_and_context_window.json` 中的定价，输入 token 单价低于 $0.5/1M token。

---

## 7. 高质量候选

适合对识图准确率要求最高的场景：

| 模型 ID | 服务商 | 说明 |
|---------|--------|------|
| `gpt-5.5` | OpenAI | 当前最强视觉理解 |
| `claude-sonnet-4.5` | Anthropic | 顶级视觉推理与细节捕捉 |
| `claude-opus-4` | Anthropic | 最高质量视觉理解 |
| `gemini-2-5-pro` | Google | 多模态旗舰 |
| `grok-4` | xAI | 多模态高性能 |
| `o3` | OpenAI | 推理增强视觉 |

高质量模型的筛选标准：综合视觉理解基准测试排名和用户反馈，优先选择最新旗舰级模型。

---

## 8. 本地候选

通过 Ollama 等本地运行时可使用的视觉模型：

| 模型 ID | 运行时 | 说明 |
|---------|--------|------|
| `llava` | Ollama | 开源视觉对话模型 |
| `llava-llama3` | Ollama | LLaVA + Llama 3 |
| `llama-3.2-vision` | Ollama | Meta 官方视觉模型 |
| `minicpm-v` | Ollama | 小型视觉模型 |
| `qwen2-vl` | Ollama | 通义千问视觉本地版 |
| `phi-3.5-vision` | Ollama | 微软小型视觉模型 |

本地模型的特征：无需 API Key，通过 `http://localhost:11434`（Ollama 默认端口）以 OpenAI 兼容接口访问。适合隐私敏感或离线场景。

---

## 9. 排除项和排除理由

以下类型模型被明确排除在视觉理解/语音理解候选之外：

| 排除类别 | 排除理由 | 典型示例 |
|----------|----------|----------|
| OCR-only 模型 | 仅有光学字符识别能力，不具备通用视觉理解（无法描述场景、分析截图内容） | 百度 OCR、腾讯 OCR |
| image-generation-only 模型 | 仅能生成图片，无法接收和理解图片输入 | DALL·E 3、Stable Diffusion |
| video-generation-primary 模型 | 主要能力为视频生成，视觉理解非主要能力 | Sora、Kling |
| TTS 模型（`mode=audio_speech`） | 语音合成，不是语音理解/转写 | `tts-1`、`tts-1-hd` |
| embedding 模型 | 文本向量化，不支持视觉理解输入 | `text-embedding-3-small` |
| rerank 模型 | 文本重排序，不支持多模态输入 | `cohere-rerank` |

排除逻辑：检查 `mode` 字段和能力标签，当模型的唯一或主要能力不属于视觉理解或语音理解时排除。

---

## 10. needsReview 清单

以下模型存在能力标签不明确的情况，需要人工确认：

### 10.1 音频模型待确认（24 个）

这些模型仅有 `audio-recognition` 能力标签，但无法确定是转写（transcription）还是直接语音理解（directAudioUnderstanding）：

- 标记为 `needsReview: true`
- 需要逐一检查服务商文档确认实际能力

### 10.2 视频生成 + 图片理解模型

部分模型同时具备 `video-generation` 和 `image-recognition` 能力：

- 视觉理解可能不是其主要能力
- 需要确认视觉理解质量是否满足截图识图需求
- 建议在 UI 中标记为"实验性"

---

## 11. 下一步如何接入 UI

### 11.1 视觉理解模型下拉框

- 数据源：`model-selection-presets.json` 的 `visionUnderstanding.default`
- 默认展示推荐模型列表
- 提供"低成本"/"高质量"/"本地"分组标签页
- 选中模型后自动填充 `modelId` 和 `provider` 配置

### 11.2 语音识别模型下拉框

- 数据源：`model-selection-presets.json` 的 `audio.transcription`
- 用于麦克风模式下的语音转文字场景
- 默认隐藏，仅在开启麦克风模式时展示

### 11.3 直接语音理解模型下拉框

- 数据源：`model-selection-presets.json` 的 `audio.directAudioUnderstanding`
- 用于麦克风模式下的直接语音理解场景（无需先转写）
- 默认隐藏，仅在开启麦克风模式时展示
- 选择后替代"转写+视觉"两步流程为"直接音频理解"一步流程

### 11.4 高级自定义模型入口

- 允许用户手动输入 `modelId` + `provider`
- 用于接入 presets 中未收录的模型
- 输入后需选择能力类型（视觉理解/语音转写/直接语音理解）
- 配置通过 `PUT /api/config` 写入，**不经** presets 文件

### 11.5 前端实现路径

| 组件 | 文件位置 | 说明 |
|------|----------|------|
| 模型选择器 UI | `web/static/` | 下拉框 + 分组标签页 |
| Presets 数据 | `data/ai-platforms/model-selection-presets.json` | 前端静态加载 |
| API 路由 | `app/web_api/routes.py` | 模型列表查询接口 |
| 配置写入 | `PUT /api/config` | 用户选择后保存配置 |

---

*本报告为 AI 模型筛选的阶段性成果，`needsReview` 清单中的模型待后续确认后更新。*
