# 工单 W-ERROR-REPORT-001 — Supabase 错误报告表与客户端

## 工单 ID

W-ERROR-REPORT-001

## 工单标题

Supabase `error_reports` 表与 `submitErrorReport` 客户端 API

## 背景

需在用户确认后接收自动错误反馈（日志摘录、诊断 JSON），与手动 `feedback` 分离。

## 目标

- 迁移 `002_error_reports.sql` 可应用
- `DanmuSupabase.submitErrorReport` / `getErrorReportQuota` 可用

## 依赖项

无（`001_announcements_feedback.sql` 已存在）

## 允许修改的区域

- `supabase/migrations/002_error_reports.sql`
- `supabase/README.md`
- `web/static/supabase-client.js`
- `web/static/supabase-config.example.js`
- `tests/test_supabase_static.py`
- `docs/WEB_CONSOLE.md`

## 禁止修改的区域

- `main.py`、`app/`
- `web/static/app.js`、`web/static/index.html`

## 验收标准

- [x] 迁移含 RLS 与 `error_reports_quota`
- [x] 客户端 POST `/rest/v1/error_reports`
- [x] `pytest tests/test_supabase_static.py -q` 通过

## 状态

已完成（2026-05-29）
