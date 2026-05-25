# 截图与弹幕外部参考整理

> 来源整理：`SCREENSHOT_BACKEND_MSS.md` 与 `danmaku_reference.md`。  
> 参考项目：[python-mss](https://github.com/BoboTiG/python-mss)、[weizhenye/Danmaku](https://github.com/weizhenye/Danmaku)。  
> 文档定位：工程决策参考，不代表立即引入新运行时依赖。

## 结论

python-mss 和 Danmaku 都对 DanmuAI 有参考价值，但当前不应直接替换现有 Qt 截图链路或 PyQt Overlay。

短期优先级应是：

1. 修复当前红灯测试，先恢复主流程可信度。
2. 保持现有 Qt-only region 裁剪路径，避免在无 benchmark 前引入新后端。
3. 后续增加 Qt vs mss 截图基准脚本，用数据决定是否引入 mss。
4. 做 Web 弹幕样式预览时，优先实现轻量自研预览，不直接把 Danmaku 作为生产依赖。

核心原则：生产路径仍保持 `main.py -> DanmuEngine -> DanmuOverlay`。新 UI 能力仍优先落在 `web/static/` 与 `app/web_api/`。

## 当前事实

截图链路：

```text
screenshot_timer（Qt 主线程）
  -> ScreenCapturer.grab()              app/snipper.py
  -> QPixmap（按 screen_index 全屏）
  -> _probe_scene_change()              app/scene_fingerprint.py
  -> _trigger_api_call()
  -> QThreadPool + AiRunnable
  -> compress_screenshot()              main.py（QPixmap -> PIL -> JPEG Base64）
  -> httpx -> AI API
```

弹幕链路：

```text
AI 回复
  -> AIReplyFIFOBuffer
  -> DanmuEngine.add_text/add_item       app/danmu_engine.py
  -> DanmuOverlay.update/paintEvent      app/overlay.py
```

已有能力：

| 方向 | 当前状态 |
|------|----------|
| 多屏选择 | `screen_index` 已用于截图与 Overlay |
| 区域裁剪 | `region_x/y/w/h` 按所选屏幕左上角的相对坐标参与截图裁剪 |
| 场景新鲜度 | `scene_generation`、`batch_id`、过时回复丢弃已存在 |
| 弹幕轨道 | `_pick_track`、`min_on_screen`、`right_visible_count` 已存在 |
| 渲染优化 | Overlay 具备 pixmap 缓存、脏区刷新、不可见停渲染 |
| Web 预览 | 已有图片压缩预览，无弹幕滚动样式预览 |

## python-mss 的价值与边界

python-mss 的主要价值在截图区域、多屏坐标和性能对照，而不是替代整个桌面栈。

值得借鉴：

- `sct.monitors[0]` 表示虚拟桌面整体，`sct.monitors[N]` 表示单屏。
- `grab({"left", "top", "width", "height"})` 天然支持任意矩形区域。
- 输出 raw RGB/BGRA，和 Pillow 衔接直接。
- MIT 许可证，未来作为依赖接入没有额外 copyleft 压力。

暂不直接集成的原因：

- 当前截图节奏约 1Hz，瓶颈更可能在 JPEG 压缩、Base64、网络请求和模型响应。
- 项目仍依赖 `QApplication` 处理 Overlay、托盘、pywebview 壳和屏幕列表。
- 在没有 benchmark 前增加双后端抽象，会扩大维护面。
- 高 DPI、多屏坐标和虚拟桌面坐标需要实机验证，不能只凭接口形态切换。

### 截图坐标决策

`region_*` 建议定义为“相对所选屏幕左上角”的坐标，而不是虚拟桌面绝对坐标。

理由：

- 更符合用户在设置页选择 `screen_index` 后再框选区域的心智。
- 与当前 Overlay 定位、屏幕下拉和文案更一致。
- 未来接 mss 时只需要在后端把屏内相对坐标换算为虚拟桌面绝对坐标。

建议语义：

| 字段 | 语义 |
|------|------|
| `screen_index` | 目标显示器 |
| `region_x` | 相对目标显示器左上角的 x |
| `region_y` | 相对目标显示器左上角的 y |
| `region_w` | 裁剪宽度，`<= 0` 表示禁用 region |
| `region_h` | 裁剪高度，`<= 0` 表示禁用 region |

无效 region 应回退全屏截图，不应让截图失败。

## Danmaku 的价值与边界

Danmaku 是浏览器弹幕渲染库，适合作为 Web 预览和轨道算法参考，不适合替代 PyQt Overlay。

值得借鉴：

- live mode 的 `emit(comment)` 思路适合设置页弹幕预览。
- `willCollide` 这类时间维碰撞预测可作为 `_pick_track` 的后续增强参考。
- 简洁生命周期 API 可用于未来内部 facade 命名参考。

暂不直接集成到生产路径的原因：

- DanmuAI 的真实上屏必须走 PyQt 透明置顶窗口和 Win32 透明穿透能力。
- DanmuAI 弹幕调度不只是渲染，还承担 AI 请求节奏、场景新鲜度、去重、批次清退。
- Web canvas 预览无法完全复现 Qt 字体度量、透明合成、淡入淡出和真实桌面叠加效果。
- 引入 JS 弹幕引擎驱动真实 Overlay 会产生双引擎状态同步问题。

### Web 弹幕预览决策

建议优先做轻量自研预览，而不是直接引入 Danmaku。

预览目标不是完全模拟生产物理，而是让用户能感知这些配置的相对效果：

| 配置 | 预览行为 |
|------|----------|
| `danmu_speed` | 调整水平移动速度 |
| `danmu_lines` | 调整可用轨道数 |
| `font_size` | 调整文字大小 |
| `opacity` | 调整整体透明度 |
| `danmu_max_chars` | 调整样例文本截断 |

预览应明确标注“近似预览”，避免用户误以为与真实 Overlay 完全一致。

如果后续决定引入 Danmaku，应仅限 `web/static/` 的预览区域，并在开源审计中记录 MIT 依赖；不得让它参与真实上屏链路。

## 推荐落地顺序

### 阶段 0：恢复测试可信度

先修复当前已知红灯测试，再扩展截图或弹幕能力。

重点包括：

- 场景新鲜度测试与 `probe_size` 参数不一致。
- `DanmuApp.__new__` 最小实例访问 QObject 属性导致 RuntimeError。
- OpenAI 流式 mock 返回值与 `_stream_openai` 实际接口不一致。
- WebView fallback 行为与测试断言不一致。
- pytest 9 下 `basetemp` 配置告警。

### 阶段 1：Qt-only region 裁剪

目标：让已有 `region_*` 配置真正生效，不引入新依赖。

实现方向：

- 在 `ScreenCapturer.grab()` 中读取 `config.get_region()`。
- 按“相对所选屏幕”的语义裁剪。
- region 无效或越界时回退/夹取到有效屏幕范围。
- Web 文案与隐私说明应明确 region 已参与裁剪，以及无效区域会回退全屏。
- 扩展 `tests/test_snipper.py`，覆盖全屏、有效 region、无效 region、越界 region、多屏索引回退。

这一阶段即可满足路线图里“region 参与裁剪”的核心目标。

### 阶段 2：截图后端基准

目标：用数据判断是否需要 mss。

建议新增脚本，不进入 CI 必跑：

```text
scripts/bench_capture_backend.py
  -> Qt full screen
  -> Qt region
  -> mss full screen（如果安装 mss）
  -> mss region（如果安装 mss）
```

记录指标：

- grab 耗时
- 图像尺寸与像素数
- JPEG 压缩耗时
- Base64 长度
- 多屏坐标差异

只有当 mss 在目标场景有明确收益时，再进入阶段 3。

### 阶段 3：可选 mss 后端

前提：阶段 2 证明 mss 有实际收益。

建议以保守方式接入：

```text
capture_backend = "qt" | "mss"
默认：qt
实验：DANMU_CAPTURE_BACKEND=mss
```

接入要求：

- 不改变 Overlay、托盘、Web 壳和 Qt 主事件循环。
- 不把上游源码 vendored 进仓库，使用 PyPI `mss`。
- 更新 `requirements.txt` 或可选依赖策略。
- 更新 `OPEN_SOURCE_AUDIT.md`。
- Windows CI 至少覆盖导入和基础 grab mock，不依赖真实桌面结果。

### 阶段 4：Web 弹幕样式预览

目标：让用户在设置页直观看到弹幕配置的近似效果。

建议实现：

- 在设置页“弹幕显示”区域加入 preview canvas/container。
- 使用轻量 JS 动画生成几条样例弹幕。
- 监听 `danmu_speed`、`danmu_lines`、`font_size`、`opacity`、`danmu_max_chars`。
- 只做视觉近似，不参与真实 Overlay。

若后续自研预览不足，再评估是否仅在预览区域引入 Danmaku。

### 阶段 5：轨道碰撞预测增强

前提：真实使用或测试证明长弹幕、高速、密集入队时存在追尾/重叠。

可参考 Danmaku 的 `willCollide` 思路增强 `_pick_track`：

- 保留现有 `can_accept` 和 fallback。
- 增加“新弹幕是否会追上同轨上一条”的预测。
- 单测覆盖长文本、高速、多条连续入队、`random.choices` 确定性路径。

不建议为了算法洁癖提前重写轨道系统。

## 明确不做

- 不用 mss 替换 Qt 桌面栈。
- 不用 Danmaku 替换 `DanmuOverlay`。
- 不在真实上屏路径里加载 WebView/canvas 弹幕引擎。
- 不在没有 benchmark 的情况下引入双截图后端。
- 不改变 `scene_generation`、`batch_id`、去重和 API 节奏调度的业务语义。

## 后续验收标准

region 裁剪完成后：

- 设置 region 后，发送给 AI 的截图尺寸应小于或等于 region 尺寸经过压缩后的结果。
- 场景指纹基于裁剪后的图像计算。
- 无效 region 不导致截图失败。
- Web/README/隐私文案与真实行为一致。

mss 后端进入实验后：

- Qt 与 mss 在同一屏幕、同一 region 下坐标偏差可解释。
- 高 DPI、多屏缩放场景有记录。
- mss 失败时可回退 Qt 或清晰报错。

Web 弹幕预览完成后：

- 不需要后端 API 即可预览基本样式。
- 修改弹幕相关配置时预览实时响应。
- 预览区域不影响真实 Overlay 状态。

## 决策记录

| 日期 | 决策 | 说明 |
|------|------|------|
| 2026-05-25 | 暂不引入 mss 主流程 | 先用 Qt 实现 region，再用 benchmark 决策 |
| 2026-05-25 | 暂不引入 Danmaku 生产路径 | 仅作为 Web 预览和轨道算法参考 |
| 2026-05-25 | `region_*` 使用屏内相对坐标并由 Qt 截图链路执行裁剪 | 更符合 `screen_index` 心智，未来可换算到 mss 绝对坐标 |
