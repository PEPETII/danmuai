# Final Architecture Baseline

> Maintainer registry for Boundary Guard `check_final_architecture_baseline` (phase5-c).
> File path: `docs/final-architecture-baseline.md` (see `scripts/boundary_guard/constants.py`).
>
> Cross-references:
> - [runtime-state-map.md](runtime-state-map.md) — runtime field projection registry
> - [main-pipeline-sequence.md](main-pipeline-sequence.md) — timer / thread-pool trigger registry
> - [glossary.md](glossary.md) — shared runtime and release terminology

---

## 1. DanmuApp as the runtime host

`DanmuApp` (`main.py` + **12** mixins; see `main.py:97-110`；`DanmuAppBililiveDmMixin` 已移除) is the **single runtime host** of the visual reply pipeline,
Qt timers, worker pools, and microphone orchestration. The following must **not** be moved out
of `DanmuApp` without updating this document and the maintainer registries above:

| Asset | Role |
|-------|------|
| `reply_buffer` | AI reply FIFO (`AIReplyFIFOBuffer`); adaptive dequeue gap. **W-GENPIPELINE-EXTRACT 已完成**：消费逻辑委托 `app/application/generation_pipeline.py`，所有权仍属 DanmuApp |
| QPixmap screenshot cache | Last capture held for AI request assembly |
| `QTimer` | Screenshot tick, reply consume, mic poll, overlay refresh. **W-GENPIPELINE-EXTRACT 已完成**：`reply_timer` 实例所有权属 `app/main_lifecycle_mixin.py:155-158`；`generation_pipeline.py` 经 `app.reply_timer.start()` 驱动，不实例化 QTimer |
| `QThreadPool` usage | Visual AI, capture, meme AI (via `app/worker_pools.py` lazy singletons) |
| `_mic_service` | Microphone capture / utterance pipeline |

**Threading contract** (summary):

- Screenshot tick, reply dequeue, and Qt object mutation run on the **main thread**.
- AI HTTP runs on dedicated `QThreadPool` workers (`MAX_IN_FLIGHT=1` for visual path).
- HTTP threads must not touch Qt objects directly; use `WebConsoleBridge` signals or
  `QTimer.singleShot(0, ...)`.

---

## 2. `app/application/` boundary layer

`app/application/` is the **read/projection and Web config write** layer. It does **not**:

- own `QTimer` or `QThreadPool`
- trigger the main screenshot → AI → reply pipeline
- mutate Qt widgets or overlay state directly

**例外（W-GENPIPELINE-EXTRACT 已完成）**：`generation_pipeline.py` 承载回复消费与三路分发（pet/floating_panel/overlay），经 `app.reply_timer.start()` 驱动回复上屏节奏。该文件由 `check_generation_pipeline_service` 规则单独治理：禁止实例化 `QTimer`/`QThreadPool`/`QPixmap`，禁止调用 `_trigger_api_call`/`_on_screenshot_timer` 等主链路触发函数；允许 `reply_timer.*` 与 reply 消费必需的 DanmuApp 方法。QTimer 实例所有权属 `app/main_lifecycle_mixin.py`。

Representative modules:

| Module | Responsibility |
|--------|----------------|
| `config_service.py` | `PUT /api/config` validation and ConfigStore writes |
| `runtime_state.py` / `status_snapshot.py` | `/api/status` immutable snapshot assembly |
| `request_scheduler.py` | API throttle (`last_api_trigger_at`); no HTTP |
| `request_timing_service.py` | RTT samples; main-thread only |
| `generation_pipeline_state.py` | `screenshot_id` / `scene_generation` projection（只读 dataclass） |
| `generation_pipeline.py` | **W-GENPIPELINE-EXTRACT 已完成**：回复消费与三路分发服务（委托自 DanmuApp façade；QTimer 所有权在 `main_lifecycle_mixin`） |
| `danmu_diagnostics.py` | 最近未上屏弹幕诊断；记录粗粒度元信息，聚合为 diagnostics 可读摘要 |
| `diagnostic_snapshot.py` | 只读诊断快照（调度/timing/代际 ID 投影），供 `/api/diagnostics`，与 `/api/status` 分离 |
| `application_stats_state.py` | 应用生命周期内统计的真实所有者；从启动到关闭，内存态、不入库 |
| `stats_state.py` | 会话内统计的真实所有者；stop() 时统计并入 lifetime_stats 持久化 |
| `live_status_projection.py` | Live status 纯只读投影；当前弹幕延迟计算、live status 快照组装（无 Qt 导入） |
| `web_runtime_state.py` | Web 控制台错误条与 Overlay 布局缓存；经 `build_status_snapshot` 对外展示 |

Web API routes (`app/web_api/*`) must call **DanmuApp public façades** or application
services — not private `danmu_app._…` fields.

---

## 3. UI and process topology

Default launch (`python main.py`):

```text
DanmuApp (Qt main thread)
├─ uvicorn thread — app/web_console.py (127.0.0.1:18765)
├─ pywebview child process — app/webview_shell.py (desktop shell)
├─ web/static/ — default Web console UI
└─ DanmuOverlay — always-on transparent danmu layer
```

Deprecated entry points (`--qt-ui`, `DANMU_WEB_CONSOLE=0`, etc.) are rejected by
`app/main_launch.py:check_deprecated_launch_args()`.

---

## 4. Change control

When adding a new timer, background thread, or moving pipeline state out of `DanmuApp`:

1. Update [main-pipeline-sequence.md](main-pipeline-sequence.md) (triggers / threads).
2. Update [runtime-state-map.md](runtime-state-map.md) if runtime fields change.
3. Update this baseline if ownership boundaries shift.
4. Run `python scripts/boundary_guard.py`.
5. Run the work-order-specific pytest files in separate `-q -x` batches per `.local-ai/prompts/IDE_AGENT_RULES.md`.
6. `python scripts/run_acceptance_gates.py` may execute broader batches; Agents must not run it unless the current work order or a maintainer explicitly authorizes the resource cost.

### W-GENPIPELINE-EXTRACT（已完成，2026-06 后）

回复消费逻辑（`_consume_reply_queue` body + `_on_ai_reply` 的解析/入队/驱动段）已迁出 DanmuApp 至 `app/application/generation_pipeline.py:GenerationPipeline`。DanmuApp 保留方法签名作委托 façade（兼容测试描述符绑定）。`reply_buffer`/`reply_timer` 所有权仍属 DanmuApp（`reply_timer` 在 `main_lifecycle_mixin.py:155-158`）；scene_generation 门控、mic 分流、失败退避复位保留在 `_on_ai_reply`。新增 `check_generation_pipeline_service` 规则治理新文件。历史 Phase 背景见 `.local-ai/scratch/archive-phases/`（非当前行为）。同步更新：`main-pipeline-sequence.md`、`app/application/__init__.py`。

---

## 5. Out of scope for this document

- Product ROADMAP items not yet split into work orders
- Full Web API route map (see AGENTS.md appendix A.3.10)
- Historical `.local-ai/` archives (background only, not current behavior)
