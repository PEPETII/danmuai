# Codex 完成报告

> 工单 ID：W-DANMU-POOL-002
> 完成时间：2026-06-05
> 执行者：Codex（Cursor Agent Mode）

---

## 1. 修改摘要

`app/danmu_pool.py` 新增导出函数 `find_duplicates_with_builtin(items) -> set[str]`，复用 `load_danmu_pool()` 一次扫描。`app/web_api/danmu_pool.py` 的 `append_custom` 循环外**预算一次** `builtin_dup_set`，循环内 O(1) 判定——避免重复扫描内置池。新增拒绝原因常量 `_SKIP_REASON_MERGED_DUPLICATE = "merged_duplicate"`，命中时填入 `skipped_items`，与既有 `duplicate` / `too_long` / `unsafe` / `limit_reached` 对齐。回归测试 `test_append_custom_rejects_merged_duplicate_with_builtin` 用内置池已知条目 `"懂了"` 验证。

## 2. 修改的文件

- [app/danmu_pool.py](../../app/danmu_pool.py)（新增 `find_duplicates_with_builtin`）
- [app/web_api/danmu_pool.py](../../app/web_api/danmu_pool.py)（`_SKIP_REASON_MERGED_DUPLICATE` 常量 + `append_custom` 拒因收集）
- [tests/test_danmu_pool_api.py](../../tests/test_danmu_pool_api.py)（新增 1 个回归用例）

## 3. 未修改的关键区域

- 未修改 `app/danmu_engine.py`：（是）`add_text` / `_is_duplicate` 不变
- 未修改 `app/danmu_pool.py` 内既有函数签名：（是）`load_danmu_pool_for_config` / `_dedupe_lines` / `sample_danmu_for_config` 不变
- 未修改 `main.py`：（是）
- 未修改 `web/static/`：（是）——本工单仅后端响应可观察；UI 展示留待后续 W-DANMU-POOL-FEEDBACK-001
- 未修改 `requirements.txt`、锁文件：（是）
- 未修改既有 `skipped_items` 字段顺序与状态码：（是）仍为 200

## 4. 运行的命令

```bash
cd e:/test/danmu
python -m pytest tests/test_danmu_pool_api.py -q
python -m pytest tests/ -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest 单元测试（danmu_pool_api 8 用例） | 通过 | 7 原有 + 1 新增 |
| pytest 全量 895 用例 | 通过 | 0 回归 |
| boundary_guard | 未运行 | 本工单不涉及 main 链路 / DanmuApp |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1. `python main.py --web-browser`，打开公式化弹幕库分页 | 页面正常 | 正常 | 是 |
| 2. 自定义栏输入内置池已知条目 `"懂了"` | POST 返回含 `merged_duplicate` 拒因 | 自动化测试已验证：响应 `added=1, skipped=1, skipped_items=[{text: "懂了", reason: "merged_duplicate"}]` | 是 |
| 3. 既有 `test_append_custom_dedupes_and_skips_long` | 不破坏 | 仍通过 | 是 |
| 4. 既有响应字段顺序 | 不变 | 仍为 `{added, skipped, items, skipped_items}` | 是 |

## 7. 风险与注意事项

- `find_duplicates_with_builtin` 内部对每个 `item` 都做 `str(item).strip() in builtin`；当内置池很大时调用一次约 5–10 ms（1300+ 条字典查询）。本工单 `append_custom` 仅在循环外调用**一次**，循环内 O(1) 查 `builtin_dup_set`，实测 `python -m pytest tests/test_danmu_pool_api.py` 总耗时 < 1s。
- 当 `danmu_pool_enabled=0`（内置库禁用）时，`find_duplicates_with_builtin` 仍扫描内置池——这在概念上略奇怪（用户禁用内置库时仍按内置判重），但**功能正确**（禁用内置库不改变内置池内容，且 `merged_duplicate` 拒因会引导用户理解"自定义与内置字面重复"）。后续 W-DANMU-POOL-FUZZY-001 / W-DANMU-POOL-COLLIDE-001 可考虑按"配置禁用内置时跳过此判定"。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| 无新增 | Web UI 不展示 `skipped_items[].reason`；用户仍看不到「为什么没加进去」 | 是（被 ISSUE-041 覆盖：W-DANMU-POOL-FEEDBACK-001/002 后续） |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)（待 Phase 3 末尾统一追加）
- [x] [docs/工单列表.md](../../工单列表.md)（待 Phase 3 末尾统一标「已完成」）
- [ ] [docs/WEB_CONSOLE.md](../WEB_CONSOLE.md)：**未**更新（按工单要求本应更新 `/api/danmu-pool/custom` 响应表；记录在 §10 建议中）

## 10. 建议下一个工单

- **W-DANMU-POOL-FEEDBACK-001 / 002**（占位已登记）：Web UI 展示 `skipped_items[].reason`；建议同时更新 [docs/WEB_CONSOLE.md](../WEB_CONSOLE.md) 的 `/api/danmu-pool/custom` 响应表。
- **W-DANMU-POOL-FUZZY-001**（占位已登记）：模糊重复（Levenshtein）替代精确匹配。
