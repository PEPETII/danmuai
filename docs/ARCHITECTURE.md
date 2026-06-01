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

## Memory modes

Process-local scene memory and bullet dedup (`app/memory/`, `app/memory_prompt_builder.py`). **Not persisted** across sessions; configured in the Web console (`memory_mode`, `memory_window`).

| `memory_mode` | Behavior |
|---------------|----------|
| `off` | No memory injection |
| `dedup_only` | Dedup hints + output constraints |
| `scene_card` | Scene state card + dedup + constraints (default-style) |
| `strong` | Same as `scene_card` with larger prompt budget and scene-switch carryover |

`memory_window` (1–20, default 10) bounds recent bullet history for dedup. Mic insert path does not inject memory. Web/API details: [WEB_CONSOLE.md](WEB_CONSOLE.md). Historical design notes: [archive/planning/MEMORY_SYSTEM_PLAN.md](archive/planning/MEMORY_SYSTEM_PLAN.md).

## Scene metadata

- Scene fingerprint helpers exist (`app/scene_fingerprint.py`); `scene_generation` is carried on requests/replies for memory and logging. Runtime scene-advance / API gate is **intentionally inactive** (`_scene_generation` stays `0`; `_scene_api_block_reason()` returns empty).
- **Normal mode reply policy** (current product):
  - No scene-generation check before enqueue or consume.
  - No hard drop of in-flight or queued replies by `screenshot_id`, `captured_at` TTL, or supersede.
  - Slow models may show replies slightly behind the live picture; continuity is preferred over strict frame sync.
  - `_is_reply_stale()` is kept as a compatibility hook and always returns not stale today.
- `freshness` config still scales screenshot interval in `_calc_auto_interval()`; it does not drop replies.
- Dormant stale-drop backoff counters (`_stale_drop_*`) and `app/live_freshness.py` helpers remain for tests/future policy.

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

Contributors: [CONTRIBUTING_ARCHITECTURE.md](CONTRIBUTING_ARCHITECTURE.md). Agents: [AGENTS.md](../AGENTS.md). Web API map: [WEB_CONSOLE.md](WEB_CONSOLE.md).
