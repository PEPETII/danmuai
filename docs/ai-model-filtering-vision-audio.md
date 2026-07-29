# 视觉理解与语音模型筛选说明

> **阶段性筛选规则（2026-06-29）**：本文解释筛选口径；[筛选报告](ai-model-filtering-vision-audio-report.md) 记录当次结果，[数据源分析](ai-platform-source-from-cherry-litellm.md) 记录 Cherry Studio 与 LiteLLM 的字段映射。三者职责不同，不互相替代。
>
> **复现前置条件（已确认）**：正文引用的 `packages/provider-registry/...` 与根级 `model_prices_and_context_window.json` 当前不在本仓库，现有可读产物位于 `data/ai-platforms/`。若要重跑筛选，必须先取得并固定上游数据快照/版本，再按本规则生成；不能仅凭现有文档还原当时输入。

---

## 1. 本次筛选范围

本次筛选仅覆盖以下两类模型：

- **视觉理解模型**：能够接收图片输入并理解图片内容的对话/聊天模型
- **语音识别/语音理解模型**：能够接收音频输入并完成转写或理解的模型

筛选目的是为 DanmuAI 的截图理解（视觉）和麦克风语音（音频）两条链路确定可用模型候选集。

---

## 2. 明确说明排除项

以下类型的模型**不在**本次筛选范围内，即使它们在源数据中出现也会被排除：

| 排除类型 | 说明 |
|----------|------|
| OCR 模型 | 仅做文字识别，不具备视觉理解能力 |
| 图片生成模型 | 输出图片而非理解图片 |
| 图片编辑模型 | 对图片进行编辑操作，非理解 |
| TTS 模型 | 文本转语音，属于语音生成而非识别 |
| 音乐生成模型 | 生成音乐，与语音识别无关 |
| 普通聊天模型 | 无图片/音频输入能力的纯文本对话模型 |
| 弹幕文本模型 | DanmuAI 自身的弹幕文本生成模型，不在本筛选范围 |

---

## 3. 视觉理解模型的判断依据

### Cherry Studio 判断规则

- `capabilities` 数组包含 `"image-recognition"`
- 且模型具备对话能力（非仅生成图片）

### LiteLLM 判断规则

- `supports_vision=true` 且 `mode="chat"`

### 排除规则

以下情况即使满足上述条件也会被排除：

- `isOcrOnly=true`：仅做 OCR，非视觉理解
- `isImageGenerationOnly=true`：仅生成图片
- `capabilities` 仅含 `image-generation` 而不含 `image-recognition`

---

## 4. 语音识别模型的判断依据

### Cherry Studio 判断规则

- `capabilities` 数组包含 `"audio-transcript"`

### LiteLLM 判断规则

- `mode="audio_transcription"`

### 排除规则

- TTS 模型（`mode="audio_speech"`）：文本转语音，非语音识别
- 音乐生成模型：生成音乐，与语音识别无关
- 普通聊天模型：不具备音频转写能力

---

## 5. 直接语音理解模型的判断依据

「直接语音理解」模型与「先转写再理解」的模型有本质区别：

- **先转写再理解**：模型仅将音频转为文本，由下游模型理解文本语义
- **直接语音理解**：模型直接接收音频输入，在对话中理解语音内容（语气、情绪、环境声等）

### Cherry Studio 判断规则

- `capabilities` 包含 `"audio-recognition"` 且 `inputModalities` 包含 `"audio"`

### LiteLLM 判断规则

- `supports_audio_input=true` 且 `mode="chat"`

### 关键区别

直接语音理解模型的 `mode` 为 `"chat"`（而非 `"audio_transcription"`），意味着它们在对话语境中理解音频，而非仅仅输出转写文本。DanmuAI 的麦克风链路如需理解语音语义（而非仅转写），应优先选择此类模型。

---

## 6. Cherry Studio 中用于判断的来源文件

| 文件 | 用途 |
|------|------|
| `providers.json` | 提供 provider id、baseURL、adapterFamily，用于确定模型的提供方和适配器类型 |
| `models.json` | 提供模型的 capabilities（image-recognition / audio-transcript / audio-recognition）、inputModalities（audio / image）、contextWindow 等关键字段 |
| `provider-models.json` | provider 级别的模型覆盖，某些 provider 会对通用模型的 capabilities 做增删 |
| `enums.ts` | 定义 EndpointType 枚举，包含 `openai-audio-transcription` 等端点类型，用于判断模型所属 API 类别 |
| `provider.ts` | 运行时类型定义，包含 AuthType、ProviderSettings 等，用于理解 provider 的认证和配置方式 |

### 字段优先级

当 `models.json` 与 `provider-models.json` 存在冲突时，`provider-models.json` 的覆盖优先级更高，因为它反映了特定 provider 下模型的实际能力。

---

## 7. LiteLLM 中用于判断的来源文件

| 文件 | 用途 |
|------|------|
| `model_prices_and_context_window.json` | 核心数据源，包含 supports_vision、mode、supports_audio_input、pricing、context_window 等字段 |
| `litellm/llms/openai/transcriptions/` | Whisper 转录实现代码，用于验证 audio_transcription 模式的实际调用方式 |

### 关键字段说明

- `supports_vision`：布尔值，标记模型是否支持图片输入
- `supports_audio_input`：布尔值，标记模型是否支持音频输入
- `mode`：模型的主要模式，常见值：`chat`、`audio_transcription`、`audio_speech`、`image_generation`
- `pricing`：包含 input/output token 价格，用于成本评估

---

## 8. 最终入选模型列表

### 统计数字

| 类别 | 数量 |
|------|------|
| 视觉理解候选 | 904 |
| 语音转写 | 17 |
| 直接音频理解 | 85 |
| 语音 needsReview | 24 |

### 说明

- **视觉理解候选（904）**：同时满足 Cherry Studio `image-recognition` 能力或 LiteLLM `supports_vision=true` + `mode="chat"` 的模型，排除 OCR-only 和 image-generation-only 后的候选集
- **语音转写（17）**：满足 Cherry Studio `audio-transcript` 或 LiteLLM `mode="audio_transcription"` 的模型
- **直接音频理解（85）**：满足 Cherry Studio `audio-recognition` + `audio` inputModalities 或 LiteLLM `supports_audio_input=true` + `mode="chat"` 的模型
- **语音 needsReview（24）**：具备部分音频能力但判断依据不完全清晰的模型，需人工复核

---

## 9. 被排除模型列表及原因

### 视觉模型排除（20 个）

以下模型因 `isOcrOnly=true` 或仅具备 `image-generation` 能力而被排除：

| 排除原因 | 说明 |
|----------|------|
| OCR-only | 模型仅做光学字符识别，不具备视觉理解能力（如识别场景、物体、关系等） |
| image-generation-only | 模型仅生成图片，`capabilities` 中只有 `image-generation` 而无 `image-recognition` |

> 具体被排除的 20 个模型名称详见筛选脚本的输出文件。

### TTS 模型排除

- `mode="audio_speech"` 的模型全部排除
- 此类模型的功能是文本转语音（Text-to-Speech），与 DanmuAI 的语音识别/理解需求相反

---

## 10. needsReview 模型列表及原因

以下模型具备部分相关能力，但无法通过自动化规则明确判定是否应入选，需人工复核。

### 类型 A：音频能力不完整的模型（24 个）

**判断条件**：Cherry Studio 中 `capabilities` 包含 `audio-recognition`，但：

- **没有** `audio-transcript` 能力
- **没有** `audio` 在 `inputModalities` 中

**疑点**：`audio-recognition` 表明模型具备音频理解能力，但缺少 `audio` 输入模态声明可能是数据缺失，也可能是模型实际不支持音频输入。需要逐一确认：

1. 若为数据缺失 → 补充 `inputModalities` 后可入选直接音频理解类别
2. 若模型实际不支持音频输入 → 排除

### 类型 B：视觉能力不确定的模型

**判断条件**：`capabilities` 同时包含 `video-generation` 和 `image-recognition`

**疑点**：此类模型的主要能力可能是视频生成，`image-recognition` 可能是辅助能力（如用于理解生成请求中的参考图），而非独立的视觉理解能力。需要确认：

1. `image-recognition` 是否可用于独立视觉理解场景
2. 模型是否支持图片输入作为对话内容（而非仅作为生成参考）

### 处理建议

- 对于类型 A，建议查阅模型官方文档确认音频输入支持情况
- 对于类型 B，建议实际调用模型 API 测试视觉理解能力
- 复核完成后，将确认入选的模型移入对应类别，确认排除的模型记入排除列表
