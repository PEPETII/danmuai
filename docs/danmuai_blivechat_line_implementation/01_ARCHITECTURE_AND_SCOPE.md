# 01｜架构与范围说明

## 1. 当前项目现状

DanmuAI 当前存在两条“从下到上浮动面板”渲染路径：

```text
样式配置
  └─ app/floating_panel_style.py
       ├─ WebView2 主路径
       │    ├─ app/main_floating_panel_mixin.py
       │    ├─ app/floating_panel_web/panel_protocol.py
       │    ├─ web/static/floating_panel/app.js
       │    └─ web/static/floating_panel/style.css
       │
       └─ QPainter 回退路径
            └─ app/floating_panel_overlay.py
```

设置页预览是第三个显示面：

```text
web/static/partials/style-generator.html
web/static/modules/app-style-generator-page.js
web/static/warm-tokens-pages.css
```

目前 Web 与预览都生成：

```html
<div class="card">
  <div class="username">AI：</div>
  <div class="content">消息内容</div>
</div>
```

背景、内边距、圆角、阴影和尾巴全部作用在 `.card`。

QPainter 当前也把用户名和内容绘制在同一个气泡主体中，并且首行用户名与内容处于同一基线。

这与 blivechat LineLike 的层级不一致。

## 2. 目标层级

统一改成稳定 DOM：

```html
<div class="card layout-line-like">
  <div class="username">AI：</div>
  <div class="bubble">
    <div class="content">消息内容</div>
  </div>
</div>
```

职责必须固定：

| 元素 | 职责 |
|---|---|
| `.card` | 单条消息外层、整体宽度、入场/退出动画、CSS 变量宿主 |
| `.username` | 用户名文字，位于气泡外 |
| `.bubble` | 消息背景、圆角、内边距、边框、阴影 |
| `.bubble::before` | LineLike 左上角尾巴 |
| `.content` | 消息文字、换行、最多两行 |

## 3. 稳定 DOM，而不是按预设生成两套 HTML

推荐所有预设统一生成：

```html
<div class="card" data-layout="card|line_like">
  <div class="username"></div>
  <div class="bubble">
    <div class="content"></div>
  </div>
</div>
```

通过 CSS 决定旧布局和 LineLike 布局。

### 旧 `card` 布局

```css
.card[data-layout="card"] {
  /* 保留旧背景、内边距、边框、圆角和尾巴 */
}

.card[data-layout="card"] > .bubble {
  display: contents;
}
```

用户名和内容仍然在同一张卡片中，兼容 `classic` 与现有 `wechat`。

### 新 `line_like` 布局

```css
.card[data-layout="line_like"] {
  background: transparent;
  border: 0;
  padding: 0;
  box-shadow: none;
}

.card[data-layout="line_like"] > .bubble {
  /* 真正的消息气泡 */
}
```

这样可避免 JS 中长期维护两套 DOM 分支。

## 4. 新增配置字段

新增：

```text
floating_panel_layout
```

合法值：

```text
card
line_like
```

不要复用现有：

```text
floating_panel_shape
```

原因：

- `shape` 表示卡片主体是普通卡片还是带尾巴气泡；
- `layout` 表示用户名与消息背景的层级关系；
- 两者不是同一维度。

推荐枚举：

```python
LAYOUT_CHOICES = ("card", "line_like")
DEFAULT_LAYOUT = "card"
```

预设映射：

| 预设 | layout | shape | 说明 |
|---|---|---|---|
| classic | card | card | 原经典卡片 |
| wechat | card | bubble | 原有整卡气泡，保持兼容 |
| blivechat_line | line_like | bubble | 用户名在外、内容独立气泡 |

## 5. 新增预设

预设 ID：

```text
blivechat_line
```

显示名称：

```text
blivechat Line
```

或中文：

```text
blivechat 气泡
```

不要把现有 `wechat` 直接改成 LineLike，否则会破坏已保存的用户视觉配置与测试锁定。

### 推荐默认值

```python
_BLIVECHAT_LINE_FLAT = {
    "floating_panel_style_preset": "blivechat_line",
    "floating_panel_layout": "line_like",
    "floating_panel_shape": "bubble",

    "floating_panel_card_colors": '["#FFFFFF"]',
    "floating_panel_card_color_mode": "equal",
    "floating_panel_card_color_weights": "{}",
    "floating_panel_text_colors": '["#000000"]',
    "floating_panel_text_color_mode": "equal",
    "floating_panel_text_color_weights": "{}",

    "floating_panel_card_opacity": "100",

    "floating_panel_outline_enabled": "0",
    "floating_panel_outline_color": "#FFFFFF",
    "floating_panel_outline_width": "0",

    "floating_panel_shadow_enabled": "0",
    "floating_panel_shadow_color": "#000000",
    "floating_panel_shadow_opacity": "0",
    "floating_panel_shadow_blur": "0",
    "floating_panel_shadow_offset_x": "0",
    "floating_panel_shadow_offset_y": "0",

    "floating_panel_border_enabled": "0",
    "floating_panel_border_color": "#FFFFFF",
    "floating_panel_border_width": "0",
    "floating_panel_border_opacity": "0",

    "floating_panel_padding_x": "20",
    "floating_panel_padding_y": "12",
    "floating_panel_radius": "24",

    "floating_panel_tail_enabled": "1",
    "floating_panel_tail_style": "blivechat_line",
    "floating_panel_tail_width": "18",
    "floating_panel_tail_height": "8",
    "floating_panel_tail_size": "8",
    "floating_panel_tail_offset_y": "0",

    "floating_panel_username_enabled": "1",
    "floating_panel_username_text": "弹幕",
    "floating_panel_username_color": "#CCCCCC",
    "floating_panel_username_size": "18",
    "floating_panel_username_weight": "700",
    "floating_panel_username_separator": "",

    "floating_panel_content_size": "20",
    "floating_panel_content_weight": "700",
    "floating_panel_content_line_height": "120",
    "floating_panel_gap_username_content": "5",

    "floating_panel_entry_animation": "fade",
    "floating_panel_entry_duration_ms": "200",
    "floating_panel_push_duration_ms": "180",
    "floating_panel_exit_animation": "none",
    "floating_panel_exit_duration_ms": "200",
    "floating_panel_stack_gap": "8",

    "floating_panel_font_family": "Noto Sans SC",
    "floating_panel_font_size": "20",
    "floating_panel_font_bold": "0",
    "floating_panel_opacity": "100",
}
```

说明：

- `tail_width=18` 对应 LineLike 长边；
- `tail_height=8` 对应基础透明边框；
- `tail_offset_y` 在 `line_like` 中不参与计算，尾巴固定锚定气泡左上角；
- 旋转角度固定为 `35deg`；
- 用户名与内容分隔符默认空字符串，用户名独占一行；
- 上游默认有头像，但本项目本次不新增头像，消息主体几何仍按无头像组件对齐。

## 6. 新鲜安装与升级策略

推荐：

- 新安装默认预设可设为 `blivechat_line`；
- 数据库中已有合法 `classic`、`wechat`、`custom` 的用户保持原值；
- 不要在启动时无条件把所有用户改成 `blivechat_line`；
- 缺失 `floating_panel_layout` 时：
  - `blivechat_line` → `line_like`
  - 其他预设 → `card`

如果现有 ConfigStore 无法区分“默认注入”与“用户明确保存”，优先保持 `DEFAULT_STYLE_PRESET = "wechat"`，由 UI 明确提供新预设，避免升级回归。产品确认后再单独调整新安装默认值。

## 7. 兼容性边界

不得改变：

- WebSocket 连接和认证；
- 卡片 ID 去重；
- 最大卡片数；
- `column-reverse` 堆积；
- 退出清理逻辑；
- 面板位置；
- 弹幕生成与人格逻辑；
- 横向滚动模式；
- `danmu_render_mode`；
- 颜色等概率/权重选择算法；
- style index 稳定性。

## 8. 许可证要求

blivechat 使用 MIT License。

若复制或改写了具有实质性的上游 CSS/实现，请：

1. 在项目现有第三方声明中追加；若没有则新增 `THIRD_PARTY_NOTICES.md`；
2. 保留：

```text
blivechat
Copyright (c) 2019 xfgryujk
MIT License
```

3. 注明使用范围：

```text
LineLike ordinary text-message bubble geometry and CSS behavior.
```
