# DanmuAI 架构审查报告（Refactoring Catalog，2026-07-14）

> **审查日期**：2026-07-14  
> **仓库路径**：`E:\test\danmu`  
> **HEAD（已确认）**：`8d4e925`（完整 `8d4e92507eb825b51898e0ba8ed2d3eb4a40efc1`）  
> **方法论**：`refactoring` skill（Phase 0 Discover → Phase 1 Plan 信号）+ `REFACTORING-CATALOG.md`（10 类模式）  
> **证据约定**：关键断言标注 **已确认**（`文件:行号` / 可复现命令）或 **推断**（说明如何确认）  
> **范围**：主进程 Python 架构（`main.py` + `app/`）的结构债与重构机会；**不实现重构、不改行为、不替代 bug 审计**  
> **权威性**：文档与实现冲突时，以 `main.py` 与 `app/` 源码为准

---

## 0. 元信息与非目标

### 0.1 本报告是什么

对当前源码做 **只读架构审查**，用 Refactoring Catalog 的可观察信号（文件长度、方法数、参数面、嵌套深度等）标出 **纯结构** 改进机会，并给出 Risk / Scope / 工单化粒度建议。

### 0.2 本报告不是什么

| 非目标 | 说明 |
|--------|------|
| 不是实施授权 | 落地须单独工单 + 负责人批准；见 `AGENTS.md` §1–§4 |
| 不是 bug 审计 | 行为缺陷见 [bug-audit-report-2026-07-14.md](bug-audit-report-2026-07-14.md) |
| 不是性能真机报告 | Profiler 状态见 [architecture-debt-wave-status-2026-07-10.md](architecture-debt-wave-status-2026-07-10.md) |
| 不修改 Boundary Guard 三表 | 三表路径与契约不变；本文件仅为日期化快照 |

### 0.3 Skill 原则（写入本报告的约束）

来自 refactoring skill：

1. **Never change structure and behavior in the same step.** 下列机会均假设「先结构、测绿，再谈行为」。
2. **Phase 0 Discover 阈值**（触发调查，非自动开单）：

| 信号 | 阈值 |
|------|------|
| 函数长度 | > 30 行 |
| 文件长度 | > 500 行 |
| 参数个数 | > 5 |
| 嵌套深度 | > 4 层 |
| 类方法数 | > 15 |
| import 语句数 | > 20（文件职责过多启发式） |
| 重复块 | 3+ 处（本报告仅点名对称分发，未做全仓 clone 检测） |

3. **Risk 1–5** = 模式风险、调用面、测试覆盖三因子均值（上取整）。  
4. **Scope**：S（1–2 步）/ M（3–5 步）/ L（6+ 步，须详细计划）。

### 0.4 度量复现

```text
# 行数（PowerShell 示例）
Get-ChildItem main.py,app -Recurse -Filter *.py | ...

# AST：函数行数 / 参数 / 嵌套 / 类方法数（Python ast 模块遍历 FunctionDef/ClassDef）
# 本报告采样日期 2026-07-14，行号会随后续提交漂移
```

---

## 1. 与既有文档的关系

| 文档 | 关系 |
|------|------|
| [final-architecture-baseline.md](final-architecture-baseline.md) | **现行**所有权基线；本报告不修改 |
| [main-pipeline-sequence.md](main-pipeline-sequence.md) | **现行**定时器 / 线程池登记 |
| [runtime-state-map.md](runtime-state-map.md) | **现行**运行态投影登记 |
| [architecture-analysis-report-2026-07-10.md](architecture-analysis-report-2026-07-10.md) | 07-10 连接关系分析；本报告补 **Catalog 信号 + 重构机会** |
| [architecture-debt-wave-status-2026-07-10.md](architecture-debt-wave-status-2026-07-10.md) | 波次 0–9 **已收官**；本报告从收官后基线继续发现 |
| [danmu-app-mixin-capability-matrix.md](danmu-app-mixin-capability-matrix.md) | **12 Mixin** 职责矩阵（已校正 Bililive 移除） |
| [architecture-report.md](architecture-report.md) / [01–06 六件套](README.md) | **历史**；仍写 8 Mixin 等，勿直接执行 |
| [AGENTS.md](../AGENTS.md) 附录 A | 协作与技术速查；与源码冲突以源码为准 |

### 相对 07-10 分析的关键校正（已确认）

1. `DanmuApp` 为 **12 Mixin + QObject**（非 13）：`DanmuAppBililiveDmMixin` 已移除（`main.py:97-110`）。  
2. 架构债波次 1–9 已结案：routes 聚合器、GP Host façade 私有写回 **0**、ConfigStore 外提等。  
3. 本报告关注 **仍超 Catalog 阈值** 的热点，而非重开已完成债。

---

## 2. 现行架构快照

### 2.1 一句话

DanmuAI 是 **Windows 本机桌面 AI 弹幕助手**：Qt 主线程持有截图 → 视觉 AI → 回复解析 → 队列 → Overlay/桌宠/浮动面板上屏；FastAPI（uvicorn 线程）+ 可选 pywebview **子进程**提供 Web 控制台；`app/application/` 为边界收口层（配置写入、状态投影、GenerationPipeline 消费）。

### 2.2 进程 / 线程（摘要）

```text
python main.py
├─ DanmuApp（main.py + 12× main_*mixin.py）  — Qt 主线程：定时器 / Overlay / 回复消费
├─ uvicorn 线程                               — app/web_console.py（127.0.0.1:18765）
├─ QThreadPool                                — 视觉 AI / 截图 / 部分 probe
├─ pywebview 子进程                           — app/webview_shell.py
└─ 其它：PortAudio 回调、TTS 播放线程等（见 AGENTS.md §9 / 附录 A）
```

**硬约束（不得借「重构」绕过）**：

- HTTP 线程写 Qt → `WebConsoleBridge` 或 `QTimer.singleShot(0, ...)`  
- `scene_generation` 过时回复丢弃（`_visual_reply_stale_reason` / `scene_generation_lagged`）  
- 主链路入口签名与调用序冻结：`_trigger_api_call` / `_on_ai_reply` / `_consume_reply_queue`（消费体在 GP）

### 2.3 DanmuApp 装配（已确认）

```python
# main.py:97-110
class DanmuApp(
    DanmuAppLaunchMixin,
    DanmuAppWebFacadeMixin,
    DanmuAppStateMixin,
    DanmuAppMicMixin,
    DanmuAppRenderCoordinatorMixin,
    DanmuAppPetMixin,
    DanmuAppOverlayMixin,
    DanmuAppFloatingPanelMixin,
    DanmuAppScreenTopologyMixin,
    DanmuAppRequestContextMixin,
    DanmuAppMemeMixin,
    DanmuAppLifecycleMixin,
    QObject,
):
```

| 指标 | 值（已确认，AST 2026-07-14） |
|------|------------------------------|
| Mixin 文件方法合计 + `DanmuApp` 本体 | **约 253** 个方法 |
| 本体 `main.py` `DanmuApp` | 32 方法 / ~946 行 |
| 最大 Mixin 方法面 | `WebFacade` **57**、`State` **40**、`RequestContext` **25**、`Meme` **21**、`Lifecycle` **20** |

> Mixin 已按职责切文件，但 **共享 `self.*` 状态** 仍是 God Object 表面（Catalog：**Extract Class** 的继承式折中，非真正 composition）。

### 2.4 主链路锚点（已确认）

| 阶段 | 符号 | 位置 |
|------|------|------|
| 定时器 | `_on_screenshot_timer` | `main.py:374` |
| 闸门 | `_on_normal_capture_tick` | `main.py:378` |
| API 触发 | `_trigger_api_call` | `main.py:562` |
| AI 回复 | `_on_ai_reply` | `main.py:819` |
| 队列消费 façade | `_consume_reply_queue` | `main.py:864` → `GenerationPipeline` |

### 2.5 分层与已收口成果

| 层 | 路径 | 健康度（相对 Catalog） |
|----|------|------------------------|
| 宿主 | `main.py` + mixins | 方法面过大；职责文件已拆 |
| 应用边界 | `app/application/` | GP / config / status / diagnostics 已立；个别方法仍超长 |
| Web | `web_api/*_routes.py` + `routes.py` 聚合器 | **routes.py ~152 行**（T4 已完成） |
| 持久化 | `config_store/` | storage 外提完成；`ConfigStore` 仍 **74** 方法 |
| 显示 | `overlay` / `danmu_engine` / `pet` / floating_panel | 类方法数与文件行数仍高 |
| AI | `ai_client*` / `providers/` | **参数面** 为最强 Catalog 信号之一 |

---

## 3. Discover 度量

### 3.1 仓库规模（已确认）

| 指标 | 数量 |
|------|------|
| `app/**/*.py` | **190** |
| `tests/test_*.py` | **212** |
| `app/application/*.py` | 15 |
| `app/web_api/*.py` | 33 |
| 文件行数 > 500（`main.py` + `app/`） | **15** |

### 3.2 文件长度 > 500（Catalog：Extract Module 候选）

| 行数 | 路径 | 备注 |
|------|------|------|
| ~1039 | `app/pet/pet_window.py` | Qt 窗口 + 动画 + 气泡；方法 63 |
| ~946 | `main.py` | 宿主 + 主链路；**不宜整文件拆出口** |
| ~889 | `app/model_catalog.py` | **多为数据**；低优先 |
| ~887 | `app/webview_shell.py` | 启动/附着长函数 |
| ~869 | `app/main_lifecycle_mixin.py` | start/stop/quit 簇 |
| ~796 | `app/config_store/storage.py` | 方法 74；T4 已外提子模块 |
| ~745 | `app/overlay.py` | 渲染热路径 |
| ~742 | `app/danmu_pool.py` | 池 CRUD + 迁移 |
| ~716 | `app/danmu_engine/track.py` | `DanmuEngine` 58 方法 |
| ~689 | `app/web_console.py` | Bridge + Server |
| ~645 | `app/model_providers.py` | **多为数据/校验** |
| ~554 | `app/tts_providers.py` | 多 Adapter 已多态 |
| ~543 | `app/floating_panel_engine.py` | |
| ~529 | `app/application/generation_pipeline.py` | 分发方法超长 |
| ~526 | `app/application/ai_butler_service.py` | |

### 3.3 类方法数 > 15（Catalog：Extract Class / 继续 façade）

| 方法数 | 类 | 文件 |
|--------|-----|------|
| 74 | `ConfigStore` | `config_store/storage.py` |
| 63 | `PetWindow` | `pet/pet_window.py` |
| 58 | `DanmuEngine` | `danmu_engine/track.py` |
| 57 | `DanmuAppWebFacadeMixin` | `main_web_facade_mixin.py` |
| 40 | `DanmuAppStateMixin` | `main_state_mixin.py`（多为 property 代理） |
| 38 | `DanmuOverlay` | `overlay.py` |
| 32 | `DanmuApp` | `main.py` |
| 25 | `DanmuAppRequestContextMixin` | `main_request_context_mixin.py` |
| 25 | `FloatingPanelEngine` | `floating_panel_engine.py` |
| 23 | `WebConsoleBridge` | `web_console.py` |
| 20 | `DanmuAppLifecycleMixin` | `main_lifecycle_mixin.py` |

合成 `DanmuApp` 对外暴露 **~253** 方法（含私有）——超过 Catalog「15 方法」阈值一个数量级；已通过 Mixin 文件切分缓解 **编辑冲突**，未消除 **状态耦合**。

### 3.4 长函数 Top（>30 行，抽样）

| 行数 | 参数 | 嵌套 | 位置 |
|------|------|------|------|
| 277 | 1 | 2 | `web_console_runtime.py:30` `run_uvicorn_locked` |
| 208 | 1 | 2 | `config_service.py:236` `ConfigService._normalize_items` |
| 178 | 1 | 3 | `generation_pipeline.py:216` `_dispatch_to_floating_panel` |
| 138 | 2 | 5 | `pet_facade.py:214` `apply_pet_settings_patch` |
| 127 | 1 | 2 | `storage_legacy.py:58` 迁移 |
| 115 | 11 | 4 | `ai_client_support.py:182` `execute_stream_request_with_retry` |
| 114 | 0 | 3 | `main_lifecycle_mixin.py:755` `quit` |
| 114 | 14 | 2 | `ai_client_requests.py:338` `request_openai` |
| 111 | 10 | 2 | `main_request_context_mixin.py:347` `_enqueue_reply_batch` |
| 102 | 5 | 4 | `webview_shell.py:785` `open_web_console_when_ready` |
| 102 | 14 | 1 | `ai_client_requests.py:199` `request_doubao` |
| 98 | 1 | 3 | `generation_pipeline.py:395` `_dispatch_to_overlay` |
| 95 | 8 | 2 | `generation_pipeline.py:55` `handle_reply_parsed` |
| 90 | 8 | 1 | `main_lifecycle_mixin.py:424` `_on_ai_error` |
| 88 | 0 | 2 | `main_lifecycle_mixin.py:522` `start` |

### 3.5 参数个数 > 5（Catalog：Introduce Parameter Object）

| 参数 | 位置 |
|------|------|
| **14** | `request_openai` / `request_doubao`（`ai_client_requests.py`） |
| **13** | `AiRunnable.__init__` |
| **11** | `execute_stream_request_with_retry`、`_run_visual_stream_request`、`AiWorker._request` 等 |
| **10** | `_enqueue_reply_batch`、`enqueue_reply_batch_for_pipeline`、`_prepare_visual_request_context`、流式 helpers |
| **8** | `handle_reply_parsed`、`_on_ai_reply`、`_on_ai_error` 等（请求身份元组反复出现） |

**已确认模式**：`persona_id, request_round, screenshot_id, captured_at, scene_generation`（+ timing）在主链路多处 **成组传递** —— 典型 Parameter Object 候选（Catalog §6）。

### 3.6 嵌套深度 > 4（Catalog：Flatten Nested Conditionals）

| 深度 | 位置 | 备注 |
|------|------|------|
| 8 | `doubao_responses_stream.py` `consume_doubao_sse_lines` | SSE 解析；高风险，需 characterization |
| 7 | `ai_butler_service.py` `_extract_json` | 纯对话路径 |
| 6 | `tray.py` 更新回调、`danmu_engine_dedup` Levenshtein 回退 | |
| 5 | `reply_parser`、`danmu_pool` 迁移/分页、`pet_facade` 设置补丁等 | |

### 3.7 import > 20（文件职责启发式）

已确认偏高：`main.py` ~47、`main_lifecycle_mixin.py` ~50、`config_store/storage.py` ~59、`webview_shell.py` ~32、`web_console.py` ~28、`main_web_facade_mixin.py` ~29。与「宿主/存储门面」角色一致；**单独降 import 不是目标**，拆职责后自然下降。

---

## 4. 按子系统健康度

| 子系统 | 状态 | 说明 |
|--------|------|------|
| **主链路宿主** | 风险-中 | 入口已拆方法；仍集中在 `main.py` + lifecycle；冻结序 |
| **GenerationPipeline** | 风险-中 | 边界正确；`_dispatch_to_*` 过长，对称结构适合 Extract Method |
| **Web façade / routes** | 较好 | routes 聚合完成；WebFacade 方法 57 仍大但职责单一（HTTP 合法入口） |
| **ConfigStore** | 风险-中 | T4 子模块外提完成；类仍 74 方法 / Lock 语义敏感 |
| **AI 请求面** | 风险-高（结构） | 14 参数贯穿；测试可覆盖但签名变更 blast radius 大 |
| **model_catalog / providers 数据** | 保持 | 行数高但数据表主导；**勿当 God Class 强拆** |
| **Overlay / Engine / Pet** | 风险-中 | 热路径 + Qt；Extract 须 characterization + 真机手验 |
| **webview_shell** | 风险-中 | 长过程函数；进程边界敏感 |
| **TTS providers** | 较好 | 已 Adapter 多态（Catalog §7 已部分落地） |
| **danmu_pool** | 风险-低～中 | 近期 rollback 修复；迁移嵌套可 Flatten |

---

## 5. 重构机会目录（Impact × Risk）

> **审查 ≠ 开工。** 每条给出 Catalog pattern、Expected shape、Risk/Scope、建议允许区 / 禁止区。  
> 排序：结构收益高且可工单化优先；高风险项靠后。

### R1 — Introduce Parameter Object：视觉请求上下文

| 项 | 内容 |
|----|------|
| **信号** | `request_openai` / `request_doubao` 各 **14** 参数；同源字段在 `_prepare_visual_request_context`、`AiRunnable`、`_on_ai_reply` 重复 |
| **Pattern** | Catalog **§6 Introduce Parameter Object** |
| **目标** | `app/ai_client_requests.py`（及签名连锁的 `ai_client.py` / `runnable.py`） |
| **Expected** | `@dataclass` 如 `VisualRequestContext`（persona / round / screenshot_id / scene_generation / captured_at / timing / resolved / audio…）；公开行为不变 |
| **Risk** | **4/5**（模式中、调用面 10+ 文件、测试部分覆盖） |
| **Scope** | **L**（须逐步改签名 + re-export 过渡） |
| **允许区建议** | `app/ai_client*.py`、`app/runnable.py`、相关 tests |
| **禁止区** | `main.py` 主链路序、Web 路由契约字段名（若 JSON 暴露则非纯重构） |
| **工单粒度** | 先引入 dataclass 并在最内层使用；外层仍拆参转发 → 再逐层收紧 |

### R2 — Extract Method：GenerationPipeline 三路分发

| 项 | 内容 |
|----|------|
| **信号** | `_dispatch_to_floating_panel` **~178 行**；`_dispatch_to_overlay` **~98**；`handle_reply_parsed` **~95** / 8 参数 |
| **Pattern** | Catalog **§1 Extract Method**（可选后续 §2 按 dispatch 目标拆文件） |
| **目标** | `app/application/generation_pipeline.py` |
| **Expected** | 每路分发：校验 → 取文本 → 引擎调用 → 统计/日志 拆为命名私有方法；`handle_reply_parsed` 保持编排 |
| **Risk** | **3/5**（模式低、主链路调用、测试有 GP 相关用例） |
| **Scope** | **M** |
| **允许区** | `generation_pipeline.py` + 对应 tests |
| **禁止区** | 改 `reply_timer` 所有权、触发 `_trigger_api_call`、实例化 QTimer/QThreadPool（boundary_guard） |
| **验收** | 分批 `tests/test_p0_main_flow.py`、reply/GP 相关用例 + `boundary_guard` |

### R3 — Introduce Parameter Object：回复批次 / 请求身份

| 项 | 内容 |
|----|------|
| **信号** | `_enqueue_reply_batch` **10** 参数 / **111** 行；`enqueue_reply_batch_for_pipeline` 10 参数；`handle_reply_parsed` 8 参数 |
| **Pattern** | Catalog **§6**（可与 R1 共用「请求身份」对象，避免两个异构 context） |
| **目标** | `main_request_context_mixin.py`、`main_web_facade_mixin.py`、`generation_pipeline.py` |
| **Expected** | `ReplyBatchContext` 或复用 `VisualRequestContext` 子集 + `normalized_items` / flags |
| **Risk** | **3/5** |
| **Scope** | **M–L** |
| **禁止区** | 改变 `QueuedReply` 持久字段语义；mic 负 `request_round` 约定 |

### R4 — Extract Method：Lifecycle start / stop / quit / AI error

| 项 | 内容 |
|----|------|
| **信号** | `quit` **114** 行、`start` **88**、`stop` **68**、`_on_ai_error` **90** / 8 参数；文件 **869** 行 / import ~50 |
| **Pattern** | **§1 Extract Method**；若簇清晰再 **§2 Extract Module**（如 `lifecycle_shutdown.py`） |
| **目标** | `app/main_lifecycle_mixin.py` |
| **Expected** | `quit` 拆为：停定时器 / 停池 / 停 Web / 持久化 flush / 退出进程 等步骤函数 |
| **Risk** | **4/5**（生命周期错误代价高；真机路径） |
| **Scope** | **L** |
| **禁止区** | 改变 stop/quit 对外顺序契约（除非有 characterization + 手验清单） |

### R5 — Extract Method / Module：webview 附着与就绪

| 项 | 内容 |
|----|------|
| **信号** | `open_web_console_when_ready` **102** 行；`attach_webview_shell` **71**；文件 ~887 行 |
| **Pattern** | **§1** → **§2 Extract Module**（就绪轮询 vs 进程 worker） |
| **目标** | `app/webview_shell.py` |
| **Risk** | **3/5**（子进程 + 超时；测试偏少则先补 characterization） |
| **Scope** | **M** |
| **禁止区** | 改 `_LOAD_TIMEOUT_SEC` 行为与 frozen 路径语义（属行为变更） |

### R6 — Extract Method：ConfigService 归一化

| 项 | 内容 |
|----|------|
| **信号** | `_normalize_items` **~208 行** |
| **Pattern** | **§1 Extract Method**（按配置域拆：视觉 / 麦 / 显示 / TTS…） |
| **目标** | `app/application/config_service.py` |
| **Risk** | **3/5**（`PUT /api/config` 面；须保留 `WEB_CONFIG_KEYS` 白名单语义） |
| **Scope** | **M** |
| **禁止区** | HTTP 线程直接写 Qt；放宽白名单 |

### R7 — Extract Method：run_uvicorn_locked

| 项 | 内容 |
|----|------|
| **信号** | `run_uvicorn_locked` **~277 行**（全仓最长函数级热点之一） |
| **Pattern** | **§1** / **§2**（锁获取、server 构建、shutdown hook） |
| **目标** | `app/web_console_runtime.py` |
| **Risk** | **3/5** |
| **Scope** | **M** |
| **注意** | 与测试中 web console 启动夹具强相关 |

### R8 — Extract Class（小步）：ConfigStore 方法簇

| 项 | 内容 |
|----|------|
| **信号** | **74** 方法 / ~796 行；`_write_lock` **非 RLock**（递归会死锁） |
| **Pattern** | **§10 Extract Class**（composition：KV / models / meme 已有子模块可继续下沉） |
| **Expected** | 保持 `ConfigStore` 为 façade；内部委托已有 `storage_*.py` |
| **Risk** | **5/5** 若一次大挪；**3/5** 若单簇小步 + 锁顺序 characterization |
| **Scope** | **L**（多工单） |
| **禁止区** | 在锁内回调可重入路径；改变 Fernet / WAL 语义 |

### R9 — Extract Method：显示热路径（Engine / Overlay）

| 项 | 内容 |
|----|------|
| **信号** | `DanmuEngine.add_text` ~71 行 / 6 参数；`DanmuOverlay.show_for_screen` ~68 行；类方法 58 / 38 |
| **Pattern** | **§1**；参数可考虑 **§6** |
| **Risk** | **3/5**（渲染正确性 + 真机手验） |
| **Scope** | **M** |
| **验收** | `tests/test_danmu_engine.py` 等 + Overlay 手验（`AGENTS` 手动验收） |

### R10 — Flatten Nested Conditionals：池迁移 / 解析 / SSE

| 项 | 内容 |
|----|------|
| **信号** | nest 5–8：`migrate_custom_danmu_pool_json`、`parse_ai_reply_payload`、`consume_doubao_sse_lines` 等 |
| **Pattern** | Catalog **§8 Flatten Nested Conditionals**（guard clauses） |
| **Risk** | 池迁移 **2/5**；SSE/parser **4/5**（易改行为） |
| **Scope** | S–M |
| **策略** | 优先 **纯结构 + 已有测试绿**；parser/SSE 必须先 characterization |

### R11 — WebFacade / State：保持 façade，避免再叠 Mixin

| 项 | 内容 |
|----|------|
| **信号** | WebFacade **57** 方法；State **40**（多为代理 property） |
| **Pattern** | **勿**再 Extract Class 为第 13 Mixin；优先 **§5 Move** 到 `app/application/*` 已有服务，Mixin 变薄委托 |
| **Risk** | **4/5** 若改公开方法名；**2/5** 若仅内部委托 |
| **Scope** | L（多波次） |
| **对齐** | 与 `danmu-app-mixin-capability-matrix.md`「下一批 stats 收口」一致 |

### R12 — Remove Dead Code / 数据文件降噪

| 项 | 内容 |
|----|------|
| **信号** | 可用 `ruff check --select F401,F841`；`model_catalog` / `model_providers` 行数高但 **非逻辑 God** |
| **Pattern** | **§9 Remove Dead Code**；数据文件 **不**优先 §10 |
| **Risk** | 死代码 **2/5**（注意动态 getattr / 插件） |
| **Scope** | S |
| **本报告** | 仅建议；未跑全仓 dead-code 证明 |

### R13 — pet_facade / tray 长过程（次优先）

| 项 | 内容 |
|----|------|
| **信号** | `apply_pet_settings_patch` ~138 行 nest 5；tray 更新回调 ~111 行 nest 6 |
| **Pattern** | **§1** + **§8** |
| **Risk** | **3/5** |
| **Scope** | M |

---

## 6. 推荐波次（仅建议，不登记工单列表）

> 符合 `AGENTS.md`：**一次一小工单**、5–10 分钟可手验；Scope L 必须先写详细计划。

### Wave A — 低风险、可并行（建议优先）

| 顺序 | 机会 | Pattern | Scope |
|------|------|---------|-------|
| A1 | GP 分发 Extract Method（R2） | §1 | M |
| A2 | ConfigService `_normalize_items` 按域拆（R6） | §1 | M |
| A3 | danmu_pool 迁移 Flatten（R10 子集） | §8 | S |
| A4 | ruff 未使用导入清理（R12，确认非动态） | §9 | S |

### Wave B — 中风险、需 characterization

| 顺序 | 机会 | Pattern | Scope |
|------|------|---------|-------|
| B1 | webview_shell 就绪/附着拆分（R5） | §1/§2 | M |
| B2 | `run_uvicorn_locked` 拆分（R7） | §1/§2 | M |
| B3 | 回复批次 Parameter Object（R3） | §6 | M–L |
| B4 | Engine/Overlay Extract Method（R9） | §1 | M |

### Wave C — 高风险 / 多工单（负责人排期）

| 顺序 | 机会 | Pattern | Scope |
|------|------|---------|-------|
| C1 | 视觉请求 Parameter Object 贯穿（R1） | §6 | L |
| C2 | Lifecycle 关闭/启动簇（R4） | §1/§2 | L |
| C3 | ConfigStore 方法簇继续 composition（R8） | §10 | L |
| C4 | WebFacade/State 下沉 application（R11） | §5/§10 | L |

**明确不做（本阶段）**：

- 合并/再拆 Mixin 继承图「大重构」  
- 移动 `docs/runtime-state-map.md` 等三表  
- 关闭 `scene_generation` 门控或改主链路序  
- 结构改造与 bugfix 同一 commit  

---

## 7. 若落地重构：Skill 门控（本仓本地化）

### 7.1 Phase 2 Baseline

```bash
# 仅相关文件，禁止全量 pytest（IDE Agent 规则）
python -m pytest tests/test_<相关>.py -q -x
```

记录：通过数、失败名、HEAD。缺测则先 **characterization tests**（只测公开行为，不修 bug）。

### 7.2 Phase 3 Execute

- 每步 < 5 分钟、可独立提交  
- 失败：**立即 revert**，缩小步长（skill Revert Protocol）  
- Scope L：每步一 commit  

### 7.3 Phase 4 Verify

| 检查 | 命令 / 动作 |
|------|-------------|
| 测试数不下降 | 同批 `pytest -q -x` 与 baseline 对比 |
| 边界 | 触达编排/Web/主链路时：`python scripts/boundary_guard.py` |
| Lint | `ruff check` 触及路径 |
| API 表面 | 公开 façade / HTTP JSON 字段不变（除非工单声明 breaking） |
| 无陈旧引用 | Move 后 `rg old_name` |

### 7.4 Phase 5 Report（工单完成报告）

沿用 `.local-ai/prompts/templates/Codex完成报告/`：修改文件列表、未越界证明、分批测试、手验、范围外问题只记不修。

---

## 8. 冻结边界与风险总表

### 8.1 冻结（重构不得破坏）

1. 主链路调用序与三入口委托关系（见 §2.4、`main-pipeline-sequence.md`）  
2. `scene_generation_lagged` 丢弃语义  
3. HTTP → 主线程桥接  
4. `GenerationPipeline`：禁止自建 QTimer/QThreadPool/QPixmap；禁止调用截图/API 触发私有入口  
5. `ConfigStore._write_lock` 非可重入  
6. Boundary Guard 三文档路径与文件名  

### 8.2 风险总表

| ID | 主题 | Risk | Scope | 建议波次 |
|----|------|------|-------|----------|
| R1 | AI 请求 Parameter Object | 4 | L | C |
| R2 | GP 分发 Extract Method | 3 | M | A |
| R3 | 回复批次 Parameter Object | 3 | M–L | B |
| R4 | Lifecycle 长方法 | 4 | L | C |
| R5 | webview_shell 拆分 | 3 | M | B |
| R6 | config normalize 拆分 | 3 | M | A |
| R7 | uvicorn locked 拆分 | 3 | M | B |
| R8 | ConfigStore Extract Class | 3–5 | L | C |
| R9 | Engine/Overlay Extract | 3 | M | B |
| R10 | Flatten 嵌套 | 2–4 | S–M | A/B |
| R11 | WebFacade/State 下沉 | 2–4 | L | C |
| R12 | Dead code / 数据文件 | 2 | S | A |
| R13 | pet_facade / tray | 3 | M | B |

---

## 9. 结论

1. **架构已明显收口**：12 Mixin、application 层、GP façade、routes 聚合、T4 ConfigStore 外提、波次 0–9 收官 —— 相对 07-02「8 Mixin + 边界失效」叙事已过时。  
2. **Catalog 视角下仍成立的债** 主要是：  
   - **参数成组传递**（14/10/8 参数链）→ Parameter Object  
   - **超长过程函数**（GP 分发、lifecycle、webview、uvicorn、normalize）→ Extract Method/Module  
   - **God 表面**（合成 253 方法、ConfigStore 74、PetWindow 63）→ 小步 composition，禁止一次大拆  
3. **最高性价比下一步**：Wave A（R2 → R6 → R10 子集），每单可验收、不触冻结边界。  
4. **最高结构收益但最贵**：R1 请求上下文对象贯穿 AI 栈（Wave C，须详细计划 + 宽测试网）。  
5. 本报告 **不授权改代码**；落地请负责人写入 `.local-ai/workorders/工单列表.md` 后再派单。

---

## 附录 A — Discover 原始汇总

### A.1 类方法 > 15（完整抽样表）

见 §3.3。

### A.2 Mixin 方法数（已确认）

| 类 | 方法数 | 文件行数约 |
|----|--------|------------|
| `DanmuApp` | 32 | 946 |
| `DanmuAppWebFacadeMixin` | 57 | 500 |
| `DanmuAppStateMixin` | 40 | 227 |
| `DanmuAppRequestContextMixin` | 25 | 482 |
| `DanmuAppMemeMixin` | 21 | 455 |
| `DanmuAppLifecycleMixin` | 20 | 869 |
| `DanmuAppPetMixin` | 16 | 132 |
| `DanmuAppRenderCoordinatorMixin` | 12 | 227 |
| `DanmuAppMicMixin` | 11 | 248 |
| `DanmuAppScreenTopologyMixin` | 9 | 216 |
| `DanmuAppLaunchMixin` | 7 | 116 |
| `DanmuAppFloatingPanelMixin` | 2 | 55 |
| `DanmuAppOverlayMixin` | 1 | 24 |
| **合计** | **~253** | |

### A.3 主链路参数成组（已确认示例）

```text
persona_id, request_round, screenshot_id, captured_at, scene_generation
(+ request_started_at, reply_received_at, input/output tokens, audio_data_uri, resolved, ...)
```

出现位置包括：`request_*`、`_on_ai_reply`、`handle_reply_parsed`、`_enqueue_reply_batch`、façade 入队 API。

---

## 附录 B — 本报告使用的 Catalog pattern 索引

| § | Pattern | 本报告用法 |
|---|---------|------------|
| 1 | Extract Method | R2, R4–R7, R9, R13 |
| 2 | Extract Module / File | R4, R5, R7 后续 |
| 3 | Rename | 未单列（无强信号） |
| 4 | Inline | 未建议（当前 indirection 多为边界 façade，有价值） |
| 5 | Move | R11 下沉 application |
| 6 | Introduce Parameter Object | R1, R3, R9 可选 |
| 7 | Replace Conditional with Polymorphism | TTS 已部分具备；AI provider 已有 adapters |
| 8 | Flatten Nested Conditionals | R10 |
| 9 | Remove Dead Code | R12 |
| 10 | Extract Class / Split God Class | R8, R11；Mixin 为历史折中 |

Skill 工作流阶段映射：本文件 = **Phase 0 Discover 输出 + Phase 1 机会计划草案**；**不包含** Phase 2–5 执行记录。

---

## 附录 C — 修订记录

| 日期 | 说明 |
|------|------|
| 2026-07-14 | 初版；HEAD `8d4e925`；纯文档；方法论 refactoring skill + catalog |
