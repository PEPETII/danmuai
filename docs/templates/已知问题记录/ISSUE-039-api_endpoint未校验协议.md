# 已知问题记录

## 问题 ID

ISSUE-039

## 发现时间

2026-06-01

## 发现来源

W-ERROR-REPORT-AUDIT-001（Supabase `error_reports` 只读审计）

## 所属模块

`app/application/config_service.py`（`apply_web_config_patch` / `_normalize_items`）、`app/model_providers.py`（自定义模型校验）

## 问题描述

生产库 `error_reports` 中 **3 条**（含 2 个不同 `client_id`）summary 含 `Request URL is missing an 'http://' or 'https://' protocol.`，来自 httpx 对无协议 `api_endpoint` 的请求。

自定义模型保存路径在 `validate_custom_model` 中校验 endpoint 须以 `http://` 或 `https://` 开头；**全局** `PUT /api/config` 的 `api_endpoint` 经 `_normalize_items` 仅解析 `api_mode`，**不**校验 URL 格式，故用户可将非法 endpoint 写入 `config.db` 并触发 AI 失败与自动上报。

## 影响范围

- 用户可见：弹幕无法生成、错误横幅与反馈弹窗
- 已证实有真实用户误配置（非纯理论）

## 严重程度

高

## 是否阻塞当前工单

否

## 状态

**已修复**（W-CONFIG-ENDPOINT-001，2026-06-01）

## 临时处理方式

Web 助手设置将 API Endpoint 改为完整 URL（含 `https://`）；参考各服务商预设默认值。

## 建议后续工单

W-CONFIG-ENDPOINT-001：在 `config_service._normalize_items` 或 Web 保存前复用 `validate_custom_model` 的 endpoint 规则；保存失败返回明确 i18n 文案

## 备注

- 样本指纹：`06eb09a8…`（2 条，退避文案）、`ecc25637…`（1 条，单次错误）
- 样本 id：`e8977bab-acac-431e-9946-317e1af19f7e`、`f09f85a8-b539-4c22-9009-34d62bdebbc1`、`915fdfad-2e8f-474c-ab96-9a3f7a863c20`
