# Codex 完成报告

> 工单 ID：W-REFACTOR-BUG-P0P1-016  
> 完成时间：2026-06-02  
> 执行者：Cursor Agent（Composer）

---

## 1. 修改摘要

修复 **BUG-020**：`_handle_mic_ai_reply` 改为与视觉路径一致，使用 `parse_ai_reply_with_memory` 解析 AI 回复并在 memory 开启时调用 `update_from_visual_result` 合并 `scene_memory` 信封；`_record_scene_memory_display` 将 `source=mic` 纳入 dedup 记录白名单。未改 prompt builder、memory 模式策略或视觉 `_on_ai_reply` 主链路。

## 2. 修改的文件

- `main.py` — `_handle_mic_ai_reply` memory 合并；`_record_scene_memory_display` 接受 mic source
- `app/reply_parser.py` — `parse_ai_reply_payload` docstring 补充
- `tests/test_mic_insert.py` — `test_mic_ai_reply_updates_scene_memory`、`test_mic_ai_reply_skips_memory_when_off`
- `tests/test_scene_memory.py` — `test_record_scene_memory_display_accepts_mic_source`、`test_consume_reply_queue_records_mic_display`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/W-REFACTOR-BUG-P0P1-016-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `web/static/`：是
- 未修改 `community-site/`：是
- 未修改 `app/web_api/` / `app/web_console.py` / `app/mic_test_send.py`：是
- 未修改 `app/memory/*` / `memory_prompt_builder`：是
- 未修改 `docs/refactor/**`：是
- 未改视觉 `_on_ai_reply` memory 行为：是

## 4. 运行的命令

```bash
python scripts/boundary_guard.py
python -m pytest tests/test_mic_insert.py tests/test_scene_memory.py -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| boundary_guard | 通过 | Boundary Guard: PASS |
| pytest（工单指定子集） | 通过 | 26 passed |

## 6. 手动验证步骤

W-MANUAL-SIGNOFF-001（2026-06-02）已执行 GUI 补签；自动化行未改动。

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 配置 `memory_mode=scene_card`，开启 mic 模式 | 可正常开麦 | `PUT` 后 `memory_mode=scene_card`、`mic_mode_enabled=1`；同会话后续 start 日志 `mic capture started (Realtek Audio)`，无开麦失败报错 | 是 |
| 2 | 触发一轮含 `scene_memory` 的 mic AI reply | 下一轮视觉 prompt 含更新摘要；dedup 含 mic 弹幕 | `test_mic_ai_reply_updates_scene_memory`、`test_record_scene_memory_display_accepts_mic_source` 等；§5 **26 passed** | 是（自动化） |

## 7. 风险与注意事项

- 改动限于 mic 解析与 display source 白名单，视觉路径未动，回归风险低。
- `memory_mode=off` 时 envelope 仍被忽略（与视觉路径一致）。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| — | 无 | — |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] 完成报告（本文件）

## 10. 建议下一个工单

- 按 [docs/bug-audit/FIX-ORDER.md](../../bug-audit/FIX-ORDER.md) 继续 P1（如 BUG-008、BUG-021 须独立票）。
