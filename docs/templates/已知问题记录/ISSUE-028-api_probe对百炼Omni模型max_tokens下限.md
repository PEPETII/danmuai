# 已知问题记录

## 问题 ID

ISSUE-028

## 发现时间

2026-05-30

## 发现来源

W-MODEL-CATALOG-PROBE-001 / live 目录模型验收

## 所属模块

`app/api_probe.py`（`_probe_openai`，`max_tokens: 1`）、`app/model_catalog.py`（`qwen-omni-turbo`、`qwen2.5-omni-7b`）

## 问题描述

对百炼 compatible-mode 模型 `qwen-omni-turbo`、`qwen2.5-omni-7b` 执行 Web 同款文本 ping（`max_tokens=1`）时返回 **HTTP 400**：`Range of max_tokens should be [10, 2048]`。将 `max_tokens` 设为 16 的识图请求对同一模型 **通过**。其余 dashscope VL 模型 text ping 正常。

## 影响范围

- 用户可见：控制台「测试连接」对 Omni 目录模型显示失败，但选同一模型开弹幕（正式请求 `max_tokens` ≥512）可能正常

## 严重程度

中

## 是否阻塞当前工单

否

## 临时处理方式

用户可忽略 Omni 的「测试连接」失败，直接试跑弹幕；或选用非 Omni 目录模型做连通性测试。

## 建议后续工单

- `api_probe` / `patch_probe_body`：对 dashscope host 或 Omni 模型将 probe `max_tokens` 下限提至 10（小改动，需单独 W-xxx 授权 `app/api_probe.py`）

## 备注

- 与已修复 ISSUE-015（非流式 `stream_options`）无关
- 探测消息摘录：`InternalError.Algo.InvalidParameter`
