# 已知问题记录

## 问题 ID

ISSUE-008

## 发现时间

2026-05-29

## 发现来源

用户反馈 / W-ANNOUNCE-BADGE-001 工单

## 所属模块

`web/static/app.js`（公告侧栏 `announcementsNavBadge`、未读判定）

## 问题描述

用户进入 Web 控制台「公告」页阅读内容后，**完全退出应用（托盘退出）再启动**，侧栏「公告」导航项仍显示红色未读圆点。原实现仅用 `localStorage` 键 `danmu_announcements_last_seen_at` 与服务端 `created_at` 做时间戳比较；`!lastSeen` 时一律视为未读，且 ISO 字符串往返可能出现精度/格式差异导致 `t > seenMs` 恒为真。已读状态未写入本机 `config.db`。

## 影响范围

用户可见（侧栏误导性未读提示）

## 严重程度

低

## 是否阻塞当前工单

否（已单独开工单 W-ANNOUNCE-BADGE-001 修复）

## 临时处理方式

每次进入公告页等待加载完成可暂时消除红点；重启后可能复现。

## 建议后续工单

已由 **W-ANNOUNCE-BADGE-001** 处理：按公告 `id` 集合判定未读 + `GET/PUT /api/announcements-read-state` 持久化至 `config.db`。

## 备注

- **状态**：已修复（2026-05-29）
- 完成报告：[W-ANNOUNCE-BADGE-001-完成报告.md](../Codex完成报告/W-ANNOUNCE-BADGE-001-完成报告.md)
- 相关常量：`ANNOUNCEMENTS_READ_IDS_KEY`、`announcements_read_state`（config.db）
- 与 ISSUE-007（Supabase 外网不可用）独立：007 为加载失败，008 为已读状态持久化/判定错误
