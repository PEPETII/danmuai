# GenerationPipeline → DanmuApp 宿主触点名册

> **日期化维护者快照（2026-07-10）**：计数对应当时的 `generation_pipeline.py`，用于解释 W-T5-GP 波次收口结果，不是永久 API 清单。修改 GP/Host 契约前须重新搜索调用点，并同步三份 Boundary Guard 登记表。
>
> **工单**：W-T5-GP-001（名册）/ W-T5-GP-005（批 3 收口）  
> **审计基准**：`app/application/generation_pipeline.py`（527 行，2026-07-10）  
> **方法**：只读 `rg 'app\._'` / `rg 'app\.reply_'` 交叉核对  
> **线程假设**：全部触点仅在 **Qt 主线程**（`reply_timer` 回调链 / `_on_ai_reply` 委托链）调用；GP 不实例化 Qt 对象。

## 摘要

| 类别 | 唯一符号数 | 源码出现次数（含重复行） |
|------|-----------|-------------------------|
| `app._*` 私有方法/属性 | **0** | **0**（W-T5-GP-005 后；原 32） |
| `app.reply_*` 公开队列/定时器 | **2** | **34** |
| GP Host Façade 公开方法 | **18** | **66**（W-T5-GP-002 首批 3 + GP-003 批 2 新增 4 + GP-005 批 3 新增 11） |

GP 通过 `self._app` 触达宿主；`reply_timer` / `reply_buffer` 所有权仍属 `DanmuApp`（Phase 4 冻结，不迁入 `application/`）。

---

## GP Host Façade 方法名册（W-T5-GP-002–005）

| 批次 | 公开方法 | 委托私有实现 | 用途 |
|------|----------|--------------|------|
| GP-002 | `enqueue_reply_batch_for_pipeline(...)` | `_enqueue_reply_batch` | 解析后批次入队 |
| GP-002 | `update_stats_from_pipeline(...)` | `_update_stats` | 会话统计 |
| GP-002 | `set_latest_displayed_from_pipeline(...)` | `_latest_displayed_*` 写 | 代龄投影写回 |
| GP-003 | `record_undisplayed(...)` | `_record_undisplayed` | 未上屏诊断 |
| GP-003 | `track_duplicate_rejection(...)` | `_track_duplicate_rejection` | 去重观测 |
| GP-003 | `maybe_duplicate_loss_topup(...)` | `_maybe_duplicate_loss_topup` | duplicate 池回填 |
| GP-003 | `display_danmu_text(...)` | `_display_danmu_text` | 单条上屏 |
| GP-005 | `is_pet_barrage_mode_enabled()` | `_pet_barrage_mode_enabled` | 三路分发分支 |
| GP-005 | `danmu_render_mode()` | `_danmu_render_mode` | overlay / fp 路径 |
| GP-005 | `reply_scene_count`（@property） | `_reply_scene_count` | 解析批次元数据 |
| GP-005 | `reply_filler_count`（@property） | `_reply_filler_count` | 解析批次元数据 |
| GP-005 | `reply_request_id(...)` | `_reply_request_id` | request_id 键 |
| GP-005 | `log_reply_pipeline(...)` | `_log_reply_pipeline` | 入队前日志 |
| GP-005 | `log_reply_pipeline_from_queued(...)` | `_log_reply_pipeline_from_queued` | 出队消费日志 |
| GP-005 | `current_batch_id`（@property） | `_batch_id` | drop_replaceable 键 |
| GP-005 | `notify_pet_visual_success()` | `_notify_pet_visual_success` | 桌宠动画 hint |
| GP-005 | `publish_live_status()` | `_publish_live_status` | live status 刷新 |
| GP-005 | `queue_low_watermark`（@property） | `_queue_low_watermark` | 低水位加速 |
| GP-005 | `maybe_pool_topup()` | `_maybe_pool_topup` | 公式化池补足 |
| GP-005 | `estimated_reply_gap_ms()` | `_estimated_reply_gap_ms` | reply_timer 间隔 |
| GP-005 | `broadcast_live_overlay_item(...)` | `_broadcast_live_overlay_item` | live-overlay SSE |
| GP-005 | `current_reply_batch`（@property） | `_current_batch` | 锚点更新上下文 |

读侧 `@property` 与 W-T5-GP-004 的 `latest_displayed_*` 对称；写路径仅经 façade 方法。

---

## 历史 `app._*` 触点名册（已全部迁移）

> W-T5-GP-005 后 GP 内 **零** `app._*` 调用。下表仅供审计回溯。

| # | 原触点名 | 现 Host Façade | 原定义落点 |
|---|--------|----------------|------------|
| 1 | `_pet_barrage_mode_enabled()` | `is_pet_barrage_mode_enabled()` | `main_render_coordinator_mixin` |
| 2 | `_danmu_render_mode()` | `danmu_render_mode()` | `main_render_coordinator_mixin` |
| 3 | `_reply_scene_count` | `reply_scene_count` | `main_lifecycle_mixin` / `main_state_mixin` |
| 4 | `_reply_filler_count` | `reply_filler_count` | 同上 |
| 5 | `_reply_request_id(...)` | `reply_request_id(...)` | `main_request_context_mixin` |
| 6 | `_log_reply_pipeline(...)` | `log_reply_pipeline(...)` | `main_request_context_mixin` |
| 7 | `_record_undisplayed(...)` | `record_undisplayed(...)` | GP-003 |
| 8 | `_batch_id` | `current_batch_id` | `main.py` |
| 9 | `_enqueue_reply_batch(...)` | `enqueue_reply_batch_for_pipeline(...)` | GP-002 |
| 10 | `_notify_pet_visual_success()` | `notify_pet_visual_success()` | `main_pet_mixin` |
| 11 | `_publish_live_status()` | `publish_live_status()` | `main_render_coordinator_mixin` |
| 12 | `_queue_low_watermark` | `queue_low_watermark` | `main_lifecycle_mixin` |
| 13 | `_log_reply_pipeline_from_queued(...)` | `log_reply_pipeline_from_queued(...)` | `main_request_context_mixin` |
| 14 | `_update_stats(...)` | `update_stats_from_pipeline(...)` | GP-002 |
| 15 | `_maybe_pool_topup()` | `maybe_pool_topup()` | `main.py` |
| 16–17 | `_latest_displayed_*` | `set_latest_displayed_from_pipeline` + `@property` 读 | GP-002 / GP-004 |
| 18 | `_estimated_reply_gap_ms()` | `estimated_reply_gap_ms()` | `main_request_context_mixin` |
| 19 | `_track_duplicate_rejection(...)` | `track_duplicate_rejection(...)` | GP-003 |
| 20 | `_display_danmu_text(...)` | `display_danmu_text(...)` | GP-003 |
| 21 | `_broadcast_live_overlay_item(...)` | `broadcast_live_overlay_item(...)` | `main_render_coordinator_mixin` |
| 22 | `_maybe_duplicate_loss_topup(...)` | `maybe_duplicate_loss_topup(...)` | GP-003 |
| 23 | `_current_batch` | `current_reply_batch` | `main.py` |

---

## `app.reply_*` 触点名册（非私有，同属 Host 边界）

| # | 触点名 | R/W | 主线程 | 所有权 | GP 内操作 |
|---|--------|-----|--------|--------|-----------|
| 1 | `reply_buffer` | R+W | ✓ | `DanmuApp`（`AIReplyFIFOBuffer`） | `drop_replaceable_fallbacks` / `pop` / `peek` / `prepend_batch` / `is_empty` / `size` |
| 2 | `reply_timer` | R+W | ✓ | `DanmuApp`（`QTimer`） | `isActive` / `start` / `stop` / `setInterval` / `interval` — **仅调度，不 new** |

> boundary_guard `check_generation_pipeline_service` 禁止 GP 实例化 `QTimer`；允许通过已有 `reply_timer` 调度。

---

## 按 GP 方法分布

| GP 方法 | 主要触达 |
|---------|----------|
| `handle_reply_parsed` | façade 读/写 #1–11 + `reply_buffer` / `reply_timer` |
| `_dispatch_to_pet` | façade #13–15, #18 + `reply_buffer` / `reply_timer` |
| `_dispatch_to_floating_panel` | façade #13–22 + `reply_buffer` / `reply_timer` |
| `_dispatch_to_overlay` | façade #13–22 + `reply_buffer` / `reply_timer` |
| `_compute_anchor_update` | `current_reply_batch` |

---

## 验证命令（负责人 spot-check）

```bash
rg -n 'app\._' app/application/generation_pipeline.py
rg -n 'app\.reply_' app/application/generation_pipeline.py
```

期望：`app._*` **0 处**；`app.reply_buffer` / `app.reply_timer` 共 34 处。
