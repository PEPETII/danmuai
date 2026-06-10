# 工单

> 工单 ID：`W-AUDIT-FIX-002`

---

## 工单 ID

`W-AUDIT-FIX-002`

## 工单标题

修复审计剩余高优先级与测试基线问题

## 背景

`W-AUDIT-001` 在 `/api/config` 之外还识别出单实例误判、退出阶段 HTTP client / 线程池顺序错误、启动同步等待过长、`pytest` 在 Python 3.14 下后置崩溃、降级状态轮询 toast spam、`HistoryWriter` 静默吞异常等问题。

## 目标

在不破坏主链路和边界守卫的前提下，完成剩余高优先级问题与测试基线问题的最小修复，并恢复 `pytest` / `ruff` / `boundary_guard` 绿灯。

## 依赖项

- `W-AUDIT-001`
- `W-AUDIT-FIX-001`

## 允许修改的区域

- `app/single_instance.py`
- `main.py`
- `app/history_writer.py`
- `app/startup_trace.py`
- `app/mic_test_send.py`
- `web/static/app.js`
- `README.md`
- `tests/`
- `docs/main-pipeline-sequence.md`
- `docs/已知问题与后续事项.md`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/工单/W-AUDIT-FIX-002-修复审计剩余高优先级与测试基线问题.md`
- `docs/templates/Codex完成报告/W-AUDIT-FIX-002-完成报告.md`

## 禁止修改的区域

- `app/` 内与本工单无关的模块
- `requirements.txt`
- `pyproject.toml`
- 打包脚本

## 需求

1. 修复 `SingleInstanceGuard` 的 `listen()` 失败误判和无条件 `removeServer()` 风险。
2. 修复 `quit()` 中先关 HTTP client 再等线程池的顺序问题，并记录超时 warning。
3. 缩短启动阶段同步 `wait_ready()` 等待，降低桌面空窗。
4. 消除 Windows + Python 3.14 下 `tests/test_single_instance.py` 的后置崩溃。
5. 为状态轮询错误 toast 增加节流。
6. `HistoryWriter.flush()` 失败必须记录日志。
7. 保持 `pytest`、`ruff`、`boundary_guard` 通过。

## 非目标

- 不重构 pywebview / Qt / Web 总体架构。
- 不调整主链路“截图 -> AI -> 回复 -> 入队 -> 上屏”顺序。
- 不新增线程模型。

## 验收标准

- [x] `python -m pytest tests/ -q` 通过
- [x] `python -m ruff check app main.py tests scripts` 通过
- [x] `python scripts/boundary_guard.py` 通过
- [x] 单实例、退出顺序、Python 3.14 测试基线、历史写入日志、轮询 toast 节流均有代码落地

## 手动验证步骤

1. 运行 `python -m pytest tests/ -q`
2. 运行 `python -m ruff check app main.py tests scripts`
3. 运行 `python scripts/boundary_guard.py`
4. 复查单实例、退出顺序、状态轮询和 README 支持说明

## 风险点

- `SingleInstanceGuard` 修复必须保守，不能把失败继续误判成主实例。
- 启动等待调整不能破坏后续 `pywebview` 异步重试链路。
- `pytest` 3.14 处理只能做明确支持边界，不应假装已支持未验证环境。

## 完成后必须更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/main-pipeline-sequence.md](../../main-pipeline-sequence.md)
- [x] [docs/已知问题与后续事项.md](../../已知问题与后续事项.md)
- [x] [docs/templates/Codex完成报告/W-AUDIT-FIX-002-完成报告.md](../Codex完成报告/W-AUDIT-FIX-002-完成报告.md)

## Codex 完成报告要求

- 使用 [Codex完成报告模板.md](../Codex完成报告/Codex完成报告模板.md)
- 必须列出全部修改文件路径
- 明确写出三项验证结果：`pytest`、`ruff`、`boundary_guard`
