# Codex 完成报告

> 工单 ID：W-REFACTOR-BUG-P0P1-003  
> 完成时间：2026-06-01  
> 执行者：Cursor Agent（Composer）

---

## 1. 修改摘要

修复 **BUG-004**：`attach_web_console` 短 `wait_ready` 超时后，terminal 失败（bind 失败 / 控制台线程退出）不再调度 pywebview，用户失败提示经 `notify_web_console_failure` 单路径且去重；慢启动（线程仍存活）仍后台等待并 attach。uvicorn 绑定成功后自动清除 attach 阶段写入的 Web 错误条，避免「先失败后可用的」状态条割裂。未改 `webview_shell.py`、browser fallback（BUG-012/014）。

## 2. 修改的文件

- `main.py` — `__init__` / `_schedule_webview_attach` / `_open_web_console_when_ready` 按 `classify_web_console_startup` 门控
- `app/web_console.py` — 启动阶段分类、`_startup_*` 标志、`clear_startup_attach_error_if_needed`、`_on_uvicorn_started` / 状态 timer 恢复
- `tests/test_web_console.py` — 分类、错误条恢复、credentials 测试对齐公开 API
- `tests/test_p0_main_flow.py` — terminal 跳过调度 / 去重 notify
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/W-REFACTOR-BUG-P0P1-003-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `web/static/`：是
- 未修改 `community-site/`：是
- 未修改 `app/webview_shell.py`：是
- 未修改 `app/web_api/`：是
- 未修改 `docs/refactor/**`：是
- 未顺手修 BUG-012 / BUG-014：是

## 4. 运行的命令

```bash
python scripts/boundary_guard.py
python -m pytest tests/test_p0_main_flow.py tests/test_web_console.py -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest（工单指定子集） | 通过 | 110 passed |
| boundary_guard | 通过 | Boundary Guard: PASS |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 占用 18765 后 `python main.py` → 单次失败提示，无 pywebview 握手风暴 | 待负责人 | 待负责人 |
| 2 | 释放端口后重启 → 桌面壳正常，状态条无陈旧 ERROR | 待负责人 | 待负责人 |
| 3 | 正常冷启动 → 仍调度 `_schedule_webview_attach` | 待负责人 | 待负责人 |

## 7. 风险与注意事项

- `wait_ready` 仍保持 W-STARTUP-002 短超时（0.5s/1.5s）；多数冷启动走 `slow` 路径，行为与改前一致。
- pywebview 握手失败后的浏览器回退（BUG-014）与 browser 模式 20s 行为（BUG-012）未在本工单处理。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| BUG-012 | browser 模式 20s 内不开浏览器 | 否（审计已有） |
| BUG-014 | pywebview 双重 fallback 浏览器 | 否（审计已有） |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] 本完成报告

## 10. 建议下一个工单

- `W-REFACTOR-BUG-P0P1-010`（BUG-014 pywebview 双重 fallback）或 BUG-003 display_count 相关 refactor 票。
