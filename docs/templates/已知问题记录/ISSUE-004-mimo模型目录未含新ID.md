# 已知问题记录

> **规则**：当前工单范围外的问题 **不要顺手修**。先按本模板记录到 [docs/workflow/已知问题与后续事项.md](../../workflow/已知问题与后续事项.md)，再由负责人在 [docs/workflow/工单列表.md](../../workflow/工单列表.md) 单独开工单处理。

---

## 问题 ID

ISSUE-004

## 发现时间

2026-05-29

## 发现来源

W-004 / [W-004-完成报告.md](../Codex完成报告/W-004-完成报告.md)

## 所属模块

`app/model_catalog.py`、`web/static/app.js`（视觉模型选择器）

## 问题描述

小米 MiMo 开放平台已列出 `mimo-v2-flash`、`mimo-v2-pro` 等模型 ID。**W-005（2026-05-29）** 已将 `mimo-v2.5` 对齐为 MiMo-V2.5 官方定价。`mimo-v2.5-pro` **不纳入视觉目录**：官方文档写明仅 `mimo-v2.5`、`mimo-v2-omni` 支持图像输入；选 Pro 做截图弹幕会报「模型不存在」。`mimo-v2-flash` 等仍未入目录。

## 影响范围

想用新旗舰/flash 模型的用户；开发/Agent 对官方模型列表的理解

## 严重程度

低

## 是否阻塞当前工单

部分（W-005 已覆盖 `mimo-v2.5-pro`；flash 仍待办）

## 临时处理方式

使用目录内 **`mimo-v2.5`**（截图弹幕）或 **`mimo-v2-omni`**（全模态，将下线）；勿选 `mimo-v2.5-pro` 做识图（仅文本）。勿手填未收录 ID（如 `mimo-v2-flash`）。

## 建议后续工单

W-005 已完成；可选后续：补充 `mimo-v2-flash` 或移除 `mimo-v2-omni`

## 备注

- 官方文档：[OpenAI API 请求体 - model 枚举](https://platform.xiaomimimo.com/docs/en-US/api/chat/openai-api?target=request-body)
- W-004 已将 MiMo 默认视觉模型固定为 `mimo-v2.5`，与 [README.md](../../README.md) FAQ 一致
