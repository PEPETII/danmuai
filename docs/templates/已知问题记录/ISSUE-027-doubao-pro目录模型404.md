# 已知问题记录

## 问题 ID

ISSUE-027

## 发现时间

2026-05-30

## 发现来源

W-MODEL-CATALOG-PROBE-001 / live 目录模型验收

## 所属模块

`app/model_catalog.py`（`DOUBAO_MODELS`）、火山方舟 Responses API

## 问题描述

在 W-MODEL-CATALOG-PROBE-001 使用负责人提供的 ark Key 对目录模型 `doubao-seed-2-0-pro-260215`（Doubao-Seed-2.0-pro）执行 `probe_connection` 与最小识图请求时，上游均返回 **HTTP 404**，应用侧映射为「模型不存在，请检查模型设置」。同 Key 下 `doubao-seed-2-0-lite-260428`、`mini`、`1.8`、`1.6`、`1.6-flash` 文本与识图均通过。

## 影响范围

- 用户可见：在 Web 视觉模型列表中选择 pro 并「测试连接」或开弹幕时可能失败（若账号同样无该模型权限）
- 仅当用户选用该 model id 时

## 严重程度

中

## 是否阻塞当前工单

否（验收工单仅记录）

## 临时处理方式

选用 lite / mini / 1.8 等已验证可用的目录模型；或在方舟控制台确认 pro 接入点 ID 与开通状态后更新 catalog 或自定义模型 ID。

## 建议后续工单

- 负责人确认：catalog 是否应保留该 ID，或改为账号实际可用的 endpoint 名称
- 可选：catalog 标注「需单独开通」或从默认列表隐藏

## 备注

- 原始探测见 `.pytest_tmp/probe_results.json`（本地，不提交）
- 同次验收硅基 9/9、mimo 1/1 全通过
