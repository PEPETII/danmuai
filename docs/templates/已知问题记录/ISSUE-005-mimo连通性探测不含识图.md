# 已知问题记录

> **规则**：当前工单范围外的问题 **不要顺手修**。先按本模板记录到 [docs/workflow/已知问题与后续事项.md](../../workflow/已知问题与后续事项.md)，再由负责人在 [docs/workflow/工单列表.md](../../workflow/工单列表.md) 单独开工单处理。

---

## 问题 ID

ISSUE-005

## 发现时间

2026-05-29

## 发现来源

W-004 手动验收分析 / [W-004-完成报告.md](../Codex完成报告/W-004-完成报告.md)

## 所属模块

`app/api_probe.py`、Web 助手设置「测试连接」

## 问题描述

`probe_connection` → `_probe_openai` 仅发送纯文本 `ping`，不含截图或 `image_url`。小米 MiMo 等视觉模型在 Web 上显示「连接成功」，但主链路识图请求仍可能因模型权限、配额、`thinking` 或请求体问题失败，易造成「测试通过但弹幕不出」的误解。

## 影响范围

用户排障体验；支持/开发误判为「网络正常即功能正常」

## 严重程度

低

## 是否阻塞当前工单

否

## 临时处理方式

以开始弹幕后日志为准：HTTP 4xx/「AI 返回为空」/`reason=mimo_reasoning_only`；勿仅依赖连接测试。

## 建议后续工单

可选：MiMo 专用 probe 带最小 Base64 图（1×1 PNG）或文档说明 probe 范围。

## 备注

W-004 已对齐 `ai_client` 识图请求体；未改 `api_probe` 行为。
