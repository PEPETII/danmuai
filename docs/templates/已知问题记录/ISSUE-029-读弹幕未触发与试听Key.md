# ISSUE-029

## 问题 ID

ISSUE-029

## 发现时间

2026-05-30

## 发现来源

W-DANMU-TTS-001/002 手动验收 / W-DANMU-TTS-003 热修

## 所属模块

`app/danmu_read_service.py`、`app/web_api/danmu_read.py`、`web/static/app.js`

## 问题描述

用户启用读弹幕后间隔 3s 仍无朗读，日志无 `danmu read:` 行。原因之一：试听与定时 tick 仅读已持久化的 `tts_api_key`，表单填写未保存时 Key 为空、定时器停或 skip。另：池线程回调若未用 Qt 信号安全回主线程，可能导致合成结果未进入播放。

## 影响范围

用户可见（功能看似完全无效）

## 严重程度

高

## 是否阻塞当前工单

否（W-DANMU-TTS-003 已修）

## 临时处理方式

保存 TTS Key 后再试听；确认已「开始生成」且屏上有可见弹幕；查看日志 `danmu read: timer started` / `no_key` / `no_visible_text`

## 建议后续工单

W-DANMU-TTS-003（已完成）

## 备注

修复：`POST /api/danmu-read/probe` 支持 body `api_key`；`run_probe(api_key_override=…)`；诊断日志与 `_log_skip_once`；`_DanmuTtsRunnable` 结果经 `_tts_ready` / `_tts_failed` 信号。

**状态**：**已修复**（2026-05-30）
