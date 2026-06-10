# ISSUE-034

## 问题 ID

ISSUE-034

## 发现时间

2026-05-31

## 发现来源

用户反馈 / W-LAYOUT-OVERLAY-002

## 所属模块

`app/danmu_engine.py`、`app/overlay.py`、`main.py::_on_config_changed`

## 问题描述

弹幕运行中将 `layout_mode` 从 `fullscreen` 保存为 `1/2`（或 `1/4`、`3/4`）时：

1. 屏幕下半屏出现「冻结」的旧弹幕残影（透明 Overlay 脏区未覆盖 abandoned 区域，且 `paintEvent` 未 Clear）。
2. 原下半屏在播弹幕经 `reload_tracks(preserve_visible=True)` 后，由 `_nearest_track_for_y` 全部挤到新布局最底轨道，同 y 重叠。

## 影响范围

用户可见

## 严重程度

中

## 是否阻塞当前工单

否（W-LAYOUT-OVERLAY-002 已修）

## 临时处理方式

无（已代码处理）；缩小前可先停止弹幕再改布局（已不再需要）

## 建议后续工单

W-LAYOUT-OVERLAY-002（已完成）

## 备注

修复要点：

- `reload_tracks(clip_to_drawable=True)`：layout ratio 缩小时仅保留 `item.y` 仍在新 `drawable_height` 内的水平可见弹幕。
- `DanmuOverlay.show_for_screen`：检测 ratio 缩小 → 旧可绘制高度整带 `update()` + 下一帧 `CompositionMode_Clear`。

单测：`tests/test_layout_mode_overlay.py`。完成报告：[W-LAYOUT-OVERLAY-002-完成报告](../Codex完成报告/W-LAYOUT-OVERLAY-002-完成报告.md)。

**状态**：**已修复**（2026-05-31）
