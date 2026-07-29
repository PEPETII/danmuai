# DanmuApp 12 Mixin 能力矩阵

> **日期化维护者快照（2026-07-14）**：W-BILILIVE-DM-REMOVE-001 移除 `DanmuAppBililiveDmMixin` 后为 **12** Mixin。行数与方法数会漂移；现行契约以 `main.py`、[架构基线](final-architecture-baseline.md) 与 [.local-ai/workorders/当前仓库状态.md](../.local-ai/workorders/当前仓库状态.md) 为准。
>
> **工单**：W-T5-MIXIN-001（历史）+ W-BILILIVE-DM-REMOVE-001（弹幕姬移除）  
> **继承顺序**（`main.py`）：Launch → WebFacade → State → Mic → RenderCoordinator → Pet → Overlay → FloatingPanel → ScreenTopology → RequestContext → Meme → Lifecycle → `QObject`  
> **统计基准**：历史行数来自 2026-07-10；结构以当前源码为准。公开方法 = `def` 名不以 `_` 开头。

## 总览矩阵

| # | Mixin 类 | 文件 | 行数（历史） | 公开方法 | Web façade 方法¹ | 与 GP / 主链路交叉 | 本波次 |
|---|----------|------|------|----------|------------------|-------------------|--------|
| 1 | `DanmuAppLaunchMixin` | `main_launch_mixin.py` | 96 | 2 | 0 | 启动 Web/pywebview；`restore_main_window` | **不拆**（启动编排高风险） |
| 2 | `DanmuAppWebFacadeMixin` | `main_web_facade_mixin.py` | 258 | 26 | **26** | 全 Web API 唯一合法写入口；status/diagnostics 快照 | **不拆**（已是 façade 层） |
| 3 | `DanmuAppStateMixin` | `main_state_mixin.py` | 171 | 18 | 12² | `danmu_count` / token 统计；`latest_displayed_*` 只读 @property | **下一批**：stats 写入收口 `stats_state`（W-T5-MIXIN-002 候选） |
| 4 | `DanmuAppMicMixin` | `main_mic_mixin.py` | 221 | 2 | 2 | 麦轨 `_poll_mic_utterance`；读弹幕 probe façade | 不拆（独立子系统） |
| 5 | `DanmuAppRenderCoordinatorMixin` | `main_render_coordinator_mixin.py` | 210 | 1 | 0 | **GP 热路径**：`_danmu_render_mode`、`_enqueue_reply_batch`、`_display_danmu_text`、`_publish_live_status`、pool topup | **下一批 façade**：显示/入队公开方法（W-T5-GP-002+） |
| 6 | `DanmuAppPetMixin` | `main_pet_mixin.py` | 98 | 13 | 13 | GP 调 `_notify_pet_visual_success`；桌宠显隐与 Web `/api/pet/*` | 不拆（子包 `app/pet/` 已收口） |
| 7 | `DanmuAppOverlayMixin` | `main_overlay_mixin.py` | 18 | 0 | 0 | `_sync_overlay_visibility` 随 `danmu_render_mode` | 不拆（薄协调层） |
| 8 | `DanmuAppFloatingPanelMixin` | `main_floating_panel_mixin.py` | 48 | 0 | 0 | 浮动面板显隐同步 | 不拆（薄协调层） |
| 9 | `DanmuAppScreenTopologyMixin` | `main_screen_topology_mixin.py` | 195 | 0 | 0 | 多屏恢复、Overlay 健康检查 | 不拆（Qt 屏拓扑事件） |
| 10 | `DanmuAppRequestContextMixin` | `main_request_context_mixin.py` | 426 | 0 | 0 | **GP 最大写回源**：`_record_undisplayed`、`_log_reply_pipeline*`、`_estimated_reply_gap_ms`、duplicate 观测、`scene_generation_lagged` | **下一批 façade 主落点**（W-T5-GP-002） |
| 11 | `DanmuAppMemeMixin` | `main_meme_mixin.py` | 310 | 5 | 4 | 烂梗采集/展示 tick；公式化弹幕旁路 | 不拆（`meme_barrage/` 子包） |
| 12 | `DanmuAppLifecycleMixin` | `main_lifecycle_mixin.py` | 766 | 5 | 0 | `start`/`stop`/`toggle`/`quit`；六段初始化；场景代龄 bump | **不拆**（生命周期所有权） |

> **已移除**：`DanmuAppBililiveDmMixin`（`main_bililive_dm_mixin.py`）— 弹幕姬插件旁路；备份见仓库根 `danmuji_backup/`（gitignore）。

¹ **Web façade 方法**：供 `app/web_api/*` 经 `DanmuApp` 公开 API 调用、或文档约定为 HTTP 边界的 `def`（不含 `_`）。  
² StateMixin 的 12 项为 status/diagnostics 只读投影属性（`danmu_count`、`latest_displayed_*` 等），由 `WebFacadeMixin.build_*_snapshot` 间接消费。

---

## 职责一句话

| Mixin | 职责 |
|-------|------|
| Launch | Web 控制台 / pywebview 子进程附着与托盘恢复 |
| WebFacade | HTTP 线程到主线程的配置写入、快照组装、探测 API |
| State | 运行态统计与只读投影（`stats_state` / `web_runtime_state` 代理） |
| Mic | 麦克风采集轨、读弹幕配置与 probe |
| RenderCoordinator | 弹幕渲染模式解析、入队、上屏、live status、池 topup |
| Pet | 桌宠窗口与 `/api/pet` 命令/素材 façade |
| Overlay | 全屏 Overlay 显隐与 `danmu_render_mode` 联动 |
| FloatingPanel | 浮动面板 V2 显隐联动 |
| ScreenTopology | 显示器热插拔与 Overlay 重连 |
| RequestContext | 请求元数据、RTT、回复管线日志、去重观测、代龄门控 |
| Meme | 烂梗库远程采集、AI 选梗、展示节奏 |
| Lifecycle | 应用生命周期、配置变更、场景版本、退出收尾 |

---

## GenerationPipeline 触点 → Mixin 映射

详见 [generation-pipeline-host-touchpoints.md](generation-pipeline-host-touchpoints.md)。GP 直接调用的私有方法主要落在：

- **RequestContext**（日志、未上屏、去重、gap 估算、`latest_displayed_*` 写）
- **RenderCoordinator**（渲染模式、入队、上屏、live status、pool）
- **Pet**（视觉成功通知）
- **main.py 字段**（`_batch_id`、`_current_batch`、`_queue_low_watermark`）

---

## 下一批可拆 façade 候选（仅建议，本波次不实现物理拆 Mixin）

| 优先级 | 候选 | 理由 |
|--------|------|------|
| P0 | `RequestContextMixin` 回复消费写路径 | GP 66 处 `app._*` 过半在此 Mixin 定义；façade 可加在同类上 |
| P0 | `RenderCoordinatorMixin` 入队/上屏 | 与 GP `handle_reply_parsed` / consume 路径耦合最深 |
| P1 | `StateMixin` stats 写入 | `_update_stats` 应经 `stats_state` 单一所有者（W-T5-MIXIN-002） |
| P2 | `main.py` 批次字段 | `_batch_id` / `_current_batch` 可收为 `@property` 或小型 batch host |

**明确不拆（本波次）**：Launch、Lifecycle、WebFacade、Overlay、FloatingPanel、ScreenTopology、Meme、Mic、Pet。

---

## 与 boundary_guard / 文档对齐

- Mixin 数量与 `AGENTS.md` §A.3.2 一致：**12**（`main_display_mixin` 已拆为显示协调 Mixin；BililiveDm 已移除）。
- GP 治理规则：`scripts/boundary_guard/rules/pipeline.py` → `check_generation_pipeline_service`。
- 主链路序：`docs/main-pipeline-sequence.md`（勿改 `_on_screenshot_timer` → `_consume_reply_queue` 顺序）。
