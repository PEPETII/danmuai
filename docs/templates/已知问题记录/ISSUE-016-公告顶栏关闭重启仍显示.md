# 已知问题记录

## 问题 ID

ISSUE-016

## 发现时间

2026-05-29

## 发现来源

用户反馈 / W-022 工单

## 所属模块

`web/static/app.js`（温馨控制台顶栏 `overviewAnnouncementBanner`）

## 问题描述

用户在温馨控制台点击顶栏公告「×」关闭后，**完全退出应用（托盘退出）再启动**，顶栏简略条仍会显示。原实现仅将已关闭的公告 `id` 写入 `localStorage` 键 `danmu_announcements_overview_banner_dismissed_id`，未经 `PUT /api/announcements-read-state` 写入本机 `config.db`；pywebview / WebView2 环境下 `localStorage` 常在重启后丢失。

## 影响范围

用户可见（重复打扰；与侧栏红点 ISSUE-008 同类根因）

## 严重程度

低

## 是否阻塞当前工单

否（已由 W-022 修复）

## 临时处理方式

每次会话内点 × 可暂时隐藏；重启后可能复现（修复前）。

## 建议后续工单

已由 **W-022** 处理：扩展 `announcements_read_state` 的 `overviewBannerDismissedId` 字段 + 前端双写 `config.db` 与 `localStorage`。

## 备注

- **状态**：已修复（2026-05-29）
- 完成报告：[W-022-完成报告.md](../Codex完成报告/W-022-完成报告.md)
- 与 ISSUE-008（侧栏红点）独立：顶栏关闭不等于「已读」、不消除红点
- 与 W-008 设计一致：仅存储单个 dismissed id；同 id 改正文不会再次显示顶栏
