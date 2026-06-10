# Codex 完成报告

> 工单 ID：W-REFACTOR-BUG-P0P1-013  
> 完成时间：2026-06-02  
> 执行者：Cursor Agent（Composer）

---

## 1. 修改摘要

修复 **BUG-017**：运行中删除 custom persona 后，`active_personae` 可能仍含已删名，导致 `pick_random` 选中失效人格、`get_prompt` 返回空 system/user。在 `PersonaManager` 内对活跃列表与 `list()` 求交，`delete_custom` 时同步修剪 `active_personae`；无有效项时稳定回退 `DEFAULT_ACTIVE`。

## 2. 修改的文件

- `app/personae.py` — `_filter_pickable_active`、`get_active` 校验、`delete_custom` 修剪活跃列表
- `tests/test_p0_main_flow.py` — `test_pick_random_skips_deleted_custom_persona`、`test_delete_custom_prunes_active_personae`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/W-REFACTOR-BUG-P0P1-013-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `main.py`：是（personae 层已覆盖 `_trigger_api_call` / mic insert 路径）
- 未修改 `web/static/`：是
- 未修改 `community-site/`：是
- 未修改 `app/web_console.py` / `app/web_api/`：是
- 未修改 `docs/refactor/**`：是
- 未改 persona 存储结构或 Web UI：是

## 4. 运行的命令

```bash
python scripts/boundary_guard.py
python -m pytest tests/test_p0_main_flow.py -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| boundary_guard | 通过 | Boundary Guard: PASS |
| pytest（工单指定子集） | 通过 | 50 passed |

## 6. 手动验证步骤

W-MANUAL-SIGNOFF-001（2026-06-02）已执行 GUI 补签；自动化行未改动。

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 创建 custom persona 并加入活跃列表，启动生成 | 正常出弹幕 | Web/API：创建 `signoff_test_persona`、加入 active、`POST /api/start`；8s 后 `display_count=8`、`running=True`；日志见 persona 出弹幕 | 是 |
| 2 | 不重启，Web 删除该 persona，继续生成 | 无异常；日志人格有效；非空 system prompt | `test_pick_random_skips_deleted_custom_persona`、`test_delete_custom_prunes_active_personae`；§5 **50 passed** | 是（自动化） |

## 7. 风险与注意事项

- 若活跃列表经删除后变为空，`set_active([])` 会写回 `DEFAULT_ACTIVE`（与既有 `_filter_removed_active` 行为一致）。
- `get_active()` 现对 Web 状态快照与 API 调度返回同一有效集合；配置里若仍有陈旧名，读取时会被过滤，删除时会被持久化修剪。

## 8. 发现但未处理的问题

无（本票范围内）。

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] 本完成报告

## 10. 建议下一个工单

- 按 [docs/bug-audit/FIX-ORDER.md](../../bug-audit/FIX-ORDER.md) 继续 P1（如 BUG-018）。
