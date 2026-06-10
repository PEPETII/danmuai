# Codex 完成报告

> 工单 ID：W-FONT-001  
> 完成时间：2026-06-06  
> 执行者：Cursor Agent

---

## 1. 修改摘要

助手设置新增独立「字体设置」tab，将横向弹幕与悬浮窗的字体名、加粗、字号从「弹幕显示」tab 集中迁出；后端新增 4 个配置键并做字号钳位、加粗归一、字体名空串兜底；`DanmuOverlay` 与 `FloatingPanel` 在既有 `config_changed` 热更新链路上读取新字段，悬浮窗通过 `_rebuild_active_pixmaps` 重建在飞 item 的 pixmap。未改动 `main.py` 主链路与 `_consume_reply_queue` 时序。

## 2. 修改的文件

- `app/config_defaults.py`
- `app/application/config_service.py`
- `app/overlay.py`
- `app/floating_panel.py`
- `web/static/index.html`
- `web/static/modules/settings.js`
- `tests/test_config_defaults.py`
- `tests/test_web_routes.py`
- `tests/test_floating_panel.py`
- `tests/test_overlay_render.py`
- `docs/工单列表/工单/W-FONT-001.md`
- `docs/工单列表/工单/W-FONT-001-完成报告.md`（本文件）
- `docs/工单列表.md`
- `docs/当前仓库状态.md`
- `docs/WEB_CONSOLE.md`

## 3. 未修改的关键区域

- 未修改 `main.py`：是（`_on_config_changed` 既有 `apply_display_settings` / `apply_config` 钩子足够）
- 未修改 `app/danmu_engine.py`：是
- 未修改 `app/ai_client.py`：是
- 未修改 `app/danmu_pool.py`：是
- 未修改 `app/mic_*.py`：是
- 未修改 `app/web_console.py` / `app/web_console_runtime.py`：是
- 未修改 `scripts/boundary_guard.py` / `scripts/boundary_guard/constants.py`：是
- 未修改 `docs/main-pipeline-sequence.md` / `docs/runtime-state-map.md`：是
- 未修改 `requirements.txt`：是

## 4. 运行的命令

```bash
python -m pytest tests/test_config_defaults.py tests/test_web_routes.py tests/test_floating_panel.py tests/test_overlay_render.py -q
python -m pytest tests/ -q
python scripts/boundary_guard.py
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest（工单相关 4 文件） | 通过 | 75 passed |
| pytest（全量） | 通过 | 958 passed, 5 skipped |
| boundary_guard | 通过 | PASS |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 助手设置出现第 7 个 tab「字体设置」 | 代码已实现 tab 按钮与 panel；待负责人 `python main.py` 目视确认 | 待负责人 |
| 2 | datalist 7 字体 + 手输可用 | HTML 已含 `<datalist id="font-family-options">` 7 项 | 待负责人 |
| 3 | 关横向加粗 → 保存 → 弹幕变细体 | `danmu_font_bold` → `_apply_font_from_config` 读配置 | 待负责人 |
| 4 | 悬浮窗已飞入 item 字体热更新 | `_rebuild_active_pixmaps` 单测通过 | 是（自动化） |
| 5 | `font_size=9999` 落库 `"72"` | `test_font_size_out_of_range_clamps_via_config_service` 通过 | 是 |
| 6 | `danmu_font_bold="true"` 落库 `"1"` | `test_font_bold_truthy_strings_normalize_to_one` 通过 | 是 |
| 7 | 「字体设置」tab 恢复默认仅 6 字段 | `SETTINGS_RESTORE_GROUPS.font` + `SETTINGS_RESTORE_CHECKBOXES.font` 已配置 | 待负责人 |
| 8 | 重启后 6 字段持久化 | `WEB_CONFIG_KEYS` + seed 单测通过 | 是（自动化） |

## 7. 风险与注意事项

- 字体名不存在时 Qt 静默回退，`display_settings_dirty` 比较 config 字符串而非实际渲染字体——与工单设计一致。
- 「弹幕显示」tab 的「恢复默认」仍含 `floating_panel_font_size`（W-FP-001 兼容）；「字体设置」tab 恢复默认也会重置该键，两边幂等。
- `_rebuild_active_pixmaps` 在 max_items=60 时主线程约 180ms，当前可接受。
- 工单验收中 Web UI 目视项（tab 可见、KaiTi 像素对比等）须负责人在真实环境补验。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| 无 | — | — |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/WEB_CONSOLE.md](../../WEB_CONSOLE.md)
- [x] [docs/工单列表/工单/W-FONT-001.md](W-FONT-001.md)

## 10. 建议下一个工单

- W-FP-004（悬浮窗模式语义与停止清理）可与字体热更新联调验收。
