# ISSUE-031

## 问题 ID

ISSUE-031

## 发现时间

2026-05-30

## 发现来源

手动验收 RuntimeError / W-DANMU-TTS-003 热修

## 所属模块

`app/danmu_read_service.py`、`main.py`

## 问题描述

退出应用时 `QThreadPool` 内 TTS 任务完成并 `emit`，报错：`RuntimeError: wrapped C/C++ object of type DanmuReadService has been deleted`（`danmu_read_service.py` 约第 60 行）。`DanmuReadService` 无父对象或 `quit()` 在 `waitForDone(2000)` 前未标记 shutdown，迟到的 emit 打到已销毁 QObject。

## 影响范围

用户可见（退出时异常日志）；开发排障

## 严重程度

中

## 是否阻塞当前工单

否（W-DANMU-TTS-003 已修）

## 临时处理方式

播放结束后再退出；或忽略退出瞬间日志（若仍偶发见 ISSUE-033）

## 建议后续工单

W-DANMU-TTS-003（已完成）；ISSUE-033 延长退出等待

## 备注

修复：`DanmuReadService(app)` 以 `DanmuApp` 为父；`shutdown()` 置 `_shutdown` 并停定时器；`_emit_tts_ready` / `_emit_tts_failed` 用 `shiboken6.isValid`；`quit()` 在 `waitForDone` 前调用 `read_svc.shutdown()`。

**状态**：**已修复**（2026-05-30）
