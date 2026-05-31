# Main Pipeline Sequence

> Human-readable overview: [MAIN_PIPELINE.md](MAIN_PIPELINE.md).  
> Boundary Guard requires this file to change when adding `QTimer` / `QThreadPool` / new thread entry points.

## Scope

Visual path only (normal mode): `截图 → AI 请求 → 回复解析 → 回复队列 → DanmuEngine → Overlay → HistoryWriter`

Mic insert reuses `_on_ai_reply()` / `_enqueue_reply_batch()`; not expanded here.

## Sequence diagram

```text
main.py::DanmuApp.start()
  -> screenshot_timer.start(normal_recognition_interval_ms)
  -> _on_normal_capture_tick()                         [initial tick]

main.py::screenshot_timer.timeout
  -> main.py::_on_screenshot_timer()
  -> main.py::_on_normal_capture_tick()
       -> [if visual in-flight: return; debug or inflight_watchdog if >= 45s]
       -> main.py::_capture_screenshot()
            -> app/snipper.py::ScreenCapturer.grab()
            -> [invalid pixmap: return, no id++]
            -> update _latest_screenshot / _latest_screenshot_id / time
            -> _collect_activity_observation()
       -> main.py::_trigger_api_call(source="normal_interval")
            -> RequestScheduler.block_reason / record_trigger_time
            -> QThreadPool.globalInstance().start(AiRunnable)
                 -> compress_screenshot -> app/ai_client.py::AiWorker._request()
        -> main.py::_on_ai_reply()
           -> app/reply_parser.py::parse_ai_reply_with_memory()
           -> app/reply_parser.py::normalize_reply_batch()
           -> main.py::_enqueue_reply_batch()
              -> app/reply_queue.py::AIReplyFIFOBuffer.extend()
           -> main.py::_consume_reply_queue()  [via reply_timer or direct]
              -> app/danmu_engine.py::DanmuEngine.add_text()
              -> history_writer.enqueue()

app/overlay.py::DanmuOverlay.start_render_loop()
  -> _tick() -> DanmuEngine.update() -> paintEvent()
```

## Timers and thread entry points

| Object | Interval / trigger | Handler | Role |
|--------|-------------------|---------|------|
| `screenshot_timer` | `normal_recognition_interval_ms` | `_on_screenshot_timer` | Normal-mode capture + API trigger |
| `reply_timer` | adaptive (single-shot) | `_consume_reply_queue` | Dequeue to engine |
| `_pool_topup_timer` | 500 ms | `_maybe_pool_topup` | Formula pool top-up |
| `_mic_poll_timer` | 400 ms | `_poll_mic_utterance` | Mic RMS endpoint (if enabled) |
| `_live_status_timer` | 500 ms | `_publish_live_status` | Web status push |
| `_lifetime_flush_timer` | (config) | lifetime flush | Stats persistence |
| `QThreadPool` | on demand | `AiRunnable.run` | AI HTTP (visual + mic) |

Removed from product: `_rhythm_check_timer`, `_check_rhythm_trigger()`, realtime display mode branch, inventory prefetch (`_schedule_next_screenshot` / `_should_request_new_batch`, W-002).

## Stage table

| Stage | Entry | Downstream | Key state |
|-------|--------|------------|-----------|
| Start | `DanmuApp.start()` | timers, overlay, `_on_normal_capture_tick` | session reset |
| Capture tick | `_on_normal_capture_tick()` | `_capture_screenshot`, `_trigger_api_call` | skips if in-flight |
| Capture | `_capture_screenshot()` | `ScreenCapturer.grab` | `_latest_screenshot_id++` only on valid frame |
| Trigger | `_trigger_api_call()` | `AiRunnable` | meta, timing mark_started, `ai_in_flight` |
| Worker | `AiRunnable.run()` | `AiWorker._request` | compressed image URI |
| Reply | `_on_ai_reply()` | parse, enqueue | tokens, memory |
| Enqueue | `_enqueue_reply_batch()` | `reply_buffer.extend` | `QueuedReply` list |
| Consume | `_consume_reply_queue()` | `engine.add_text`, history | adaptive delay |
| Render | `DanmuOverlay._tick` | `engine.update`, paint | tracks |

## Key fields

- `screenshot_id`: set in `_capture_screenshot()` on valid frames only; carried on requests and queue items.
- `scene_generation`: reset on start/stop; carried on requests (memory); not advanced by live scene-change loop today.
- `request_round`: `screenshot_round` for visual; negative for mic.
- `request_timing_id`: `f"{request_round}:{screenshot_id}:{scene_generation}"` for `_pending_request_meta` and `RequestTimingService`.

## Observability (structured log `reason=`)

| reason | When |
|--------|------|
| `invalid_pixmap` | Capture rejected (null / zero size) |
| `inflight_watchdog` | Visual in-flight ≥ `VISUAL_INFLIGHT_WARN_SEC` (45s) |
| `request_meta_missing` | Reply/error without pending meta |
| `timing_not_started` | RTT consume with no matching mark_started |
| `empty_parse` | AI text parsed to zero danmu items |

See also [AGENTS.md](../AGENTS.md) and `DANMU_SCENE_DEBUG` / `DANMU_API_SCHEDULE_DEBUG`.

## Web status side path (unchanged pipeline)

- `WebConsoleBridge.refresh_status()` → `DanmuApp.build_status_snapshot()` → `StatusSnapshotBuilder`.
- Does not participate in capture → overlay data path.

## Bootstrap / UI shell (outside visual pipeline)

| Entry | Thread / process | Role |
|-------|------------------|------|
| `app/web_console.py::WebConsoleServer.start()` | `threading.Thread` (`DanmuWebConsole`) | uvicorn FastAPI on `127.0.0.1:18765` |
| `app/webview_shell.py::WebViewShell.begin_start()` | `multiprocessing.Process` (`DanmuWebView`, spawn) | pywebview desktop shell (child owns `webview.start()`) |
| `app/webview_shell.py::_nav_poll_loop` | `threading.Thread` (`DanmuWebViewNav`, daemon, child process) | Cross-process `nav_queue` → `window.load_url` |
| `attach_webview_shell` handshake | Qt `QTimer` 50 ms poll on main thread | Non-blocking `ready_queue` drain; does not block capture pipeline |

Startup timing: `app/startup_trace.py` → `%APPDATA%/DanmuAI/startup.log` (frozen).

Shutdown note: `DanmuApp.quit()` waits `QThreadPool.globalInstance().waitForDone(2000)` before `ai_worker.close()`, so in-flight AI workers do not touch closed `httpx` clients during teardown.

## Non-goals

- Full `_on_ai_error()` backoff branches.
- Web route registration details.
