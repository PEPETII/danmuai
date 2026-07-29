# Runtime State Map — 运行时状态字段业务含义映射

> 本文档由 `boundary_guard` 的 `check_runtime_state_doc` 规则维护。
> 增删 `DanmuApp.__init__` 中的运行态字段时必须同步更新本表。
> 文件路径：`docs/runtime-state-map.md`（由 `scripts/boundary_guard/constants.py` 中的 `RUNTIME_STATE_DOC` 定义）
> 共享术语见 [glossary.md](glossary.md)。

---

## RuntimeState 字段（`app/application/runtime_state.py`）

| 字段 | 类型 | 业务含义 |
|------|------|----------|
| `running` | `bool` | 应用主循环是否处于运行状态（engine.running） |
| `danmu_count` | `int` | 累计弹幕计数（来自 StatsState） |
| `queue_count` | `int` | 回复队列当前待消费条数（reply_buffer.size()） |
| `display_count` | `int` | 当前实际显示的弹幕数量（Overlay 或浮动面板） |
| `danmu_render_mode` | `str` | 渲染模式：`fullscreen` / `floating_panel`（来自 config） |
| `overlay_display_count` | `int` | Overlay 轨道当前显示的弹幕数 |
| `floating_panel_active_count` | `int` | 浮动面板当前活跃面板数量 |
| `floating_panel_render_active` | `bool` | 浮动面板渲染层是否激活 |
| `input_tokens` | `int` | 累计输入 Token 数（StatsState._total_input_tokens） |
| `output_tokens` | `int` | 累计输出 Token 数（StatsState._total_output_tokens） |
| `runtime_sec` | `float` | 本次运行时长（秒），monotonic clock 差值 |
| `app_session_danmu_count` | `int` | 应用级累计弹幕计数（来自 ApplicationStatsState） |
| `app_session_input_tokens` | `int` | 应用级累计输入 Token 数（来自 ApplicationStatsState） |
| `app_session_output_tokens` | `int` | 应用级累计输出 Token 数（来自 ApplicationStatsState） |
| `app_session_runtime_sec` | `float` | 应用级运行时长（秒，来自 ApplicationStatsState.runtime_sec） |
| `error_message` | `str` | 当前错误信息（如有），来自 WebRuntimeState._web_error_message |
| `is_error` | `bool` | 当前是否为错误状态，来自 WebRuntimeState._web_error_is_error |
| `active_problem` | `dict \| None` | 当前活跃问题摘要（来自 WebRuntimeState） |
| `problem_event_id` | `str` | 当前问题事件 ID（来自 WebRuntimeState） |
| `recent_problems` | `list[dict]` | 最近问题列表（来自 WebRuntimeState） |
| `cached_danmu_lines` | `int` | 弹幕缓存行数，来自 WebRuntimeState._cached_danmu_lines |
| `cached_layout_mode` | `str` | 布局模式缓存，来自 WebRuntimeState._cached_layout_mode |
| `live_snapshot` | `Any \| None` | 实时状态快照（running=True 时由 build_live_status_snapshot 生成） |
| `persona_names` | `list[str]` | 当前激活的人格名称列表 |
| `screen_index` | `int` | 截图目标屏幕索引（config.screen_index） |
| `has_api_key` | `bool` | 是否已配置 API Key |
| `dedup_profile` | `dict \| None` | 去重统计快照（仅 dedup_profile_enabled() 时有效） |
| `lifetime` | `dict` | 生命周期累计统计（来自 lifetime_stats.snapshot） |
| `session_runs` | `list[dict]` | 场次记录列表（来自 session_run_log.list_dicts_newest_first） |
| `generation_pipeline` | `GenerationPipelineState` | 视觉请求代际流水线状态 |

---

## DanmuApp.__init__ 中已排除的运行时字段

> 以下字段由 `RUNTIME_FIELD_EXCLUDE`（`scripts/boundary_guard/constants.py`）豁免登记，
> 通常为组件引用（engine/overlay/tray 等）或全局单例，无需在 RuntimeState 中重复投影。

| 字段 | 排除原因 |
|------|----------|
| `web_launch_mode` | 启动模式标记，非运行时状态 |
| `config` | 配置对象本身，非状态字段 |
| `logger` | 日志实例，非状态字段 |
| `personae` | PersonaManager 单例，非状态字段 |
| `templates` | TemplateManager 单例，非状态字段 |
| `history` | HistoryWriter 单例，非状态字段 |
| `history_writer` | HistoryWriter 单例，非状态字段 |
| `capturer` | 截图捕获器组件引用，非状态字段 |
| `engine` | DanmuEngine 组件引用，非状态字段 |
| `overlay` | DanmuOverlay 组件引用，非状态字段 |
| `tray` | QSystemTrayIcon 组件引用，非状态字段 |
| `hotkey` | 键盘热键处理器，非状态字段 |
| `ai_worker` | AI Worker 组件引用，非状态字段 |
| `floating_panel_overlay` | 浮动面板 QPainter 渲染组件（W-FP-V2-001；Web 面板失败时 fallback） |
| `floating_panel_engine` | 浮动面板引擎组件（W-FP-V2-001；Web/QPainter 共用去重与堆积） |
| `_panel_process` | pywebview 浮动面板子进程管理（`PanelProcess`；`app/floating_panel_web/panel_process.py`） |
| `_panel_bridge` | 浮动面板 WS 桥（`PanelBridge`；通常挂在 `WebConsoleBridge.panel_bridge`） |
| `_panel_web_active` | 当前是否走 Web 面板路径（bool） |
| `font_registry` | 字体注册表（W-FONT-002） |

---

## 所有权、线程与消费者

| 状态组 | 写入所有者 | 读取线程/消费者 | 生命周期 |
|--------|------------|-----------------|----------|
| `running`、计数、Token、运行时长 | `DanmuApp` / `StatsState` | Qt 主线程；`/api/status` 读取不可变快照 | 启停或新会话时更新；累计值可持久化 |
| 队列与显示计数 | `DanmuApp`、GenerationPipeline、Overlay/浮动面板 | Qt 主线程写；Web 线程只读 snapshot | 入队、出队、显示和 stop 时变化 |
| Web 错误与缓存 | `WebRuntimeState` | Web snapshot 与诊断接口 | 新错误覆盖；明确清理时复位 |
| `generation_pipeline` | `GenerationPipelineState.from_app` 投影 | `/api/status`、诊断与日志 | 每次截图、回复和场景代际变化时更新 |
| `live_snapshot` | `build_live_status_snapshot()` | WebSocket/SSE/状态接口 | `running=false` 时可为空 |

### 最小状态示例

```json
{
  "running": true,
  "queue_count": 3,
  "display_count": 5,
  "screen_index": 0,
  "has_api_key": true,
  "generation_pipeline": {
    "scene_generation": 8,
    "latest_screenshot_id": 47
  }
}
```

示例仅说明关系；完整字段和序列化形状以 `app/application/runtime_state.py`、`generation_pipeline_state.py` 和 `status_snapshot.py` 为准。

---

## 维护说明

- 新增运行态字段：添加到上方表格，并在 `DanmuApp.__init__` 中赋值后同步到本文档
- 删除字段：从上方表格移除
- 修改字段含义：在"业务含义"列更新描述
- 白名单字段：`RUNTIME_FIELD_EXCLUDE` 定义在 `scripts/boundary_guard/constants.py`，修改时需同步更新本文档对应小节
- 验证：运行 `python scripts/boundary_guard.py`，再按 `.local-ai/prompts/IDE_AGENT_RULES.md` 对相关状态/API 测试分批执行 `-q -x`
- 完成报告：记录新增/删除字段、写入所有者、线程、消费者、默认值或 reset 条件，以及门禁前后 delta
