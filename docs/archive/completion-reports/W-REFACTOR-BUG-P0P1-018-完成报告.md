# Codex 完成报告

> 工单 ID：W-REFACTOR-BUG-P0P1-018  
> 完成时间：2026-06-02  
> 执行者：Cursor Agent（Composer）

---

## 1. 修改摘要

修复 **BUG-022**：当识图区域无有效尺寸（`region_w <= 0` 或 `region_h <= 0`）时，`ConfigStore.set_region` 将 `region_x/y/w/h` 四键一致写入 `0`；`get_region` 读侧返回 `(0,0,0,0)`；`ConfigStore.__init__` 在加载配置后修复历史 DB 中「半清零」残留。未改 capture-region API 与框选 UI。

## 2. 修改的文件

- `app/config_store.py` — `_normalize_region`、`_repair_stale_region_if_needed`、`get_region` / `set_region`
- `tests/test_config_store.py` — `test_set_region_zeros_all_keys_when_size_non_positive`、`test_set_region_clear_persists_after_reopen`、`test_config_store_repairs_stale_region_on_init`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/W-REFACTOR-BUG-P0P1-018-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `main.py`：是（`reset_capture_region` → `clear_capture_region` 已写四零，逻辑集中在 `ConfigStore`）
- 未修改 `web/static/`：是
- 未修改 `community-site/`：是
- 未修改 `app/web_console.py` / `app/web_api/` / `app/region_selector.py`：是
- 未修改 `docs/refactor/**`：是

## 4. 运行的命令

```bash
python scripts/boundary_guard.py
python -m pytest tests/test_config_store.py -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| boundary_guard | 通过 | Boundary Guard: PASS |
| pytest（工单指定子集） | 通过 | 13 passed |

## 6. 手动验证步骤

W-MANUAL-SIGNOFF-001（2026-06-02）已执行 GUI 补签；自动化行未改动。

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 框选并保存自定义截图区域 | 区域持久化，`capture_region_mode=custom` | `POST /api/capture-region/select` + 屏上拖拽；`GET` `mode=custom` `region={x:427,y:240,w:133,h:100}`；日志 `capture region saved` | 是 |
| 2 | Web「恢复全屏」 | 四键归零，`mode=full` | `test_set_region_zeros_all_keys_when_size_non_positive` | 是（自动化） |
| 3 | 退出并重启应用 | `/api/capture-region` 或 `/api/status` 中 `region_*` 均为 0；截图全屏 | `test_set_region_clear_persists_after_reopen`、`test_config_store_repairs_stale_region_on_init`；§5 **13 passed** | 是（自动化） |

## 7. 风险与注意事项

- 任何经 `set_region` 写入的「无有效尺寸」状态均会变为四键全零（符合全屏语义）。
- 启动时 `_repair_stale_region_if_needed` 会对已有 config.db 做一次写库修复；与 `set_batch` 同事务/锁，无新线程。

## 8. 发现但未处理的问题

无（本票范围内）。

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] 本完成报告

## 10. 建议下一个工单

- 按 [docs/bug-audit/FIX-ORDER.md](../../bug-audit/FIX-ORDER.md) 继续 P1（如 BUG-018、BUG-023）。
