# Codex 完成报告 — W-FONT-002

> 工单 ID：W-FONT-002  
> 完成时间：2026-06-06  
> 执行者：Cursor Agent

---

## 1. 修改摘要

在 W-FONT-001 字体设置 tab 基础上，新增本地 `.ttf` / `.otf` 字体文件导入能力：核心 `FontRegistry` 将字体落盘至 `%APPDATA%/DanmuAI/fonts/<sha256>.<ext>`，元信息持久化至 `config.db` 键 `imported_fonts`；Web 提供 3 个 API 路由与导入 UI。写操作经 `bridge.invoke_on_main` 在主线程调用 `QFontDatabase`；选用 imported family 后仍走既有 `danmu_font_family` / `floating_panel_font_family` 配置热更链，主链路零侵入。

## 2. 修改的文件

- `app/font_registry.py`（新增）
- `app/web_api/font_registry.py`（新增）
- `app/web_api/routes.py`
- `main.py`
- `app/config_defaults.py`
- `scripts/boundary_guard/constants.py`
- `web/static/index.html`
- `web/static/modules/settings.js`
- `tests/test_font_registry.py`（新增）
- `tests/fixtures/minimal.ttf`（新增，自系统 arial.ttf 复制）
- `tests/test_config_defaults.py`
- `tests/test_web_routes.py`
- `tests/test_floating_panel.py`
- `tests/test_overlay_render.py`
- `docs/WEB_CONSOLE.md`
- `docs/工单列表.md`
- `docs/工单列表/工单/W-FONT-002-完成报告.md`（本文件）

## 3. 未修改的关键区域

- `app/overlay.py`：未改（W-FONT-001 已锁定 `QFont(family, ...)` 解析）
- `app/floating_panel.py`：未改
- `app/danmu_engine.py` / `app/ai_client.py`：未改
- `app/mic_*.py`：未改
- `app/web_console.py` / `app/web_console_runtime.py`：未改
- `main.py` 的 `_on_config_changed` / `_consume_reply_queue` / `_on_screenshot_timer`：未改
- `scripts/boundary_guard.py` 主文件：未改（仅 `constants.py` 追加 `font_registry` exclude）
- `docs/runtime-state-map.md` / `docs/main-pipeline-sequence.md` / `docs/final-architecture-baseline.md`：未改
- `web/static/app.js`：未改（鉴权复用 `transport.js` 的 `API.token` + `apiFormFetch`/`apiFetch`）

## 4. 运行的命令

```bash
python -m pytest tests/test_font_registry.py tests/test_config_defaults.py tests/test_web_routes.py tests/test_floating_panel.py tests/test_overlay_render.py -q
python -m pytest tests/ -q
python scripts/boundary_guard.py
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest（本工单相关） | 通过 | 102 passed（含 11 个 `test_font_registry` + 5 个 web 路由 + 1 config + 2 Qt 集成） |
| pytest（全量） | 部分失败 | 989 passed, 5 skipped, **3 failed**（`tests/test_lifetime_stats.py` 的 `display_mode` 与 `WebStatusSnapshot` 不匹配，**范围外**，本工单未引入） |
| boundary_guard | 通过 | `RUNTIME_FIELD_EXCLUDE` 已含 `font_registry` |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 相关 pytest 全绿 | 102 passed | 是 |
| 2 | boundary_guard PASS | PASS | 是 |
| 3 | 字体设置 tab 末段「导入本地字体」区可见 | 代码已追加 HTML section | 待负责人 |
| 4 | 合法 .ttf 导入 toast + datalist 更新 | 逻辑已实现 | 待负责人 |
| 5 | 焦点自动填入 family | `uploadFontFile` 已实现 | 待负责人 |
| 6 | 4 类 4xx（zip/空/超大/无效） | 单测 + 路由契约测覆盖 | 是（自动化） |
| 7 | 保存 `danmu_font_family` 后热更上屏 | 走 W-FONT-001 钩子，未改主链路 | 待负责人 |
| 8 | 重启后 `imported_fonts` + 文件恢复 | `load_all` 已实现 | 待负责人 |
| 9 | 目录与 DB 互校验 | 孤儿补录；缺失文件保留 DB | 是（单测） |
| 10 | DELETE 幂等 / 404 | 路由 + 单测覆盖 | 是（自动化） |
| 11 | `__danmu_token` 核查 | 仓库使用 `API.token`（`transport.js`），非 `window.__danmu_token` | 是（已按负责人确认改用 transport） |
| 12 | 删除已导入字体 | UI + DELETE 路由已实现 | 待负责人 |

## 7. 风险与注意事项

- **Qt 主线程**：`import_bytes` / `delete` 仅经 `invoke_on_main`；`load_all` 在 `DanmuApp.__init__` 主线程执行。
- **写盘一致性**：`addApplicationFont` 失败会 `unlink` 已写文件。
- **`%APPDATA%` 不可写**：`FontRegistry` 降级为 `_disabled`，HTTP 返回 503，不拖崩启动。
- **鉴权**：前端使用 `apiFormFetch`/`apiFetch`（与压缩预览一致），未使用工单草稿中的 `window.__danmu_token`（仓库中不存在该变量）。
- **HTTP 单测**：`test_web_routes` 字体用例 mock `FontRegistry`，避免在 FastAPI 工作线程调用 `QFontDatabase`（会 access violation）；真实 Qt 行为由 `test_font_registry.py` 覆盖。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| — | `tests/test_lifetime_stats.py` 3 例失败：`WebStatusSnapshot` 不接受 `display_mode` 参数（与本工单无关） | 否（范围外，建议单独工单） |

## 9. 已更新的文档

- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/WEB_CONSOLE.md](../../WEB_CONSOLE.md)
- [x] [docs/工单列表/工单/W-FONT-002-完成报告.md](W-FONT-002-完成报告.md)

## 10. 建议下一个工单

- W-FONT-003（可选）：Web 端导入字体预览（CSS `font-family` 示例文字）
- 修复 `test_lifetime_stats` 与 `WebStatusSnapshot.display_mode` 不同步（独立小工单）
