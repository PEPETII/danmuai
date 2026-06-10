# 工单 W-ERROR-REPORT-002 — Web 错误反馈弹窗

## 工单 ID

W-ERROR-REPORT-002

## 工单标题

`is_error` 时 Web 确认弹窗与日志/诊断自动提交

## 背景

W-ERROR-REPORT-001 已提供 `error_reports` 与客户端 API。

## 目标

- `is_error` false→true 时弹出「是否要将该问题反馈」
- 确认后提交脱敏日志与诊断

## 依赖项

W-ERROR-REPORT-001

## 允许修改的区域

- `web/static/index.html`
- `web/static/app.js`
- `tests/test_bundle_paths.py`
- `docs/WEB_CONSOLE.md`、`docs/当前仓库状态.md`、`docs/工单列表.md`

## 禁止修改的区域

- `main.py`、`app/web_console.py`、`app/web_api/`

## 验收标准

- [x] `#errorReportModal` 与 `maybePromptErrorReport`
- [x] `pytest tests/test_bundle_paths.py tests/test_supabase_static.py -q` 通过

## 状态

已完成（2026-05-29）
