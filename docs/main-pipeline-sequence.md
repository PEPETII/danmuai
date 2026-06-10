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
       -> [if visual in-flight: return; debug or inflight_watchdog warn if >= 45s;
           force recover via _try_recover_stale_visual_inflight if >= 48s (S-011)]
       -> main.py::_capture_screenshot()
            -> app/snipper.py::ScreenCapturer.grab()
            -> [invalid pixmap: return, no id++]
            -> update _latest_screenshot / _latest_screenshot_id / time
       -> main.py::_trigger_api_call(source="normal_interval")
            -> RequestScheduler.block_reason / record_trigger_time
            -> ai_worker_pool().start(AiRunnable)
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
| `_pool_topup_timer` | 500 ms | `_maybe_pool_topup` | Custom formula pool top-up |
| `_meme_collect_timer` | `meme_barrage_collect_interval_sec` | `_meme_collect_tick` | Meme barrage fetch / local ingest (if enabled) |
| `_meme_display_timer` | `meme_barrage_display_interval_sec` | `_meme_display_tick` | Meme barrage dequeue to `DanmuEngine` (independent of `reply_buffer`) |
| `_mic_poll_timer` | 600 ms single-shot; 250 ms initial phase (`MIC_POLL_PHASE_MS`); rescheduled in `_schedule_next_mic_poll` | `_poll_mic_utterance` | Mic RMS utterance endpoint (if enabled; `MIC_POLL_MS`) |
| `_live_status_timer` | 500 ms | `_publish_live_status` | Web status push |
| `_lifetime_flush_timer` | (config) | lifetime flush | Stats persistence |
| `QThreadPool` | on demand | `AiRunnable.run` / `_MicProbeRunnable.run` / `MemeFetchRunnable.run` / `MemeAiSelectRunnable.run` | AI HTTP + meme barrage remote fetch / AI select |

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

See also [AGENTS.md](../AGENTS.md) and `DANMU_API_SCHEDULE_DEBUG`.

## Web status side path (unchanged pipeline)

- `WebConsoleBridge.refresh_status()` → `DanmuApp.build_status_snapshot()` → `StatusSnapshotBuilder`.
- Does not participate in capture → overlay data path.

## Bootstrap / UI shell (outside visual pipeline)

| Entry | Thread / process | Role |
|-------|------------------|------|
| `app/web_console.py::WebConsoleServer.start()` | `threading.Thread` (`DanmuWebConsole`) | uvicorn FastAPI on `127.0.0.1:18765` |
| `attach_web_console` `web_status_timer` | Qt `QTimer` 500 ms on main thread | Status publish; S-006 capped uvicorn auto-restart (`maybe_restart_web_console`, max 3, backoff 2/5/10 s) |
| Visual/mic `AiRunnable` | `app/worker_pools.ai_worker_pool()` (max 2) | S-014: isolated from global pool meme/TTS/probe workers |
| `app/webview_shell.py::WebViewShell.begin_start()` | `multiprocessing.Process` (`DanmuWebView`, spawn) | pywebview desktop shell (child owns `webview.start()`); up to 3 spawn retries on early child exit / `Process.start()` OSError before handshake failure |
| `app/webview_shell.py::_nav_poll_loop` | `threading.Thread` (`DanmuWebViewNav`, daemon, child process) | Cross-process `nav_queue` → `window.load_url` |
| `attach_webview_shell` handshake | Qt `QTimer` 50 ms poll on main thread | Non-blocking `ready_queue` drain; does not block capture pipeline |
| `main.py::_schedule_webview_attach` / `_retry_webview_attach` | Qt `QTimer` (800/400 ms initial delay, 1200 ms attach retry) | After deferred handshake failure: destroy shell and re-attach (max 2 schedule attempts) before single browser fallback |

Startup timing: `app/startup_trace.py` → `%APPDATA%/DanmuAI/startup.log` (frozen).

Shutdown note: `DanmuApp.quit()` waits `QThreadPool.globalInstance().waitForDone(2000)` before `ai_worker.close()`, so in-flight AI workers do not touch closed `httpx` clients during teardown.

## Test modules (regression only)

Split pytest modules under `tests/test_web_*.py`, `tests/test_capture_flow.py`, `tests/test_ai_pipeline.py`, and `tests/test_reply_enqueue.py` may reference `threading.Thread`, `QThreadPool`, or `QThread` to simulate production scheduling (Web console startup, `invoke_on_main` contention, `DanmuApp.quit()` pool drain). They do **not** register new runtime schedulers.

## Non-goals

- Full `_on_ai_error()` backoff branches.
- Web route registration details.
