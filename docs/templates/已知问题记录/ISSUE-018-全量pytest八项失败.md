# ISSUE-018：全量 pytest 8 项既有失败

## 问题 ID

ISSUE-018

## 发现时间

2026-05-29

## 发现来源

W-017 / W-018 / W-021 / W-023 完成报告（全量 pytest 记录 8 failed）

## 所属模块

`tests/test_danmu_pool_api.py`、`tests/conftest.py`、`app/logger.py`（`LogEmitBus`）

## 问题描述

全量 `python -m pytest tests/ -q` 稳定出现 8 项失败，分两类：

1. `test_danmu_pool_routes_registered`：`POST /api/danmu-pool/custom` 返回 200 但响应无 `added` 字段（`KeyError`）。W-016 后写 API 经 `bridge.invoke_on_main`，测试使用裸 `MagicMock()` 未 stub，未真正执行 `pool_api.append_custom`。
2. 其余 7 项（p0_main_flow ×3、p1_log_sanitization ×4）：`RuntimeError: wrapped C/C++ object of type LogEmitBus has been deleted`。W-018 模块级 `_log_bus` 在 Qt 测试销毁 `QApplication` 后仍指向已删除的 `QObject`。

单文件或子集重跑常通过。

## 影响范围

仅 CI/本地全量测试；生产运行时 `main.py` 全程持有 `QApplication`，正常不触发。

## 严重程度

中（阻塞全量 pytest 全绿）

## 是否阻塞当前工单

否（已由 W-024 修复）

## 临时处理方式

单独重跑失败文件；或仅跑子集验收

## 建议后续工单

W-024（2026-05-29 已完成）

## 备注

修复：`bridge.invoke_on_main.side_effect`；`tests/conftest.py` autouse 重置 `_log_bus`；`get_log_bus()` + `sip.isdeleted` 防御重建。见 [W-024-完成报告.md](../Codex完成报告/W-024-完成报告.md)。
