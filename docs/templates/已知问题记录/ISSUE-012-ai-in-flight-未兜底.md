# ISSUE-012

## 问题 ID

ISSUE-012

## 发现时间

2026-05-29

## 发现来源

主链路代码审查 / W-015 工单登记

## 所属模块

`app/runnable.py`、`app/ai_client.py`（配置读取与适配器构造在 HTTP 重试 try 块之外）

## 问题描述

`AiRunnable.run()` 仅在截图压缩阶段有 try/except；`worker._request()` 无外层兜底。当配置值非法（如 `temperature`/`max_tokens` 导致 `ConfigStore.get_float`/`get_int` 抛 `ValueError`）、Provider 适配器构造异常或其它请求准备阶段异常时，工作线程可能未 emit `error` 信号。主线程 `_on_ai_error` 不会被调用，`ai_in_flight`（或 `mic_in_flight`）无法通过 `_release_inflight_for_source` 递减，截图 tick 持续因 `in_flight` 跳过，弹幕生成表现为「静默停止」。

## 影响范围

用户可见（识图/开麦后弹幕不再更新，无崩溃）

## 严重程度

高

## 是否阻塞当前工单

否（W-015 即为本问题的修复工单）

## 临时处理方式

重启应用或 `stop()` 后再 `start()`（`stop()` 会将 `ai_in_flight` 置 0）

## 建议后续工单

W-015（AiRunnable 对 `_request` 最终异常兜底）

## 备注

- 修复：在 `app/runnable.py` 包裹 `_request` 并 `_emit_safe("error", ...)`
- 45s `inflight_watchdog` 仅告警，不自动复位（见 `docs/MAIN_PIPELINE.md`）
