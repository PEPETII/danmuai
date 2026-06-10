# 已知问题记录

## 问题 ID

ISSUE-037

## 发现时间

2026-06-01

## 发现来源

W-ERROR-REPORT-AUDIT-001（Supabase `error_reports` 只读审计）

## 所属模块

`app/application/diagnostic_snapshot.py`（`DiagnosticSnapshotBuilder`）、`web/static/app.js`（`collectErrorReportContext`）

## 问题描述

`error_reports.diagnostics_json` 由 `GET /api/diagnostics` → `build_diagnostic_snapshot()` 写入，当前仅含 scheduler/timing/runtime_state（代际 ID、统计）与 `diagnosis` 布尔标志，**不含** `active_model_id`、`provider_id`、`api_endpoint`（脱敏主机）等配置上下文。

`collectErrorReportContext` 在 `logs_excerpt` 末尾追加 `--- status ---` 块，仅含 `active_model_id` 与 `persona_names`；与 JSON 字段重复且不足以区分服务商/端点。运维对比多条 HTTP 405/400 报告时难以判断用户当时选用的模型与接入方式。

## 影响范围

- 开发/运维排障（Supabase 表数据）
- 不影响终端用户功能

## 严重程度

中

## 是否阻塞当前工单

否

## 状态

**已修复**（W-ERROR-REPORT-004，2026-06-01）

## 临时处理方式

请用户说明模型与服务商；或对照同期 `feedback` 表（若有）与版本号 `app_version`。

## 建议后续工单

W-ERROR-REPORT-004：在诊断快照或上报 payload 中增加只读字段（`active_model_id`、`provider_id`、endpoint 主机名脱敏），并同步 `buildDiagnosticReportText`

## 备注

- `GenerationPipelineState` 亦不含 model id（见 `app/application/generation_pipeline_state.py`）
- 审计时 9 条报告 `diagnostics_json` 均为 object，长度约 940–1083 字符
