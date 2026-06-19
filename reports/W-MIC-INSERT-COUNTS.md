# 工单 ID

W-MIC-INSERT-COUNTS

## 工单标题

将麦克风模式“说话后额外插入弹幕”的固定 6/3 规则改为可配置的 x/y 配置

## 背景

已确认当前麦克风模式并不是独立的普通生成模式，也不是主视觉链路的一部分，而是“用户说话结束后，额外发起一次 mic insert 请求，并把结果插队显示”的既有机制。当前需求要求保留这条机制，不新增模式，不重构链路，只把数量规则参数化。

当前实现现状已确认：

1. 麦克风插入 prompt 仍然硬编码“生成 6 条、前 3 条回应语音”。
   证据：
   - `app/mic_prompt.py`
2. 麦克风请求仍由 `main_mic_mixin.py` 调用 `build_mic_insert_user_pt(...)` 注入 prompt。
   证据：
   - `app/main_mic_mixin.py:19`
   - `app/main_mic_mixin.py:137`
3. `normal_reply_count` 当前统一约束来自人格/契约层，后端上限是 `1..50`。
   证据：
   - `app/persona_contract.py:150-165`
   - `app/personae.py` re-export `NORMAL_REPLY_COUNT_MAX`
   - `app/application/config_service.py:303-312`
4. 前端“每次生成弹幕数”输入框当前也是 `min=1 max=50`。
   证据：
   - `web/static/partials/settings.html:297-298`
5. 麦克风设置页真实模板文件是 `web/static/partials/settings.html`，不是只改打包后的 `index.html`。
6. 现有 Web 设置默认值与恢复默认分组由 `web/static/modules/settings-defaults.js` 管理。
7. 当前已有麦克风 prompt 测试存在，可直接扩展。
   证据：
   - `tests/test_mic_mode.py:165+`

因此，这次工单应聚焦为“让 mic insert 的数量规则配置化，并与 normal_reply_count 使用同一套范围约束”，而不是扩展麦克风模式形态。

## 目标

完成后必须满足：

1. 默认行为保持不变：`x=6, y=3`。
2. 在“助手设置 → 麦克风模式”中新增两个可保存配置项：
   - `mic_insert_reply_count`
   - `mic_insert_voice_reply_count`
3. `x` 的范围与 `normal_reply_count` 完全一致，不允许另起一套不一致的常量。
4. `y` 的范围为 `0..x`，且后端保存时必须做钳位。
5. `mic_prompt.py` 不再硬编码“6 条 / 前 3 条”。
6. 不改变麦克风采集逻辑、MicOrchestrator 生命周期、主视觉请求占用关系、mic insert 的独立调用方式。

## 依赖项

- Python 3.12+
- 现有 Web 设置页面与 ConfigService 流程
- 分批运行相关 pytest，不允许本地全量 pytest

## 允许修改的区域

- `app/config_defaults.py`
- `app/application/config_service.py`
- `app/mic_prompt.py`
- `web/static/modules/settings-defaults.js`
- `web/static/partials/settings.html`
- 与本工单直接相关的设置页脚本文件
- `tests/test_mic_mode.py`
- `tests/test_web_auth.py`
- `tests/test_config_defaults.py`
- 如需要，新增与本功能直接相关的测试文件

## 禁止修改的区域

- `app/mic_capture.py`
- `app/mic_service.py`
- `app/mic_orchestrator.py`
- `main.py` / `app/main_*` 中与生命周期、in_flight 调度有关的主链路逻辑
- 不新增普通模式 / 独立模式 / 开关分支
- 不把 mic insert 合并进视觉主生成链路
- 不修改麦克风采集、音频编码、请求调度归属

## 当前实现梳理

### 1. 当前固定规则位置

`app/mic_prompt.py` 当前常量 `MIC_INSERT_BLOCK` 中直接写死：

- 生成 `6` 条 JSON 数组弹幕
- 前 `3` 条必须直接回应用户刚才说的话
- 后 `3` 条可结合截图氛围

这是这次最核心的改造点。

### 2. 当前配置默认值与 Web 保存链路

- 默认值：
  - `app/config_defaults.py`
- Web 允许写入的 key：
  - `app/application/config_service.py` 里的 `WEB_CONFIG_KEYS`
- Web 保存时的后端钳位：
  - `ConfigService._normalize_items(...)`

### 3. 当前前端设置页接线

- 设置页真实模板：
  - `web/static/partials/settings.html`
- 默认值字段与恢复默认：
  - `web/static/modules/settings-defaults.js`

### 4. 当前 normal_reply_count 的统一范围来源

必须复用现有这套约束来源，不能手写另一套：

- `DEFAULT_NORMAL_REPLY_COUNT = 5`
- `NORMAL_REPLY_COUNT_MAX = 50`
- 最小值隐含为 `NORMAL_REPLY_COUNT_MIN = 1`

建议执行人直接复用：

- `app.personae.NORMAL_REPLY_COUNT_MAX`
- `app.personae.DEFAULT_NORMAL_REPLY_COUNT`
- 如需要最小值，也应从人格/契约层统一来源读取，而不是在 mic 配置里重新定义

## 需求

1. 新增配置项：
   - `mic_insert_reply_count`，默认 `6`
   - `mic_insert_voice_reply_count`，默认 `3`
2. 在“助手设置 → 麦克风模式”新增两个数字输入项：
   - `x：说话后额外插入弹幕数`
   - `y：其中回应语音的弹幕数`
3. `x` 的范围必须与 `normal_reply_count` 一致：
   - 最小值一致
   - 最大值一致
   - 默认值可不同，但范围和钳位逻辑必须一致
4. `y` 的范围为 `0..x`。
5. 如果用户把 `x` 调小导致 `y > x`，保存时必须自动把 `y` 钳位到 `x`。
6. `y = 0` 时表示“不强制回应语音”，不是报错，也不是禁用 mic insert。
7. `app/config_defaults.py` 必须新增这两个默认值。
8. `app/application/config_service.py` 必须：
   - 把这两个 key 加入 `WEB_CONFIG_KEYS`
   - 在 `_normalize_items(...)` 中做后端钳位
   - 保证 `y` 的钳位基于保存后的 `x`
9. `web/static/modules/settings-defaults.js` 必须：
   - 把这两个字段加入 `CONFIG_FIELDS`
   - 加入 `SETTINGS_RESTORE_GROUPS.mic`
   - 如存在前端预钳位/预览逻辑，可补充，但不能替代后端钳位
10. `web/static/partials/settings.html` 必须新增对应 UI 控件，放在麦克风模式区域内。
11. `app/mic_prompt.py` 必须改为根据配置动态生成 prompt，不允许保留写死的“6 条 / 前 3 条”。
12. prompt 文案必须满足：
   - `x=5, y=2`：明确表达“生成 5 条，前 2 条回应语音，其余 3 条结合截图氛围”
   - `y=0`：不得出现“前 0 条必须回应语音”这种坏文案；应表达为“不强制回应语音，但可以自然参考用户刚才说话内容”
   - `y=x`：应表达为“全部弹幕都需要回应用户刚才说的话”
13. 不允许改变以下行为边界：
   - 不改变麦克风采集逻辑
   - 不改变 MicOrchestrator 生命周期
   - 不让麦克风请求占用视觉主链路 `ai_in_flight`
   - 不把 mic insert 合并进主视觉生成链路
   - 不新增普通模式/独立模式开关

## 非目标

- 不改麦克风采样、ring buffer、编码、probe 逻辑
- 不改 `main_mic_mixin.py` 的调用时机与生命周期策略
- 不改视觉主链路 normal batch 的生成方式
- 不改麦克风模式是否与视觉模型共用的现有开关逻辑
- 不扩展新的 prompt 模板系统

## 推荐实现方式

### 一、默认值

在 `app/config_defaults.py` 中新增：

- `mic_insert_reply_count = "6"`
- `mic_insert_voice_reply_count = "3"`

### 二、后端钳位

在 `app/application/config_service.py` 中：

1. 将两个 key 加入 `WEB_CONFIG_KEYS`
2. 在 `_normalize_items(...)` 中统一做：
   - `x` 按 `normal_reply_count` 的同范围钳位
   - `y` 按 `0..x` 钳位
3. 钳位顺序必须先得到最终 `x`，再钳位 `y`

建议：

- 直接复用 `normal_reply_count` 的常量来源
- 避免在 `config_service.py` 内再写新的 `50`

### 三、前端设置

在 `web/static/partials/settings.html` 的麦克风模式区域新增两个 `<input type="number">`：

- `mic_insert_reply_count`
- `mic_insert_voice_reply_count`

要求：

1. `x` 的 `min/max` 与 `normal_reply_count` 保持一致
2. `y` 的 `min=0`
3. 若前端做联动体验：
   - 用户调小 `x` 时可即时把 `y` 限制到 `x`
   - 但最终以后端保存钳位为准

### 四、settings-defaults 接线

在 `web/static/modules/settings-defaults.js` 中：

1. 把两个字段加入 `CONFIG_FIELDS`
2. 加入 `SETTINGS_RESTORE_GROUPS.mic`
3. 如该模块已有统一 clamp helper，可复用；否则不要为了这点需求大改结构

### 五、prompt 生成

建议把 `MIC_INSERT_BLOCK` 从固定常量改为函数式拼装，例如：

- 先算出 `x`
- 再算出 `y`
- 按三种分支生成自然语言：
  - `0 < y < x`
  - `y == 0`
  - `y == x`

注意：

1. 不能输出自相矛盾的文案
2. 中文措辞要自然，不要出现“前 0 条”
3. 仍需保留“同时参考语音与截图”的原意

## 建议修改文件

- `app/config_defaults.py`
- `app/application/config_service.py`
- `app/mic_prompt.py`
- `web/static/modules/settings-defaults.js`
- `web/static/partials/settings.html`
- 可能需要联动的设置页脚本文件
- `tests/test_mic_mode.py`
- `tests/test_web_auth.py`
- `tests/test_config_defaults.py`

## 验收标准

- [ ] 默认行为仍然是 `x=6, y=3`
- [ ] UI 中可以修改 `x/y`
- [ ] `x` 的范围与 `normal_reply_count` 完全一致
- [ ] `y` 永远不会大于 `x`
- [ ] `y=0` 时 prompt 不会出现“前 0 条必须回应语音”
- [ ] `y=x` 时 prompt 会表达“全部弹幕都需要回应用户刚才说的话”
- [ ] `app/mic_prompt.py` 不再硬编码“6 条”和“前 3 条”
- [ ] 后端保存时会对 `x/y` 做统一钳位
- [ ] 未改变麦克风采集逻辑、MicOrchestrator 生命周期、视觉主链路 in_flight 关系
- [ ] 相关测试已更新并通过

## 手动验证步骤

1. 打开“助手设置 → 麦克风模式”，确认能看到两个新输入项。
2. 保持默认值，保存后重新加载配置，确认仍为 `x=6, y=3`。
3. 设置 `x=5, y=2`，保存后检查 prompt 或相关测试，确认规则变为“5 条 / 前 2 条回应语音”。
4. 设置 `x=4, y=0`，保存后确认不会出现“前 0 条”文案。
5. 设置 `x=4, y=9`，保存后确认最终 `y` 被钳位到 `4`。
6. 设置 `x` 为超出 `normal_reply_count` 范围的值，确认会按同一范围被钳位。

## 测试要求

至少补充并执行：

1. `python -m pytest tests/test_mic_mode.py -q -x`
2. `python -m pytest tests/test_web_auth.py -q -x`
3. `python -m pytest tests/test_config_defaults.py -q -x`

建议增加或更新的测试覆盖：

- 默认值导出包含 `mic_insert_reply_count=6`
- 默认值导出包含 `mic_insert_voice_reply_count=3`
- `apply_config_patch` / `ConfigService` 对 `x` 的范围钳位
- `apply_config_patch` / `ConfigService` 对 `y > x` 的钳位
- `build_mic_insert_user_pt()` 在 `y=0` 时的文案
- `build_mic_insert_user_pt()` 在 `y=x` 时的文案
- `build_mic_insert_user_pt()` 在 `0 < y < x` 时的文案

## 风险点

1. 如果前端只做 UI 限制、后端不做钳位，配置可被 API 直接写坏。
2. 如果 `x` 的范围复用了错误的常量来源，容易和 `normal_reply_count` 将来漂移。
3. 如果 prompt 分支写得不严谨，最容易出现“前 0 条”或“全部回应”与“其余结合截图”并存的矛盾文案。
4. 设置页如果只改 `partials/settings.html` 但遗漏 `settings-defaults.js`，恢复默认和字段加载会不完整。

## 完成后必须给出的报告

实现完成后，执行人必须明确说明：

1. 当前固定 6/3 规则原本写在哪里
2. 新增了哪些配置项与默认值
3. `x` 是否已与 `normal_reply_count` 使用同一套范围约束
4. `y` 是否已在后端保证不大于 `x`
5. `mic_prompt.py` 是否已改为动态生成
6. 是否完全未改动麦克风采集与主链路边界
7. 执行了哪些相关测试

## 交接提示

执行人先读：

1. `E:/test/danmu/.local-ai/prompts/AGENTS.md`
2. `E:/test/danmu/.local-ai/prompts/Fable5.md`
3. `E:/test/danmu/.local-ai/prompts/ai-project-context.md`

再读以下现状文件：

1. `E:/test/danmu/app/mic_prompt.py`
2. `E:/test/danmu/app/config_defaults.py`
3. `E:/test/danmu/app/application/config_service.py`
4. `E:/test/danmu/web/static/modules/settings-defaults.js`
5. `E:/test/danmu/web/static/partials/settings.html`
6. `E:/test/danmu/tests/test_mic_mode.py`
7. `E:/test/danmu/tests/test_web_auth.py`
