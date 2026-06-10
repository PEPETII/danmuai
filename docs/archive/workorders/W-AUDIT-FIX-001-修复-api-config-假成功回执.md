# 工单

> 工单 ID：`W-AUDIT-FIX-001`

---

## 工单 ID

`W-AUDIT-FIX-001`

## 工单标题

修复 `/api/config` 保存假成功回执

## 背景

`W-AUDIT-001` 审计确认：`/api/config` 通过 `save_config_requested` 把配置写入委托给 Qt 主线程，但 HTTP 路由没有检查 `done.wait(timeout=5.0)` 的结果，也没有接收主线程失败信息，导致前端可能收到 `{"ok": true}`，实际却没有保存成功。

## 目标

只有在主线程 `apply_web_config_payload()` 真正完成且成功时，`/api/config` 才返回 `{"ok": true}`；主线程超时或保存异常时，接口必须返回失败状态和稳定错误码。

## 依赖项

无。

## 允许修改的区域

- `app/web_console.py`
- `tests/test_web_console.py`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/工单/W-AUDIT-FIX-001-修复-api-config-假成功回执.md`
- `docs/templates/Codex完成报告/W-AUDIT-FIX-001-完成报告.md`

## 禁止修改的区域

- `main.py`
- `app/` 内除 `app/web_console.py` 外的其他文件
- `web/static/`
- `tests/` 内除 `tests/test_web_console.py` 外的其他文件
- `requirements.txt`
- `pyproject.toml`
- `scripts/`

## 需求

1. 保持“HTTP 线程发信号、Qt 主线程落盘”的边界，不允许 HTTP 线程直接写配置。
2. `/api/config` 仅在主线程显式确认成功后返回 `{"ok": true}`。
3. 主线程超时返回 `504`，响应体包含稳定错误码 `save_timeout`。
4. 主线程保存异常返回 `500`，响应体包含稳定错误码 `save_failed`。
5. 新增最小回归测试覆盖成功、超时、异常三类结果。

## 非目标

- 不修改 `ConfigService.apply_web_config_payload()` 逻辑。
- 不修改 Web 前端提示文案或交互。
- 不处理审计中的其他问题。

## 验收标准

- [ ] `/api/config` 不再在超时或异常时返回 `{"ok": true}`
- [ ] 成功、超时、异常三类回归测试均通过
- [ ] `Boundary Guard` 通过

## 手动验证步骤

1. 运行 `python -m pytest tests/test_web_console.py -q`
2. 运行 `python scripts/boundary_guard.py`
3. 检查 `/api/config` 路由实现，确认失败路径返回错误状态码而不是成功响应

## 风险点

- 必须避免新增任何绕过 `save_config_requested` / `apply_web_config_payload()` 的写配置路径。
- 结果回执与 `threading.Event` 的写入顺序必须正确，否则仍可能出现竞态假成功。

## 完成后必须更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/templates/Codex完成报告/W-AUDIT-FIX-001-完成报告.md](../Codex完成报告/W-AUDIT-FIX-001-完成报告.md)

## Codex 完成报告要求

- 使用 [Codex完成报告模板.md](../Codex完成报告/Codex完成报告模板.md)
- 必须列出全部修改文件路径
- 不得顺手处理 `W-AUDIT-001` 里的其他问题
