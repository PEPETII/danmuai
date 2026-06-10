# ISSUE-032

## 问题 ID

ISSUE-032

## 发现时间

2026-05-30

## 发现来源

用户反馈 / W-DANMU-TTS-003 热修

## 所属模块

`app/danmu_tts_playback.py`

## 问题描述

单句朗读结尾听感「硬切」，缺少自然收尾。非下一条打断（见 ISSUE-030）时，多为 API WAV 尾音突变或播放到最后一采样即结束，无留白。

## 影响范围

用户可见（体验）

## 严重程度

低

## 是否阻塞当前工单

否（W-DANMU-TTS-003 已修）

## 临时处理方式

无（已代码处理）

## 建议后续工单

W-DANMU-TTS-003（已完成）

## 备注

修复：`_append_trailing_pause` — 句尾约 80ms 线性淡出 + **1.0s** 静音尾韵；不截断原音频、不使用 `sd.stop()` 强切。常量 `TRAILING_SILENCE_SEC` / `TRAILING_FADE_MS` 可调。

**状态**：**已修复**（2026-05-30）
