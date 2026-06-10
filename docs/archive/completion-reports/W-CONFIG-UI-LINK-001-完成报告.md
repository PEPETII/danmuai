# Codex 完成报告

> 工单 ID：W-CONFIG-UI-LINK-001  
> 完成时间：2026-06-09  
> 执行者：Cursor Agent

---

## 1. 修改摘要

闭合 [docs/配置与UI联动审查.md](../配置与UI联动审查.md) §八 全部 6 项缺陷：从 `CONFIG_DEFAULTS` / `WEB_CONFIG_KEYS` 移除 `floating_panel_click_through` 与 `floating_panel_lifetime_sec` 两个死配置；在 `ConfigService._normalize_items` 为 `danmu_speed`、`dedup_threshold`、`empty_accel`、`pet_position_x/y` 补齐写入层钳位与布尔归一化；配套 8 个测试用例更新/新增。

## 2. 修改的文件

- `app/config_defaults.py`
- `app/application/config_service.py`
- `tests/test_config_defaults.py`
- `tests/test_web_console.py`
- `tests/test_web_routes.py`
- `tests/test_floating_panel_engine.py`
- `docs/工单列表/工单/W-CONFIG-UI-LINK-001.md`
- `docs/工单列表.md`
- `docs/当前仓库状态.md`
- `docs/配置与UI联动审查.md`
- `docs/templates/Codex完成报告/W-CONFIG-UI-LINK-001-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `main.py`：是
- 未修改 `app/main_*_mixin.py`：是
- 未修改 `app/overlay.py`、`app/danmu_engine.py`：是
- 未修改 `web/static/`：是
- 未修改 `scripts/boundary_guard.py`：是

## 4. 运行的命令

```bash
python -m pytest tests/test_config_defaults.py tests/test_web_console.py tests/test_web_routes.py tests/test_floating_panel_engine.py -q
python -m pytest tests/ -q --maxfail=3 --tb=line
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 本工单相关 pytest | 通过 | 74 passed |
| 全量 pytest | 部分失败（范围外） | 404 passed；3 failed 为既有问题（`DanmuApp` super init、`WebStatusSnapshot.screen_index_fallback_warning`），与本工单无关 |
| boundary_guard | 未运行 | 未触达主链路 / web_api 路由 |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 相关单测 | 74 passed | 74 passed | 是 |
| `danmu_speed=-5` 经 ConfigService | 落库 `0.1` | `test_danmu_speed_negative_clamps_to_min` 断言通过 | 是 |
| `dedup_threshold=2` | 落库 `1` | `test_dedup_threshold_over_one_clamps` 通过 | 是 |
| `empty_accel=true` | 落库 `1` | `test_empty_accel_truthy_string_normalizes_to_one` 通过 | 是 |
| `pet_position_x=999999` | 落库 `32000` | `test_pet_position_x_over_max_clamps` 通过 | 是 |

## 7. 风险与注意事项

- 用户 DB 中已有的 `floating_panel_lifetime_sec` / `floating_panel_click_through` 成为孤儿键，不影响运行；未做 migration 删除。
- `danmu_speed` 后端上界 10.0 宽于前端 HTML `max=5`，与审查建议一致。

## 8. 发现但未处理的问题

- 全量 pytest 中 `test_danmu_dedup.py::test_start_clears_dedup_window`、`test_lifetime_stats.py` 两处失败为范围外既有缺陷，未在本工单修复。

## 9. 已更新的文档

- `docs/工单列表/工单/W-CONFIG-UI-LINK-001.md`
- `docs/工单列表.md`
- `docs/当前仓库状态.md`
- `docs/配置与UI联动审查.md`

## 10. 项目说明文件反查

已检查限制/边界入口文件、AGENTS.md、README.md 和相关项目说明文件：`floating_panel_lifetime_sec` / `floating_panel_click_through` 仅见于历史工单/报告文档，当前行为说明无需更新 AGENTS 附录；本次无需更新 README / AGENTS / WEB_CONSOLE。
