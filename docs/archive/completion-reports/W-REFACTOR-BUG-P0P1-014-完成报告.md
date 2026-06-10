# Codex 完成报告

> 工单 ID：W-REFACTOR-BUG-P0P1-014  
> 完成时间：2026-06-02  
> 执行者：Cursor Agent（Composer）

---

## 1. 修改摘要

修复 **BUG-018**：将 mic utterance 轮询从 400ms 调整为 600ms 并加 250ms 相位偏移，`_mic_poll_timer` 改为单次触发后在 `_poll_mic_utterance` 末尾重排程，避免与 500ms 主线程定时器簇叠帧；`MicCaptureService.try_snapshot_pcm_ms` 在 ring buffer 锁忙时非阻塞跳过本帧，降低与 sounddevice 回调的锁竞争。未改 utterance 业务逻辑与 BUG-020。

## 2. 修改的文件

- `main.py` — `MIC_POLL_MS` / `MIC_POLL_PHASE_MS`、single-shot 轮询、`_schedule_next_mic_poll`、`try_snapshot_pcm_ms` 路径
- `app/mic_capture.py` — `try_snapshot_pcm_ms`
- `tests/test_mic_mode.py` — 常量守卫 + 非阻塞快照测试
- `tests/test_mic_utterance.py` — `test_utterance_poll_does_not_block_audio_callback`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/W-REFACTOR-BUG-P0P1-014-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `web/static/`：是
- 未修改 `community-site/`：是
- 未修改 `app/web_api/` / `app/web_console.py` / `app/mic_test_send.py`：是
- 未修改 `app/mic_utterance.py` / `app/mic_service.py`：是
- 未修改 `docs/refactor/**`：是
- 未处理 BUG-020（`_handle_mic_ai_reply` / `scene_memory`）：是

## 4. 运行的命令

```bash
python scripts/boundary_guard.py
python -m pytest tests/test_mic_mode.py tests/test_mic_utterance.py -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| boundary_guard | 通过 | Boundary Guard: PASS |
| pytest（工单指定子集） | 通过 | 14 passed |

## 6. 手动验证步骤

W-MANUAL-SIGNOFF-001（2026-06-02）已执行 GUI 补签；自动化行未改动。

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 开启 mic 模式运行 5–10 分钟 | 无明显卡顿、掉帧或异常 mic 日志 | `mic_mode_enabled=1` + start 连续 **300s**；`/api/logs/recent` 采样无连续 mic/utterance error；Overlay 掉帧未目视。自动化见上行 | 是（自动化） / GUI：是 |

## 7. 风险与注意事项

- utterance 结束检测最坏多 ~200ms 延迟（600ms 轮询 vs 原 400ms）。
- 锁竞争时跳过单帧 poll，不影响校准/utterance-end 的阻塞式 `snapshot_pcm_ms`。
- `main.py` 经 `_mic_service._capture.try_snapshot_pcm_ms` 调用（`mic_service.py` 未在允许区内）。
- **文档漂移**：`docs/main-pipeline-sequence.md` mic poll 间隔已由 [W-REFACTOR-CLOSE-002](W-REFACTOR-CLOSE-002-完成报告.md) 同步为 600/250 ms。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| — | 无 | — |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] 本完成报告

## 10. 建议下一个工单

- 按 [docs/bug-audit/FIX-ORDER.md](../../bug-audit/FIX-ORDER.md) 继续 P1（如 BUG-019、BUG-020 须独立票）。
