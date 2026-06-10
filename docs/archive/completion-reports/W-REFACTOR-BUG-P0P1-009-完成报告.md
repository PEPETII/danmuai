# Codex 完成报告

> 工单 ID：W-REFACTOR-BUG-P0P1-009  
> 完成时间：2026-06-02  
> 执行者：Cursor Agent（Composer）

---

## 1. 修改摘要

修复 **BUG-012**：`web_launch_mode == "browser"`（`--web-browser`）时 `_open_web_console_when_ready(use_browser=True)` 在首次调用即 `open_web_console_browser`，用 `WebConsoleServer._browser_launch_opened` 防止重复开 tab；HTTP 未就绪时以 0.25s 短探测 + 500ms 重试仅用于 `clear_startup_attach_error_if_needed`，不再 20s 静默。pywebview 路径（`use_browser=False`）逻辑未改。未改 `webview_shell` 双 fallback（BUG-014）。

## 2. 修改的文件

- `main.py` — browser/webview 分支分叉；browser 启动 warning 文案
- `tests/test_p0_main_flow.py` — `test_browser_mode_opens_browser_when_server_slow` 等 3 条
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/W-REFACTOR-BUG-P0P1-009-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `web/static/`：是
- 未修改 `community-site/`：是
- 未修改 `app/web_console.py`：是
- 未修改 `app/webview_shell.py`：是
- 未修改 `app/web_api/`：是
- 未修改 `docs/refactor/**`：是
- 未顺手修 BUG-014 / BUG-021：是

## 4. 运行的命令

```bash
python scripts/boundary_guard.py
python -m pytest tests/test_p0_main_flow.py -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| boundary_guard | 通过 | Boundary Guard: PASS |
| pytest（工单指定子集） | 通过 | 38 passed |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | `python main.py --web-browser` → ~1s 内出现浏览器 tab | 待负责人 | 待负责人 |
| 2 | 模拟 server 慢启 → 仍只开一次浏览器，无 20s 空白 | 待负责人 | 待负责人 |
| 3 | 默认 pywebview 冷启动行为不变 | 待负责人 | 待负责人 |

## 7. 风险与注意事项

- 浏览器可能先于 uvicorn 就绪打开，短暂连接失败页；server 就绪后由 status timer / 用户刷新恢复。
- `server._browser_launch_opened` 为 `main.py` 侧约定，非 Boundary Guard 登记字段。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| BUG-014 | pywebview 双重 fallback 浏览器 | 否（审计已有） |
| BUG-021 | browser 模式其它边界路径 | 否（主路径已覆盖；独立票 W-017 可再验） |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] 本完成报告

## 10. 建议下一个工单

- `W-REFACTOR-BUG-P0P1-010`（BUG-014 pywebview 双重 fallback 浏览器）。
