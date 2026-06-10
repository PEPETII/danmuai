# ISSUE-014：场景探测未接线与文档漂移

## 问题 ID

ISSUE-014

## 发现时间

2026-05-29

## 发现来源

W-019（全库死代码静态审计）

## 所属模块

`main.py`、`app/scene_fingerprint.py`、`docs/runtime-state-map.md`

## 问题描述

- `_probe_scene_change` 已不存在；`_scene_generation` 在运行中恒为 `0`（单测 `test_capture_does_not_advance_scene_generation` 锁定该行为）。
- `scene_fingerprint.is_scene_change` / 截图 hash 未用于 API 触发前节流；静态画面与动态画面请求频率相同。
- W-019 已删除仅 reset、无逻辑的 scene gate 死状态字段；**未**恢复场景代际推进。

## 影响范围

- 用户：功能可用；静态场景下 vision API 与 token 消耗偏高。
- 开发/记忆：`scene_generation` 代际淘汰语义弱化；维护者文档曾描述已删除链路（W-019 已部分校正）。

## 严重程度

低

## 是否阻塞当前工单

否（W-019 只清理死代码，不恢复探测）

## 临时处理方式

- 依赖 `freshness` 配置影响 reply 延迟因子；截图 stale 丢弃仍走 `_record_stale_drop` 退避（`live_freshness.screenshot_interval_ms`）。
- 见 [token-consumption-audit.md](../../audits/token-consumption-audit.md)。

## 建议后续工单

**W-020**：恢复 `_probe_scene_change`（或等价逻辑）+ 可选 API 前 hash 跳过；需产品确认是否允许截图推进 `scene_generation`，并更新 `tests/test_p0_main_flow.py` / `tests/test_scene_freshness.py`。

## 备注

- 与 ISSUE-003（本地 fallback 未接 main）独立。
- W-019 完成报告 §8 引用本 ID。
