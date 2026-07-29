# 03｜QPainter 回退路径实施说明

## 1. 为什么必须修改

DanmuAI 默认优先使用 WebView2，但以下情况会回退到：

```text
app/floating_panel_overlay.py
```

例如：

- WebView2 Runtime 不可用；
- Web 面板启动失败；
- Web 面板连续重启达到上限；
- 配置显式关闭 Web 浮窗。

当前 QPainter 代码虽然注释称“用户名与内容分离”，但实际仍将用户名与首行内容绘制在同一个气泡主体、同一基线中。

这不符合 LineLike。

## 2. 验收定位

必须区分：

### Web 主路径

同 Chromium、同字体、同 DPR 条件下做像素级 1:1。

### QPainter 回退

由于 Qt 与 Chromium 的字体栅格化、字距和抗锯齿不同，不能承诺每个文字像素完全相同。

QPainter 必须达到：

- DOM/层级语义一致；
- 用户名在气泡外；
- 气泡几何一致；
- 尾巴锚点、尺寸、角度一致；
- 尺寸误差在验收容差内；
- 不退回“用户名在气泡里”的旧样式。

## 3. 推荐重构结构

不要继续让 `_render_card_pixmap()` 同时承担所有布局。

拆分为：

```python
_render_legacy_card_pixmap(...)
_render_line_like_pixmap(...)
```

入口：

```python
def _render_card_pixmap(...):
    if self._style.layout == "line_like":
        return self._render_line_like_pixmap(...)
    return self._render_legacy_card_pixmap(...)
```

这样可保护旧 `classic/wechat`。

## 4. 新增几何数据结构

建议定义内部 dataclass：

```python
@dataclass(frozen=True)
class _LineLikeGeometry:
    total_width: float
    total_height: float

    username_rect: QRectF
    bubble_rect: QRectF
    content_rect: QRectF

    tail_overhang_left: float
    tail_overhang_top: float

    shadow_pad_left: float
    shadow_pad_top: float
    shadow_pad_right: float
    shadow_pad_bottom: float
```

所有测量和绘制必须使用同一个几何结果，禁止分别猜尺寸。

## 5. 测量流程

### 5.1 字体

用户名：

```text
Noto Sans SC
18px
700
#CCCCCC
```

内容：

```text
Noto Sans SC
20px
700
#000000
line-height 1.2
```

Qt 中 `QFont` 的 point size 与 CSS px 不是完全等价。

推荐使用：

```python
font.setPixelSize(...)
```

而不是：

```python
font.setPointSize(...)
```

这样更接近 CSS 像素尺寸，也减少 DPI 差异。

旧布局若依赖 point size，可只在 `line_like` 分支使用 pixel size。

### 5.2 用户名块

```python
username_h = username_metrics.height()
username_w = username_metrics.horizontalAdvance(username_text)
author_gap = 5.0
```

用户名独立一行，不拼接内容。

### 5.3 内容块

```python
bubble_pad_x = 20.0
bubble_pad_y = 12.0
bubble_radius = 24.0
```

内容最多两行。

```python
bubble_body_w = text_w + 2 * bubble_pad_x
bubble_body_h = text_block_h + 2 * bubble_pad_y
```

长文本时：

```text
bubble body 宽度 = 可用最大宽度
```

短文本时：

```text
bubble body 宽度 = 文本自然宽度 + 40px
```

### 5.4 总尺寸

用户名与气泡左边缘对齐。

尾巴会超出气泡左侧和上方，因此 pixmap 必须分配 overhang。

推荐先保守计算：

```python
tail_left_overhang = 20.0
tail_top_overhang = 16.0
```

然后通过与 Chromium reference 截图对比调整到最小不裁切值。

总宽度：

```python
max(username_w, bubble_w + tail_left_overhang)
+ shadow pads
```

总高度：

```python
username_h
+ 5
+ tail_top_overhang
+ bubble_h
+ shadow pads
```

注意：用户名和尾巴上沿不能相互覆盖。

## 6. 尾巴绘制

上游 CSS 使用 border triangle：

```css
border: 8px solid transparent;
border-left-width: 18px;
border-right: 18px solid background;
transform: translate(-50%, -50%) rotate(35deg);
```

QPainter 不应继续使用当前 `round` 的贝塞尔水滴。

对 `tail_style == "blivechat_line"`：

1. 创建与 CSS border triangle 等价的三角多边形；
2. 尾巴锚点位于 `bubble_rect.topLeft()`；
3. 将三角中心平移到相当于 `translate(-50%, -50%)` 的位置；
4. 绕自身中心旋转 `35°`；
5. 使用气泡实际 RGBA 填充；
6. 无描边；
7. 在气泡主体之前或之后绘制，以与浏览器重叠关系一致；
8. 确保气泡主体覆盖尾巴不需要显示的接缝。

推荐辅助函数：

```python
def _line_like_tail_path(
    bubble_rect: QRectF,
    *,
    base: float = 8.0,
    long_edge: float = 18.0,
    angle_deg: float = 35.0,
) -> QPainterPath:
    ...
```

使用 `QTransform` 完成旋转，不要手工使用魔法坐标。

## 7. 绘制顺序

推荐：

```text
1. 清空透明 pixmap
2. 阴影
3. 尾巴
4. 圆角气泡主体
5. 气泡边框（默认关闭）
6. 用户名
7. 内容文字
```

用户名必须绘制在气泡外，不受气泡 clip。

## 8. 内容与用户名坐标

```python
username_x = visual_left
username_y = visual_top + username_ascent

bubble_x = visual_left
bubble_y = visual_top + username_h + 5 + tail_top_overhang

content_x = bubble_x + 20
content_y = bubble_y + 12
```

不要继续使用：

```python
username_w
content_max_w = max_text_w - username_w - gap
```

这是旧的“同一行”实现，LineLike 分支必须删除。

## 9. `_estimate_item_height`

当前估算只考虑内容气泡。

LineLike 下必须加入：

```text
username height
+ 5px gap
+ tail top overhang
+ bubble height
+ shadow pads
```

否则堆积引擎会让卡片互相覆盖。

建议：

```python
if st.layout == "line_like":
    return estimated_username_h + 5 + tail_top_overhang + estimated_bubble_h + shadow_h
```

## 10. `_prepare_item_pixmap`

LineLike 下不能继续将 `width` / `height` 仅解释为“整张内容 body”。

推荐：

- legacy 分支维持原接口；
- line_like 分支独立测量用户名和内容；
- 最终更新 `item.height` 为完整 pixmap 逻辑高度；
- `item.pixmap` 包含完整用户名 + 尾巴 + 气泡。

## 11. 颜色与透明度

气泡颜色仍使用：

```python
pick_palette_color(...)
```

并叠加：

```text
floating_panel_card_opacity
```

尾巴必须使用同一个 `QColor` 实例或相同 RGBA，避免接缝。

用户名使用：

```text
floating_panel_username_color
```

内容使用：

```text
floating_panel_text_colors
```

## 12. 阴影

上游 LineLike 默认无阴影。

`blivechat_line` 主验收：

```text
shadow_enabled = false
```

因此先确保无阴影 1:1。

custom 模式开启阴影时，阴影应该只作用于气泡+尾巴，不作用于用户名。

## 13. QPainter 兼容性测试

新增测试：

```text
test_line_like_username_is_above_bubble_geometry
test_line_like_total_height_includes_username_and_gap
test_line_like_tail_extends_from_bubble_top_left
test_line_like_tail_not_legacy_waterdrop
test_line_like_short_message_width_is_fit_content
test_line_like_long_message_respects_panel_width
test_line_like_two_lines_height
test_line_like_color_stable_after_apply_config
test_legacy_wechat_geometry_unchanged
test_classic_geometry_unchanged
```

## 14. 可测试几何接口

为了避免只能对 pixmap 做模糊判断，建议暴露内部纯函数：

```python
_measure_line_like_geometry(...)
```

测试直接断言：

```python
geometry.username_rect.bottom() + 5 <= geometry.bubble_rect.top()
geometry.username_rect.left() == geometry.bubble_rect.left()
geometry.content_rect.left() == geometry.bubble_rect.left() + 20
geometry.content_rect.top() == geometry.bubble_rect.top() + 12
```

## 15. 禁止方案

- 不允许只在 QPainter 中把用户名 `y` 往上挪，但仍画在同一个背景 path 中；
- 不允许继续用现有 `round` 水滴尾巴冒充 LineLike；
- 不允许为了省事在回退时强制改回 `wechat`；
- 不允许 QPainter 回退丢失用户名；
- 不允许测量与绘制各写一套坐标公式；
- 不允许修改堆积引擎的去重和生命周期逻辑。

## 16. QPainter 完成检查

- [ ] 使用 `layout` 分支；
- [ ] legacy 渲染保持原状；
- [ ] LineLike 用户名单独绘制；
- [ ] LineLike 用户名不在气泡 path 内；
- [ ] 气泡 padding 为 12/20；
- [ ] 气泡 radius 为 24；
- [ ] 尾巴锚定左上并旋转 35°；
- [ ] pixmap 不裁切尾巴；
- [ ] item height 包含用户名和 gap；
- [ ] 长文本不超面板；
- [ ] 全部 overlay 测试通过。
