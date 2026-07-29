# DanmuAI 周期性 Bug 审计报告（2026-07-01）

> **历史审计快照**：发现、测试数量与风险等级只对 commit `93bcee8` 及当时未提交工作树有效。当前缺陷与修复状态以 [.local-ai/workorders/已知问题与后续事项.md](../.local-ai/workorders/已知问题与后续事项.md) 为准。
>
> 本报告由 Spec 工作流 `W-BUG-AUDIT-0701-001` 产出，覆盖 A–J 共 10 个维度。所有结论均绑定具体文件:行号；无证据的「可能有问题」一律不写入。审计基于当前工作区状态（含 7 个未提交改动），未回滚任何用户既有改动。

## 0. 本次审计范围

- 当前分支：`main`
- 当前 commit：`93bcee8953b16694633e5d62ccb3b1741025a188`
- 检查时间：`2026-07-01`（北京时间）
- 版本号：`app/version.py:__version__ = "0.3.6"`
- 上一轮报告：`docs/bug-audit-report-2026-06-21-v4.md`（含 BUG-001/002/003/004 四项）

### 已读取的关键文件（按维度分组）

| 维度 | 关键文件 |
|------|----------|
| A 启动 | `main.py`、`app/main_lifecycle_mixin.py`、`app/main_launch.py`、`app/main_launch_mixin.py`、`app/single_instance.py`、`app/webview_shell.py`、`app/tray.py`、`app/font_registry.py` |
| B 弹幕 | `app/danmu_engine.py`、`app/overlay.py`、`app/danmu_engine_dedup.py`、`app/reply_queue.py`、`app/reply_parser.py`、`app/main_request_context_mixin.py` |
| C 模型 | `app/ai_client_requests.py`、`app/doubao_responses_stream.py`、`app/providers/adapters/default_openai.py`、`app/providers/adapters/mimo.py`、`app/providers/capabilities.py`、`app/providers/constants.py`、`app/model_providers.py`、`app/model_catalog.py` |
| D 麦克风 | `app/mic_buffer.py`、`app/mic_capture.py`、`app/mic_service.py`、`app/mic_utterance.py`、`app/danmu_tts_playback.py`、`app/danmu_read_service.py` |
| E 桌宠 | `app/pet/pet_assets.py`、`app/pet/pet_barrage.py`、`app/pet/pet_facade.py`、`app/pet/pet_window.py`、`app/web_api/pet.py` |
| F 配置/SQLite | `app/config_store.py`、`app/persona_manager.py`、`app/danmu_pool.py`、`app/session_run_log.py`、`app/lifetime_stats.py` |
| G 公式化弹幕库 | `app/web_api/danmu_pool.py`、`app/web_api/meme_barrage.py`、`app/meme_barrage/client.py`、`app/meme_barrage/store.py`、`app/reply_parser.py` |
| H 发布更新 | `DanmuAI.spec`、`scripts/build_exe.ps1`、`scripts/publish_windows_release.ps1`、`app/supabase_config.py`、`app/web_api/app_update_state.py` |
| I Web 社区 | `app/web_api/bililive_dm_bridge.py`、`app/web_api/live_overlay.py`、`supabase/migrations/001_announcements_feedback.sql`、`app/web_api/announcements_state.py` |
| J 测试验收 | `scripts/run_acceptance_gates.py`、`scripts/boundary_guard.py`、`scripts/boundary_guard/rules/baseline.py`、`scripts/boundary_guard/constants.py`、`tests/test_acceptance_gates.py`、`web/static/modules/settings-hints.js` |

### 已运行的命令与测试基准

按 AGENTS.md §A.4.1 分批 `-q -x` 执行，禁止本地全量 pytest：

| 批次 | 命令 | 结果 |
|------|------|------|
| 1 | `python -m pytest tests/test_acceptance_gates.py -q -x` | **0 passed, 1 failed**（BUG-003 引用已删除测试文件） |
| 2 | `python -m pytest tests/test_boundary_guard_*_rules.py -q -x` | 33 passed |
| 3 | `python -m pytest tests/test_overlay_render.py tests/test_danmu_engine.py tests/test_danmu_motion.py -q -x` | 73 passed, **1 failed**（B-001/B-002 fallback clamp） |
| 4 | `python -m pytest tests/test_reply_parser.py tests/test_reply_queue.py tests/test_reply_contract.py -q -x` | 全绿 |
| 5 | `python -m pytest tests/test_config_store.py tests/test_p1_sqlite_concurrency.py tests/test_danmu_pool.py -q -x` | 全绿 |
| 6 | `python -m pytest tests/test_ai_client.py tests/test_provider_adapters.py tests/test_model_providers.py -q -x` | 全绿 |
| 7 | `python -m pytest tests/test_mic_mode.py tests/test_mic_utterance.py tests/test_mic_capture.py -q -x` | 全绿 |
| 8 | `python -m pytest tests/test_pet_lifecycle.py tests/test_pet_window_drag.py tests/test_pet_assets.py -q -x` | 全绿 |
| 9 | `python -m pytest tests/test_meme_barrage_api.py tests/test_meme_barrage_runtime.py -q -x` | 全绿 |
| 10 | `python -m pytest tests/test_web_console.py tests/test_web_server.py -q -x` | 7 passed, **1 failed**（settings-hints.js 缺失文案 + BUG-004 detail 结构） |

### 上一轮 4 个 Bug 复核结果

| 编号 | 状态 | 说明 |
|------|------|------|
| BUG-001（Supabase 凭据泄露，P0） | **部分修复** | `web/static/supabase-config.js` 本体已加入 `.gitignore:31` 并 `git ls-files` 验证未跟踪；但本地仍存在 `web/static/supabase-config.js.codex-release-backup` 含真实 anon key，且 `DanmuAI.spec:66-70` 的 `_collect_dir_datas` 排除规则**仅匹配 `supabase-config.js`，未排除 `.codex-release-backup` 变体** → 形成本轮新发现 **BUG-H-001（HIGH）** |
| BUG-002（发布脚本阻断，P1） | **行为未变，已由 spec 兜底** | `scripts/publish_windows_release.ps1:13-17` 仍会因本地 `supabase-config.js` 存在而中止；但因 `DanmuAI.spec` 已排除该文件不打入包，属冗余安全门，不再单独列为 bug |
| BUG-003（验收门引用已删除测试，P1） | **未修复** | `scripts/run_acceptance_gates.py:11-12` 仍引用 `tests/test_boundary_guard.py` 和 `tests/test_diagnostics.py`，两文件均不存在（已用 Glob 确认） |
| BUG-004（invoke_on_main 504 结构不一致，P2） | **未修复** | `app/web_api/routes.py:172-175` 的 `_invoke_main` 仍返回纯字符串 `detail="主线程操作超时，请稍后重试。"`，与 `docs/features/WEB_CONSOLE.md:161-168` 的结构化契约不符 |

---

## 1. 结论总览

按严重程度分级汇总（P0 = 发布阻断/凭据泄露；P1 = 严重功能/安全/验收门阻断；P2 = 中等；P3 = 低/文档）：

### P0（1 项）

| 编号 | 标题 | 维度 |
|------|------|------|
| BUG-H-001 | `supabase-config.js.codex-release-backup` 凭据泄露到发布包，绕过 spec/build/publish 三道防护 | H |

### P1（9 项）

| 编号 | 标题 | 维度 |
|------|------|------|
| BUG-J-002 | `docs/final-architecture-baseline.md` 维护者登记表缺失导致 boundary_guard 与验收门阻断 | J |
| F-001 | `PersonaManager._load_custom` 无 JSON 解析异常处理，损坏人格数据导致启动崩溃 | F |
| B-001 | `_pick_track` fallback clamp 将离屏排队弹幕错误回夹至屏幕内，导致弹幕重叠上屏 | B |
| G-001 | `append_custom` 主线程对每条文本同步 DB 查询，5000 条导入阻塞 UI 数秒 | G |
| G-002 | `GET /api/meme-barrage/tags` 在 HTTP 线程同步发起外部 HTTP 请求（20s 超时） | G |
| D-002 | `mic_in_flight` 无看门狗恢复机制（视觉路径有 45s/48s，mic 缺失） | D |
| BUG-I-001 | bililive-dm 桥接 POST 路由完全无鉴权 | I |
| BUG-I-002 | live-overlay 状态与 SSE 路由无鉴权，泄露屏幕衍生弹幕 | I |
| BUG-003（旧） | `run_acceptance_gates.py` 仍引用已删除测试文件，验收门稳定失败 | J |

### P2（18 项）

| 编号 | 标题 | 维度 |
|------|------|------|
| F-002 | `set_custom_danmu_pool_for_store` 用 INSERT 非 INSERT OR IGNORE + 无 try/except | F |
| F-003 | `SessionRunLog._persist` 无 try/except | F |
| F-004 | ConfigStore 多处写方法只捕获 OperationalError | F |
| B-002 | `_pick_track` fallback 测试相互矛盾，两测试不可同时通过 | B/J |
| B-003 | `drop_pending_below_generation` / `drop_items_with_batch_id` 死代码，场景切换后旧弹幕不清理 | B |
| C-001 | `request_doubao` 注入 `thinking: THINKING_ENABLED` 时未校验 `caps.supports_thinking` | C |
| C-002 | `get_model_config` 仅按 `modelId` 匹配，未读 `default_model_id` | C |
| C-003 | `stream_doubao_responses` JSON body 路径未应用 `first_content_timeout` | C |
| D-001 | mic_window_sec 允许 1-30s 但环形缓冲区仅 12s，超 12s 静默截断 | D |
| D-003 | DefaultOpenAIAdapter 静默丢弃 mic 音频 | D |
| E-001 | `frame_rect` 忽略实际网格列数，自定义 spritesheet 列数不足时越界源矩形 | E |
| E-002 | `PetBarrageController.deliver_batch` 不清空未分配弹幕的窗口旧气泡 | E |
| E-003 | 弹幕模式下 `submit_pet_command` 将 one-shot 投递到隐藏主窗口 | E |
| E-007 | `GET /api/pet/status` 在 HTTP 线程读 `QWidget.isVisible()` 违反 Qt 线程安全 | E |
| G-005 | `normalize_reply_batch` 每次 AI 回复触发冗余 DB 查询 + 全表 `ORDER BY RANDOM()` | G |
| G-003 | `get_tags()` 创建的 `httpx.Client` 从未关闭（连接池泄漏） | G |
| G-007 | `meme_barrage_library` 写操作用 `_write_lock` 而非 `_pool_write_lock`，与 `custom_danmu_pool` 锁策略不一致 | G |
| BUG-004（旧） | `_invoke_main` 504 detail 结构与文档契约/测试不一致 | J |
| BUG-A01 | 单实例激活信号在 `DanmuApp.__init__` 期间被 `processEvents()` 提前处理，激活丢失 | A |

### P3（低 / 文档漂移，11 项）

E-004（hide_pet 不重置状态）、E-005（paintEvent 内移动窗口抖动）、E-006（命令框无屏幕边界钳位）、B-004（user_nickname 纳入 fingerprint）、F-005（`_migrate_active_personae` 死代码）、F-P002（`get_custom_danmu_pool_for_store` 不分页）、G-004（烂梗 `reason=empty_parse` 丢失）、BUG-H-002（app_update_state docstring 路径不符）、BUG-I-003/I-004/I-005（quota RPC / client_id / 大小上限）、BUG-I-006（docstring 过期）、BUG-J-003（settings-hints.js 缺失文案）、BUG-J-004（diagnostics SSE 无 504 超时）、C-H-002（AGENTS.md PROVIDERS/平台数漂移）、C-H-003（AGENTS.md §8 与 §A.7 `inflight_watchdog_recover` 自相矛盾）、DOC-D1（AGENTS.md §A.5.4 TTS 描述过时）。

---

## 2. 已确认 Bug

### BUG-H-001：`supabase-config.js.codex-release-backup` 凭据泄露到发布包

- 严重等级：**P0**
- 影响功能：发布包安全、Supabase anon key 泄露、社区后端访问边界
- 维度：H（自动更新与发布）
- 证据文件：
  - `web/static/supabase-config.js.codex-release-backup`（本地存在，已用 Glob 确认）
  - `DanmuAI.spec:66-70`
  - `scripts/build_exe.ps1:138-145`
  - `scripts/publish_windows_release.ps1:13-17`
  - `.gitignore:31-32`
- 证据代码：
  ```python
  # DanmuAI.spec:31-40 — _collect_dir_datas 仅按 path.name 精确匹配排除
  def _collect_dir_datas(src_dir, dest_prefix, *, exclude_names=frozenset()) -> list:
      for path in sorted(src_dir.rglob("*")):
          if not path.is_file() or path.name in exclude_names:
              continue
  # DanmuAI.spec:66-70 — exclude_names 仅含 "supabase-config.js"
  datas += _collect_dir_datas(
      root / "web" / "static", "web/static",
      exclude_names=frozenset({"supabase-config.js"}),
  )
  ```
  ```
  # 本地存在（含真实 anon key）：
  # web/static/supabase-config.js.codex-release-backup
  ```
- 复现路径：
  1. 当前工作区下 `web/static/supabase-config.js.codex-release-backup` 存在（Glob 已确认）。
  2. 运行 `pyinstaller DanmuAI.spec --noconfirm`。
  3. `_collect_dir_datas` 因 `path.name="supabase-config.js.codex-release-backup"` 不在 `exclude_names` 中，被打入 `datas`。
  4. 发布包内携带真实 Supabase URL + anon key。
  5. `scripts/build_exe.ps1:138-145` 与 `scripts/publish_windows_release.ps1:13-17` 的安全门仅检查 `supabase-config.js` 精确文件名，**不匹配 `.codex-release-backup` 变体** → 三道防护全部被绕过。
- 根因分析：
  - 上一轮 BUG-001 修复时仅堵了 `supabase-config.js` 本体（`.gitignore` + spec 排除 + build/publish 检查），但未覆盖 `.codex-release-backup` 等同目录变体。
  - `.gitignore:32` 虽已加入 `web/static/supabase-config.js.codex-release-backup` 防止入库，但**本地工作区仍存在该文件**，且 PyInstaller 的 `_collect_dir_datas` 按磁盘文件收集，不依赖 git 跟踪状态。
- 最小修复建议：
  1. 立即删除本地 `web/static/supabase-config.js.codex-release-backup`。
  2. 将 `DanmuAI.spec:69` 的 `exclude_names` 改为 `frozenset({"supabase-config.js", "supabase-config.js.codex-release-backup"})`，或改为 glob 通配排除 `supabase-config*`。
  3. 同步 `scripts/build_exe.ps1` 与 `scripts/publish_windows_release.ps1` 的安全门检查匹配 `.codex-release-backup` 变体。
  4. 轮换当前 Supabase anon key，核对该 key 的 RLS/权限边界（已泄露的 key 视为不可信）。
- 是否建议本次自动修复：**否**（涉及发布配置变更与凭据轮换，需人工确认 + 真机构建冒烟）
- 需要补充的测试：
  - 新增仓库卫生测试，断言 `web/static/` 目录下不存在任何 `supabase-config*` 文件（除 `.example.js`）。
  - 扩展 `tests/test_supabase_static.py`，对构建输入做通配存在性检查。

### BUG-J-002：`docs/final-architecture-baseline.md` 维护者登记表缺失，导致 boundary_guard 与验收门阻断

- 严重等级：**P1**
- 影响功能：boundary_guard 验收门、发布前门禁、架构治理基线
- 维度：J（测试与验收）
- 证据文件：
  - `scripts/boundary_guard/rules/baseline.py:17-20`
  - `scripts/boundary_guard/constants.py:19`
  - 已用 Glob 确认 `docs/final-architecture-baseline.md` **不存在**
- 证据代码：
  ```python
  # scripts/boundary_guard/constants.py:19
  BASELINE_FILE = "docs/final-architecture-baseline.md"
  # scripts/boundary_guard/rules/baseline.py:17-20 — 读取该文件作为基线
  ```
  ```
  # Glob "docs/final-architecture-baseline.md" → No file found
  # 但 docs/main-pipeline-sequence.md、docs/runtime-state-map.md 均存在
  ```
- 复现路径：
  1. 运行 `python scripts/boundary_guard.py`。
  2. baseline 规则因找不到 `docs/final-architecture-baseline.md` 而失败或被跳过。
  3. `scripts/run_acceptance_gates.py:10` 调用 boundary_guard，验收门报红。
- 根因分析：
  - AGENTS.md §9 第 10 条与 §A.9 明确「维护者登记表位于 `docs/` 根，禁止移动或重命名」，列出三份：`runtime-state-map.md`、`main-pipeline-sequence.md`、`final-architecture-baseline.md`。
  - 实际 `docs/` 下仅存在前两份，第三份缺失，导致 boundary_guard 的 baseline 规则无基线可比对。
- 最小修复建议：
  - 由维护者补建 `docs/final-architecture-baseline.md`（内容应为当前架构的冻结快照，供 boundary_guard 比对）。
  - 或在 `scripts/boundary_guard/rules/baseline.py` 中显式处理基线缺失为「未配置」而非静默失败。
- 是否建议本次自动修复：**否**（基线文件内容需维护者根据当前架构权威产出，Agent 不应凭空生成）
- 需要补充的测试：
  - 新增 smoke test，断言三份维护者登记表文件均存在。

### F-001：`PersonaManager._load_custom` 无 JSON 解析异常处理，损坏人格数据导致启动崩溃

- 严重等级：**P1**
- 影响功能：启动稳定性、人格管理
- 维度：F（配置/SQLite/本地数据）
- 证据文件：`app/persona_manager.py:172-180`
- 证据代码：
  ```python
  def _load_custom(self) -> dict:
      if not self._custom:
          raw = self.config.get("custom_personae", "{}")
          loaded = json.loads(raw)  # ← 无 try/except，损坏 JSON 直接抛 JSONDecodeError
          if isinstance(loaded, dict):
              self._custom = {normalize_persona_name(name): value for name, value in loaded.items()}
          else:
              self._custom = {}
      return self._custom
  ```
- 复现路径：
  1. 在 `config.db` 中将 `custom_personae` 的 JSON 改为损坏字符串（如 `"{not json"`）。
  2. 启动 `python main.py`。
  3. `PersonaManager.__init__` 调用 `_load_custom` → `json.loads` 抛 `JSONDecodeError` 未捕获 → 启动崩溃。
- 根因分析：`_load_custom` 假设 `custom_personae` 永远是合法 JSON，未对历史损坏、手动编辑、迁移失败等场景兜底。
- 最小修复建议：
  ```python
  def _load_custom(self) -> dict:
      if not self._custom:
          raw = self.config.get("custom_personae", "{}")
          try:
              loaded = json.loads(raw)
              self._custom = {normalize_persona_name(name): value for name, value in loaded.items()} if isinstance(loaded, dict) else {}
          except json.JSONDecodeError:
              logger.exception("custom_personae JSON 损坏，重置为空")
              self._custom = {}
      return self._custom
  ```
- 是否建议本次自动修复：**否**（虽范围小，但涉及启动路径与配置恢复策略，需工单确认重置 vs 备份恢复策略）
- 需要补充的测试：`tests/test_persona_manager.py` 新增 `test_load_custom_corrupt_json_falls_back_to_empty`。

### B-001：`_pick_track` fallback clamp 将离屏排队弹幕错误回夹至屏幕内，导致弹幕重叠上屏

- 严重等级：**P1**
- 影响功能：弹幕显示、轨道选择、视觉体验
- 维度：B（弹幕显示链路）
- 证据文件：`app/danmu_engine.py:930-942`
- 证据代码：
  ```python
  # 3. 全满 fallback：允许在任意右侧 x 排队（仅 min_gap 防重叠，无固定数量上限）
  candidates = sorted(self.tracks, key=lambda t: t.rightmost_edge())[:3]
  best_track = random.choice(candidates)
  tail_edge = best_track.rightmost_edge()
  item.x = max(item.x, tail_edge + random.uniform(50.0, 250.0))
  if item.x < tail_edge + min_gap:
      item.x = tail_edge + min_gap
  # 屏幕边界校验：确保弹幕不越界
  item_width = item.width if item.width > 0 else len(item.content) * _DANMU_FALLBACK_CHAR_WIDTH
  max_allowed_x = self.screen_width - item_width - min_gap
  if item.x > max_allowed_x:
      item.x = max_allowed_x  # ← BUG：将本应在屏幕外排队的弹幕回夹至屏幕右边缘
  return best_track
  ```
- 复现路径：
  1. 所有轨道的 `rightmost_edge()` 都已接近屏幕右边缘（满载场景）。
  2. 新弹幕进入 fallback，`item.x` 被设为 `tail_edge + random(50,250)`（远超屏幕宽度）。
  3. `max_allowed_x = screen_width - item_width - min_gap` 为屏幕内可见区域。
  4. `item.x > max_allowed_x` → `item.x = max_allowed_x`，弹幕被回夹至屏幕内可见位置。
  5. 与已上屏弹幕重叠显示。
- 根因分析：fallback 设计意图是「在屏幕外右侧排队等待」，但 clamp 逻辑错误地把排队弹幕拉回屏幕内可见区，违背了「离屏排队」语义。
- 最小修复建议：移除 clamp，或仅在 `item.x < 0` 时钳位到 `min_gap`；满载时应允许 `item.x > screen_width`（离屏排队），由滚动逻辑自然带入。
- 是否建议本次自动修复：**否**（与 B-002 测试矛盾相关，需先确定 fallback 期望语义并统一测试，属设计决策）
- 需要补充的测试：统一 `tests/test_pick_track_fallback_min_gap.py` 与 `tests/test_danmu_motion.py::test_pick_track_fallback_accepts_far_offscreen_tail` 的期望（见 B-002）。

### G-001：`append_custom` 主线程对每条文本同步 DB 查询，5000 条导入阻塞 UI 数秒

- 严重等级：**P1**
- 影响功能：自定义弹幕库导入、UI 响应性
- 维度：G（公式化弹幕库/外部数据）
- 证据文件：`app/web_api/danmu_pool.py:118-171`、`app/config_store.py:779-782`、`app/danmu_pool.py:169`
- 证据代码：
  ```python
  # app/web_api/danmu_pool.py:128-132
  config = app.config
  existing_set: set[str] = set()
  contains = getattr(config, "custom_danmu_contains_text", None)  # config_store 有此方法
  if not callable(contains):
      existing_set = set(config.get_custom_danmu_pool())
  # app/web_api/danmu_pool.py:151-154 — 走 contains 分支时逐条 DB 查询
  if callable(contains):
      dup = text in batch_seen or contains(text)  # ← 每条文本 1 次 DB 查询
  # app/config_store.py:779-782 — contains 实现
  def custom_danmu_contains_text(self, text: str) -> bool:
      from app.danmu_pool import custom_danmu_contains_text_for_store
      return custom_danmu_contains_text_for_store(self, text)  # ← 单条 SELECT
  ```
- 复现路径：
  1. 通过 `POST /api/danmu-pool/custom` 一次性导入 5000 条弹幕。
  2. 由于 `config.custom_danmu_contains_text` 是 callable，进入 `contains(text)` 分支。
  3. 每条文本触发 1 次 SQLite SELECT（主线程同步）。
  4. 5000 条 = 5000 次同步 DB 查询，UI 卡顿数秒。
- 根因分析：`append_custom` 优先用 callable 的 `contains` 而非预加载 `existing_set`，导致 O(N) 次 DB 往返。
- 最小修复建议：在 `append_custom` 入口先 `existing_set = set(config.get_custom_danmu_pool())` 一次性预加载，循环内用 `text in existing_set` 内存判断；仅在 `get_custom_danmu_pool` 不可用时回退到 `contains`。
- 是否建议本次自动修复：**否**（虽范围小，但改变去重策略的执行路径，需工单确认与测试覆盖）
- 需要补充的测试：`tests/test_danmu_pool_api.py` 新增大批量导入性能测试，断言 DB 查询次数 ≤ 常数。

### G-002：`GET /api/meme-barrage/tags` 在 HTTP 线程同步发起外部 HTTP 请求（20s 超时）

- 严重等级：**P1**
- 影响功能：烂梗标签筛选 UI、HTTP 线程池健康
- 维度：G（公式化弹幕库/外部数据）
- 证据文件：`app/web_api/meme_barrage.py:148-166`
- 证据代码：
  ```python
  # GET /api/meme-barrage/tags — HTTP 线程内同步外部请求
  client = httpx.Client(timeout=20.0)  # ← 20s 超时
  resp = client.get(...)  # ← 阻塞 HTTP 线程
  ```
- 复现路径：
  1. 启动应用，打开 Web 控制台烂梗设置页。
  2. 触发标签加载。
  3. 远端慢响应或不可达时，HTTP 线程被阻塞最多 20s。
- 根因分析：GET 路由在 FastAPI 工作线程内同步发外部请求，未走 `invoke_on_main` 或异步，慢请求会耗尽 HTTP 线程池。
- 最小修复建议：改为 `async def` + `httpx.AsyncClient`，或加本地缓存 + 短超时（如 3s）+ 失败回退本地标签。
- 是否建议本次自动修复：**否**（涉及异步改造与缓存策略，需工单授权）
- 需要补充的测试：`tests/test_meme_barrage_api.py` 新增 tags 路由超时回退测试。

### D-002：`mic_in_flight` 无看门狗恢复机制

- 严重等级：**P1**
- 影响功能：麦克风链路、AI 调度
- 维度：D（麦克风/语音/读弹幕）
- 证据文件：`app/main_helpers.py`（视觉路径有 `VISUAL_INFLIGHT_WARN_SEC=45` / `VISUAL_INFLIGHT_RECOVER_SEC=48`）、`app/main_request_context_mixin.py:139`
- 证据代码：
  ```python
  # 视觉路径有看门狗：
  # VISUAL_INFLIGHT_WARN_SEC=45 / VISUAL_INFLIGHT_RECOVER_SEC=48
  # reason=inflight_watchdog_recover 由 _try_recover_stale_visual_inflight() 触发
  # mic 路径无对应常量与恢复逻辑
  ```
- 复现路径：
  1. 开启麦克风模式，`mic_in_flight=True` 后 AI 请求异常未回调。
  2. 视觉路径有 48s 强制恢复，mic 路径无恢复机制。
  3. `mic_in_flight` 永久卡住，麦克风链路停止。
- 根因分析：`MAX_MIC_IN_FLIGHT=1` 定义在 `app/main_helpers.py`，但未配套 WARN/RECOVER 常量与恢复逻辑。
- 最小修复建议：为 mic 路径新增 `MIC_INFLIGHT_WARN_SEC` / `MIC_INFLIGHT_RECOVER_SEC` 与对应的 `_try_recover_stale_mic_inflight()`。
- 是否建议本次自动修复：**否**（涉及主链路调度逻辑，需工单单独授权）
- 需要补充的测试：`tests/test_inflight_recovery.py` 新增 mic inflight 超时恢复用例。

### BUG-I-001：bililive-dm 桥接 POST 路由完全无鉴权

- 严重等级：**P1**
- 影响功能：Web API 安全边界、弹幕注入
- 维度：I（Web 社区与后端）
- 证据文件：`app/web_api/bililive_dm_bridge.py:33-39`
- 证据代码：POST 路由未调用 `check_token(authorization)`，任意本地/同网客户端可注入弹幕。
- 复现路径：直接 `curl -X POST http://127.0.0.1:18765/api/bililive-dm/bridge` 无需 Bearer token。
- 根因分析：桥接路由注册时漏传 `check_token`。
- 最小修复建议：在 `register_bililive_dm_bridge_route` 中对 POST 路由加 `check_token`。
- 是否建议本次自动修复：**否**（需工单确认是否允许外部工具无 token 调用，属设计决策）
- 需要补充的测试：`tests/test_bililive_dm_bridge.py` 新增无 token 401 用例。

### BUG-I-002：live-overlay 状态与 SSE 路由无鉴权，泄露屏幕衍生弹幕

- 严重等级：**P1**
- 影响功能：Web API 安全边界、屏幕内容泄露
- 维度：I（Web 社区与后端）
- 证据文件：`app/web_api/live_overlay.py:41-96`
- 证据代码：live-overlay 状态查询与 SSE 流未调用 `check_token`，泄露当前屏幕截图衍生的弹幕内容。
- 复现路径：浏览器直接访问 `/api/live-overlay/state` 与 `/api/live-overlay/stream` 无需鉴权。
- 根因分析：live-overlay 路由为本地预览设计，但未加鉴权门。
- 最小修复建议：对 live-overlay 路由统一加 `check_token`。
- 是否建议本次自动修复：**否**（需工单确认本地预览是否需无 token 调用）
- 需要补充的测试：`tests/test_live_overlay.py` 新增无 token 401 用例。

### BUG-003（旧，未修复）：`run_acceptance_gates.py` 仍引用已删除测试文件

- 严重等级：**P1**
- 影响功能：验收门、发布前门禁可信度
- 维度：J（测试与验收）
- 证据文件：`scripts/run_acceptance_gates.py:11-12`
- 证据代码：
  ```python
  COMMANDS = [
      ("boundary_guard", [sys.executable, "scripts/boundary_guard.py"]),
      ("test_boundary_guard", [sys.executable, "-m", "pytest", "tests/test_boundary_guard.py", "-q"]),  # ← 不存在
      ("test_diagnostics", [sys.executable, "-m", "pytest", "tests/test_diagnostics.py", "-q"]),  # ← 不存在
  ]
  ```
- 已用 Glob 确认：`tests/test_boundary_guard.py` 与 `tests/test_diagnostics.py` 均不存在。
- 复现路径：运行 `python scripts/run_acceptance_gates.py` → `test_boundary_guard` 与 `test_diagnostics` 两步以「file or directory not found」退出码 4 失败。
- 根因分析：上一轮已识别但未修复；测试文件已迁移为 `tests/test_acceptance_gates.py` 等新入口，脚本未同步。
- 最小修复建议：将 `COMMANDS` 中的旧路径替换为现存测试文件，或合并到 `tests/test_acceptance_gates.py` 的现有断言。
- 是否建议本次自动修复：**是**（见第 9 章）
- 需要补充的测试：smoke test 断言 `run_acceptance_gates.py` 的 COMMANDS 引用的测试文件均存在。

---

## 3. 高风险但未确认问题

> 以下问题证据指向明显风险，但未达「已确认 bug」的复现确定性，需人工进一步验证。

### RISK-A01：`global_exception_hook` 吞掉 "has been deleted" RuntimeError
- 证据：`app/main_launch.py:global_exception_hook` 捕获并仅记录日志，未区分 Qt 对象已被删除的 `RuntimeError: wrapped C/C++ object of type ... has been deleted`。
- 风险：Qt 对象销毁后仍被引用的场景下，异常被静默吞掉，可能导致退出路径残留。
- 待确认：需真实退出场景复现，观察是否影响 `quit()` 可靠性。

### RISK-A02：`quit()` 中 `capture_worker_pool().waitForDone(2000)` 仅 2s
- 证据：`app/main_lifecycle_mixin.py:264-267`，等待工作线程完成仅 2s 超时。
- 风险：AI 请求未完成时强制退出可能丢失状态。
- 待确认：需在 AI 请求进行中触发退出，观察 worker 是否被强制中断。

### RISK-A03：`webview_shell.destroy()` 的 `proc.join(timeout=2.0)`
- 证据：`app/webview_shell.py`，pywebview 子进程 join 仅 2s。
- 风险：WebView2 卡死时子进程残留。
- 待确认：需在 WebView2 卡死场景复现。

### RISK-A04：`show_startup_notice_if_needed` 模态对话框阻塞
- 证据：`app/main_launch.py:show_startup_notice_if_needed` 在主线程弹模态 `QMessageBox`。
- 风险：用户未点击时阻塞 Web 控制台与 Overlay 启动。
- 待确认：需确认是否在 Web 启动前弹窗。

### RISK-B04：`user_nickname` 纳入 `scene_version_fingerprint`
- 证据：`app/main_request_context_mixin.py`，`scene_version_fingerprint` 含 `user_nickname`。
- 风险：用户改昵称时正常回复被误判为过时并丢弃。
- 待确认：需确认昵称变更频率与丢弃阈值的关系。

### RISK-C-H-002：AGENTS.md 文档漂移（PROVIDERS/平台数）
- 证据：AGENTS.md §A.5.5 称「9 个服务商预设」「5 个平台」，但 `app/model_providers.py` 实际 14 个预设，`app/model_catalog.py` 实际 11 个平台。
- 风险：文档与代码不一致，误导开发。
- 待确认：需以 `app/model_providers.py` 与 `app/model_catalog.py` 源码为准更新文档（属文档工单）。

### RISK-C-H-003：AGENTS.md §8 与 §A.7 关于 `inflight_watchdog_recover` 表述自相矛盾
- 证据：§9 第 8 条称「仅告警，不自动复位应用层 `ai_in_flight`」；§A.7 称「强制释放」。
- 风险：维护者对恢复语义理解分裂。
- 待确认：以 `app/main_request_context_mixin.py:139` 源码为准统一表述。

### DOC-D1：AGENTS.md §A.5.4「TTS HTTP 走主线程」描述过时
- 证据：AGENTS.md §A.5.4 称「`danmu_read_service.run_probe` 在主线程发起 HTTP，慢请求会卡 UI」，但实际 `danmu_read_service` 已改用 QThreadPool。
- 风险：误导开发者在主线程改 TTS 逻辑。
- 待确认：以 `app/danmu_read_service.py` 源码为准更新文档。

### RISK-E005/E006：桌宠 paintEvent 移动窗口抖动、命令框无屏幕边界钳位
- 证据：`app/pet/pet_window.py` paintEvent 内 `_sync_bubble_horizontal_side` 移动窗口；`_apply_window_geometry(reposition=False)` 无边界钳位。
- 风险：多屏/缩放场景下桌宠位置异常。
- 待确认：需在多屏 + 不同 DPI 场景真机验证。

### RISK-G006：`skip_dedup=True` 可能导致屏上可见重复弹幕
- 证据：`app/reply_parser.py` 中 `normalize_reply_batch` 对填充弹幕 `skip_dedup=True`。
- 风险：填充弹幕与上屏弹幕重复。
- 待确认：需观察真实场景下填充弹幕是否与 AI 弹幕重叠上屏。

---

## 4. 性能与卡顿风险

### PERF-G001：`append_custom` N 次 DB 查询（主线程）
- 见 G-001。5000 条导入 = 5000 次同步 SQLite SELECT，主线程阻塞数秒。
- 文件：`app/web_api/danmu_pool.py:151-154`、`app/config_store.py:779-782`。

### PERF-G005：`normalize_reply_batch` 每次 AI 回复触发冗余 DB 查询 + 全表 `ORDER BY RANDOM()`
- 证据：`app/reply_parser.py:86-97`，`_scene_fillers` 与 `_generic_fillers` 各调用 `load_danmu_pool_for_config` + `sample_danmu_for_config`；`app/danmu_pool.py:476` 的 `sample_danmu_for_config` 使用 `ORDER BY RANDOM() LIMIT ?`。
- 影响：每次 AI 回复都重新 load pool + 2 次 `ORDER BY RANDOM()` 全表扫描；高频回复时主链路卡顿。
- 建议：缓存 pool 到内存 + 预生成随机采样池，避免每次回复都全表 `ORDER BY RANDOM()`。

### PERF-G002：`get_custom_danmu_pool_for_store` 不分页读全表（LIMIT 20000）
- 证据：`app/danmu_pool.py`，`get_custom_danmu_pool_for_store` 默认上限 20000，主线程调用时窗口化渲染可能 hang。
- 影响：弹幕库接近 20000 条时，Web 页加载与渲染卡顿。

### PERF-G003：`get_tags()` 创建的 `httpx.Client` 从未关闭
- 证据：`app/web_api/meme_barrage.py`，每次 tags 请求新建 `httpx.Client` 未关闭。
- 影响：连接池泄漏，长时间运行后 fd 耗尽。

### PERF-A01：`FontRegistry.load_all()` 主线程 SHA256
- 证据：`app/font_registry.py`，启动时对所有字体文件计算 SHA256。
- 影响：字体数量多时启动变慢。

### PERF-A03：pet 可见时同步创建 5 个 Qt 窗口
- 证据：`app/pet/pet_barrage.py`，`PetBarrageController` 初始化 5 个 `PetBarrageWindow`。
- 影响：开启桌宠时主线程同步创建窗口，可能短暂卡顿。

### PERF-A04：WebView2 冷启动 >12s
- 证据：`app/webview_shell.py`，`_LOAD_TIMEOUT_SEC=25`，WebView2 冷启动可能超过 12s。
- 影响：首次启动桌面壳长时间白屏（已实现缓解，但仍是已知卡顿点）。

### PERF-F-P001：ConfigStore 多次同步迁移
- 证据：`app/config_store.py` 启动期多次 schema 迁移同步执行。
- 影响：迁移多时启动变慢。

---

## 6. 发布与更新风险

### BUG-H-001（P0，见第 2 章）
`supabase-config.js.codex-release-backup` 凭据泄露到发布包，绕过 `DanmuAI.spec` / `scripts/build_exe.ps1` / `scripts/publish_windows_release.ps1` 三道防护。**这是当前发布链最直接的阻断项与安全风险。**

### BUG-J-002（P1，见第 2 章）
`docs/final-architecture-baseline.md` 缺失导致 boundary_guard baseline 规则无基线可比对，`scripts/run_acceptance_gates.py:10` 调用 boundary_guard 时验收门报红，发布前门禁不可信。

### BUG-003（P1，见第 2 章）
`scripts/run_acceptance_gates.py:11-12` 仍引用不存在的 `tests/test_boundary_guard.py` 和 `tests/test_diagnostics.py`，验收门稳定失败。与 BUG-J-002 叠加，发布前门禁完全失灵。

### 上一轮 BUG-002 状态
行为未变：`scripts/publish_windows_release.ps1:13-17` 仍会因本地 `supabase-config.js` 存在而中止。但因 `DanmuAI.spec` 已排除该文件不打入包，属冗余安全门，不再单独列为 bug。**注意：若 BUG-H-001 未修复，发布包仍会携带 `.codex-release-backup` 凭据，publish 脚本的安全门不会检测到。**

### BUG-H-002（P3）：`app_update_state.py` docstring 路由与方法不符
- 证据：`app/web_api/app_update_state.py` docstring 称 `/api/app-update/state` POST，实际 `routes.py:241-253` 注册为 `/api/app-update-state` GET/PUT。
- 影响：文档误导，低风险。
- 是否建议本次自动修复：**是**（纯 docstring 修正，见第 9 章）。

### 未做的真机验收（待人工确认）
- 本轮未做 R2 / GitHub Releases / Velopack 安装/升级/卸载的真实联网验收。
- 本轮未做 frozen EXE 双击冷启动验收。
- 本轮未做 MSI/Setup.exe 安装入口一致性验收。

---

## 7. 安全与隐私风险

### BUG-H-001（P0，见第 2 章）
Supabase anon key 随发布包泄露。anon key 虽设计为前端可见，但 RLS 策略必须严格；若 RLS 配置不当，泄露的 key 可被用于越权读写。

### BUG-I-001（P1，见第 2 章）
bililive-dm 桥接 POST 路由无鉴权，任意本地/同网客户端可注入弹幕，可能被用于投递不当内容。

### BUG-I-002（P1，见第 2 章）
live-overlay 状态与 SSE 路由无鉴权，泄露当前屏幕截图衍生的弹幕内容（可能含用户隐私场景的描述）。

### BUG-I-003（P3）：quota RPC 接受任意 client_id，泄露他人额度
- 证据：`supabase/migrations/001_announcements_feedback.sql:71-113`，quota RPC 以 client_id 为参数未校验归属。
- 风险：可枚举他人额度使用情况。

### BUG-I-004（P3）：client_id 客户端可控，限流可绕过 + 配额 DoS
- 证据：同上迁移，client_id 由客户端生成。
- 风险：可伪造大量 client_id 绕过限流，或耗尽他人配额。

### BUG-I-005（P3）：context_json / diagnostics_json 无大小上限
- 证据：反馈/诊断接口接受任意大小 JSON。
- 风险：超大 payload 可耗尽存储或带宽。

### 单实例与本地数据
- `%APPDATA%/DanmuAI/config.db` + `.key`（Fernet 加密）存储敏感配置；丢失 `.key` 则已加密 Key 不可恢复（AGENTS.md §A.5.1 已记录）。
- 本轮未发现新的本地数据泄露向量。

---

## 8. 建议新增的测试

| 测试 | 覆盖 bug | 类型 |
|------|----------|------|
| `test_supabase_config_no_credentials_in_build_input` | BUG-H-001 | 仓库卫生 |
| `test_maintainer_registry_files_exist`（断言三份登记表存在） | BUG-J-002 | smoke |
| `test_run_acceptance_gates_commands_target_existing_files` | BUG-003 | smoke |
| `test_invoke_main_route_timeout_returns_structured_504`（保留） | BUG-004 | 契约回归 |
| `test_persona_manager_load_custom_corrupt_json` | F-001 | 单测 |
| `test_pick_track_fallback_offscreen_queue_no_clamp` + 统一矛盾测试 | B-001/B-002 | 单测 |
| `test_append_custom_uses_preloaded_set_not_per_row_query` | G-001 | 性能 |
| `test_normalize_reply_batch_caches_pool` | G-005 | 性能 |
| `test_meme_tags_route_timeout_fallback` | G-002 | 单测 |
| `test_mic_inflight_watchdog_recovery` | D-002 | 单测 |
| `test_bililive_dm_bridge_requires_token` | BUG-I-001 | 安全 |
| `test_live_overlay_requires_token` | BUG-I-002 | 安全 |
| `test_session_run_log_persist_swallows_db_error` | F-003 | 单测 |
| `test_custom_danmu_pool_set_ignores_duplicate_insert` | F-002 | 单测 |
| `test_request_doubao_respects_supports_thinking` | C-001 | 单测 |
| `test_mic_window_sec_clamped_to_buffer_capacity` | D-001 | 单测 |
| `test_pet_frame_rect_respects_grid_columns` | E-001 | 单测 |
| `test_pet_barrage_deliver_batch_clears_stale_bubbles` | E-002 | 单测 |

---

## 9. 本次可自动修复项

> 严格对照 5 条门槛：(1) 证据明确 (2) 修复范围很小 (3) 不改变现有功能设计 (4) 能补充或更新测试 (5) 能说明修改前后行为差异。

### 候选 1：BUG-003 — 修正 `run_acceptance_gates.py` 的 COMMANDS

| 门槛 | 是否满足 | 说明 |
|------|----------|------|
| (1) 证据明确 | ✅ | `scripts/run_acceptance_gates.py:11-12` 引用两不存在文件，Glob 已确认 |
| (2) 范围很小 | ✅ | 仅改 `COMMANDS` 列表两行 |
| (3) 不改变设计 | ✅ | 仅替换为现存测试文件，验收语义不变 |
| (4) 能补测试 | ✅ | 新增 `test_run_acceptance_gates_commands_target_existing_files` |
| (5) 行为差异 | ✅ | 前：两步稳定失败（exit 4）；后：两步正常运行 |

**结论：建议本次自动修复。**
- 修改：将 `tests/test_boundary_guard.py` 替换为现存 `tests/test_acceptance_gates.py`（或直接删除该子步骤，因 `boundary_guard` 步骤已覆盖）；将 `tests/test_diagnostics.py` 替换为现存的诊断相关测试文件。

### 候选 2：BUG-004 — 恢复 `_invoke_main` 504 结构化 detail

| 门槛 | 是否满足 | 说明 |
|------|----------|------|
| (1) 证据明确 | ✅ | `app/web_api/routes.py:172-175` 纯字符串 detail，与 `docs/features/WEB_CONSOLE.md:161-168` 及 `tests/test_web_server.py` 契约不符 |
| (2) 范围很小 | ✅ | 仅改 `_invoke_main` 的 504 分支 |
| (3) 不改变设计 | ✅ | 恢复文档与测试已定义的结构化契约 |
| (4) 能补测试 | ✅ | 保留 `test_invoke_main_route_timeout_returns_504` 作为契约回归 |
| (5) 行为差异 | ✅ | 前：`{"detail": "主线程操作超时，请稍后重试。"}`；后：`{"detail": {"ok": false, "error": "main_thread_timeout", "detail": "..."}}` |

**结论：建议本次自动修复。**
- 修改：`app/web_api/routes.py:172-175` 改为结构化 detail。

### 候选 3：BUG-H-002 — 修正 `app_update_state.py` docstring

| 门槛 | 是否满足 | 说明 |
|------|----------|------|
| (1) 证据明确 | ✅ | docstring 称 `/api/app-update/state` POST，实际 `/api/app-update-state` GET/PUT |
| (2) 范围很小 | ✅ | 仅 docstring |
| (3) 不改变设计 | ✅ | 纯文档 |
| (4) 能补测试 | ✅ | 可选，docstring 不影响运行 |
| (5) 行为差异 | ✅ | 前：docstring 误导；后：docstring 准确 |

**结论：建议本次自动修复（纯文档，无运行时影响）。**

### 候选 4：BUG-I-006 — 修正 announcements_state / app_update_state 模块 docstring 过期

| 门槛 | 是否满足 | 说明 |
|------|----------|------|
| (1)-(5) | ✅ | 纯 docstring 修正，同候选 3 |

**结论：建议本次自动修复（纯文档）。**

### 不建议本次自动修复的项（示例）

- **BUG-H-001**：涉及发布配置变更与凭据轮换，需人工确认 + 真机构建冒烟。门槛 (2)(3) 不满足（改 spec 排除规则 + 删文件 + 轮换 key 属发布流程变更）。
- **BUG-J-002**：基线文件内容需维护者权威产出，Agent 不应凭空生成。门槛 (3) 不满足。
- **F-001**：虽范围小，但涉及启动路径与配置恢复策略（重置 vs 备份恢复），需工单确认。门槛 (3) 边界模糊。
- **B-001**：与 B-002 测试矛盾相关，需先确定 fallback 期望语义并统一测试。门槛 (3) 不满足（属设计决策）。
- **G-001/G-002/G-005**：涉及去重策略/异步改造/缓存策略，需工单授权。门槛 (2)(3) 不满足。
- **D-002**：涉及主链路调度逻辑，需工单单独授权。门槛 (3) 不满足。
- **BUG-I-001/BUG-I-002**：需工单确认是否允许外部工具无 token 调用，属设计决策。门槛 (3) 不满足。
- 其余 P2/P3 项多数涉及行为变更或需工单确认，不建议自动修复。

> **注**：按 spec「默认不做任何代码修改（除非满足自动修复条件且经用户确认）」，本次审计**不实际执行任何代码修改**。上述 4 个候选项已标记为「建议本次自动修复」，等待用户确认后再以独立工单实施。

---

## 10. 最终建议

按优先级排序的 **3 个最优先事项**：

### 优先 1：修复 BUG-H-001（P0，凭据泄露）
立即删除本地 `web/static/supabase-config.js.codex-release-backup`，将 `DanmuAI.spec:69` 的 `exclude_names` 改为通配排除 `supabase-config*`（保留 `.example.js`），同步 `scripts/build_exe.ps1` 与 `scripts/publish_windows_release.ps1` 的安全门检查，并轮换 Supabase anon key。这是当前发布链最严重的安全风险，必须在下一次发布前完成。

### 优先 2：补建 `docs/final-architecture-baseline.md` 并修复 BUG-003（P1，验收门阻断）
由维护者补建 `docs/final-architecture-baseline.md` 维护者登记表（恢复 boundary_guard baseline 规则），并修正 `scripts/run_acceptance_gates.py:11-12` 的 COMMANDS（候选自动修复项 1）。两项叠加后，`scripts/run_acceptance_gates.py` 才能恢复为可信的发布前门禁。

### 优先 3：修复 F-001 与 B-001（P1，启动崩溃 + 弹幕重叠）
为 `PersonaManager._load_custom` 添加 JSON 异常兜底（防止损坏人格数据导致启动崩溃），并统一 `_pick_track` fallback 的离屏排队语义（消除 B-001 重叠 + B-002 测试矛盾）。两者均直接影响核心体验：启动稳定性与弹幕显示。

### 后续工单建议顺序

1. W-BUG-H-001：Supabase 凭据变体泄露修复 + spec/build/publish 安全门统一
2. W-BUG-J-002：补建 `docs/final-architecture-baseline.md`
3. W-BUG-003-004：验收门 + 504 结构契约修复（可自动修复候选 1+2）
4. W-F-001：PersonaManager JSON 异常兜底
5. W-B-001-002：`_pick_track` fallback 语义统一
6. W-G-001-005：自定义弹幕库导入性能 + normalize_reply_batch 缓存
7. W-D-002：mic_in_flight 看门狗
8. W-I-001-002：bililive-dm / live-overlay 鉴权门
9. W-G-002：meme tags 路由异步化
10. 文档工单：修正 AGENTS.md §A.5.4/§A.5.5/§8 与 §A.7 漂移（C-H-002/C-H-003/DOC-D1）

---

## 附录：审计维度与发现索引

| 维度 | 已确认 Bug | 高风险未确认 | 性能风险 |
|------|-----------|-------------|---------|
| A 启动 | BUG-A01 | RISK-A01~A04 | PERF-A01/A03/A04/F-P001 |
| B 弹幕 | B-001/B-002/B-003 | RISK-B04 | — |
| C 模型 | C-001/C-002/C-003 | RISK-C-H-002/C-H-003 | — |
| D 麦克风 | D-001/D-002/D-003 | DOC-D1 | — |
| E 桌宠 | E-001/E-002/E-003/E-007 | RISK-E005/E006 | PERF-A03 |
| F 配置 | F-001/F-002/F-003/F-004/F-005 | — | PERF-F-P001/F-P002 |
| G 公式化 | G-001/G-002/G-003/G-005/G-007 | RISK-G006 | PERF-G001/G005/G002/G003 |
| H 发布 | BUG-H-001/BUG-H-002 | — | — |
| I Web 社区 | BUG-I-001/BUG-I-002/BUG-I-003~006 | — | — |
| J 测试 | BUG-J-001/BUG-J-002/BUG-J-003/BUG-J-004 + BUG-003/BUG-004（旧） | — | — |

---

*报告产出时间：2026-07-01（北京时间）*
*审计工作流：Spec `W-BUG-AUDIT-0701-001`*
*基线 commit：`93bcee8953b16694633e5d62ccb3b1741025a188`*
