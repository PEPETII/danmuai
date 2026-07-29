# 05｜交给 IDE/Codex 的总执行提示词

你正在修改 GitHub 项目：

```text
PEPETII/danmuai
```

请先完整阅读并严格执行以下文档，按顺序：

```text
README.md
01_ARCHITECTURE_AND_SCOPE.md
02_WEB_AND_STYLE_CONTRACT_IMPLEMENTATION.md
03_QPAINTER_FALLBACK_IMPLEMENTATION.md
04_TEST_AND_VISUAL_ACCEPTANCE.md
```

## 任务目标

在 DanmuAI 的“从下到上浮动面板”中新增：

```text
blivechat_line
```

预设，实现 `xfgryujk/blivechat` 的 `LineLike.vue` 普通文字消息块视觉 1:1。

这里的 1:1 不是“相似”，而是：

- 用户名必须在气泡外；
- 消息内容必须由独立 `.bubble` 包裹；
- 气泡默认 padding 为 `12px 20px`；
- 气泡默认圆角为 `24px`；
- 用户名与气泡间距为 `5px`；
- 尾巴必须复刻 LineLike 左上角 border triangle：
  - 基础边框 8px；
  - 长边 18px；
  - `translate(-50%, -50%) rotate(35deg)`；
- 用户名默认 `Noto Sans SC / 18px / 700 / #CCCCCC`；
- 内容默认 `Noto Sans SC / 20px / 700 / #000000`；
- 气泡默认 `#FFFFFF`；
- 入场默认 200ms；
- 设置页预览、真实 WebView2 浮窗和 QPainter 回退语义一致；
- WebView2 主路径通过同 Chromium reference 截图对比。

## 重要架构要求

新增：

```text
floating_panel_layout = card | line_like
```

新增预设：

```text
blivechat_line
```

不要直接改变旧 `wechat`。

所有 Web 消息统一 DOM：

```html
<div class="card" data-layout="card|line_like">
  <div class="username"></div>
  <div class="bubble">
    <div class="content"></div>
  </div>
</div>
```

- 旧 `card` 布局保持原有整卡视觉；
- 新 `line_like` 布局让 `.card` 透明，由 `.bubble` 承担背景、padding、radius、border、shadow 和 tail；
- CSS 变量继续写在 `.card` 上，由子元素继承；
- LineLike 尾巴必须挂在 `.bubble::before`，不得挂在 `.card::before`。

## 必须检查和修改的文件

至少检查：

```text
app/floating_panel_style.py
app/config_defaults.py
app/application/config_service.py
app/floating_panel_web/panel_protocol.py
app/main_floating_panel_mixin.py
app/floating_panel_overlay.py

web/static/floating_panel/app.js
web/static/floating_panel/style.css

web/static/partials/style-generator.html
web/static/modules/app-style-generator-page.js
web/static/warm-tokens-pages.css

web/static/locales/zh/*
web/static/locales/en/*

tests/test_floating_panel_style.py
tests/test_style_generator_page.py
tests/test_floating_panel_overlay.py
```

根据代码依赖补充其他相关测试和协议文件。

## QPainter 要求

QPainter 是 WebView2 失败时的回退路径，不能忽略。

将渲染分为：

```python
_render_legacy_card_pixmap()
_render_line_like_pixmap()
```

LineLike 分支：

- 用户名独立绘制在气泡上方；
- 用户名与内容不能再处于同一基线；
- 使用 pixel size 接近 CSS px；
- 新建统一几何测量函数；
- item height 包含用户名、5px gap、尾巴 overhang、气泡和阴影；
- 尾巴使用旋转三角，不使用当前贝塞尔水滴；
- legacy classic/wechat 保持不变。

## 测试要求

不要只做字符串测试。

必须新增：

1. preset/config roundtrip；
2. CardStyle layout 协议兼容；
3. Web DOM 层级测试；
4. 预览与真实 DOM 同构测试；
5. LineLike computed style/bounding box 测试；
6. Chromium reference 与 candidate 截图差异测试；
7. QPainter 几何测试；
8. classic/wechat 回归测试。

建立最小 MIT reference fixture：

```text
tests/visual/fixtures/blivechat_line_reference.html
```

视觉测试固定：

```text
360×520
DPR=1
zoom=100%
同一个 Chromium
同一字体
```

尺寸误差：

```text
≤ 1 CSS px
```

气泡+尾巴像素差异：

```text
≤ 0.1%
```

整组件差异建议：

```text
≤ 0.5%
```

字体抗锯齿可单独遮罩，但不得掩盖布局错误。

## 兼容要求

不得破坏：

- classic；
- wechat；
- custom；
- scrolling 模式；
- danmu_render_mode；
- WebSocket；
- 去重；
- style index；
- 颜色权重；
- 最大卡片数；
- column-reverse；
- 动画生命周期；
- 鼠标穿透和置顶。

不要完整移植 `yt-live-chat-*` DOM，不要把 blivechat 整个前端嵌入项目。

## 许可证

blivechat 为 MIT License。

若复制实质性 CSS或代码，新增或更新：

```text
THIRD_PARTY_NOTICES.md
```

保留：

```text
Copyright (c) 2019 xfgryujk
MIT License
```

## 执行方式

1. 先检查仓库当前实现和测试，不要假定文档中的行号永久准确；
2. 写一份简短实施计划；
3. 分阶段修改；
4. 每阶段运行相关测试；
5. 最后运行完整测试集；
6. 生成视觉 reference/candidate/diff；
7. 修复所有回归；
8. 输出实现报告。

不要停留在分析或只生成报告；本次需要完成代码实现、测试和验收。

## 最终输出

生成：

```text
docs/reports/BLIVECHAT_LINE_IMPLEMENTATION_REPORT.md
```

报告必须包含：

- 实际修改文件；
- 新增字段与预设；
- Web DOM/CSS 结构；
- QPainter 实现；
- 向后兼容说明；
- 测试命令；
- 测试结果；
- 视觉差异指标；
- 截图路径；
- 未完成项和已知风险。

如果无法达到阈值，必须明确写出差异位置和原因，不得宣称 1:1。
