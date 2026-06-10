# ISSUE-033

## 问题 ID

ISSUE-033

## 发现时间

2026-05-30

## 发现来源

W-DANMU-TTS-003 完成报告 §8

## 所属模块

`main.py`、`app/danmu_tts_playback.py`

## 问题描述

`DanmuApp.quit()` 在 `read_svc.shutdown()` 后对全局 `QThreadPool.waitForDone(2000)`。TTS 合成 HTTP 与 `sounddevice` 播放在**独立 daemon 线程**中，长句 + 1s 尾韵可能超过 2s；进程退出时播放可能被截断，或极少数情况下仍有迟到的池任务竞态（ISSUE-031 已用 `isValid` 兜底 emit）。

## 影响范围

用户可见（退出瞬间音频中断）；低概率日志

## 严重程度

低

## 是否阻塞当前工单

否

## 临时处理方式

朗读播完后再退出；或接受退出时音频立即停止

## 建议后续工单

可选：`quit()` 在 `DanmuTtsPlayback.is_busy()` 时延长等待或提示；勿在退出路径调用 `sd.stop()` 以免硬切

## 备注

与 ISSUE-031 区分：031 为 emit 已销毁对象；033 为退出时序与播放时长。当前刻意不 `sd.stop()`，优先自然结束。

**状态**：待处理
