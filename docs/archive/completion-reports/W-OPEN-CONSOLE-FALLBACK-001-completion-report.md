# Codex 完成报告

> 工单 ID：W-OPEN-CONSOLE-FALLBACK-001
> 完成时间：2026-06-10
> 执行者：Codex / Cursor Agent

---

## 1. 修改摘要

修复了 `app/main_launch_mixin.py::_open_web_console` 在 `shell.handshake_failed=True` 时静默 `return` 的 bug。当 pywebview 子进程启动失败、Web 服务器仍在 18765 端口运行时，**托盘「设置」菜单和双击托盘**改为弹 QMessageBox 询问用户是否在系统浏览器打开控制台；用户选「是」→ 打开 `http://127.0.0.1:18765/#settings`；选「否」→ 静默记日志；启动期已 fallback 过一次（`server._browser_launch_opened=True`）→ 不再弹窗（保留 BUG-014 dedupe）。webview/browser 模式行为统一。

## 2. 修改的文件

- `app/main_launch_mixin.py`
- `tests/test_capture_flow.py`
- `docs/工单列表/工单/W-OPEN-CONSOLE-FALLBACK-001.md`
- `docs/工单列表.md`
- `docs/当前仓库状态.md`
- `docs/reports/W-OPEN-CONSOLE-FALLBACK-001-completion-report.md`（本文件）

## 3. 未修改的关键区域

- 未修改 `app/web_console.py`：是
- 未修改 `app/webview_shell.py` 主体：仅复用 `open_web_console_browser` 和 `server._browser_launch_opened` 标志
- 未修改 `app/main_lifecycle_mixin.py`、`app/main_mic_mixin.py`、`app/main_display_mixin.py`、`app/main_request_context_mixin.py`、`app/main_state_mixin.py`、`app/main_web_facade_mixin.py`：是
- 未修改 `main.py`：是
- 未修改 `app/tray.py`：是（仍调用 `app.show_settings` → `_open_web_console`）
- 未修改 `app/translations.py`：是（沿用 `tr(key, default)` 第二参数为默认值，**无需在翻译表注册**——与 `_maybe_prompt_slow_webview_start` 的 `webview.slow_start_title/message` 模式一致）
- 未修改 `web/`、`requirements*.txt`、锁文件、`.github/`、`DanmuAI.spec`、打包配置：是
- 未修改 `tests/test_web_launch.py`、`tests/test_webview_shell.py`：是

## 4. 运行的命令

```bash
python -m pytest tests/test_capture_flow.py -q -x
python -m pytest tests/test_web_launch.py tests/test_webview_shell.py -q -x
python -m pytest tests/test_p0_main_flow.py tests/test_web_console.py -q -x
python scripts/boundary_guard.py
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 分批测试（IDE_AGENT_RULES §10） | 通过 | 3 批：14 + 41 + 13 = 68 passed |
| boundary_guard | 通过 | "Boundary Guard: PASS" |
| 其他 | — | |

### 5.1 分批测试报告

| 批次 | 命令 | 结果 | 失败项 |
|------|------|------|--------|
| 1（改动相关） | `python -m pytest tests/test_capture_flow.py -q -x` | 14 passed | 无 |
| 2（web 启动回归） | `python -m pytest tests/test_web_launch.py tests/test_webview_shell.py -q -x` | 41 passed | 无 |
| 3（主链路 / web 控制台回归） | `python -m pytest tests/test_p0_main_flow.py tests/test_web_console.py -q -x` | 13 passed | 无 |

**未执行全量确认**：本工单严格遵守 IDE_AGENT_RULES §10，**未执行** `python -m pytest tests/`。CI 维护者全量留待 CI。

**未执行测试说明**：
- `tests/test_capture_flow.py`：14 个用例，其中 3 个为本工单新增/改写（`_patch_fallback_message_box` helper + 3 个 `_open_web_console` handshake_failed 测试）
- `tests/test_web_launch.py`：未改动，回归通过
- `tests/test_webview_shell.py`：未改动，回归通过
- `tests/test_p0_main_flow.py` / `tests/test_web_console.py`：未改动，回归通过

**结论**：3 批全部通过；本工单引入的新行为已被显式测试覆盖；既有契约（BUG-014 dedupe）通过 `server._browser_launch_opened` 标志继续守护。

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 在 WebView2 缺失的 Windows 环境 `python main.py` | 待负责人在真实环境执行 | 待 |
| 2 | 托盘出现；pywebview 启动失败；Web 服务器 18765 存活 | 待 | 待 |
| 3 | 右键托盘 → 「设置」→ 弹窗；Yes → 默认浏览器打开 `http://127.0.0.1:18765/#settings` | 待 | 待 |
| 4 | 再点托盘「设置」→ 弹窗（`_browser_launch_opened` 已置位，**不弹**） | 待 | 待 |
| 5 | 双击托盘图标 → 同 3 | 待 | 待 |
| 6 | `--web-browser` 启动后同样条件 → 行为一致（用户确认 q2：统一） | 待 | 待 |
| 7 | 正常 WebView2 环境 → 弹窗**不**触发；pywebview 窗口直接打开 | 待 | 待 |

> **IDE Agent 限制**：步骤 1-7 需要在真实 Windows 桌面环境手动执行；本工单在 CI/headless 环境下无法完整手动验证（pywebview 子进程需 WebView2），仅完成代码 + 自动化测试 + boundary guard 验证。手动验证由负责人在真实环境补全。

## 7. 风险与注意事项

- **风险 1**：`QMessageBox.question` 在测试中未被 monkeypatch 会同步阻塞测试。本工单已通过 `_patch_fallback_message_box` helper 处理，测试不阻塞。
- **风险 2**：原 BUG-014 dedupe 在启动期仍由 `finalize_handshake_failure` + `_browser_launch_opened` 守护；本工单仅在托盘显式点击时绕过该 dedupe，不影响启动期行为。
- **风险 3**：若用户持续选「否」→ `_browser_launch_opened` 不会被置位，每次点托盘都会再弹。本设计是**故意的**——用户可拒绝但不应被默默静默；如需更激进的 dedupe，可后续增加「每日最多弹 N 次」计数。
- **风险 4**：`open_web_console_browser` 内部调用 `webbrowser.open`，可能因系统无默认浏览器而抛 `webbrowser.Error`。本工单已加 try/except 兜底，失败时复位 `_browser_launch_opened = False` 并 logger.warning。
- **回滚**：仅 `_open_web_console` + 新 helper `_prompt_browser_fallback_after_webview_failure` 共 ~50 行；git revert 单 commit 即可。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| — | 无 | — |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] 新建工单 [docs/工单列表/工单/W-OPEN-CONSOLE-FALLBACK-001.md](../../工单列表/工单/W-OPEN-CONSOLE-FALLBACK-001.md)
- [x] 新建完成报告（本文件）

## 10. 建议下一个工单

- **W-OPEN-CONSOLE-FALLBACK-002**（可选）：pywebview 失败后自动重试 attach（不依赖用户托盘点击）。本工单已搭好 helper 结构，后续可增加 `_schedule_webview_attach_retry(server, path)` 调度。
- **W-OPEN-CONSOLE-DAILY-DEDUPE**（可选）：托盘 fallback 弹窗的「每日最多 N 次」计数器，避免用户持续被问。
- **i18n 翻译表注册**（可选）：当前用 `tr(key, default)` 传默认文案，未在 `app/translations_*.py` 注册 zh/en 正式翻译键。`_maybe_prompt_slow_webview_start` 也是同样模式。若后续要做多语言覆盖率审计，可批量补登。
