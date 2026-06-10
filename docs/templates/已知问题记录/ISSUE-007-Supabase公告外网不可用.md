# 已知问题记录

## 问题 ID

ISSUE-007

## 发现时间

2026-05-29

## 发现来源

Web 控制台 WebSocket 调试 / 用户 Console 报错

## 所属模块

`web/static/app.js`（公告页 / Supabase REST）

## 问题描述

未配置或无法访问 Supabase 时，`announcements` REST 请求失败（如 `net::ERR_CONNECTION_CLOSED`）。公告为可选功能，不影响弹幕、配置、WebSocket 状态/日志推送。

## 影响范围

用户可见（公告 Tab 为空或报错；核心控制台可用）

## 严重程度

低

## 是否阻塞当前工单

否

## 临时处理方式

不配置 `supabase-config.js` 时可忽略；或确保网络可访问 Supabase 项目域名。

## 建议后续工单

可选：公告加载失败时 UI 静默降级，减少 Console 噪音；或文档说明离线环境预期行为。

## 备注

见 `app.js` 公告相关逻辑与 `ANNOUNCEMENTS_*` 常量。
