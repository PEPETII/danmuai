# ISSUE-015：api_probe 非流式误带 stream_options（百炼 400）

## 问题 ID

ISSUE-015

## 发现时间

2026-05-29

## 发现来源

W-021 计划 / Provider 适配层回归分析

## 所属模块

`app/providers/adapters/default_openai.py`、`app/api_probe.py`、Web「测试连接」

## 问题描述

`probe_connection` → `_probe_openai` 使用 `stream: false` 的非流式 `ping`，但 `DefaultOpenAIAdapter.patch_probe_body` 经 `patch_openai_chat_body` 在 `stream_usage_in_final_chunk=True`（百炼/DashScope 等）时仍注入 `stream_options: {"include_usage": true}`。OpenAI 约定下该字段仅对 `stream: true` 有意义；百炼 compatible-mode 对非流式 + `stream_options` 常返回上游 HTTP 400。应用层 `POST /api/probe` 仍 200，`ok: false`，Toast 显示 `HTTP 400: ...`。主链路 `_request_openai` 为 `stream: true` 且同样带 `stream_options`，故弹幕生成可能正常。

## 影响范围

用户可见：百炼/部分 OpenAI 兼容预设「测试连接」误报失败，误导排障

## 严重程度

中

## 是否阻塞当前工单

否（由 W-021 修复）

## 临时处理方式

以开始弹幕后日志与弹幕为准，勿仅凭「测试连接」判定模型不可用

## 建议后续工单

W-021（已实施）

## 备注

与 ISSUE-005（MiMo 探测无识图）正交。修复：`patch_openai_chat_body` 仅在 `data.get("stream")` 为真时设置 `stream_options`。
