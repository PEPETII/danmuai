# 工单 W-018

## 工单 ID

W-018

## 工单标题

SanitizedLogger 日志 UI 推送单例化（全局 LogEmitBus）

## 背景

Web 控制台仅连接 `danmu_app.logger.log_emitted`。`AiRunnable`、`HotkeyManager`、`global_exception_hook` 等会临时 `SanitizedLogger()`，每个实例原先各自持有独立 `QObject` 信号，导致部分错误能进 Python logger 但进不了 Web 日志环。对 `console=False` 打包 exe，会放大「用户无界面、排障日志不足」问题。

## 目标

任意 `SanitizedLogger()` 实例写出的日志，凡经 `_emit` 脱敏后，均进入同一全局 UI 推送通道；已连接 `danmu_app.logger.log_emitted` 的 Web 控制台能收到这些日志。

## 依赖项

无

## 允许修改的区域

- `app/logger.py`
- `tests/test_p1_log_sanitization.py`
- `docs/`（工单、完成报告、当前仓库状态、工单列表）

## 禁止修改的区域

- `main.py`
- `app/web_console.py`（现有 `danmu_app.logger.log_emitted.connect` 应继续有效）
- `app/runnable.py`、`app/hotkey.py`（调用方无需改）
- `web/`、`requirements.txt`、Boundary Guard 登记表

## 需求

1. 引入模块级 `LogEmitBus` 单例与 `get_log_bus()`。
2. `SanitizedLogger._emit` 经 `get_log_bus().log_emitted` 发射，不再使用实例级 signal。
3. 保留 `SanitizedLogger.log_emitted` 属性指向全局 bus，兼容现有 `connect` 写法。
4. 单测验证两个独立 `SanitizedLogger` 实例的日志均被同一 bus 订阅者收到。

## 非目标

- 不重构 `AiRunnable` / `HotkeyManager` 改为注入 `danmu_app.logger`
- 不改 Web 控制台连接方式（除非属性兼容不足）
- 不统一 Python `logging` 以外来源（如 uvicorn 自带日志）的 UI 推送

## 验收标准

- [ ] `app/logger.py` 存在 `LogEmitBus` / `get_log_bus()`，所有 `SanitizedLogger._emit` 走全局 bus
- [ ] `tests/test_p1_log_sanitization.py` 新增多实例 bus 用例通过
- [ ] `python -m pytest tests/test_p1_log_sanitization.py -q` 全通过
- [ ] 现有 P1 脱敏单测无回归

## 手动验证步骤

1. `python -m pytest tests/test_p1_log_sanitization.py -q` — 12 passed
2. `python main.py`，打开 Web 控制台日志 Tab
3. 触发会走 `AiRunnable` 的路径（如压缩失败需 mock 或断 API）或故意注册无效热键 — 对应 warning/error 应出现在 Web 日志环
4. （可选）打包 exe `console=False` 复验 startup.log + Web 日志

## 风险点

- 全局 bus 在 pytest 全量顺序执行时可能与 caplog 用例交互；单文件运行应稳定
- `SanitizedLogger` 不再继承 `QObject`，若有代码依赖 `isinstance(..., QObject)` 需后续排查（当前无已知调用）

## 完成后必须更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)（标为已完成）
- [x] [docs/templates/Codex完成报告/W-018-完成报告.md](../Codex完成报告/W-018-完成报告.md)

## Codex 完成报告要求

- 使用 [Codex完成报告模板.md](../Codex完成报告/Codex完成报告模板.md)
