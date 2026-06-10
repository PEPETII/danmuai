# 工单 ID

W-OPEN-CONSOLE-FALLBACK-001

## 工单标题

pywebview 启动失败后托盘「设置」/ 双击托盘改为浏览器回退（弹窗询问）

## 背景

当 pywebview 子进程启动失败（静默崩溃 / 超时 / WebView2 未安装）后，托盘图标右键菜单的「设置」选项和双击托盘图标都没有任何反应——不会弹出窗口，也不会自动在浏览器中打开设置页面。但 Web 服务器（127.0.0.1:18765）仍正常运行。

定位到 `app/main_launch_mixin.py` `_open_web_console()` 第 58-64 行：`shell.handshake_failed` 命中后直接 `return`，无任何浏览器回退或用户提示。

## 目标

消除 `_open_web_console` 在 `shell.handshake_failed=True` 时静默 `return` 的行为。改为：

- 弹 QMessageBox 询问用户是否在系统浏览器打开 `http://127.0.0.1:18765/#settings`
- 用户选「是」→ 默认浏览器打开设置页 + 设置 `server._browser_launch_opened = True` 去重
- 用户选「否」→ 静默（日志记录）
- 启动期已经回退过一次浏览器（`server._browser_launch_opened=True`）→ 不再弹窗（保留 BUG-014 dedupe）
- webview 模式与 browser 模式行为统一

## 依赖项

- 无（直接基于现有 `_fallback_to_system_browser` / `open_web_console_browser` 基础设施）

## 允许修改的区域

- `app/main_launch_mixin.py`
- `app/translations.py`
- `tests/test_capture_flow.py`
- `docs/工单列表/工单/W-OPEN-CONSOLE-FALLBACK-001.md`（本工单）
- `docs/archive/completion-reports/W-OPEN-CONSOLE-FALLBACK-001-completion-report.md`
- `docs/workflow/工单列表.md`
- `docs/workflow/当前仓库状态.md`
- `docs/已知问题与后续事项.md`

## 禁止修改的区域

- `main.py`
- `app/main_lifecycle_mixin.py`、`app/main_mic_mixin.py`、`app/main_display_mixin.py`、`app/main_request_context_mixin.py`、`app/main_state_mixin.py`、`app/main_web_facade_mixin.py`
- `app/webview_shell.py`（仅复用已有 helper，不改主体）
- `app/web_console.py`
- `web/`
- `requirements*.txt`、锁文件
- `.github/`、CI 配置
- `DanmuAI.spec`、打包脚本
- `tests/test_web_launch.py`、`tests/test_webview_shell.py`（保持不动）

## 需求

1. 在 `app/main_launch_mixin.py` 中重写 `_open_web_console`：
   - 删除原第 58-64 行的「handshake_failed → return」分支
   - 新增分支：若 `shell.handshake_failed` 且 `self.web_server` 存在，且 `not getattr(self.web_server, "_browser_launch_opened", False)` → 主线程 `QMessageBox.question` 询问，Yes 调 `open_web_console_browser(self.web_server, path)` 并设 `_browser_launch_opened=True`，No 静默记日志
   - 已 fallback 过 → 静默 return
   - webview/browser 模式统一
2. 在 `app/translations.py` 注册新 i18n 键：
   - `webview.fallback_to_browser_title`（zh / en）
   - `webview.fallback_to_browser_message`（zh / en）
3. 改写 `tests/test_capture_flow.py::test_open_web_console_after_handshake_failed_does_not_reopen_browser`：
   - 重命名为 `test_open_web_console_after_handshake_failed_prompts_browser_fallback`
   - monkeypatch `QMessageBox.question` 返回 Yes
   - 断言弹窗被调用、`open_web_console_browser` 被以 `(server, "/#settings")` 调用、`_browser_launch_opened=True`
4. 新增 2 个测试：
   - `test_open_web_console_after_handshake_failed_no_prompt_when_browser_already_opened`（`_browser_launch_opened=True` → 不弹窗）
   - `test_open_web_console_after_handshake_failed_user_declines`（用户选 No → 不打开浏览器）

## 非目标

- 不重写 `app/webview_shell.py` 的 `_maybe_prompt_slow_webview_start`（启动期慢启动弹窗独立存在）
- 不实现「pywebview 失败后自动重试 attach」逻辑
- 不动托盘菜单结构、Web UI
- 不修复 BUG-009 状态（已修复）— 本工单属于 BUG-009 系列后续打磨
- 不改 `app/web_console.py` / `app/webview_shell.py` 主体

## 验收标准

- [x] pywebview 启动失败后右键托盘「设置」弹窗询问用户
- [x] 用户选「是」→ 系统浏览器打开 `http://127.0.0.1:18765/#settings`
- [x] 用户选「否」→ 静默
- [x] 启动期已 fallback 过一次后 → 再次点击托盘不弹窗
- [x] webview/browser 模式行为统一
- [x] 既有 `test_open_web_console_after_handshake_failed_does_not_reopen_browser` 改写完成
- [x] 2 个新增测试通过
- [x] 分批 pytest 3 批全部通过
- [x] `python scripts/boundary_guard.py` PASS

## 手动验证步骤

1. 在 WebView2 缺失的 Windows 环境 `python main.py`
2. 托盘出现；pywebview 启动失败；Web 服务器 18765 端口存活
3. 右键托盘 → 「设置」→ 弹窗「桌面窗口不可用，是否在系统浏览器中打开本地网页端？」→ Yes → 默认浏览器打开 `http://127.0.0.1:18765/#settings`
4. 再点托盘「设置」→ 弹窗（`_browser_launch_opened` 已置位，**不弹**）
5. 双击托盘图标 → 同 3
6. `--web-browser` 启动后同样条件 → 行为一致
7. 正常 WebView2 环境 → 弹窗**不**触发；pywebview 窗口直接打开

## 风险点

- i18n 键未在 `translations.py` 既有结构中注册会 `KeyError`：先 Grep 现有 `webview.slow_start_title` 找到插入点
- `QMessageBox.question` 在测试中未被 monkeypatch 会同步阻塞测试：用 `monkeypatch.setattr` 替换
- 既有测试契约被改写：原 BUG-014 dedupe 在启动期仍由 `finalize_handshake_failure` + `_browser_launch_opened` 守护，本工单不取消该 dedupe

## 完成后必须更新的文档

- [x] [docs/workflow/当前仓库状态.md](../../workflow/当前仓库状态.md)
- [x] [docs/workflow/工单列表.md](../../workflow/工单列表.md)
- [x] 完成报告 [docs/archive/completion-reports/W-OPEN-CONSOLE-FALLBACK-001-completion-report.md](../../archive/completion-reports/W-OPEN-CONSOLE-FALLBACK-001-completion-report.md)
