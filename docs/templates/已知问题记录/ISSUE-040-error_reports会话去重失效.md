# 已知问题记录

## 问题 ID

ISSUE-040

## 发现时间

2026-06-01

## 发现来源

W-ERROR-REPORT-AUDIT-001（Supabase `error_reports` 只读审计）

## 所属模块

`web/static/app.js`（`ERROR_REPORT_DISMISS_STORAGE` / `sessionStorage`）、`supabase/migrations/002_error_reports.sql`（3h/3 条配额）

## 问题描述

Web 对同一 `error_fingerprint` 使用 `sessionStorage` 做 24h 内不重复弹窗。应用重启或新 Web 会话后 storage 清空，用户可对**同一错误**再次确认提交。

审计观测：指纹 `a6d2fbc0…`（HTTP 405 退避）由**同一** `client_id` 在约 19 分钟内提交 2 条（`1b33c49b…` 17:53 UTC、`7f19ce65…` 18:12 UTC）。库侧 `error_reports_insert_allowed` 仅限制 3h 内每 client 最多 3 条，不按 fingerprint 去重。

## 影响范围

- 运维：重复噪声、配额消耗
- 用户：可能重复点击「发送反馈」

## 严重程度

低

## 是否阻塞当前工单

否

## 状态

**已修复**（W-ERROR-REPORT-006，2026-06-01）

## 临时处理方式

Dashboard 按 `error_fingerprint` 分组查看；分析时取最新一条。

## 建议后续工单

W-ERROR-REPORT-006：将 dismiss/sent 指纹迁至 `localStorage`（与 `danmu_feedback_client_id` 同寿命），或 RPC 提交前检查近期同指纹行数

## 备注

- `client_id` 存于 `localStorage`（`danmu_feedback_client_id`），与 session 去重存储分离
- 与 ISSUE-036 叠加时，重复条目的 `logs_excerpt` 质量可能同样偏低
