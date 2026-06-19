# Main Pipeline

> 本文只描述当前**视觉主链路**。  
> 机器校验用步骤表见 [main-pipeline-sequence.md](main-pipeline-sequence.md)。

---

## 1. 范围

当前唯一视觉路径：

`截图 -> AI 请求 -> 回复解析 -> 回复队列 -> DanmuEngine -> Overlay -> HistoryWriter`

不展开：

- Web 控制台启动
- pywebview 壳启动
- 读弹幕 TTS
- 麦克风插入细节（它复用 `_on_ai_reply()` / `_enqueue_reply_batch()`）

---

## 2. 当前调用链

```text
DanmuApp.start()
  -> screenshot_timer.start()
  -> _on_normal_capture_tick()            [立即首 tick]

screenshot_timer.timeout
  -> _on_screenshot_timer()
  -> _on_normal_capture_tick()
       -> 若视觉请求在途：返回
       -> _schedule_capture()
            -> app/snipper.py::build_capture_plan()     [主线程，仅几何]
            -> capture_worker_pool().start(CaptureRunnable)
                 -> app/snipper.py::execute_capture()   [worker，grabWindow]
                 -> CaptureCoordinator.completed → _on_capture_completed()
                      -> _apply_capture_result()
                      -> _trigger_api_call(source="normal_interval")
            -> RequestScheduler.block_reason()
            -> RequestScheduler.record_trigger_time()
            -> RequestTimingService.mark_started()
            -> ai_worker_pool().start(AiRunnable)
                 -> AiWorker._request()

AiWorker.finished
  -> _on_ai_reply()
       -> parse_ai_reply_payload()
       -> normalize_reply_batch()
       -> _enqueue_reply_batch()
       -> 立即消费或调度 reply_timer

reply_timer.timeout
  -> _consume_reply_queue()
       -> reply_buffer.pop()
       -> DanmuEngine.add_text()
       -> HistoryWriter.enqueue()
       -> Overlay render loop
```

---

## 3. 冻结入口

以下 3 个入口仍是当前主链路的固定锚点：

- `_trigger_api_call`
- `_on_ai_reply`
- `_consume_reply_queue`

可以在这些方法周边拆辅助逻辑，但不应：

- 把这 3 个方法迁出 `main.py`
- 绕开它们增加第二条视觉路径
- 在 Web/API 层直接驱动 `DanmuEngine` 或 `Overlay`

---

## 4. 每一段负责什么

| 阶段 | 当前入口 | 说明 |
|------|----------|------|
| 启动 | `DanmuApp.start()` | 重置会话状态，启动截图与队列节奏 |
| 截图 tick | `_on_normal_capture_tick()` | in-flight 闸门、调度异步截图 |
| 截图计划 | `_schedule_capture()` | 主线程 `build_capture_plan`，投递 `CaptureRunnable` |
| 截图执行 | `CaptureRunnable.run()` → `execute_capture()` | worker 线程 `grabWindow`；结果经 `CaptureCoordinator.completed` 回主线程 |
| 截图落盘 | `_apply_capture_result()` | 仅有效 `QPixmap` 递增 `screenshot_id` |
| 触发 | `_trigger_api_call()` | 注册 request meta、RTT 起点、投递 `AiRunnable` |
| 回复 | `_on_ai_reply()` | 解析、memory 更新、入队 |
| 入队 | `_enqueue_reply_batch()` | 生成 `QueuedReply` 批次并更新库存 |
| 出队 | `_consume_reply_queue()` | 上屏、记历史、调整下一次消费间隔 |

- W-RACE-001（bug-03 缺陷 3）：`_on_ai_reply` 入口代际校验；`meta` 为空（已被 `stop()` 清空，_pop_request_meta 返回空 dict）时打 `stale_reply_dropped` warning 并直接 return，避免陈旧 reply 上屏或消耗新会话 in-flight 槽位。`_pop_request_meta` 既有 `request_meta_missing: reason=pop_before_reply` warning 保留作可观测性。

---

## 5. 关键标识符

### `screenshot_id`

- 只在 `_apply_capture_result()` 成功得到有效截图后递增
- 无效截图必须记录 `reason=invalid_pixmap`
- 无效截图不会触发 API

### `scene_generation`

- 当前运行期仅作为请求 / memory 兼容键
- `start()` / `stop()` 时重置
- 当前不会通过截图 hash 自动推进

### `request_round`

- 视觉链路：`screenshot_round`
- 麦克风插入：负数序列号

### `request_timing_id`

- 复合键：`{request_round}:{screenshot_id}:{scene_generation}`
- 同时用于：
  - `_pending_request_meta`
  - `RequestTimingService.mark_started()`
  - `RequestTimingService.consume_timing()`

---

## 6. 调度与 RTT

### `RequestScheduler`

负责：

- 最小 API 间隔
- 视觉请求 in-flight 闸门
- `last_api_trigger_at`

### `RequestTimingService`

负责：

- `mark_started`
- `consume_timing`
- `request_started_at_by_id`
- `rtt_history`

### 边界要求

- 不允许绕过 `RequestScheduler`
- 不允许再引入并行 throttle 字段
- 不允许在其它层复制 RTT 归属

---

## 7. 当前队列节奏

- `reply_buffer` 是唯一回复库存
- `reply_timer` 是唯一逐条出队计时器
- `_estimated_reply_gap_ms()` 按同屏密度和右侧可见数量调整下次延迟
- `_pool_topup_timer` 独立负责公式化弹幕池补足，不等于第二条 AI 主流程

---

## 8. 结构化日志锚点

常见 `reason=`：

| `reason` | 含义 |
|----------|------|
| `invalid_pixmap` | 截图无效，不触发 API |
| `inflight_watchdog` | 视觉请求在途时间 ≥45s，仅告警 |
| `inflight_watchdog_recover` | 视觉请求在途 ≥48s 且无回调，主线程强制释放 in-flight 并清理 meta/timing |
| `request_wall_clock` | `AiRunnable` 墙上时钟 45s：流式 hung 时 `error` 回调释放 in-flight（S-012） |
| `request_meta_missing` | 回复回来时缺少 request meta |
| `stale_reply_dropped` | 陈旧 AiRunnable reply（meta 已被 stop 清空），丢弃 |
| `timing_not_started` | RTT 消费时找不到起点 |
| `empty_parse` | AI 有回复，但解析后无弹幕 |

---

## 9. 明确不属于当前主链路的东西

- pywebview attach 重试
- `/api/status` / `/api/diagnostics` 只读快照
- 公告、反馈
- 版本更新弹窗
- 读弹幕 TTS

它们可能依赖运行态，但不应改变 `截图 -> AI -> 回复解析 -> 入队 -> 上屏` 的顺序。

---

## 10. 修改这条链路前先问自己

1. 是否会改变三个冻结入口的位置或职责？
2. 是否绕过了 `RequestScheduler` / `RequestTimingService`？
3. 是否引入了新的 `QTimer` / 线程 / 池任务入口？
4. 是否让 Web 层得以直接碰触主链路私有状态？

只要其中一项回答是“会”，就应先停下来补边界评估。

---

## 11. 截图线程边界（W-PERF-HIGH-001）

| 步骤 | 线程 | 说明 |
|------|------|------|
| `build_capture_plan` | Qt 主线程 | 读取 `QApplication.screens()` 与区域配置，不抓像素 |
| `execute_capture` / `grabWindow` | `capture_worker_pool`（max 1） | 像素抓取；禁止触碰 `DanmuApp` / QWidget |
| `_apply_capture_result` | Qt 主线程 | 校验 pixmap、更新 `_latest_screenshot*`、失败计数 |
| `_trigger_api_call` | Qt 主线程 | 调度与 RTT 仍经 `RequestScheduler` / `RequestTimingService` |

失败回传：`CaptureRunnable` emit `None` 或无效 pixmap → `_on_capture_completed` → `_apply_capture_result` 记 `invalid_pixmap` / `capture_failed`，**不**触发 API。`stop()` / `quit()` 后迟到的 `completed` 信号在主线程槽内丢弃（`!engine.running` 或 `ai_worker._stopping`）。

`quit()` 在 `ai_worker.close()` 前对 `capture_worker_pool().waitForDone(2000)` 与全局池同样 drain。

---
