# Codex 完成报告

> 工单 ID：W-ERROR-REPORT-AUDIT-001  
> 完成时间：2026-06-01  
> 执行者：Cursor Agent

---

## 1. 修改摘要

对生产 Supabase `public.error_reports` 执行只读 SQL 审计（共 **9** 条，2026-05-31，均为 `app_version=0.2.2`）。上报链路（`is_error` → 模态框 → `submitErrorReport`）可用，但 **6/9** 条在运维侧难以仅凭表字段定位根因：日志摘录缺 ERROR、HTTP 摘要被隐藏、诊断 JSON 缺模型/端点上下文。另登记 3 条用户配置类根因（无协议 endpoint、模型不存在、429）供后续代码工单处理。本工单仅更新文档，未改业务代码。

## 2. 修改的文件

- `docs/templates/Codex完成报告/W-ERROR-REPORT-AUDIT-001-完成报告.md`
- `docs/templates/已知问题记录/ISSUE-036-error_reports日志摘录缺ERROR.md`
- `docs/templates/已知问题记录/ISSUE-037-error_reports诊断缺模型上下文.md`
- `docs/templates/已知问题记录/ISSUE-038-error_reports_HTTP详情已隐藏.md`
- `docs/templates/已知问题记录/ISSUE-039-api_endpoint未校验协议.md`
- `docs/templates/已知问题记录/ISSUE-040-error_reports会话去重失效.md`
- `docs/已知问题与后续事项.md`
- `docs/工单列表.md`
- `docs/当前仓库状态.md`

## 3. 未修改的关键区域

- 未修改 `app/`：是
- 未修改 `web/`：是
- 未修改 `main.py`：是
- 未修改 `tests/`：是
- 未修改 `supabase/migrations/`：是

## 4. 运行的命令

```sql
-- 总量（Supabase MCP execute_sql）
SELECT count(*) AS total_rows,
       min(created_at) AS first_at,
       max(created_at) AS last_at,
       count(DISTINCT client_id) AS distinct_clients,
       count(DISTINCT error_fingerprint) AS distinct_fingerprints
FROM public.error_reports;
-- 结果：9 行，7 client，7 指纹；2026-05-31 05:28～18:12 UTC

-- 指纹聚类
SELECT error_fingerprint, count(*) AS cnt, count(DISTINCT client_id) AS clients,
       min(created_at) AS first_at, max(created_at) AS last_at,
       array_agg(DISTINCT left(summary, 100)) AS summaries
FROM public.error_reports
GROUP BY error_fingerprint ORDER BY cnt DESC, last_at DESC;

-- 逐条质量（节选列）
SELECT id, created_at, left(summary, 80) AS summary_short,
       length(logs_excerpt) AS logs_len,
       (logs_excerpt LIKE '%ERROR%') AS has_error_level,
       (logs_excerpt LIKE '%405%') AS has_405_literal,
       (logs_excerpt LIKE '%--- diagnostics ---%') AS has_diag_section,
       (logs_excerpt LIKE '%--- status ---%') AS has_status_section
FROM public.error_reports ORDER BY created_at DESC;
```

### 审计摘要表

| 指标 | 值 |
|------|-----|
| 总行数 | 9 |
| 独立 client_id | 7 |
| 独立 error_fingerprint | 7 |
| 重复指纹（cnt>1） | 2（`a6d2fbc…` 同 client×2；`06eb09a…` 2 client×各1） |
| summary 含「详情已隐藏」 | 3（含 2 条 405 退避） |
| summary 含 missing protocol | 3 |
| logs 无 ERROR 行 | 3（均为退避类 summary 的 405 / missing protocol） |
| logs 无字面量 `405`（405 报告） | 2 |

### 指纹聚类（用户可见 summary）

| 指纹（前 8 位） | 条数 | 典型 summary |
|-----------------|------|----------------|
| a6d2fbc0 | 2 | 连续 5 次失败 + HTTP 405 (详情已隐藏) |
| 06eb09a8 | 2 | 连续 5 次失败 + URL 缺少 http(s) 协议 |
| 3487426e | 1 | 模型不存在，请检查模型设置 |
| 72f36b0d | 1 | HTTP 400 (详情已隐藏) |
| 996b5281 | 1 | HTTP 500 (详情已隐藏) |
| 21467cb0 | 1 | 请求过于频繁，请稍后重试 |
| ecc25637 | 1 | URL 缺少 http(s) 协议（单次） |

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest | 未运行 | 文档工单 |
| boundary_guard | 未运行 | 未改 `app/` |
| git diff | 仅 `docs/` | 见 §2 |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| Supabase Dashboard → `error_reports` 行数 | 9 | MCP 查询 9 | 是 |
| `git diff --name-only` | 仅 `docs/**` | 待负责人本地确认 | — |
| 完成报告与 ISSUE-036～040 链接一致 | 可打开 | 已写入 templates | 是 |

## 7. 风险与注意事项

- 审计数据含用户错误摘要，勿将完整 `logs_excerpt` 复制到公开渠道。
- HTTP 405 根因未在本工单调查（可能为 endpoint/transport 与上游路径不匹配），需单独复现工单。
- ISSUE-027 已修复 catalog pro 404，但 `3487426e…` 报告仍可能来自历史配置或其它 model id。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| ISSUE-036 | 日志摘录缺 ERROR/HTTP | 是 |
| ISSUE-037 | 诊断缺 model/provider | 是 |
| ISSUE-038 | HTTP「详情已隐藏」难溯源 | 是 |
| ISSUE-039 | 全局 api_endpoint 无协议校验 | 是 |
| ISSUE-040 | session 去重致重复入库 | 是 |
| ISSUE-017 | 致命异常无 Web 反馈（既有） | 是（未改） |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/已知问题与后续事项.md](../../已知问题与后续事项.md)

## 10. 建议下一个工单

- **W-ERROR-REPORT-003**（ISSUE-036）：仅改 `web/static/app.js` 日志摘录，风险最小。
- **W-CONFIG-ENDPOINT-001**（ISSUE-039）：阻断无协议 endpoint 写入，减少无效上报。
- **W-ERROR-REPORT-004/005/006**：诊断字段、HTTP 摘要、localStorage 去重，按优先级拆分。
