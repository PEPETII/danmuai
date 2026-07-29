# AI管家 功能规格说明书

> **状态**：**功能已删除**（`W-AIBUTLER-REMOVE-*`，2026-07-23）。本文仅作历史规格存档，**不是**现行能力。  
> **编写日期**：2026-07-02  
> **最后更新**：2026-07-23（W-AIBUTLER-REMOVE：后端/路由/Web 页/CSS/i18n/hiddenimports 已移除）  
> **历史工单**：W-AIBUTLER-001 ~ 006、W-AIBUTLER-CHAT-ONLY-001（已被 REMOVE 计划取代）  
>
> **现行行为**：无 `POST /api/ai-butler/chat`、无侧边栏 AI 管家入口、无 `app/application/ai_butler_service.py`。用户改设置须在 Web 设置页手动操作。  
>
> 下文全文为删除前设计记录；实现文件与测试已不存在。

---

## 1. 功能概述

### 1.1 定位

「AI管家」是 DanmuAI 内置的**自然语言设置代理**。用户通过对话界面直接描述需求，AI 解析意图后自动修改系统设置，无需手动查找各个设置项。

### 1.2 核心价值

- **降低设置认知成本**：用户不需要记住「识图区域在弹幕设置页」等分散入口
- **减少操作路径**：一句话完成多步设置组合
- **提供变更安全感**：所有写操作必须经过确认，用户可随时取消

### 1.3 用户入口

侧边栏新增一级导航入口「🤖 AI管家」，点击后进入对话界面。

---

## 2. 界面布局

### 2.1 整体结构

```
┌──────────────────────────────────────────┐
│  🤖 AI管家                                │
│  ─────────────────────────────────────── │
│  我是你的设置助手，可以直接对我说：         │
│  "把弹幕速度调快一点"                     │
│  "把 API 改成 OpenAI 模式"               │
│  "开启麦克风模式"                         │
├──────────────────────────────────────────┤
│                                          │
│  当前使用模型：mimo-v2.5          [▼]    │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │ AI: 好的，我来为您把 API 模式切换   │  │
│  │ 为 openai。                         │  │
│  │                                    │  │
│  │ ┌─ 变更预览 ────────────────────┐  │  │
│  │ │ • API 模式: doubao → openai   │  │  │
│  │ │ • 视觉模型: 保持不变            │  │  │
│  │ └───────────────────────────────┘  │  │
│  │                                    │  │
│  │ [ 确认执行 ]    [ 取消 ]            │  │
│  └────────────────────────────────────┘  │
│                                          │
├──────────────────────────────────────────┤
│  ┌──────────────────────┐ [发送]        │
│  │ 告诉我想调整什么设置...│              │
│  └──────────────────────┘              │
└──────────────────────────────────────────┘
```

### 2.2 顶部能力说明

进入页面时，顶部展示静态的能力说明卡片：

```
我是你的设置助手，可以直接对我说：
• "把弹幕速度调快一点"
• "把 API 改成 OpenAI 模式"
• "开启麦克风模式"
• "识图区域选第二个显示器"
```

**设计要点**：
- 使用与设置页一致的 `.card` 样式
- 文案为静态文本，不随对话变化
- 用户首次使用后有印象，再次进入可折叠/最小化（可选）

### 2.3 当前模型展示

对话界面中部（输入框上方）固定展示：

```
当前使用模型：mimo-v2.5          [▼]
```

**设计要点**：
- 显示内容：当前 `default_model_id`（即【API与模型】页选中的"使用"模型）
- 下拉选择：点击 `[▼]` 可展开下拉框，切换当前使用的模型
- 切换后：后续对话自动使用新模型；当前对话历史保留
- 与后端集成：下拉选择走 `POST /api/custom-models/{index}/default`

---

## 3. 对话交互流程

### 3.1 正常流程（确认执行）

```
用户输入: "把 API 模式改成 openai"
    ↓
AI 解析意图 → 生成工具调用: { tool: "switch_api_mode", params: { mode: "openai" } }
    ↓
展示确认卡片:
  ┌─────────────────────────────────┐
  │ 📋 变更预览                       │
  │ • API 模式: doubao → openai      │
  └─────────────────────────────────┘
  [ 确认执行 ]    [ 取消 ]
    ↓
用户点击「确认执行」
    ↓
后端执行: PUT /api/config { api_mode: "openai" }
    ↓
成功: 对话追加系统消息 "✅ API 模式已切换为 openai"
失败: 对话追加系统消息 "❌ 设置保存失败: {error}"
```

### 3.2 用户取消流程

```
AI 展示确认卡片
    ↓
用户点击「取消」
    ↓
确认卡片消失，对话追加系统消息 "已取消"
（或静默消失，不追加消息）
```

**决策**：采用记录式 —— 确认卡片消失，对话中保留一条「已取消」的系统消息，让用户知道刚才发生了什么。

### 3.3 多工具调用流程

如果一句话触发多个设置变更：

```
用户输入: "把弹幕速度调快一点，透明度调高一点"
    ↓
AI 解析 → 生成两个工具调用:
  1. update_danmu_display({ danmu_speed: 8 })
  2. update_danmu_display({ opacity: 0.9 })
    ↓
展示确认卡片:
  ┌─────────────────────────────────┐
  │ 📋 变更预览（共 2 项）            │
  │ • 弹幕速度: 5 → 8               │
  │ • 透明度: 0.7 → 0.9             │
  └─────────────────────────────────┘
  [ 确认执行 ]    [ 取消 ]
    ↓
用户点击「确认执行」
    ↓
后端批量执行两个变更
```

---

## 4. AI 可控制的设置范围及权限

### 4.1 权限分级

| 级别 | 设置项 | 行为 | 示例 |
|------|--------|------|------|
| **自动执行** | `danmu_font_bold`、`danmu_speed`、`danmu_lines`、`opacity`、`dedup_threshold` | 无需确认，直接执行 | "把弹幕速度调快" |
| **确认后执行** | `api_endpoint`、`model`、`api_mode`、`screen_index`、`mic_mode_enabled` | 展示确认卡片 | "把 API 改成 OpenAI" |
| **禁止** | `api_key` | 工具层不暴露；AI 只回文字指引去设置页改 | "帮我改 API Key" → AI 回复「请在【弹幕设置 → API 与模型】页面修改」 |
| **仅建议** | 删除自定义模型、重置所有设置、清空弹幕池 | AI 只给出文字指引，不执行 | "帮我清空弹幕池" → AI 回复「请在公式化弹幕库页面操作」 |

### 4.2 工具定义（Function Calling Schema）

AI 仅可调用以下三个工具。工具层**不暴露** `api_key` / `use_thinking` / `persona_model_bindings` / 删除模型 / 清空弹幕池 等敏感字段（见 §4.3）。

#### 4.2.1 `update_config` —— 修改 WEB_CONFIG_KEYS 子集

```json
{
  "name": "update_config",
  "description": "修改弹幕显示、API 模式、识图屏幕等设置项。仅允许 WEB_CONFIG_KEYS 白名单内的键。",
  "parameters": {
    "type": "object",
    "properties": {
      "changes": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "key":   { "type": "string", "description": "配置键，如 danmu_speed / api_mode / opacity" },
            "value": { "type": "string", "description": "新值（字符串形式，与 ConfigStore 一致）" },
            "label": { "type": "string", "description": "人类可读的变更说明，如「弹幕速度: 5 → 8」" }
          },
          "required": ["key", "value", "label"]
        },
        "minItems": 1
      },
      "require_confirm": {
        "type": "boolean",
        "description": "true=确认级（前端必须展示确认卡片）；false=自动级（直接执行）。由 AI 按 §4.1 权限表填写。"
      }
    },
    "required": ["changes", "require_confirm"]
  }
}
```

**前端执行**：确认后调既有 `PUT /api/config`，payload 为 `{key: value, ...}`。

#### 4.2.2 `set_default_model` —— 切换当前使用模型

```json
{
  "name": "set_default_model",
  "description": "切换当前使用的模型档案（即【API与模型】页的「使用」模型）。按档案在列表中的 index 寻址。",
  "parameters": {
    "type": "object",
    "properties": {
      "index": { "type": "integer", "description": "目标模型档案的列表索引（0 起）" },
      "model_id": { "type": "string", "description": "目标 default_model_id（用于前端展示，实际按 index 切换）" },
      "label": { "type": "string", "description": "人类可读说明，如「视觉模型: doubao-seed → mimo-v2.5」" }
    },
    "required": ["index", "label"]
  }
}
```

**前端执行**：确认后调既有 `POST /api/custom-models/{index}/default`。此工具恒为「确认级」。

#### 4.2.3 `query_config` —— 只读查询当前配置（供 AI 决策）

```json
{
  "name": "query_config",
  "description": "查询当前配置值，用于在生成变更建议前确认现状（如当前 api_mode、当前 screen_index、有哪些模型档案）。",
  "parameters": {
    "type": "object",
    "properties": {
      "keys": { "type": "array", "items": { "type": "string" }, "description": "想查询的配置键列表；传 [\"custom_models\"] 返回模型档案概览（apiKey 掩码）" }
    },
    "required": ["keys"]
  }
}
```

**后端执行**：HTTP 线程直接读 `GET /api/config` 快照 + `GET /api/custom-models`，返回给 AI。不写、不触主链路。

#### 4.2.4 权限映射表

| 工具参数 | 权限级 | `require_confirm` |
|----------|--------|------------------|
| `danmu_font_bold` / `danmu_speed` / `danmu_lines` / `opacity` / `dedup_threshold` | 自动执行 | `false` |
| `api_endpoint` / `model` / `api_mode` / `screen_index` / `mic_mode_enabled` | 确认后执行 | `true` |
| `set_default_model`（任何参数） | 确认后执行 | 恒 `true` |
| 删除模型 / 重置所有设置 / 清空弹幕池 | 仅建议 | 不产生工具调用，AI 只回文字指引 |

### 4.3 权限边界（AI 绝对不能做的事）

- 删除自定义模型档案（`DELETE /api/custom-models/{id}`）
- **修改 `api_key`**（工具层完全不暴露此字段；AI 遇到「改 API Key」需求时只回文字指引：「请在【弹幕设置 → API 与模型】页面修改」，不生成 `update_config` 调用）
- 启用/禁用麦克风权限（涉及系统硬件；`mic_mode_enabled` 虽可写，但 AI 需先经 `query_config` 确认有可用设备，仍走确认卡片）
- 修改 `persona_model_bindings`（人格绑定可能影响多个人格）
- 修改 `use_thinking`（运行时固定 `thinking:disabled`，改了也无实际效果；工具层不暴露）
- 修改 `region_x/y/w/h`（识图子区域裁剪，由鼠标框选管理，不在 `WEB_CONFIG_KEYS`；AI 只能切整屏 `screen_index`）

**`screen_index` 副作用提示**：`screen_index` 属于 `SCENE_VERSION_CONFIG_KEYS`，修改会递增 `_scene_generation`，导致在途 AI 回复被丢弃（`reason=scene_generation_lagged`）。AI 在生成此工具调用时，label 应注明「切换屏幕会使当前生成中的回复失效」。

---

## 5. 确认按钮样式与反馈

### 5.1 视觉样式

确认卡片必须复用 DanmuAI 温馨设计系统（`warm-tokens-*.css`），**不写死 hex**，全部引用 token：

| 元素 | 复用类 / 实现 | 说明 |
|------|--------------|------|
| 确认卡片容器 | `.card`（`warm-tokens-base.css:131`） | `background: var(--color-surface)`; `border-radius: var(--radius-lg)`; `box-shadow: var(--shadow-warm)`；内边距 `p-5` |
| 变更预览标题 | `.settings-section-title`（`warm-tokens-pages.css:376`） | 「📋 变更预览」字号 0.9375rem / 700 |
| 变更行 | `.settings-field`（`warm-tokens-pages.css:398`） | 每行一个变更，`• {label}`；`background: rgba(255,255,255,0.85)`；暗黑模式自动随 token 翻转 |
| 确认执行按钮 | `.btn-primary`（`warm-tokens-base.css:143`） | `background: var(--color-primary)`（#ffa5a5）；hover → `--color-primary-hover`；文案「确认执行」 |
| 取消按钮 | 次级按钮样式（既有约定） | `bg-white border border-gray-200 rounded-xl font-semibold text-warmText hover:bg-gray-50` |
| 系统消息 | 新增 `.ai-butler-system-msg` | `color: var(--color-text-muted)`；`font-size: 0.75rem`；斜体 |
| 输入框 | `.settings-field-control`（`warm-tokens-pages.css:405`） | 与设置页输入框一致 |

**按钮状态类**（§5.2 引用）：

- `.ai-butler-btn-confirm`：默认 = `.btn-primary`；成功态附加 `background: #4ade80`（绿色，仅此一处例外，因 token 无成功色）；失败态附加 `background: #ef4444`（红色）。
- `.ai-butler-btn-loading`：`disabled` + 行内 spinner（`<svg class="animate-spin">`，Tailwind 自带）。
- `.ai-butler-chat-bubble`：用户消息靠右、AI 消息靠左；`border-radius: var(--radius-md)`；最大宽度 80%。
- `.ai-butler-msg-user`：`background: var(--color-primary-light)`（#ffc8c8）；`color: var(--color-text)`。
- `.ai-butler-msg-ai`：`background: var(--color-surface)`；`border: 1px solid var(--border)`。

**暗黑模式**：所有颜色经 token 自动翻转（`[data-theme="dark"]`，`warm-tokens-base.css:55`），无需额外规则。

### 5.2 反馈状态

| 状态 | 按钮文案 | 按钮样式 | 说明 |
|------|----------|----------|------|
| 待确认 | 确认执行 | `.ai-butler-btn-confirm` | 可点击 |
| 执行中 | 应用中... | `.ai-butler-btn-loading` | disabled，显示 spinner |
| 成功 | 完成 | `.ai-butler-btn-confirm`（绿色） | 短暂显示后消失 |
| 失败 | 重试 | `.ai-butler-btn-confirm`（红色） | 保留确认卡片，显示错误 |

---

## 6. 异常场景处理

### 6.1 用户取消

| 场景 | 处理 |
|------|------|
| 点击「取消」按钮 | 确认卡片消失，对话追加系统消息「已取消」 |
| 页面关闭/侧栏切换 | **静默取消**未确认卡片，追加「已取消」系统消息（不阻塞导航；与现有 `navigate()` 行为一致，见 §7.3） |
| 用户输入新消息覆盖 | 取消前一个变更计划，开始新的解析 |

### 6.2 设置冲突

| 场景 | AI 行为 |
|------|---------|
| 用户说「把 API 改成 OpenAI」，但当前有豆包 custom model | AI 主动询问：「检测到您有自定义豆包模型档案，切换 API 模式后这些档案将保留但不会自动生效，是否继续？」 |
| 用户说「开启麦克风」，但当前没有麦克风设备 | AI 回复：「未检测到麦克风设备，请先连接设备后再开启」 |
| 用户说「把模型改成 mimo-v2.5」，但当前 api_mode 是 doubao | AI 询问：「当前 API 模式为 doubao，是否同时切换为 openai-compatible 以适配 mimo-v2.5？」 |

### 6.3 LLM 解析失败

| 场景 | 处理 |
|------|------|
| 工具调用参数不合法 | 前端捕获 validation error，显示「我没太理解您的意思，请换个说法试试」 |
| LLM 返回空响应或超时 | 显示 toast「网络开小差了，请重试」，保留用户输入框内容 |
| 返回无法识别的意图 | 降级为普通对话，回复「我目前可以帮您调整弹幕设置，您可以试试说「把弹幕速度调快」」 |

### 6.4 配置写入失败

| 场景 | 处理 |
|------|------|
| `apply_config_patch` 返回错误 | 显示 toast「设置保存失败：{error.message}」，不关闭确认 UI |
| ConfigStore 加密异常 | 显示「配置存储异常，请重启应用」，不尝试自动恢复 |
| 网络请求超时 | 显示「应用设置超时，请重试」 |

---

## 7. 数据流与状态机

### 7.1 对话状态机（前端）

每个用户输入驱动一次状态流转；同一时刻只允许一条进行中的请求。

```
idle ──(用户发送)──▶ awaiting_llm
                         │
                  ┌───────┴────────┐
                  │ LLM 返回工具调用 │
                  ▼                ▼
        awaiting_confirm     plain_reply
                  │                │
        ┌─────────┴─────┐        (无工具调用)
        │               │             │
     [确认]           [取消]          ▼
        │               │          done
        ▼               ▼
     applying        cancelled
        │               │
   ┌────┴────┐          ▼
   │         │       done
 成功      失败
   │         │
   ▼         ▼
 done    awaiting_confirm（保留卡片，显示错误，可重试）
```

**状态定义**：

| 状态 | 前端行为 | 输入框 |
|------|----------|--------|
| `idle` | 等待用户输入 | 可用 |
| `awaiting_llm` | 显示「思考中…」气泡；发送按钮 disabled + spinner | disabled |
| `plain_reply` | 渲染 AI 纯文本回复（无工具调用） | 可用 |
| `awaiting_confirm` | 渲染确认卡片；发送按钮可用（新输入会取消当前计划，见 §6.1） | 可用 |
| `applying` | 卡片按钮进入 loading 态；输入框可用但发送会排队 | 可用 |
| `done` | 卡片转为「完成」短暂显示后消失；追加成功/失败系统消息 | 可用 |
| `cancelled` | 卡片消失；追加「已取消」系统消息 | 可用 |

### 7.2 一次请求的时序

```
1. 前端 POST /api/ai-butler/chat {messages, model_id?}
2. 后端（HTTP 线程）：
   a. resolve_request_credentials(config) 取凭证（duck-typed worker 模式）
   b. 组装 system prompt + tools schema + 历史
   c. 调 stream_openai / stream_doubao（带超时，默认 15s）
   d. 解析返回 → {reply: str, tool_calls?: list}
   e. 不执行任何变更，仅返回结构化结果给前端
3. 前端：
   a. 无 tool_calls → 渲染纯文本回复（plain_reply）
   b. 有 tool_calls → 渲染确认卡片（awaiting_confirm）
   c. 若 tool_calls 含 require_confirm=false → 直接执行，跳过卡片
4. 用户确认 → 前端按工具类型调既有写端点：
   - update_config → PUT /api/config（经 bridge 主线程 apply_config_patch）
   - set_default_model → POST /api/custom-models/{index}/default（经 bridge 主线程）
5. 写端点返回 → 前端更新卡片状态（done / 失败重试）
6. 追加系统消息；前端拉新配置刷新 UI
```

### 7.3 状态恢复

| 场景 | 行为 |
|------|------|
| 刷新页面 | 对话历史清空（纯内存）；状态归 `idle` |
| 侧栏切换再切回 | 对话历史保留（DOM 不销毁）；未确认卡片**静默取消**并追加「已取消」（与 §6.1 一致，不阻塞导航） |
| 应用重启 | 全部清空 |

### 7.4 后端无状态约束

后端 `POST /api/ai-butler/chat` **完全无状态**：每次请求由前端携带完整 `messages` 历史。后端不保存会话、不依赖上一次调用的中间结果。`query_config` 工具的执行结果由后端在本次请求内合成进 AI 上下文（即后端在 LLM 调用前先读 config 快照注入 system prompt，而非让 LLM 真的发 tool call 往返）—— 这降低延迟并避免 LLM 工具调用解析复杂度。

---

## 8. 待决策事项（实施 IDE 已决策）

> 本节原为待决策项；实施 IDE（2026-07-02）已据 §7 与代码先例给出决策，标注如下。

1. **LLM 复用策略** ✅ 已决策：复用 `ai_client_requests` 的 `stream_openai` / `stream_doubao` + `resolve_request_credentials`，采用 duck-typed worker 模式（非 QObject，不触 Qt / 主链路）。
2. **System Prompt 管理** ✅ 已决策：硬编码在 `app/application/ai_butler_service.py`（与 bridge service 一致，简单可控）。
3. **对话历史上限** ✅ 已决策：前端保留，限 **20 轮（40 条消息）**；超出自动丢弃最早的。
4. **Markdown 渲染** ✅ 已决策：**纯文本** + 变更预览用结构化卡片；不引入 markdown 渲染库。
5. **流式输出** ✅ 已决策：**不流式**，等完整生成后一次性显示。原因：工具调用需完整 JSON，流式会破坏 function calling 解析；且 bridge service 先例为非流式。

---

## 9. 验收标准

- [ ] 侧边栏可见「🤖 AI管家」入口
- [ ] 进入页面后顶部展示能力说明卡片
- [ ] 输入框上方展示当前使用模型名称及下拉切换
- [ ] 发送「把弹幕速度调快」后，AI 展示确认卡片
- [ ] 点击「确认执行」后设置生效，对话追加成功消息
- [ ] 点击「取消」后确认卡片消失，对话追加「已取消」
- [ ] 发送超出权限范围的需求（如「删除所有模型」），AI 回复仅建议不执行
- [ ] 刷新页面后对话历史清空
- [ ] 切换侧边栏再切回，对话历史保留（本次会话内）
- [ ] 暗黑模式下聊天界面正常显示
- [ ] **权限分级正确**：自动级（danmu_speed 等）跳过卡片直接执行；确认级（api_mode 等）展示卡片；禁止级（api_key）AI 只回文字指引
- [ ] **多工具调用**：一句话触发多个变更时，确认卡片列出全部变更项，一次确认批量执行
- [ ] **`screen_index` 切换**：确认卡片 label 注明「会使当前生成中的回复失效」

---

## 10. 参考文档

> 路径从仓库根解析（spec 位于 `docs/`，故为 `../`，非 `../../`）。

- [DanmuAI 技术速查](../AGENTS.md#附录-a-danmuai-技术速查)
- [Web API 路由注册](../app/web_api/routes.py)
- [配置服务 ConfigService](../app/application/config_service.py)
- [现有 LLM 请求实现](../app/ai_client_requests.py)
- [WEB_CONFIG_KEYS 白名单](../app/application/config_service.py#L16)
- [前端构建脚本](../web/static/build_index_html.py)
