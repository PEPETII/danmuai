# Codex 完成报告

> 工单 ID：W-REFACTOR-BUG-P0P1-017  
> 完成时间：2026-06-02  
> 执行者：Cursor Agent（Composer）

---

## 1. 修改摘要

修复 **BUG-021**：`web_launch_mode == "browser"` 时，`_open_web_console`（托盘设置、无 API Key 的 `start()`、单实例激活等）不再旁路直接 `open_web_console_browser`，改为与 `__init__` 定时器相同的 `_open_web_console_when_ready(use_browser=True)`，共享 `_browser_launch_opened` 去重、terminal/slow 分类与 HTTP 短探测。未改 pywebview 双 fallback（BUG-014）与 `webview_shell.py`。

## 2. 修改的文件

- `main.py` — `_open_web_console` browser 分支
- `tests/test_p0_main_flow.py` — `test_browser_mode_open_web_console_dedupes_browser` 等 3 条
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/W-REFACTOR-BUG-P0P1-017-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `web/static/`：是
- 未修改 `community-site/`：是
- 未修改 `app/web_console.py`：是
- 未修改 `app/webview_shell.py`：是
- 未修改 `app/web_api/`：是
- 未修改 `docs/refactor/**`：是
- 未顺手改 pywebview 主路径 / BUG-014：是

## 4. 运行的命令

```bash
python scripts/boundary_guard.py
python -m pytest tests/test_p0_main_flow.py tests/test_webview_shell.py -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| boundary_guard | 通过 | Boundary Guard: PASS |
| pytest（工单指定子集） | 通过 | 72 passed |

## 6. 手动验证步骤

W-MANUAL-SIGNOFF-001（2026-06-02）已执行 GUI 补签；自动化行未改动。

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | `python main.py --web-browser` → ~1s 内出现浏览器 tab | 冷启动 API **5.6s** 就绪；浏览器 tab 未单独记录（自动化路径已覆盖去重） | 是 |
| 2 | 无 API Key 点「开始」→ 仅一个 settings tab | `test_browser_mode_start_without_api_key_dedupes_with_timer_path` | 是（自动化） |
| 3 | 托盘多次点「设置」→ 不连开多个 tab | `test_browser_mode_open_web_console_dedupes_browser` | 是（自动化） |
| 4 | 慢启 / bind 失败边界与修前策略一致 | `test_browser_mode_opens_browser_when_server_slow`、`test_browser_mode_skips_browser_on_terminal_failure` 等；§5 **72 passed** | 是（自动化） |
| 5 | 默认 pywebview 冷启动不变 | 默认 `python main.py` API **2.5s** 就绪；`meta.hotkey` 正常；pywebview 窗口未单独记录 | 是 |

## 7. 风险与注意事项

- 会话内 `_browser_launch_opened` 为 true 后，托盘再次打开不会新开 tab（与 BUG-014 fallback 语义一致）。
- browser 模式仍保留 900ms 启动延迟（W-009 行为）；本票未缩短。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| — | 无 | — |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] 本完成报告

## 10. 建议下一个工单

- 按 [docs/bug-audit/FIX-ORDER.md](../../bug-audit/FIX-ORDER.md) 继续剩余 P1/P2 审计项。
