# 02｜Web 主路径与样式契约实施说明

## 1. 实施目标

完成以下链路：

```text
配置字段
  → FloatingPanelStyleSnapshot
  → CardStyle WebSocket 协议
  → web/static/floating_panel/app.js
  → web/static/floating_panel/style.css
  → 样式生成器预览
```

WebView2/Chromium 是本任务“像素级 1:1”的主验收路径。

---

## 2. `app/floating_panel_style.py`

### 2.1 新增布局枚举

```python
LAYOUT_CHOICES: tuple[str, ...] = ("card", "line_like")
DEFAULT_LAYOUT = "card"
```

### 2.2 新增尾巴类型

当前：

```python
TAIL_STYLE_CHOICES = ("round", "sharp", "none")
```

改为：

```python
TAIL_STYLE_CHOICES = ("round", "sharp", "blivechat_line", "none")
```

不要把 `round` 的语义改掉。

### 2.3 新增字段

将：

```text
floating_panel_layout
```

加入：

- `STYLE_FIELD_KEYS`
- `STYLE_RESTORE_KEYS`
- `STYLE_PRESET_APPLY_KEYS`
- 配置默认值导出链路
- Web 配置白名单
- 快照 dataclass
- normalize 逻辑
- API 字段描述

### 2.4 新增预设

增加：

```python
STYLE_PRESET_IDS = ("classic", "wechat", "blivechat_line")
STYLE_PRESET_CHOICES = ("classic", "wechat", "blivechat_line", "custom")
```

增加：

```python
BLIVECHAT_LINE_CARD_COLORS = ("#FFFFFF",)
BLIVECHAT_LINE_TEXT_COLOR = "#000000"
BLIVECHAT_LINE_USERNAME_COLOR = "#CCCCCC"
```

增加：

```python
blivechat_line_factory_defaults()
```

### 2.5 归一化规则

```python
layout = normalize_choice(
    raw_layout,
    LAYOUT_CHOICES,
    fallback="line_like" if preset == "blivechat_line" else "card",
)
```

必须保证：

- 非法 layout 不保存为空；
- 旧配置缺字段时不崩溃；
- `custom + layout=line_like` 合法；
- `blivechat_line` 展开时自动写入 `line_like`；
- preset patch 不得触碰 `danmu_render_mode`。

---

## 3. `app/config_defaults.py`

确保：

```python
CONFIG_DEFAULTS["floating_panel_layout"]
```

存在。

推荐兼容默认：

```python
"card"
```

若产品决定新安装直接使用 LineLike，则通过 `blivechat_line_factory_defaults()` 生成新安装默认，但不要覆盖已有 DB。

---

## 4. `app/application/config_service.py`

将：

```text
floating_panel_layout
```

加入 Web 可保存字段。

保存 `floating_panel_style_preset=blivechat_line` 时必须展开完整 patch。

保存 `custom` 时只归一化用户提交字段，不强制改回 `card`。

---

## 5. `app/floating_panel_web/panel_protocol.py`

### 5.1 扩展 `CardStyle`

新增：

```python
layout: str = "card"
```

建议紧邻：

```python
shape: str = "bubble"
```

保持向后兼容：

- 旧消息不带 `layout` 时回退 `"card"`；
- `from_mapping()` 继续忽略未知字段；
- 不改变协议 `type="card"`。

### 5.2 不新增第二套 CardMessage

不要创建：

```text
LineLikeCardMessage
```

布局是样式属性，不是新消息类型。

---

## 6. `app/main_floating_panel_mixin.py`

在 `_build_web_panel_card_dict()` 创建 `CardStyle` 时加入：

```python
layout=str(snap.layout or "card"),
```

不要改变：

- `username` 数据来源；
- `content`；
- `persona_id`；
- `style_index`；
- 颜色选择；
- UUID；
- 时间戳。

---

## 7. `web/static/floating_panel/app.js`

### 7.1 `applyCardStyleVars`

新增：

```js
var layout = String(style.layout || "card");
cardEl.dataset.layout = layout === "line_like" ? "line_like" : "card";
cardEl.classList.toggle("layout-line-like", layout === "line_like");
cardEl.classList.toggle("layout-card", layout !== "line_like");
```

尾巴 class 逻辑：

```js
var isBubble = style.shape === "bubble" && style.tail_enabled === true;
cardEl.classList.toggle("is-bubble", isBubble);
```

仍保留，但 CSS 根据 layout 决定尾巴挂在 `.card` 还是 `.bubble`。

### 7.2 统一 DOM

把当前：

```js
'<div class="username">' + ... + '</div>' +
'<div class="content">' + content + '</div>'
```

改为：

```js
'<div class="username">' + username + usernameSeparator + '</div>' +
'<div class="bubble">' +
  '<div class="content">' + content + '</div>' +
'</div>'
```

用户名关闭时也保留稳定节点：

```js
'<div class="username is-hidden"></div>' +
'<div class="bubble">' +
  '<div class="content">' + content + '</div>' +
'</div>'
```

### 7.3 状态报告

当前 state report 读取 `.card` 的背景、圆角和阴影。

LineLike 下这些属性位于 `.bubble`，因此改为：

```js
var visualEl =
  firstCard.dataset.layout === "line_like"
    ? firstCard.querySelector(".bubble")
    : firstCard;
```

报告中建议新增：

```js
layout: firstCard.dataset.layout || "card",
usernameRect: ...,
bubbleRect: ...,
contentRect: ...,
```

用于自动化验收。

---

## 8. `web/static/floating_panel/style.css`

### 8.1 基础 wrapper

统一 `.card` 只负责：

```css
.card {
  position: relative;
  max-width: var(--card-max-width);
  animation: slideUp var(--entry-duration) ease-out;
  will-change: transform, opacity;
  font-family: var(--font-family);
  box-sizing: border-box;
}
```

不要直接删除旧视觉规则，而是迁到 `.layout-card`。

### 8.2 旧布局兼容

```css
.card.layout-card {
  background: var(--card-bg);
  border: var(--border-width) solid var(--card-border);
  border-radius: var(--card-radius);
  padding: var(--padding-y) var(--padding-x);
  box-shadow: var(--card-shadow);
}

.card.layout-card > .bubble {
  display: contents;
}
```

旧尾巴保持挂在：

```css
.card.layout-card.is-bubble::before
```

原 `round`、`sharp`、`none` 行为不变。

### 8.3 LineLike wrapper

```css
.card.layout-line-like {
  display: block;
  width: fit-content;
  overflow: visible;
  background: transparent;
  border: 0;
  border-radius: 0;
  padding: 0;
  box-shadow: none;
  margin-left: 0;
}
```

### 8.4 用户名

```css
.card.layout-line-like > .username {
  display: block;
  width: fit-content;
  margin: 0 0 5px 0;
  color: var(--username-color);
  font-family: var(--font-family);
  font-size: var(--font-size-username);
  font-weight: var(--font-weight-username);
  line-height: 1.2;
  white-space: nowrap;
  overflow: visible;
  text-overflow: clip;
}
```

LineLike 默认不应给用户名添加气泡背景。

### 8.5 独立 bubble

```css
.card.layout-line-like > .bubble {
  display: block;
  position: relative;
  width: fit-content;
  max-width: var(--card-max-width);
  overflow: visible;
  box-sizing: border-box;

  background: var(--card-bg);
  border: var(--border-width) solid var(--card-border);
  padding: var(--padding-y) var(--padding-x);
  border-radius: var(--card-radius);
  box-shadow: var(--card-shadow);
}
```

预设默认值必须使最终计算结果为：

```text
padding: 12px 20px
border-radius: 24px
background: #FFFFFF
border: 0
box-shadow: none
```

### 8.6 LineLike 尾巴

使用上游同语义，不要继续使用当前 clip-path/水滴尾巴：

```css
.card.layout-line-like.is-bubble[data-tail-style="blivechat_line"] > .bubble::before {
  content: "";
  display: block;
  position: absolute;
  top: 0;
  left: 0;

  border: var(--tail-h) solid transparent;
  border-left-width: var(--tail-w);
  border-right: var(--tail-w) solid var(--tail-color);

  transform: translate(-50%, -50%) rotate(35deg);
  transform-origin: center;
  pointer-events: none;
}
```

默认：

```text
--tail-h: 8px
--tail-w: 18px
```

确保尾巴颜色与当前气泡实际 RGBA 完全一致。

如果有边框，尾巴边框一致性属于 custom 模式增强；`blivechat_line` 默认无边框，因此主验收不要求复杂双层尾巴。

### 8.7 文本

```css
.card.layout-line-like .content {
  color: var(--content-color);
  font-family: var(--font-family);
  font-size: var(--font-size-content);
  font-weight: var(--font-weight-content);
  line-height: var(--content-line-height);
  overflow-wrap: break-word;
  word-break: break-word;
}
```

保持最多两行规则，但必须确认与上游参考用例的换行宽度一致。

### 8.8 描边与粗体

描边选择器必须同时覆盖：

```css
.card.has-outline .username
.card.has-outline .content
```

不要把描边施加到 `.bubble` 背景。

---

## 9. 样式生成器 HTML

文件：

```text
web/static/partials/style-generator.html
```

### 9.1 新增预设按钮

```html
<button
  type="button"
  id="sgBtnPresetBlivechatLine"
  class="sg-preset-btn ..."
  data-preset="blivechat_line">
  blivechat 气泡
</button>
```

### 9.2 新增布局控件

在“形态”附近新增：

```html
<select name="floating_panel_layout" id="sg-floating_panel_layout">
  <option value="card">整卡布局</option>
  <option value="line_like">用户名外置气泡</option>
</select>
```

### 9.3 提示文字

更新只提 classic/wechat 的说明，使其包含 `blivechat_line`。

增加提示：

```text
blivechat 气泡：用户名在气泡外，消息内容使用独立气泡。
```

### 9.4 国际化

同步更新项目实际使用的中英文 locale 文件，不要只写死中文。

---

## 10. `web/static/modules/app-style-generator-page.js`

### 10.1 保存字段

将：

```text
floating_panel_layout
```

加入：

```js
STYLE_SAVE_KEYS
```

### 10.2 读取预览样式

增加：

```js
layout: readStr('floating_panel_layout', 'card'),
```

### 10.3 应用 class

预览 `applyCardStyleVars()` 增加与真实浮窗完全相同的：

```js
cardEl.dataset.layout = ...
cardEl.classList.toggle(...)
```

不要重新发明另一套判断。

### 10.4 预览 DOM

统一改为：

```js
el.innerHTML =
  `<div class="username...">${...}</div>` +
  `<div class="bubble">` +
    `<div class="content">${...}</div>` +
  `</div>`;
```

### 10.5 重构建议

为了避免预览与真实 app.js 再次漂移，至少提取并共享以下纯规则，或建立契约测试锁定：

- layout normalization；
- class 切换；
- CSS 变量名；
- DOM 层级；
- tail style 映射。

如果当前构建结构不适合共享模块，保留两处实现，但测试必须断言两处都包含 `.bubble` 与 `data-layout`。

---

## 11. `web/static/warm-tokens-pages.css`

把 `.sg-preview-card` 重构为与真实 `.card` 相同语义：

```text
.sg-preview-card.layout-card
.sg-preview-card.layout-line-like
.sg-preview-card > .username
.sg-preview-card > .bubble
.sg-preview-card > .bubble > .content
```

LineLike 尾巴必须挂在：

```css
.sg-preview-card.layout-line-like > .bubble::before
```

不能继续挂在 `.sg-preview-card::before`。

预览允许有深色舞台背景，但消息块自身尺寸、字体、气泡和尾巴必须与真实浮窗相同。

---

## 12. 建议修改文件清单

必须检查并按实际依赖更新：

```text
app/floating_panel_style.py
app/config_defaults.py
app/application/config_service.py
app/floating_panel_web/panel_protocol.py
app/main_floating_panel_mixin.py

web/static/floating_panel/app.js
web/static/floating_panel/style.css

web/static/partials/style-generator.html
web/static/modules/app-style-generator-page.js
web/static/warm-tokens-pages.css

web/static/locales/zh/*
web/static/locales/en/*

tests/test_floating_panel_style.py
tests/test_style_generator_page.py
```

项目若有 Web 协议专用测试，也必须同步更新。

---

## 13. Web 实施完成检查

- [ ] CardStyle 带 `layout`；
- [ ] WS card payload 带 `layout=line_like`；
- [ ] 真实 DOM 存在 `.bubble`；
- [ ] 预览 DOM 存在 `.bubble`；
- [ ] `card` 和 `line_like` 都可切换；
- [ ] `classic` 外观未被破坏；
- [ ] `wechat` 外观未被破坏；
- [ ] `blivechat_line` 用户名位于气泡外；
- [ ] 尾巴挂在 `.bubble::before`；
- [ ] 预览和真实浮窗 bounding box 一致；
- [ ] state report 能报告 bubble/username 几何。
