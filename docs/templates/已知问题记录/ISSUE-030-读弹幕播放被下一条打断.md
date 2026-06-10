# ISSUE-030

## 问题 ID

ISSUE-030

## 发现时间

2026-05-30

## 发现来源

手动验收 / W-DANMU-TTS-003 热修

## 所属模块

`app/danmu_read_service.py`、`app/danmu_tts_playback.py`

## 问题描述

朗读约 7 个汉字即停止，非 API 截断。根因：HTTP 合成返回后 `_tts_in_flight` 被清零，定时器在间隔到期再次 `sd.play()`，sounddevice 默认行为打断当前播放，听感为「只读前半句」。

## 影响范围

用户可见

## 严重程度

高

## 是否阻塞当前工单

否（W-DANMU-TTS-003 已修）

## 临时处理方式

将读弹幕间隔调到 ≥15s，且等上一句完全播完

## 建议后续工单

W-DANMU-TTS-003（已完成）

## 备注

修复：`_on_tts_ready` 保持 `_tts_in_flight` 直至 `DanmuTtsPlayback.playback_finished`；tick 与 probe 在 `is_busy()` 时拒绝新播放。Web 文案说明间隔须大于合成+播放时长。

**状态**：**已修复**（2026-05-30）
