# 04｜测试与视觉 1:1 验收说明

## 1. 验收原则

“看起来很像”不算完成。

必须同时进行：

1. 配置契约测试；
2. DOM/CSS 结构测试；
3. Web 协议测试；
4. 几何尺寸测试；
5. Chromium 同环境截图对比；
6. QPainter 回退布局测试；
7. 原有预设回归测试。

---

## 2. 固定参考环境

视觉测试必须固定：

```text
Viewport: 360 × 520
Device scale factor: 1
Browser zoom: 100%
Background: transparent 或统一深色测试底
Font: Noto Sans SC（若环境没有，reference 与 candidate 必须使用同一 fallback）
Animation: 首帧几何测试时关闭；动画测试单独进行
```

参考与候选必须在同一个 Chromium 进程/版本中截图。

---

## 3. 建立最小上游参考 fixture

建议新增：

```text
tests/visual/fixtures/blivechat_line_reference.html
```

只包含普通文字消息需要的最小 DOM 与 LineLike CSS。

示例 DOM：

```html
<div class="reference-message">
  <div class="reference-username">弹幕</div>
  <div class="reference-bubble">
    <span class="reference-content">这波操作666</span>
  </div>
</div>
```

CSS 必须按上游 LineLike 默认参数实现：

```css
.reference-username {
  margin-bottom: 5px;
  font-family: "Noto Sans SC", sans-serif;
  font-size: 18px;
  font-weight: 700;
  color: #CCCCCC;
}

.reference-bubble {
  display: block;
  position: relative;
  width: fit-content;
  overflow: visible;
  padding: 12px 20px;
  border-radius: 24px;
  background: #FFFFFF;
}

.reference-bubble::before {
  content: "";
  display: block;
  position: absolute;
  top: 0;
  left: 0;
  border: 8px solid transparent;
  border-left-width: 18px;
  border-right: 18px solid #FFFFFF;
  transform: translate(-50%, -50%) rotate(35deg);
}

.reference-content {
  font-family: "Noto Sans SC", sans-serif;
  font-size: 20px;
  font-weight: 700;
  color: #000000;
  line-height: 1.2;
}
```

文件顶部加入来源和 MIT 版权说明。

---

## 4. 候选页面

推荐直接加载：

```text
web/static/floating_panel/index.html
```

通过 WebSocket 测试桥发送：

```json
{
  "type": "card",
  "id": "visual-case-1",
  "username": "弹幕",
  "content": "这波操作666",
  "style": {
    "layout": "line_like",
    "shape": "bubble",
    "tail_enabled": true,
    "tail_style": "blivechat_line",
    "tail_width": 18,
    "tail_height": 8,
    "padding_x": 20,
    "padding_y": 12,
    "border_radius": 24
  }
}
```

如果测试环境启动真实 WS 成本过高，可为 `app.js` 增加仅测试可调用的纯函数，或使用独立 candidate fixture，但不得让 candidate fixture 另写一套 CSS。

---

## 5. 固定视觉用例

至少包含：

### Case A：短消息

```text
用户名：弹幕
内容：这波操作666
```

检查 `width: fit-content`。

### Case B：极短消息

```text
用户名：AI
内容：6
```

检查最小气泡和尾巴。

### Case C：中文长消息

```text
这是一条用于验证换行宽度和两行高度的测试弹幕内容
```

检查两行换行。

### Case D：中英数字混合

```text
Boss HP 10%，快收尾！
```

检查字距与断行。

### Case E：用户名较长

```text
测试人格名称很长
```

检查用户名不会改变气泡自然宽度，外层宽度取两者最大值。

### Case F：用户名隐藏

检查气泡上方不残留 5px 空白。

---

## 6. Bounding box 断言

对 reference 和 candidate 分别读取：

```js
getBoundingClientRect()
```

元素：

```text
message/card
username
bubble
content
```

阈值：

```text
left/top/right/bottom：误差 ≤ 1 CSS px
width/height：误差 ≤ 1 CSS px
用户名与气泡 gap：误差 ≤ 0.5 CSS px
```

尾巴可通过 pseudo-element computed style 与截图共同验证：

```js
getComputedStyle(bubble, "::before")
```

断言：

```text
top = 0px
left = 0px
border-top-width = 8px
border-left-width = 18px
border-right-width = 18px
transform 含 35deg 等价矩阵
```

---

## 7. 像素差异测试

推荐使用 Playwright/Puppeteer + Pillow。

流程：

1. reference 截图；
2. candidate 截图；
3. 裁切到消息组件边界；
4. 统一画布尺寸；
5. 计算差异图；
6. 输出：
   - `reference.png`
   - `candidate.png`
   - `diff.png`
   - JSON 指标。

建议阈值：

```text
几何边界完全通过后：
不同像素占比 ≤ 0.5%
平均通道绝对误差 ≤ 1.5
```

如果环境字体抗锯齿造成文字像素差异：

- 额外做“仅气泡+尾巴遮罩”的像素比较；
- 气泡+尾巴不同像素占比应 ≤ 0.1%；
- 文字部分以 bounding box、字号、字重 computed style 为主。

不得直接把阈值调到很大以掩盖布局错误。

---

## 8. 动画验收

LineLike 上游默认：

```text
fadeInTime = 200ms
slide = true
reverseSlide = false
```

分别在：

```text
0ms
100ms
200ms
```

采样。

断言：

- 0ms 透明；
- 中间帧透明度与位移处于插值状态；
- 200ms opacity=1；
- 结束时无残留 transform；
- 新卡片加入不会使旧卡片闪烁；
- `column-reverse` 堆积顺序不变。

若 DanmuAI 现有 `slideUp` 方向与上游横向 slide 不同，必须按目标 reference 校准；不能因为已有动画叫 `slideUp` 就默认保留。

---

## 9. 配置契约测试

更新：

```text
tests/test_floating_panel_style.py
```

新增断言：

```python
assert "blivechat_line" in STYLE_PRESETS
assert STYLE_PRESETS["blivechat_line"]["floating_panel_layout"] == "line_like"
assert STYLE_PRESETS["blivechat_line"]["floating_panel_padding_x"] == "20"
assert STYLE_PRESETS["blivechat_line"]["floating_panel_padding_y"] == "12"
assert STYLE_PRESETS["blivechat_line"]["floating_panel_radius"] == "24"
assert STYLE_PRESETS["blivechat_line"]["floating_panel_tail_width"] == "18"
assert STYLE_PRESETS["blivechat_line"]["floating_panel_tail_height"] == "8"
assert STYLE_PRESETS["blivechat_line"]["floating_panel_username_size"] == "18"
assert STYLE_PRESETS["blivechat_line"]["floating_panel_content_size"] == "20"
```

同时更新当前只允许：

```python
{"classic", "wechat"}
```

的测试。

新增：

```text
test_invalid_layout_falls_back
test_line_like_layout_roundtrip
test_blivechat_line_patch_does_not_touch_render_mode
test_legacy_missing_layout_defaults_to_card
```

---

## 10. 协议测试

对 `CardStyle` 增加：

```text
test_card_style_layout_default_is_card
test_card_style_layout_roundtrip
test_card_style_old_payload_without_layout_is_compatible
```

---

## 11. 样式生成器测试

更新：

```text
tests/test_style_generator_page.py
```

断言：

- HTML 中有 `data-preset="blivechat_line"`；
- 有 `floating_panel_layout` 控件；
- `STYLE_SAVE_KEYS` 包含 layout；
- 预览 JS 创建 `.bubble`；
- CSS 有 `.layout-line-like > .bubble`；
- CSS 尾巴选择器挂在 `.bubble::before`；
- 不允许 LineLike 尾巴仍挂在 card wrapper；
- 预览和真实 CSS 变量名一致。

---

## 12. QPainter 测试

更新：

```text
tests/test_floating_panel_overlay.py
```

推荐增加纯几何断言，不只检查 pixmap 是否存在。

要求：

```text
username_rect.bottom < bubble_rect.top
gap = 5
bubble padding x = 20
bubble padding y = 12
bubble radius = 24
tail anchor = bubble top-left
```

旧测试必须继续通过：

- classic 无尾巴；
- wechat 旧尾巴；
- panel width budget；
- style index 稳定；
- apply_config 不清空；
- 左对齐；
- clip rect；
- timer lifecycle。

---

## 13. 手工验收

### 样式生成器

- [ ] 点击 `blivechat 气泡`；
- [ ] 用户名在气泡外；
- [ ] 预览三条消息布局正常；
- [ ] 修改颜色即时更新；
- [ ] 修改文字即时更新；
- [ ] 保存后刷新仍保留；
- [ ] 切回 classic/wechat 正常；
- [ ] 手动修改后标记 custom。

### 真实 WebView2 浮窗

- [ ] 与预览一致；
- [ ] 透明背景正常；
- [ ] 鼠标穿透正常；
- [ ] 多卡片堆积正常；
- [ ] 长消息不越界；
- [ ] 尾巴不裁切；
- [ ] 面板边缘第一条卡片不裁切；
- [ ] 热更新可刷新现有或后续卡片，行为符合项目约定。

### QPainter 回退

临时设置：

```text
floating_panel_use_web = 0
```

检查：

- [ ] 用户名仍在气泡外；
- [ ] 不重回旧整卡；
- [ ] 尾巴位置合理；
- [ ] 无重叠；
- [ ] 长文本宽度正常；
- [ ] DPI 100%、125%、150% 可用。

---

## 14. 最终报告要求

IDE 完成后必须输出：

```text
docs/reports/BLIVECHAT_LINE_IMPLEMENTATION_REPORT.md
```

包含：

1. 修改文件；
2. 核心架构；
3. 新增配置字段；
4. 兼容策略；
5. Web 与 QPainter 差异；
6. 测试命令和结果；
7. reference/candidate/diff 图片路径；
8. 未完成项；
9. 已知风险；
10. 是否达到 1:1 阈值。

不得只回复“已完成”。
