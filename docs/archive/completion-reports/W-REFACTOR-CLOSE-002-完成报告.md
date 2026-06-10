# Codex 完成报告

> 工单 ID：W-REFACTOR-CLOSE-002  
> 完成时间：2026-06-02  
> 执行者：Cursor Agent（Composer）

---

## 1. 修改摘要

将 [`docs/main-pipeline-sequence.md`](../../main-pipeline-sequence.md) Timers 表中 `_mic_poll_timer` 从 **400 ms** 同步为与 [`main.py`](../../../main.py) 一致的 **600 ms** 稳态 single-shot 轮询、**250 ms** 启动相位（`MIC_POLL_PHASE_MS`）及 `_schedule_next_mic_poll` 重排程，闭合 [W-REFACTOR-BUG-P0P1-014](W-REFACTOR-BUG-P0P1-014-完成报告.md) 遗留的 main-pipeline 文档漂移。本轮未改业务代码。

## 2. 修改的文件

- `docs/main-pipeline-sequence.md` — `_mic_poll_timer` 行（600/250 ms、single-shot、重排程）
- `docs/当前仓库状态.md` — 当前阶段 W-REFACTOR-CLOSE-002；014 小节移除 400ms 待跟进
- `docs/工单列表.md` — 登记 W-REFACTOR-CLOSE-002 已完成
- `docs/templates/Codex完成报告/W-REFACTOR-CLOSE-002-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `app/`：是
- 未修改 `web/static/`：是
- 未修改 `main.py`：是
- 未修改 `tests/`：是
- 未修改 `community-site/`：是
- 未修改 `supabase/`：是

## 4. 运行的命令

```bash
git diff --name-only
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| git diff --name-only | 通过 | 仅 `docs/**` 路径 |
| pytest / boundary_guard | 未运行 | 纯文档票 |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | `main.py` `MIC_POLL_MS` / `MIC_POLL_PHASE_MS` | 600 / 250 | 已核对 | 是 |
| 2 | `docs/main-pipeline-sequence.md` Timers 表 `_mic_poll_timer` | 600 ms single-shot、250 ms phase、`_schedule_next_mic_poll` | 已核对 | 是 |
| 3 | `git diff --name-only` | 无 `main.py`、`app/`、`tests/`、`web/` | 已核对 | 是 |

## 7. 风险与注意事项

- 无运行时风险（仅文档）。
- `docs/bug-audit/` 等审计文档仍可能写 400ms；不在本票允许区，未改。

## 8. 发现但未处理的问题

- 无。

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/main-pipeline-sequence.md](../../main-pipeline-sequence.md)
- [x] 本完成报告

## 10. 建议下一个工单

- 继续 `docs/refactor/REFACTOR-TASKS.md` 中未闭合项，或按需另开文档票统一 `docs/bug-audit/` 中 BUG-018 的 400ms 描述。
