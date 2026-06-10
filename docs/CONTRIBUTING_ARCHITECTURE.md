# Contributing Architecture

> 适用范围：所有会触达 `main.py`、`app/main_*mixin.py`、`app/web_api/`、`app/application/`、`web/static/` 的改动。

---

## 1. 改动前先确认

先读：

1. [ARCHITECTURE.md](ARCHITECTURE.md)
2. [MAIN_PIPELINE.md](MAIN_PIPELINE.md)
3. [RUNTIME_STATE.md](RUNTIME_STATE.md)
4. [BOUNDARY_GUARD.md](BOUNDARY_GUARD.md)

如果会改调度、RTT 或运行态归属，再读：

- [final-architecture-baseline.md](final-architecture-baseline.md)
- [main-pipeline-sequence.md](main-pipeline-sequence.md)
- [runtime-state-map.md](runtime-state-map.md)

---

## 2. 代码应该落在哪里

| 需求 | 优先位置 |
|------|----------|
| 控制台 UI、前端页面、文案、交互 | `web/static/` |
| Web API / 路由注册 | `app/web_api/` |
| 主链路编排、截图、AI、回复队列 | `main.py`、`app/main_*mixin.py` |
| Overlay / 轨道 / 渲染 | `app/overlay.py`、`app/danmu_engine.py` |
| 调度 / 状态投影 / 只读快照 | `app/application/` |
| 麦克风 / 读弹幕 / 音频链路 | `app/mic_*`、`app/danmu_read_service.py` |

---

## 3. Web / API 边界

### 禁止

在 `app/web_console.py`、`app/web_api/*` 中禁止新增：

- `danmu_app._*`
- `app._*`
- `ai_worker._*`
- 直接读取 `RequestScheduler` / `RequestTimingService` 的私有实现字段
- 路由内手拼 `/api/status` 返回 dict
- HTTP 线程直接改 Qt 对象

### 允许

Web 层应通过 `DanmuApp` 公开 façade：

- `build_status_snapshot()`
- `build_diagnostic_snapshot()`
- `build_live_status_snapshot()`
- `apply_web_config_payload()`
- `get_request_scheduler()`
- `get_request_timing_service()`
- `api_schedule_block_reason()`
- `start()` / `stop()` / `toggle()`
- `probe_api_connection()`
- `request_capture_region_selection()` / `reset_capture_region()` / `get_capture_region_status()`

如果缺 façade，应先在 `DanmuApp` 上补 façade，再给 Web 用。

---

## 4. 主链路边界

当前唯一视觉主链路：

```text
_on_screenshot_timer
-> _on_normal_capture_tick
-> _capture_screenshot
-> _trigger_api_call
-> _on_ai_reply
-> _enqueue_reply_batch
-> _consume_reply_queue
-> DanmuEngine.add_text
-> Overlay
```

### 冻结要求

以下 3 个入口继续留在 `main.py`：

- `_trigger_api_call`
- `_on_ai_reply`
- `_consume_reply_queue`

允许把辅助逻辑拆到 mixin，但不允许：

- 绕开这 3 个入口再造平行流程
- 改变截图到上屏的调用顺序
- 把 `DanmuEngine` / `Overlay` 重写成另一套耦合方式

---

## 5. 运行态归属

### 继续留在 `DanmuApp`

- `QTimer`
- `QThreadPool` 的使用入口
- `QPixmap` 最新截图缓存
- `reply_buffer`
- `ai_in_flight`
- `mic_in_flight`
- `_pending_request_meta`
- `_scene_generation`

### 服务对象所有权

| 状态 | 所有权 |
|------|--------|
| `last_api_trigger_at` | `RequestScheduler` |
| `request_started_at_by_id`、`rtt_history` | `RequestTimingService` |
| `danmu_count`、token 总数、会话开始时间 | `StatsState` |
| Web 错误文案、layout/lines cache | `WebRuntimeState` |

禁止在 `DanmuApp` 重新引入这些已迁移字段的平行副本。

---

## 6. 线程 / 定时器规则

### 新增以下内容时，必须同步文档

- `QTimer(...)`
- `QTimer.singleShot(...)`
- `QThreadPool.globalInstance().start(...)`
- `threading.Thread(...)`
- `asyncio.create_task(...)`

同步文件：

- [main-pipeline-sequence.md](main-pipeline-sequence.md)

### 额外要求

- 不要新建“第二套调度器”
- 不要在非主线程写 Qt 对象
- 不要把 pywebview / uvicorn / queue / overlay 的生命周期关系改成隐式

---

## 7. `DanmuEngine` / `Overlay` 边界

- `DanmuEngine` 仍可受控依赖 `Overlay` 提供的测量与渲染事实
- 不要在 `DanmuEngine` 中继续扩散 Web/API 依赖
- 不要把前端需求顺手塞进 `DanmuEngine`
- 不要把 Overlay 改成由 Web 直接驱动

---

## 8. 存储边界

`config.conn` 仍只允许出现在白名单模块中。新增扩散前，先评估是否应复用已有 `ConfigStore` 能力。

高风险存储改动包括：

- schema 变更
- `config.db` 新表 / 新索引
- 批量迁移
- 新的长期持久化文件

这类改动必须带迁移说明与文档更新。

- **写入临界区**（W-CONC-001）：`ConfigStore.with_write_lock()` 上下文管理器封装 `self._write_lock`，仅供同包模块（`HistoryWriter` 等）在批量 SQLite 写入时使用，禁止 HTTP 线程、Web 路由、其他包模块直接调用。普通 SET 仍走 `ConfigStore.set` / `set_batch`。

---

## 9. 提交前检查

本地 **禁止** 全量 `python -m pytest tests/`（700+ 用例、内存压力大）。按改动范围分批，每批 `-q -x`；全量留给 CI。详见 `.local-ai/prompts/IDE_AGENT_RULES.md` §10。

```bash
python scripts/boundary_guard.py
python -m pytest tests/test_request_scheduling.py tests/test_boundary_guard_web_rules.py tests/test_boundary_guard_runtime_rules.py tests/test_boundary_guard_request_rules.py tests/test_boundary_guard_diagnostics_rules.py -q -x
```

另按本次改动追加相关 `tests/test_*.py` 批次（仍须 `-q -x`，禁止无参全量）。

同时人工确认：

- 没有新增 `app/web_api/*` 对私有字段的访问
- 没有新增未登记运行态字段
- 没有引入新的线程 / 定时器却忘记更新 `main-pipeline-sequence.md`
- 没有把状态展示逻辑从 snapshot builder 拉回路由层

---

## 10. 一句话约束

**优先拆辅助，不重写主链路；优先补 façade，不让 Web 读私有；优先维护所有权，不扩散运行态。**
