# W-FONT-003 — 字体设置将 `<datalist>` 替换为可见下拉控件

> **来源**：W-FONT-002 反馈（2026-06-06 debug session）；用户连续反馈"下拉框里无法找到原本的默认字体"——确认是 W-FONT-001 选型 bug（`<datalist>` 不适合字体选择场景），不是 UX 偏好问题。

---

## 工单 ID

W-FONT-003

## 性质

**Bug 修复延续**（非新功能）：W-FONT-001 选用 `<input list="font-family-options">` + `<datalist>` 形态本身是错误选型——`<datalist>` 配合 `<input>` 在 Chromium 系下**只在用户键入字符时弹出自动补全**，没有可发现的下拉入口，**且当前输入框值非空时浏览器只显示匹配项**（runtime 证实 8 个 option 但用户视觉仅看到 1 个）。W-FONT-002 沿用此形态，导入字体后用户的"找不到默认字体"问题被放大。

**根因**：`web/static/index.html:665,679,689-697` 选用 `<datalist>` 不当。

## 工单标题

把"字体名"输入框的 `<datalist>` 自动补全替换为可点击展开的自定义下拉控件，使用户能直接看到全部 7 个内置 + 全部已导入字体。

## 背景

- W-FONT-001 / W-FONT-002 已落地的字体设置 UI 使用 `<input list="font-family-options">` + `<datalist>` 形态（`web/static/index.html:665, 679, 689-697`）。
- 2026-06-06 debug session 中，runtime 证据（`web/static/modules/settings.js:1965` 的 DEBUG 块）证实 datalist 实际有 8 个 option（7 个内置 + 1 个导入），**datalist 本身没丢字**。
- 用户反馈"下拉框里无法找到原本的默认字体"。根因分析：`<datalist>` 配合 `<input>` 在浏览器中**只在用户键入字符时弹出自动补全**，不会像 `<select>` 那样点击即展示全部候选项；用户**没有可发现的下拉入口**，误以为"默认字体消失"。
- 截图证据：用户截图里"字体名"输入框**没有下拉箭头**（这与 `<input list>` 形态一致），可佐证用户预期的"下拉"不存在。

## 目标

- 让"横向弹幕字体"和"悬浮窗字体"输入框配套一个**始终可见**的下拉控件。
- 点击下拉箭头即可看到全部 8 个候选项（7 个内置 + N 个已导入），其中**当前已选中的字体名**高亮。
- 选择某项 → 自动填入对应输入框 → 触发既有 `change` 事件 → 走 W-FONT-001 的 `apply_config_patch` 热更链。
- 不得修改 `app/`、`main.py`、后端 font_registry 任何逻辑；后端 API（`/api/fonts`）已能返回 `families` 数组，前端复用即可。

## 依赖项

- W-FONT-001（已完成）：`danmu_font_family` / `floating_panel_font_family` config key + 既有热更链
- W-FONT-002（已完成）：`/api/fonts` 返回 `{families, imported}`

## 允许修改的区域

- `web/static/index.html`（**仅** `#settingsTab-font` 面板内的字体名输入块，**不**改其他 tab/字段）
- `web/static/modules/settings.js`（**仅** `refreshFontDatalist` 替换实现 + 相关初始化；**不**改 `CONFIG_FIELDS` / `SETTINGS_RESTORE_GROUPS` / `applyDefaultToField` / `collectFormData`）
- `web/static/warm-tokens.css` 或新 CSS（仅当下拉样式需要新规则时）
- `tests/`：仅当新交互需要覆盖时追加 1-2 个用例
- `docs/`：更新 `docs/WEB_CONSOLE.md` 字体设置地图、`docs/workflow/当前仓库状态.md`、本工单完成报告

## 禁止修改的区域

- `app/`（含 `app/font_registry.py`、`app/web_api/font_registry.py`）
- `main.py`
- `requirements.txt`、锁文件
- `web/static/` 的其他模块（`app.js` / `warmup.js` 等），除非确有必要

## 需求

1. 在 `#danmu_font_family` 和 `#floating_panel_font_family` 输入框**紧邻**的位置，提供一个**始终可见的下拉箭头按钮**或**复合控件**（点击展开 8 个候选项）。
2. 候选项内容 = `['Microsoft YaHei', 'SimHei', 'SimSun', 'KaiTi', 'DengXian', 'Arial', 'Segoe UI']` 硬编码内置 + `/api/fonts` 的 `families` 数组；去重保序。
3. 当前输入框值在候选项中高亮（若匹配）。
4. 点击候选项 → 输入框值变更 → 派发 `change` 事件，使既有 `PUT /api/config` 链路生效。
5. 保留**手输**能力：用户仍可在输入框键入未列出的字体名（如"我的自定义字体"）。
6. 删 `font-family-options` 的 `<datalist>`（既然不再被引用）。
7. DEBUG 块（`#font-datalist-debug`）保留到本工单验证后由 Codex 撤掉。

## 非目标

- 不实现"导入字体实时预览"（CSS `font-family` 示例文字）
- 不重构字体配置热更链
- 不动后端 font_registry
- 不加新的 config key

## 验收标准

- [ ] 打开"字体设置"tab，"字体名"控件旁有**始终可见**的下拉箭头
- [ ] 点击箭头弹出 8 个候选项（7 内置 + 1 已导入），无重复
- [ ] 已选中字体名在候选项中高亮
- [ ] 选择候选项后输入框值更新，且"保存设置"按钮变红点
- [ ] 输入框仍可手输（验证 `keydown` 不会被新组件拦截）
- [ ] 导入第二个字体后下拉自动增加该字体名
- [ ] 删 `<datalist id="font-family-options">` 不影响输入
- [ ] 撤掉 DEBUG 块（`#font-datalist-debug` 与 `uploadFontFile` 中的 debug 块、`delete` handler 中的 debug 块）

## 手动验证步骤

1. 重启 `python main.py`，Ctrl+Shift+R 硬刷新浏览器
2. 打开"助手设置"→"字体设置"
3. 点击"横向弹幕字体"输入框右侧的下拉箭头
4. 验证弹出 8 个候选项，`Microsoft YaHei` 处于高亮（如果当前值是它）
5. 切换到 `SimHei`，点保存
6. 验证横向弹幕实际渲染字体变更
7. 选 `zihunbaigetianxingti` 验证导入字体可下拉选中
8. 在输入框手输 `MyCustomFont` 验证手输能力未丢
9. 导入第二个字体，验证下拉自动增加
10. 全程不出现 JS console 报错

## 风险点

- 复合控件（input + 按钮）需要键盘可访问性（焦点、Tab 序、ARIA 标签）
- 替换 datalist 后既有"点击输入框右下角小箭头展开候选项"行为失效（用户已被告知这是范围）
- 自定义下拉样式需与现有 warm-tokens 风格一致，避免视觉突兀

## 完成后必须更新的文档

- [ ] [docs/workflow/当前仓库状态.md](../../workflow/当前仓库状态.md)
- [ ] [docs/workflow/工单列表.md](../../workflow/工单列表.md)（标为已完成）
- [ ] [docs/WEB_CONSOLE.md](../../WEB_CONSOLE.md)（字体设置地图更新）
- [ ] [docs/工单列表/工单/W-FONT-003-完成报告.md](../../工单列表/工单/W-FONT-003-完成报告.md)

## Codex 完成报告要求

- 使用 [Codex完成报告模板.md](../Codex完成报告/Codex完成报告模板.md)
- 必须列出**全部**修改文件路径
- 范围外问题写入 [docs/已知问题与后续事项.md](../../workflow/已知问题与后续事项.md)，不得顺手修复
