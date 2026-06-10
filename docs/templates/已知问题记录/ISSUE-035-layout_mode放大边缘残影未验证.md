# ISSUE-035

## 问题 ID

ISSUE-035

## 发现时间

2026-05-31

## 发现来源

W-LAYOUT-OVERLAY-002 完成报告 / 计划风险项

## 所属模块

`app/overlay.py`

## 问题描述

W-LAYOUT-OVERLAY-002 仅对 **layout ratio 缩小**（如 1/2→1/4、fullscreen→1/2）启用 `clip_to_drawable` 与整带 Clear。**放大**（如 1/2→fullscreen）仍 `preserve_visible=True` 且不触发缩小专用 repaint。若透明层在可绘制带外缘留有旧帧，放大后边缘可能出现短暂残影；本环境未复现，待手动验收确认。

## 影响范围

用户可见（若复现）

## 严重程度

低

## 是否阻塞当前工单

否

## 临时处理方式

放大布局后若见边缘残影，可停止再启动弹幕，或切换一次 layout 触发重绘

## 建议后续工单

W-LAYOUT-OVERLAY-003（可选：放大时对称 Clear / 全 widget update）

## 备注

与 ISSUE-034（缩小，**已修复**）对称；勿与主链路截图/AI 工单混做。

**状态**：待处理
