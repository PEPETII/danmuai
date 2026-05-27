# GenerationPipelineState Plan

> Archived. Implemented: `app/application/generation_pipeline_state.py` (read-only projection).

## 设计目标

`GenerationPipelineState` 为视觉主链路提供集中只读投影；不承接真实写路径。

## 已迁移所有权（不在本对象）

- `last_api_trigger_at` → `RequestScheduler` (Phase 4-D)
- `request_started_at_by_id`, `rtt_history` → `RequestTimingService` (Phase 4-E/F)

## 冻结

主链路字段（`reply_buffer`, `ai_in_flight`, `_scene_generation`, `_latest_screenshot`, …）不得迁入本对象写路径。见 [phase4-freeze.md](phase4-freeze.md).

## 历史函数列表

文档曾列 `_probe_scene_change`, `_check_rhythm_trigger`, `_on_scene_generation_advanced` — 当前普通模式主路径不依赖节奏定时器；场景代际推进循环未激活。

完整 Phase 3-C–4-G 段落见 git history 中 `docs/generation-pipeline-state-plan.md` 修订前版本。
