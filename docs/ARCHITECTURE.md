# Architecture

## 总体结构

- `main.py`
  - `DanmuApp` 负责状态机、截图调度、回复消费、失败退避和统一退出
  - **Web 控制台**（`app/web_console.py` + `web/static/` + `app/webview_shell.py`）始终启动；遗留 Qt 主窗已移除
- `app/web_console.py` + `app/web_api/`
  - 默认 UI：设置、人格工坊、自定义模型、压缩预览、日志过滤；详见 [`WEB_CONSOLE.md`](WEB_CONSOLE.md)
- `app/snipper.py`
  - `ScreenCapturer` 按 `screen_index` 抓取所选显示器；`region_w/h > 0` 时按相对所选屏幕左上角的 `region_x/y/w/h` 裁剪，否则全屏
- `app/ai_client.py`
  - `AiWorker` 在 `QThreadPool` 线程中通过 `httpx` 发起同步请求，并把结果通过 Qt 信号回送主线程
- `app/reply_queue.py`
  - `AIReplyFIFOBuffer` 维护有限长度回复队列，避免内存无限增长
- `app/reply_parser.py`
  - 解析模型输出并标准化为固定 5 条弹幕
- `app/overlay.py` + `app/danmu_engine.py`
  - 负责弹幕布局、轨道调度、碰撞规避和渲染（**独立于主窗 UI 主题**）

## 默认 UI：Web 控制台

| 能力 | 状态 |
|------|------|
| 运行启停 / 配置 | ✅ |
| 节奏 / 截图 / 图像参数 | ✅ |
| 人格提示词 + 版本 | ✅ 人格工坊 |
| 自定义模型 CRUD | ✅ |
| 截图压缩预览 | ✅ API + 上传 |
| 日志多选 / 复制 | ✅ |
| 英文 Web UI | ❌ 暂缓（`language` 字段保留，Web 侧未切换） |

Web 视觉原型：[`prototype/Qwen_html_20260524_481u8vlmv.html`](../prototype/Qwen_html_20260524_481u8vlmv.html)。历史 Qt 主窗见 [archive/qt6_ui_redesign_plan.md](archive/qt6_ui_redesign_plan.md)。

## 麦克风模式（双轨并行）

已实现：Visual 截图轨与 Mic 插入轨并行；麦克风默认关；音频不落盘；日志不输出完整音频 Base64。隐私说明见 [`PRIVACY.md`](PRIVACY.md)。

```text
Visual 轨
  screenshot_timer → _rhythm_check_timer → _trigger_api_call()
  → AiRunnable（仅 JPEG）→ 5 条弹幕 → 更新 BatchTracker 节奏锚点

Mic 插入轨
  MicCaptureService → MicUtteranceDetector（RMS 100ms 轮询）
  → 说话结束 → _trigger_mic_api_call()
  → AiRunnable（JPEG + WAV）→ 5 条弹幕 prepend 插队
  → 不更新 BatchTracker；与 visual 各 1 个 in-flight 槽并行
```

| 文件 | 职责 |
|------|------|
| `app/mic_buffer.py` | PCM 环形缓冲 + `take_recent_ms` |
| `app/mic_capture.py` / `app/mic_service.py` | sounddevice 采集与 snapshot |
| `app/mic_utterance.py` | RMS 状态机（idle → speaking → silence → fire → cooldown） |
| `app/mic_encode.py` | PCM → `data:audio/wav;base64,...` |
| `app/mic_prompt.py` | `build_mic_insert_user_pt()` 插入专用 prompt |
| `main.py` | `_trigger_mic_api_call`、`_pending_request_meta`、`from_mic_insert` 入队 |
| `app/runnable.py` | 线程池内编码音频（mic 轨专用） |
| `app/ai_client.py` | `_request_doubao` 附加 `input_audio` |

| 配置键 | 默认 | 说明 |
|--------|------|------|
| `mic_mode_enabled` | `0` | Web 开关 |
| `mic_window_sec` | `5` | utterance 结束时 snapshot 窗口（秒） |
| `mic_speech_rms` | `400` | 语音 RMS 阈值（内部默认，Web 未暴露） |
| `mic_silence_ms` | `500` | 静音判定时长 |
| `mic_min_speech_ms` | `400` | 最短有效语音 |
| `mic_cooldown_sec` | `4` | 触发后冷却 |

边界：Mic 回复 `source=mic`、`prepend_batch`，不重置 `BatchTracker`；Mic 错误不计入 visual 连续失败退避；**Mic 与普通模式均不做 `stale_ttl` 硬过期**（实时模式视觉回复仍可按 `drop_stale` + `freshness` 丢弃）。不改 Overlay / 弹幕 JSON / 去重核心。豆包 Responses 需支持 `input_audio` 的模型（如 `doubao-seed-2-0-mini`）。

## 关键时序

1. `DanmuApp.start()` 重置状态并触发下一次截图调度。
2. 主线程按节奏抓取所选屏幕（可 region 裁剪），生成新的 `screenshot_id`。
3. **场景探测**（`app/scene_fingerprint.py`）：对截图计算灰度 hash；若判定场景切换则递增 `_scene_generation`（strict 模式下可清屏上旧批弹幕）。`DANMU_SCENE_DEBUG=1` 可输出探测日志。
4. `AiRunnable.run()` 在线程池里压缩截图，再调用 `AiWorker._request()`。
5. `AiWorker` 返回后触发 `finished` 或 `error` 信号。
6. `DanmuApp._on_ai_reply()` 先做过期判定（`screenshot_id`、`scene_generation`、`app/live_freshness.py` 新鲜度 TTL），再把回复标准化为 5 条，放入有限队列。
7. `DanmuApp._consume_reply_queue()` 按右侧密度自适应节奏逐条送入 `DanmuEngine`。

## 稳定性约束

- 每次截图都有单调递增的 `screenshot_id`
- **场景代际**（`scene_generation`）：`fingerprint_from_pixmap` / `is_scene_change` 推进代际；回复携带的代际低于当前值则丢弃（`stale_scene` / `stale_scene_in_flight`）
- **新鲜度**（`app/live_freshness.py`）：按 `drop_stale` 档位丢弃超出 TTL 的回复（loose 12s / medium 8s / strict 5s）；截图退避与本地兜底批次亦在此模块
- `AiWorker` 使用请求超时和连续失败退避，避免无限挂起
- `quit()` 会先 `stop()`、标记停止、关闭 HTTP 客户端并等待线程池短暂收尾

## 发布边界

- 支持多屏索引选择；默认截图为所选屏全屏
- `region_*` 使用相对所选屏幕左上角的坐标；宽高大于 0 时 `ScreenCapturer` 会裁剪截图
- 历史记录默认只保存弹幕文本，不保存截图原图
- 控制台 UI 为 Web（`web/static/`），弹幕层为 Qt Overlay
