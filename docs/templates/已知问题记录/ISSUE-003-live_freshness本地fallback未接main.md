# 已知问题记录

## 问题 ID

ISSUE-003

## 发现时间

2026-05-28（W-002 初版）；2026-05-29（W-002 收尾复核确认仍待接）

## 发现来源

W-002（死代码清理 + 截图退避最小接线）；[token-consumption-audit.md](../../audits/token-consumption-audit.md) T22

## 所属模块

`app/live_freshness.py`、`main.py`

## 状态

**已修复**（W-REFACTOR-BUG-P1-011-013，2026-06-03）。`main._maybe_inject_local_fallback` 已接入；Web `live_local_fallback` 随 `_local_fallback_active` 投影。

## 问题描述

`is_model_slow` 与 `build_local_fallback_batch` 在 `app/live_freshness.py` 中实现并有单元测试（`tests/test_live_freshness.py`），但 `main.py` 主链路从不调用。`_build_live_status_snapshot` 中 `LiveStatusSnapshot.local_fallback` 恒为 `False`；Web 控制台「直播状态」不会显示本地兜底文案。

W-002 已删除库存预取死链、`_local_fallback_active` 死状态，并完成截图退避接线（`screenshot_interval_ms`）；**未**实现慢模型零 API 顶屏。

## 影响范围

慢模型或 API 延迟较高时，屏上可能出现较长空窗；维护者若仅读 `live_freshness` 模块 docstring 外的旧审计/文档，易误以为本地 fallback 已在运行。

## 严重程度

低

## 是否阻塞当前工单

否（W-002 非目标明确排除）

## 临时处理方式

以 `app/live_freshness.py` 模块 docstring 与 [token-consumption-audit.md](../../audits/token-consumption-audit.md) 为准；公式化弹幕库 `min_on_screen` 补足仍走 `danmu_pool`（非本 ISSUE 的 fallback 路径）。

## 建议后续工单

**W-003（待登记）**：`is_model_slow` 为真时调用 `build_local_fallback_batch`，`from_local_fallback=True` 入队，并设置 `local_fallback=True`；可视情况推迟 `_trigger_api_call`。

## 备注

- W-002 完成报告：[W-002-完成报告.md](../Codex完成报告/W-002-完成报告.md)
- `main.py` 已保留 `from_local_fallback` 入队分支（`test_local_fallback_is_marked_replaceable`），仅缺主链路触发。
