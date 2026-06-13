# Architecture

DanmuAI is a desktop overlay danmaku assistant: it captures the screen on a fixed interval, calls a vision-language model, parses short comments, and renders them on a transparent Qt overlay. Configuration and control live in a local Web console (pywebview shell); the overlay and system tray always run with the app.

## Runtime layout

```text
python main.py
├─ DanmuApp (main.py)           bootstrap, lifecycle, screenshot/AI orchestration
├─ uvicorn thread               app/web_console.py — FastAPI on 127.0.0.1:18765
├─ pywebview thread             app/webview_shell.py — desktop shell
├─ web/static/                  default control UI (index.html, app.js, warm-tokens.css)
├─ app/web_api/                 personas, custom models, danmu pool, diagnostics routes
└─ DanmuOverlay (app/overlay.py) + DanmuEngine — always-on transparent danmaku layer
```

**UI facts**

- Default: Web console + pywebview + Qt overlay/tray. Legacy Qt main window and `--qt-ui` / `--legacy-ui` are removed (`sys.exit(2)`).
- New product features belong in `web/static/` and `app/web_api/` (`routes.py` registration).
- Overlay is independent of which control UI is used.

## Core modules

| Module | Role |
|--------|------|
| [main.py](../main.py) | `DanmuApp`: timers, capture, API trigger, reply queue consumption, mic insert |
| [app/web_console.py](../app/web_console.py) | HTTP/WebSocket bridge; config patches via signals to main thread |
| [app/web_api/](../app/web_api/) | REST routes; must use public `DanmuApp` facades |
| [app/ai_client.py](../app/ai_client.py) | Doubao `/responses` stream + OpenAI-compatible SSE; thinking disabled |
| [app/reply_parser.py](../app/reply_parser.py) | JSON parse + batch normalize (`normal_reply_count`) |
| [app/reply_queue.py](../app/reply_queue.py) | `AIReplyFIFOBuffer`, adaptive dequeue delay |
| [app/danmu_engine.py](../app/danmu_engine.py) | Tracks, dedup, collision-aware placement |
| [app/overlay.py](../app/overlay.py) | Transparent topmost render loop (~60 fps when animating) |
| [app/floating_panel_engine.py](../app/floating_panel_engine.py) + [app/floating_panel_overlay.py](../app/floating_panel_overlay.py) | V2/V3 侧边悬浮窗：连续上滚、竖向 min_gap 准入、独立 reply 节奏、右侧透明窄窗 |
| [app/danmu_pool.py](../app/danmu_pool.py) | Built-in/custom formula pool for on-screen top-up |
| [app/config_store.py](../app/config_store.py) | SQLite config, Fernet-encrypted keys (`%APPDATA%/DanmuAI`) |
| [app/application/](../app/application/) | Read-only projections, status/diagnostics snapshots, scheduling/timing services |

### `app/application/` (state boundaries)

| Component | Responsibility |
|-----------|----------------|
| `runtime_state.py` | Read-only runtime projection (`RuntimeState.from_app`) |
| `status_snapshot.py` | `/api/status` via `StatusSnapshotBuilder` |
| `diagnostic_snapshot.py` | `/api/diagnostics` (read-only, separate from status) |
| `generation_pipeline_state.py` | Read-only projection of generation-related fields |
| `request_scheduler.py` | API schedule gates; owns `last_api_trigger_at` |
| `request_timing_service.py` | RTT samples, `request_started_at_by_id`, cooldown inputs |
| `stats_state.py` | Session counters (danmu count, tokens, runtime) |
| `web_runtime_state.py` | Web error banner + display cache |
| `config_service.py` | Web config apply path |

`DanmuApp` remains the **bootstrap / lifecycle owner** and a thin **façade** for Web and tests. Do not move queue, screenshot `QPixmap`, or in-flight request ownership out of `main.py` without an explicit architecture change (see [CONTRIBUTING_ARCHITECTURE.md](CONTRIBUTING_ARCHITECTURE.md)).

## Visual main pipeline (normal mode)

Only **normal mode** is active: fixed screenshot interval (`normal_recognition_interval_ms`) and one visual API call per successful capture when no visual request is in flight. Legacy `danmu_display_mode=realtime` is normalized to `normal` on load.

```text
screenshot_timer
  → _on_screenshot_timer()
  → _on_normal_capture_tick()
  → _capture_screenshot()
  → _trigger_api_call()
  → AiRunnable (QThreadPool) → AiWorker
  → _on_ai_reply()
  → reply_parser → _enqueue_reply_batch()
  → _consume_reply_queue()
  → DanmuEngine.add_text()
  → DanmuOverlay paint loop
```

Details: [MAIN_PIPELINE.md](MAIN_PIPELINE.md). Machine-checked sequence table: [main-pipeline-sequence.md](main-pipeline-sequence.md).

**Mic insert** (optional): parallel path via `MicService` → `_trigger_mic_api_call()` → same `_on_ai_reply()` / queue, with `prepend_batch` and separate in-flight slot. Does not reset visual batch pacing.

## Threading

- Screenshot timers run on the **Qt main thread**.
- AI HTTP runs in **QThreadPool** (`MAX_IN_FLIGHT=1` for visual).
- HTTP handlers must not touch Qt objects directly; use `WebConsoleBridge` signals or `QTimer.singleShot(0, ...)`.

## Scene metadata

- **No screenshot hash / scene-change gate**: the product does not compare consecutive frames to skip API calls. `scene_generation` is still carried on requests/replies for logging and request identity; it stays `0` for the whole run.
- **Normal mode reply policy** (current product):
  - No hard drop of in-flight or queued replies by `screenshot_id`, `captured_at` TTL, scene generation, or supersede.
  - Slow models may show replies slightly behind the live picture; continuity is preferred over strict frame sync.
- `app/live_freshness.py` provides slow-model detection and local fallback batches only.

## Stability

- Monotonic `screenshot_id` per **valid** accepted frame (`isNull()` / zero-size captures do not increment the id).
- `RequestTimingService` keys RTT samples by composite `{request_round}:{screenshot_id}:{scene_generation}` so mic and visual requests on the same frame do not overwrite each other.
- Consecutive API failures → backoff pause; 401/403/402 pause immediately.
- `quit()`: `stop()` → release hotkeys/tray → close `AiWorker` → `waitForDone` thread pool → flush history/config.

## Where to change things

| Goal | Start here |
|------|------------|
| Web UI / new API | `web/static/`, `app/web_api/routes.py` |
| Overlay / tracks | `app/overlay.py`, `app/danmu_engine.py` (high risk) |
| Capture / AI orchestration | `main.py` (high risk; read pipeline docs first) |
| Models / providers | `app/model_providers.py`, `app/model_catalog.py` |
| Floating panel V2 | `app/floating_panel_engine.py` + `app/floating_panel_overlay.py` (W-FP-V2-001) |

## Floating panel mode V2 (W-FP-V2-001 / W-FP-V2-002)

`danmu_render_mode`（默认 `scrolling`）互斥控制弹幕渲染：
- `scrolling`：横向 `DanmuOverlay` + `DanmuEngine`（向后兼容）。
- `floating_panel`：右侧窄窗 `FloatingPanelOverlay` + `FloatingPanelEngine`（底部进入、持续上滚、越顶移除）；**不显示**横向 Overlay。W-FP-V3-003：`can_accept_new_item` 按末条底边 + `min_gap=max(12, height*0.25)` 准入；`_consume_reply_queue` spacing 阻塞时 peek 不 pop；`_estimated_reply_gap_ms` 不复用横向 `visibility_counts`。

遗留 W-FP `display_mode`（`overlay` / `floating_panel` / `both`）在 `ConfigStore.__init__` 由 `migrate_legacy_display_mode_to_render_mode()` 写回 `danmu_render_mode` 后不再读取；`both` 映射为 `scrolling`。

显隐与生命周期：
- `_sync_overlay_visibility()` / `_sync_floating_panel_visibility()` 按 `danmu_render_mode` 互斥显隐。
- `stop()` → `floating_panel_overlay.reset_session_state()` + `floating_panel_engine.stop()`。
- `/api/status`：`danmu_render_mode`；`display_count` 在 `floating_panel` 模式下为 `floating_panel_active_count`（**无** `display_mode` 字段）。

数据流：
- `_consume_reply_queue` →（floating_panel 且底部空间不足时 defer，条目留队）→ `_display_danmu_text()` 路由器 → `DanmuEngine.add_text` **或** `FloatingPanelOverlay.add_danmu_text`（互斥，无旁路 feed）。

Contributors: [CONTRIBUTING_ARCHITECTURE.md](CONTRIBUTING_ARCHITECTURE.md). Web API map: [WEB_CONSOLE.md](WEB_CONSOLE.md).
