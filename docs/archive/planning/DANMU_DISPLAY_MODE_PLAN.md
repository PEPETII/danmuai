# 弹幕显示模式切换实施规划（已 superseded）

> **Archived.** Realtime mode was removed; only **normal mode** remains. See [CHANGELOG.md](../../CHANGELOG.md) Unreleased.

本规划描述已废弃的 `danmu_display_mode=realtime` 双模式方案。当前产品行为：

- 固定间隔截图 + `normal_reply_count` 批次
- 遗留 `realtime` 配置在启动时规范为 `normal`

---

## 目标（历史）

在 Web 控制台「设置 / 弹幕显示」tab 新增模式切换：

- `实时模式`：1 秒截图、200ms 节奏检查、预触发下一批 AI（**已移除**）
- `普通模式`：定时识别 + 每批 y 条弹幕（**当前唯一模式**）

## 验收标准（历史）

普通模式相关能力已实现；实时模式路径已删除。

完整原文见 git history 中 `docs/DANMU_DISPLAY_MODE_PLAN.md`（2026-05 文档治理前）。
