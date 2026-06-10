# 已知问题记录

## 问题 ID

ISSUE-038

## 发现时间

2026-06-01

## 发现来源

W-ERROR-REPORT-AUDIT-001（Supabase `error_reports` 只读审计）

## 所属模块

`app/ai_client.py`（`format_http_status_error`）、`app/translations.py`（`ai.error_http_hidden`）

## 问题描述

当上游 HTTP 响应 body 消息为空或长度超过 240 时，`format_http_status_error` 将用户可见 `error_message` 设为「HTTP {code}: (详情已隐藏)」。该字符串进入 Web `summary` 并写入 Supabase。

审计中 3 条报告 summary 为 `HTTP 400/500/405: (详情已隐藏)`（指纹 `72f36b0d…`、`996b5281…`、退避包裹的 `a6d2fbc0…`），且部分报告 `logs_excerpt` 未包含可读的 provider 错误 body（见 ISSUE-036）。Dashboard 侧无法从 summary  alone 判断是参数错误、路由错误还是配额问题。

## 影响范围

- 运维分析 `error_reports`
- 用户仍能看到顶栏错误横幅（含隐藏文案）

## 严重程度

中

## 是否阻塞当前工单

否

## 状态

**已修复**（W-ERROR-REPORT-005，2026-06-01）

## 临时处理方式

让用户重试并打开 Web「诊断」页；或本地查未脱敏应用日志（若仍保留）。

## 建议后续工单

W-ERROR-REPORT-005：对上报专用路径保留**脱敏后**的短错误摘要（如截断 message、映射常见 code），与 UI 展示策略分离；须避免 API Key 泄漏

## 备注

- 对照：`ai.error_http_with_message` 在 message ≤240 时展示正文
- 样本 id：`1f196d32-11dc-4e62-b8d4-7916b14b0b9e`（400）、`c03e0fa3-09ea-4b54-b322-5fe0a5be6174`（500）
