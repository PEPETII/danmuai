# W-024：修复全量 pytest 8 项既有失败

## 工单 ID

W-024

## 工单标题

修复全量 pytest 8 项既有失败（danmu_pool 路由桩 + LogEmitBus 测试隔离）

## 背景

W-016 后 Web 写 API 经 `bridge.invoke_on_main` 在主线程执行；W-018 引入模块级 `LogEmitBus` 单例。全量 `pytest tests/` 时稳定出现 8 项失败（1 项弹幕池路由集成测试 + 7 项 LogEmitBus），单文件或子集重跑常通过。与 W-023「恢复默认」无关，属测试隔离债务。

## 目标

`python -m pytest tests/ -q` 不再出现上述 8 项失败。

## 依赖项

- W-016（`invoke_on_main`）
- W-018（`LogEmitBus` / `get_log_bus()`）

## 允许修改的区域

- `tests/test_danmu_pool_api.py`
- `tests/conftest.py`
- `app/logger.py`（仅 `get_log_bus` 防御性重建）
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/已知问题与后续事项.md`
- `docs/templates/工单/W-024-pytest既有8项失败修复.md`
- `docs/templates/Codex完成报告/W-024-完成报告.md`
- `docs/templates/已知问题记录/ISSUE-018-全量pytest八项失败.md`

## 禁止修改的区域

- `main.py`
- `web/`
- `app/web_api/routes.py`
- `app/runnable.py`
- `app/web_api/danmu_pool.py`
- Boundary Guard 登记表（`runtime-state-map.md` 等）
- `requirements.txt`、锁文件

## 需求

1. `test_danmu_pool_routes_registered` 为 `bridge.invoke_on_main` 配置 `side_effect`，与 `test_web_console.py` 一致，使 POST/DELETE 真正执行 `pool_api` 函数。
2. `tests/conftest.py` 增加 autouse fixture，每个用例前后将 `app.logger._log_bus` 置为 `None`。
3. `get_log_bus()` 在 `sip.isdeleted` 检测到已销毁对象时重建 `LogEmitBus`。

## 非目标

- 不改 W-016 主线程收口设计
- 不重构 Web 路由测试框架
- 不顺手修 ISSUE-003 等其他已知问题

## 验收标准

- [x] `test_danmu_pool_routes_registered` 通过
- [x] p0/p1 所列 7 项 LogEmitBus 相关用例通过
- [x] `python -m pytest tests/ -q` 全绿（允许既有 skipped）

## 手动验证步骤

1. `python -m pytest tests/test_danmu_pool_api.py::test_danmu_pool_routes_registered -q`
2. `python -m pytest tests/test_p1_log_sanitization.py tests/test_p0_main_flow.py::test_compress_screenshot_failure_path tests/test_p0_main_flow.py::test_runnable_request_uncaught_exception_emits_error tests/test_p0_main_flow.py::test_runnable_request_failure_releases_in_flight -q`
3. `python -m pytest tests/ -q`

## 风险点

- autouse 重置 bus 不影响同用例内多实例共享 bus 的断言
- `sip.isdeleted` 依赖 PyQt6 自带 sip

## 完成后必须更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/已知问题与后续事项.md](../../已知问题与后续事项.md)

## Codex 完成报告要求

- 使用 [Codex完成报告模板.md](../Codex完成报告/Codex完成报告模板.md)
- 见 [W-024-完成报告.md](../Codex完成报告/W-024-完成报告.md)
