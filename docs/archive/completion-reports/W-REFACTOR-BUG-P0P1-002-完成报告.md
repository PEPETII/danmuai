# Codex 完成报告

> 工单 ID：W-REFACTOR-BUG-P0P1-002  
> 完成时间：2026-06-02  
> 执行者：Cursor Agent（Composer）

---

## 1. 修改摘要

修复 **BUG-003**：Web 运行概览「屏上弹幕」(`display_count`) 在启动或 `reload_tracks` 后第一帧错误显示 0。根因是 `DanmuEngine` 可见性缓存在 `reload_tracks` 清零后未重建，且 `update()` 末尾无重建地设置 `_visibility_counts_seeded=True`。现于保留弹幕后立刻 `_rebuild_visibility_counts()`，移除 `update()` 假 seeded 尾，并在 `engine.start()` 标记 visibility stale。

## 2. 修改的文件

- `app/danmu_engine.py` — `reload_tracks` / `update` / `start` visibility 修复
- `app/application/status_snapshot.py` — `display_count` 语义注释
- `tests/test_p0_main_flow.py` — `test_start_seeds_visibility_counts`
- `tests/test_danmu_motion.py` — `test_reload_tracks_visible_display_count_after_preserve`
- `tests/test_web_console.py` — `test_build_status_snapshot_display_count_when_engine_visible`
- `docs/当前仓库状态.md`
- `docs/bug-audit/BUGS-OVERVIEW.md`
- `docs/bug-audit/TEST-GAPS.md`
- `docs/refactor/BUG-FIX-MERGE-PLAN.md`
- `docs/templates/Codex完成报告/W-REFACTOR-BUG-P0P1-002-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `main.py`：是
- 未修改 `web/static/`：是
- 未修改 `community-site/`：是
- 未修改 `app/web_api/`：是
- 未修改 `app/application/runtime_state.py`：是（仍经 `visible_display_count()` 读引擎）

## 4. 运行的命令

```bash
python scripts/boundary_guard.py
python -m pytest tests/test_p0_main_flow.py tests/test_web_console.py -q
python -m pytest tests/test_danmu_motion.py::test_reload_tracks_visible_display_count_after_preserve -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| boundary_guard | 通过 | Boundary Guard: PASS |
| pytest（工单指定子集） | 通过 | 117 passed（含新增 3 条） |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 启动生成后，屏上已有可见弹幕时 `#statDisplay` 不为错误 0 | 待负责人 | 待负责人 |
| 2 | 布局/轨道 reload 后保留的屏上弹幕，`display_count` 与可见条数一致 | 待负责人 | 待负责人 |

## 7. 风险与注意事项

- `reload_tracks` 有保留项时增加一次 O(n) 可见性重建（与原先惰性首次读取成本相当，时序更正确）。
- 指标仍为**可见**弹幕数，不含右侧待入场的 pending（语义与「屏上弹幕」一致）。

## 8. 发现但未处理的问题

无（范围外问题未在本次发现）。

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/bug-audit/BUGS-OVERVIEW.md](../../bug-audit/BUGS-OVERVIEW.md)
- [x] [docs/refactor/BUG-FIX-MERGE-PLAN.md](../../refactor/BUG-FIX-MERGE-PLAN.md)
- [x] [docs/bug-audit/TEST-GAPS.md](../../bug-audit/TEST-GAPS.md)
- [x] 本完成报告

## 10. 建议下一个工单

- 按 [docs/bug-audit/FIX-ORDER.md](../../bug-audit/FIX-ORDER.md) 继续 P0P1（如 BUG-005 mic 模型、BUG-007 overlay 字体等）。
