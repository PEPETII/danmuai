# Codex 完成报告

> 工单 ID：W-REFACTOR-BUG-P0P1-011  
> 完成时间：2026-06-02  
> 执行者：Cursor Agent（Composer）

---

## 1. 修改摘要

修复 **BUG-015**：`_consume_reply_queue` 成功上屏后，`history_writer.enqueue` 改为写入 `display_content`（`normalize_danmu_display_text` 结果），与 Overlay / 直播旁路上屏文案一致；不再落库未截断的 `queued.content`。

## 2. 修改的文件

- `main.py` — `history_writer.enqueue(display_content, …)`
- `app/history_writer.py` — `enqueue` docstring 注明 content 须已 display-normalize
- `tests/test_p0_main_flow.py` — `test_history_enqueue_matches_display_truncation`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/W-REFACTOR-BUG-P0P1-011-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `web/static/`：是
- 未修改 `community-site/`：是
- 未修改 `app/web_console.py` / `app/web_api/`：是
- 未修改 `app/overlay.py` / `app/danmu_engine.py` / `app/reply_parser.py`：是
- 未修改 `docs/refactor/**`：是
- 未改用户可见截断策略（`normalize_danmu_display_text` 规则不变）：是

## 4. 运行的命令

```bash
python scripts/boundary_guard.py
python -m pytest tests/test_history_writer.py tests/test_p0_main_flow.py -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| boundary_guard | 通过 | Boundary Guard: PASS |
| pytest（工单指定子集） | 通过 | 48 passed |

## 6. 手动验证步骤

W-MANUAL-SIGNOFF-001（2026-06-02）首次 GUI 补签未在随机 AI 路径中观察到长弹幕；后续已由 W-GUI-RETEST-011-001（2026-06-02）补充确定性运行态复测。

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 触发一条会被 `danmu_max_chars` 截断的长弹幕上屏 | 屏上为截断 + `...` | Win32 10.0.22631；W-GUI-RETEST-011-001 新增 `POST /api/test/danmu`，`danmu_max_chars=5` 下向主线程注入 `LONG-VERIFY-ABCDE12345`；接口返回 `expected_texts=["LONG-..."]`、`active_texts=["LONG-..."]`。Windows 分层透明窗口截图未稳定捕获 Overlay，故以运行态轨道文本作为确定性复测证据 | 是 |
| 2 | Web「弹幕日记」/历史列表查看同条记录 | 与屏上文案一致 | `test_history_enqueue_matches_display_truncation`；§5 **48 passed** | 是（自动化） |

## 7. 风险与注意事项

- 修复前已写入的历史行仍为长文，本票不做数据迁移。
- `HistoryWriter` 不负责截断；调用方须传入 display-normalized 文案。

## 8. 发现但未处理的问题

无（本票范围内）。

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] 本完成报告

## 10. 建议下一个工单

- 按 [docs/bug-audit/FIX-ORDER.md](../../bug-audit/FIX-ORDER.md) 继续第一阶段 P1（如 BUG-017、BUG-018）。
