# W-PET-BUBBLE-STYLE-001 完成报告

## 1. 修改摘要

将桌宠弹幕气泡从深色圆角提示框改为漫画对白框风格：白底、2px 深灰描边、20px 大圆角、深色文字、quadTo 平滑尾巴指向角色头顶。行为（跟随、淡入淡出、左右翻转）未改。

## 2. 修改的文件列表

| 路径 | 变更 |
|------|------|
| `app/pet/pet_window.py` | 新增样式常量、`BubbleLayout`、`bubble_colors`、`compute_bubble_layout`、`build_bubble_path`；改写 `_paint_bubble` |
| `tests/test_pet_window_bubble_style.py` | 新增 4 项样式/布局/淡入回归测试 |
| `reports/W-PET-BUBBLE-STYLE-001-report.md` | 本报告 |

## 3. 未修改的关键区域

- `main.py`、`app/pet/pet_barrage.py`、`app/main_display_mixin.py`
- `app/config_*`、`app/web_api/*`、`web/static/*`
- `app/mic_*`、CI / 发布脚本

## 4. 运行的命令

```bash
python -m pytest tests/test_pet_window_bubble_style.py tests/test_pet_window_drag.py -q -x
```

## 5. 构建/测试结果

| 批次 | 结果 |
|------|------|
| `tests/test_pet_window_bubble_style.py` | 4 passed |
| `tests/test_pet_window_drag.py` | 10 passed |

合计 **14 passed**。

## 6. 手动验证步骤与结果

| 步骤 | 状态 | 说明 |
|------|------|------|
| 开启桌宠弹幕，触发 5 条弹幕观察白底气泡 | 待负责人验收 | 需本地 `python main.py` + 真实 barrage 模式 |
| 拖动桌宠确认气泡跟随 | 待负责人验收 | 布局逻辑单测覆盖左右翻转 |
| 连续多轮弹幕确认淡入淡出 | 待负责人验收 | `set_bubble_text` 目标 alpha 单测回归通过 |
| 拖至屏幕边缘确认裁切可接受 | 待负责人验收 | 未改窗口几何，沿用既有裁切策略 |
| 单桌宠模式未破坏 | 待负责人验收 | 气泡仅 barrage 调用 `set_bubble_text` |

## 7. 风险与注意事项

- 气泡宽度仍大于 pet 窗口宽度时存在 widget 级水平裁切（既有行为，本工单未扩窗）。
- 2px 描边 + 大圆角已通过增大 `_BUBBLE_PADDING_*` 缓解文字区挤压。
- `_paint_bubble` 内启用 `Antialiasing` 减轻尾巴与圆角接缝锯齿。

## 8. 发现但未处理的问题

无。

## 9. 已更新的文档

- `reports/W-PET-BUBBLE-STYLE-001-report.md`

## 10. 验收标准对照

- [x] 代码层不再使用深色矩形主视觉（`rgb(30,30,38)` 已移除）
- [x] 白底 + 粗描边 + 大圆角 + 平滑尾巴实现
- [x] 深色文字与浅色底对比
- [ ] 5 桌宠实机气泡跟随/切换（待手动）
- [ ] 边缘裁切实机确认（待手动）
- [ ] 单桌宠模式实机确认（待手动）
- [x] 定向测试通过

## 11. 建议下一个工单

- 负责人完成本工单 5 步手动验收后关闭工单。
- 若边缘裁切影响可读性，可单独开「气泡布局/窗口高度」小工单（非本单范围）。
