# 已知问题记录

## 问题 ID

ISSUE-019

## 发现时间

2026-05-29

## 发现来源

W-APP-UPDATE-001 实现

## 所属模块

Supabase / `app_updates`

## 问题描述

客户端已依赖 `public.app_updates` 表读取 `latest_version`。若生产 Supabase 尚未执行 `supabase/migrations/003_app_updates.sql` 或未插入 `enabled=true` 配置行，Web 侧栏将显示「检查失败」，无法展示最新版本或弹窗提醒。

## 影响范围

版本更新提醒功能；不影响弹幕主链路与应用启动。

## 严重程度

低

## 是否阻塞当前工单

否

## 临时处理方式

在 Supabase Dashboard 按 [`supabase/README.md`](../../../supabase/README.md) 执行迁移并插入一行 `app_updates`。

## 建议后续工单

运维 checklist 或发布脚本中自动校验 `app_updates` 行存在。

## 备注

见 [W-APP-UPDATE-001-完成报告](../Codex完成报告/W-APP-UPDATE-001-完成报告.md) §7。
