# Codex 完成报告

> 工单 ID：W-REFACTOR-BUG-P0P1-001  
> 完成时间：2026-06-01  
> 执行者：Cursor Agent（Composer）

---

## 1. 修改摘要

修复 **BUG-001**：首装启动时 `config.startup_notice` 除写日志外，通过 `QMessageBox.information(None, …)` 向用户展示一次性可见引导；复用 `ConfigStore.is_first_run` / `get_startup_notice()`，二次启动 `config.db` 已存在时不弹窗。未改 Web 启动链路与禁止区文件。

## 2. 修改的文件

- `main.py` — `show_startup_notice_if_needed()`；`DanmuApp.__init__` 在 `attach_web_console` 之后调用
- `app/config_store.py` — `get_startup_notice()` 文档说明
- `tests/test_p0_main_flow.py` — 首装弹窗 / 非首装跳过 2 用例
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/W-REFACTOR-BUG-P0P1-001-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `web/static/`：是
- 未修改 `community-site/`：是
- 未修改 `app/web_api/`、`app/web_console.py`、`app/webview_shell.py`：是
- 未修改 `app/application/status_snapshot.py`：是
- 未修改 `docs/refactor/**`：是
- 未顺手修 BUG-004 / BUG-012 / BUG-014：是

## 4. 运行的命令

```bash
python scripts/boundary_guard.py
python -m pytest tests/test_p0_main_flow.py -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest（工单指定子集） | 通过 | 32 passed |
| boundary_guard | 通过 | Boundary Guard: PASS |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 删除 `%APPDATA%/DanmuAI/` 后 `python main.py` → 出现信息框 | 待负责人 | 待负责人 |
| 2 | 再次启动 → 无信息框 | 待负责人 | 待负责人 |

## 7. 风险与注意事项

- 首装时模态框会短暂阻塞主线程直至用户确认；Web 服务在独立线程，与现有 `QMessageBox` 用法一致。
- Web 控制台内横幅 / `/api/status` 投影未做（工单禁止区）；可后续单独工单补齐。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| — | 无 | — |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] 本完成报告

## 10. 建议下一个工单

- refactor 路线下一项开放 P0 bug（如 BUG-003 display_count、BUG-004 启动失败 attach）或 `W-REFACTOR-BUG-P0P1-009`（托盘无 API Key 反馈）。
