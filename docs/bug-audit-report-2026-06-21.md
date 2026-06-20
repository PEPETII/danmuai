# DanmuAI 周期性 Bug 审计报告

## 1. 本次审计范围

- 当前分支：`main`
- 当前 commit：`035acf9`
- 版本号：`0.3.4`
- 检查时间：2026-06-21
- 已读取的关键文件：
  - `main.py` — 入口与 DanmuApp 定义
  - `app/main_lifecycle_mixin.py` — 启动/停止/退出生命周期
  - `app/main_launch_mixin.py` — 启动编排
  - `app/main_launch.py` — 启动辅助
  - `app/single_instance.py` — 单实例守卫
  - `app/webview_shell.py` — pywebview 子进程壳
  - `app/web_console.py` — Web 控制台服务器
  - `app/tray.py` — 系统托盘
  - `app/startup_trace.py` — 启动追踪
  - `app/overlay.py` — Qt 透明置顶弹幕渲染
  - `app/danmu_engine.py` — 弹幕引擎（轨道、去重、加速）
  - `app/danmu_engine_dedup.py` — 去重逻辑
  - `app/danmu_engine_models.py` — 引擎数据模型
  - `app/reply_parser.py` — AI 回复解析
  - `app/reply_queue.py` — AI 回复 FIFO 缓冲
  - `app/live_freshness.py` — 截图退避
  - `app/win32_overlay_zorder.py` — Win32 overlay z-order 管理
  - `app/floating_panel_engine.py` — 悬浮窗引擎
  - `app/floating_panel_overlay.py` — 悬浮窗渲染
  - `app/ai_client.py` — AI 请求客户端
  - `app/ai_client_requests.py` — AI 请求构建
  - `app/ai_client_support.py` — AI 客户端支持函数
  - `app/doubao_responses_stream.py` — 豆包 Responses 流式解析
  - `app/image_compress.py` — 图像压缩
  - `app/screenshot_compress.py` — 截图压缩
  - `app/jpeg_resize.py` — JPEG 缩放
  - `app/model_providers.py` — 模型服务商预设
  - `app/model_selection.py` — 模型选择逻辑
  - `app/model_catalog.py` — 模型目录
  - `app/providers/` — Provider 适配器（base.py, default_openai.py, mimo.py, registry.py, capabilities.py, constants.py）
  - `app/api_probe.py` — API 探测
  - `app/api_schedule.py` — API 调度
  - `app/mic_service.py` — 麦克风模式门面
  - `app/mic_orchestrator.py` — 麦克风编排
  - `app/mic_capture.py` — 音频采集
  - `app/mic_utterance.py` — 语音端点检测
  - `app/mic_prompt.py` — 麦克风提示词组装
  - `app/mic_buffer.py` — 麦克风缓冲
  - `app/mic_encode.py` — 麦克风编码
  - `app/danmu_read_service.py` — 读弹幕服务
  - `app/danmu_tts.py` — TTS
  - `app/danmu_tts_playback.py` — TTS 播放
  - `app/tts_providers.py` — TTS 服务商
  - `app/tts_catalog.py` — TTS 目录
  - `app/tts_audio_utils.py` — TTS 音频工具
  - `app/pet/pet_window.py` — 桌宠窗口
  - `app/pet/pet_state.py` — 桌宠配置
  - `app/pet/pet_barrage.py` — 桌宠弹幕模式
  - `app/pet/pet_assets.py` — 桌宠素材加载
  - `app/pet/pet_animation_mapper.py` — 动画映射
  - `app/pet/pet_facade.py` — 桌宠门面
  - `app/pet/pet_command_service.py` — 桌宠命令服务
  - `app/pet/pet_prompt.py` — 桌宠提示词
  - `data/pet/default/pet.json` — 默认桌宠配置
  - `app/config_store.py` — SQLite 配置存储
  - `app/config_defaults.py` — 配置默认值
  - `app/application/config_service.py` — 配置服务
  - `app/danmu_pool.py` — 自定义弹幕池
  - `app/danmu_pool_overlay.py` — 弹幕池 overlay
  - `app/lifetime_stats.py` — 持久累计统计
  - `app/session_run_log.py` — 场次记录
  - `app/history_writer.py` — 历史记录写入
  - `app/meme_barrage/client.py` — 烂梗远程客户端
  - `app/meme_barrage/ai_select.py` — 烂梗 AI 识别
  - `app/meme_barrage/config.py` — 烂梗配置
  - `app/meme_barrage/runnable.py` — 烂梗 Runnable
  - `app/meme_barrage/service.py` — 烂梗服务
  - `app/meme_barrage/store.py` — 烂梗存储
  - `app/main_meme_mixin.py` — 烂梗 Mixin
  - `DanmuAI.spec` — PyInstaller 打包配置
  - `app/update_service.py` — Velopack 更新服务
  - `app/velopack_config.py` — Velopack 更新源 URL
  - `app/velopack_runtime.py` — Velopack 运行时
  - `app/supabase_app_updates.py` — Supabase 更新查询
  - `app/supabase_config.py` — Supabase 凭据解析
  - `app/version.py` — 版本号定义
  - `app/version_compare.py` — 版本比较
  - `app/release_channels.py` — 发布渠道
  - `app/uninstall_service.py` — 卸载服务
  - `scripts/publish_windows_release.ps1` — 发布脚本
  - `scripts/upload_r2_release.ps1` — R2 上传脚本
  - `scripts/upload_github_release.ps1` — GitHub 发布上传
  - `scripts/velopack_pack.ps1` — Velopack 打包脚本
  - `scripts/build_exe.ps1` — 构建脚本
  - `scripts/sign_windows_release.ps1` — 代码签名脚本
  - `scripts/run_acceptance_gates.py` — 验收门禁
  - `supabase/migrations/001_announcements_feedback.sql` — 公告与反馈迁移
  - `supabase/migrations/002_error_reports.sql` — 错误报告迁移
  - `supabase/migrations/003_app_updates.sql` — 应用更新迁移
  - `supabase/migrations/008_error_reports_user_note.sql` — 错误报告用户备注
  - `supabase/migrations/009_tutorial_links.sql` — 教程链接
  - `supabase/migrations/010_feedback_context.sql` — 反馈上下文
  - `web/static/supabase-config.example.js` — Supabase 配置模板
  - `web/static/supabase-client.js` — Supabase 客户端
  - `app/web_api/routes.py` — Web API 路由
  - `app/web_api/custom_models.py` — 自定义模型 API
  - `app/web_api/persona.py` — 人格 API
  - `app/web_api/danmu_pool.py` — 弹幕池 API
  - `app/web_api/danmu_read.py` — 读弹幕 API
  - `app/web_api/mic_test.py` — 麦克风测试 API
  - `app/web_api/pet.py` — 桌宠 API
  - `app/web_api/meme_barrage.py` — 烂梗 API
  - `app/web_api/capture_region.py` — 截图区域 API
  - `app/web_api/update.py` — 更新 API
  - `app/web_api/announcements_state.py` — 公告状态
  - `app/web_api/live_overlay.py` — 直播弹幕层 API
  - `app/web_api/preview_compress.py` — 压缩预览 API
  - `app/web_console_session_auth.py` — 会话鉴权
  - `app/web_console_ws.py` — WebSocket
  - `app/web_console_runtime.py` — Web 控制台运行时
  - `website/.vercel/project.json` — Vercel 项目配置
  - `.env.example` — 环境变量模板
  - `.gitignore` — Git 忽略规则
  - `conftest.py` — 根 conftest
  - `tests/conftest.py` — 测试 conftest
  - `tests/fakes.py` — 共享假对象
  - `pytest.ini` — Pytest 配置
  - `requirements.txt` — 依赖
  - `requirements-dev.txt` — 开发依赖
  - `.github/workflows/ci.yml` — CI 工作流
  - `docs/bug-audit-report-2026-06-19.md` — 上一轮审计报告
- 已运行的命令：
  - `git branch --show-current` → `main`
  - `git rev-parse --short HEAD` → `035acf9`
  - `python -m pytest tests/test_version_compare.py tests/test_config_defaults.py -q -x --tb=short` → 26 passed in 1.32s
- 未能运行的命令及原因：
  - 未运行全量 pytest（按 IDE_AGENT_RULES §10 禁止本地全量测试）
  - 未运行 `scripts/run_acceptance_gates.py`（需要完整 Python 环境与 PyQt6 GUI，CI 环境外无法完整执行）

---

## 2. 结论总览

### P0：会导致无法启动、数据丢失、安全泄露、发布不可用的问题

本轮未发现新的 P0 问题。上一轮 BUG-01（supabase-config.js 泄露）和 BUG-02（Fernet 密钥丢失提示）需确认修复状态。

### P1：会导致核心功能不可用或明显影响用户体验的问题

| 编号 | 标题 | 维度 |
|------|------|------|
| BUG-A01 | `_on_ai_error` 缺少陈旧请求守卫，致命错误可导致新会话被立即暂停 | A |
| BUG-C01 | 豆包 Responses 流 `response.output_text.done` 事件导致弹幕文本重复 | C |
| BUG-D01 | TTS 播放线程 `playback_finished.emit()` 跨线程调用 Qt 信号 | D |
| BUG-G01 | 烂梗远程 API 默认禁用 SSL 证书验证，存在中间人攻击风险 | G |
| BUG-H02 | `upload_github_release.ps1` 硬编码旧日期文件，新版本发布会找不到文件而报错 | H |
| BUG-H03 | `velopack_runtime.py` 中 `app.run()` 异常时 `raise` 重新抛出，可能导致应用无法启动 | H |
| BUG-H04 | `supabase-config.js` 被打包排除，打包版永远无法从文件读取 Supabase 凭证 | H |
| BUG-I01 | Supabase 反馈/错误报告速率限制可被 client_id 伪造绕过 | I |

### P2：会导致性能下降、边界异常、配置不生效的问题

| 编号 | 标题 | 维度 |
|------|------|------|
| BUG-A02 | `_capture_in_flight` 在 `start()` 中未重置，stop→start 快速切换可能导致截图管道短暂卡死 | A |
| BUG-B01 | `FloatingPanelOverlay` 始终使用慢速 `QPainterPath.addText`，CJK 内容可导致帧率下降 | B |
| BUG-B02 | `FloatingPanelEngine.is_duplicate` 无 TTL 剪枝，去重窗口永不过期 | B |
| BUG-B03 | `reply_parser._try_parse_json_object` 对 `}{` 拼接只取第一段，可能丢弃有效弹幕 | B |
| BUG-C02 | 豆包路径 `temperature=0` 时请求体缺少 temperature 字段 | C |
| BUG-D02 | `MicCaptureService.try_snapshot_pcm_ms` 直接访问 `MicRingBuffer` 私有属性 | D |
| BUG-D03 | 读弹幕 `run_probe` 在主线程同步执行 TTS HTTP 请求 | D |
| BUG-E01 | `validate_pet_pack_dir` 中 QPixmap 验证用对象未释放，多次调用累积显存 | E |
| BUG-E02 | `PetBarrageController.show()` 在 barrage 未启用时调用 `hide()`，语义不清晰 | E |
| BUG-F01 | `custom_danmu_list_for_store` 等读操作未持 `_write_lock`，并发时可能数据不一致 | F |
| BUG-F02 | `custom_danmu_list_for_store` 中 search 参数未转义 LIKE 通配符 | F |
| BUG-F03 | `set_custom_danmu_pool_for_store` 全量 DELETE + INSERT 无上限检查 | F |
| BUG-F05 | `ConfigStore.close()` 后 `get()` 仍可读取 `_cache`，返回可能过期的数据 | F |
| BUG-G02 | `_tags_cache` 模块级全局缓存永不过期且无法刷新 | G |
| BUG-G05 | 烂梗 AI 识别模式与主链路共用 `ai_worker_pool`，无优先级或隔离 | G |
| BUG-G06 | `_meme_display_tick` 递归调度无批次数限制 | G |
| BUG-H01 | R2 上传脚本 `DanmuAI-Setup.exe` latest 别名使用 `no-cache`，与契约文档建议不一致 | H |
| BUG-H05 | `update_service.py` 中 `_manager()` 每次调用都创建新的 `UpdateManager` 实例 | H |
| BUG-H07 | `uninstall_service.py` 中 `delete_user_data_if_requested` 仅检查 marker 文件名，未验证内容 | H |
| BUG-I02 | `listAnnouncements()` 未在查询中过滤 `published=true`，完全依赖 RLS | I |
| BUG-I03 | Live Overlay SSE 端点无鉴权，本地任意进程可订阅实时弹幕 | I |
| BUG-J01 | `FakeConfig.get_json()` 对非法 JSON 值无容错 | J |

### P3：代码卫生、文档不一致、潜在维护问题

| 编号 | 标题 | 维度 |
|------|------|------|
| BUG-A03 | `_init_request_pipeline_state` 中 `_capture_in_flight = False` 重复赋值 | A |
| BUG-E03 | `_persist_position` 逐键写入位置，未用 `set_batch` | E |
| BUG-G04 | `custom_danmu_list_for_store` 中 f-string 拼接 SQL（当前安全，代码风格问题） | G |
| BUG-H06 | `update_service.py` 中 `thread.start()` 注释说"blocking"但实际非阻塞 | H |
| BUG-H08 | `version_compare.py` 的 `_split_core_prerelease` 仅按第一个 `-` 分割 | H |
| BUG-I04 | `/api/preview/compress` 端点 `max_width` 和 `quality` 参数无边界校验 | I |
| BUG-I05 | `.vercel/project.json` 含 Vercel 项目/组织 ID 并已提交到仓库 | I |
| BUG-J02 | `conftest.py` 的 `tmp_path` fixture 覆盖了 pytest 内置 `tmp_path` | J |

---

## 3. 已确认 Bug

### BUG-A01：`_on_ai_error` 缺少陈旧请求守卫，致命错误可导致新会话被立即暂停

- 严重等级：**P1**
- 影响功能：主链路 start/stop 循环；失败退避机制
- 证据文件：[main_lifecycle_mixin.py](file:///e:/test/danmu/app/main_lifecycle_mixin.py)
- 证据代码：
  ```python
  # _on_ai_reply (line 564-593) — 有守卫：
  meta = self._pop_request_meta(request_round, screenshot_id, scene_generation)
  if not meta:
      return  # W-RACE-001 修复

  # _on_ai_error (line 417-418) — 无守卫：
  meta = self._pop_request_meta(request_round, screenshot_id, scene_generation)
  source = meta.get("source") or "visual"  # meta 为 {} 时不崩溃，但继续处理
  ```
  后续 line 447-468：
  ```python
  self._consecutive_failures += 1          # 陈旧错误递增新会话的失败计数
  is_fatal = "401" in msg or "402" in msg or "403" in msg ...
  if is_fatal:
      self._failure_backoff_paused = True  # 陈旧致命错误暂停新会话！
      self.screenshot_timer.stop()         # 新会话的截图定时器被停！
  ```
- 复现路径：
  1. API Key 无效，启动后收到 401 错误 → `_failure_backoff_paused = True`
  2. 用户在 Web 控制台修改 API Key
  3. 点击 Stop → `stop()` 清空 `_pending_request_meta`
  4. 快速点击 Start → `start()` 重置 `_failure_backoff_paused = False`，启动 `screenshot_timer`
  5. 旧 AiRunnable 的错误信号到达 → `_on_ai_error` 被调用
  6. `_pop_request_meta` 返回 `{}`（已被 stop 清空）
  7. `msg` 含 "401" → `is_fatal = True` → 新会话被立即暂停
- 根因分析：`_on_ai_error` 缺少与 `_on_ai_reply` 相同的 `if not meta: return` 守卫。W-RACE-001 修复仅覆盖了成功路径。
- 最小修复建议：在 `_on_ai_error` 的 `_pop_request_meta` 调用后，增加与 `_on_ai_reply` 一致的陈旧判断：
  ```python
  meta = self._pop_request_meta(request_round, screenshot_id, scene_generation)
  if not meta:
      self.logger.warning("stale_error_dropped: ...")
      return
  ```
- 是否建议本次自动修复：**是**
- 需要补充的测试：测试 stop→start 快速切换后旧 AiRunnable 错误信号到达时，新会话的 `_failure_backoff_paused` 和 `screenshot_timer` 不受影响

---

### BUG-A02：`_capture_in_flight` 在 `start()` 中未重置，stop→start 快速切换可能导致截图管道短暂卡死

- 严重等级：**P2**
- 影响功能：主链路截图调度
- 证据文件：[main_lifecycle_mixin.py](file:///e:/test/danmu/app/main_lifecycle_mixin.py)
- 证据代码：
  ```python
  # stop() (line 589-650) — 未重置 _capture_in_flight：
  def stop(self) -> None:
      ...
      self.ai_worker.mark_stopping()
      self.ai_in_flight = 0
      # _capture_in_flight 未重置！

  # start() (line 497-575) — 也未重置 _capture_in_flight：
  def start(self) -> None:
      ...
      self.ai_in_flight = 0
      self._is_generating = False
      # _capture_in_flight 未重置！
  ```
  `_schedule_capture` (main.py:322) 的守门条件：
  ```python
  if self._capture_in_flight:
      self.logger.debug("跳过截图调度: reason=capture_in_flight")
      return
  ```
- 复现路径：
  1. 正常运行中，一次截图正在 capture_worker_pool 中执行，`_capture_in_flight = True`
  2. 用户点击 Stop → `stop()` 未重置 `_capture_in_flight`
  3. 用户快速点击 Start → `start()` 也未重置 `_capture_in_flight`
  4. `_on_normal_capture_tick()` → `_schedule_capture()` → `_capture_in_flight` 仍为 True → 跳过
  5. 直到旧 capture worker 完成，截图管道恢复（但如果旧 worker 挂起，管道永久卡死）
- 根因分析：`start()` 重置了 `ai_in_flight`、`_is_generating` 等状态，但遗漏了 `_capture_in_flight`。测试 conftest 中显式 `app._capture_in_flight = False` 佐证了此问题。
- 最小修复建议：在 `start()` 中增加 `self._capture_in_flight = False`
- 是否建议本次自动修复：**是**
- 需要补充的测试：测试 stop→start 快速切换后 `_capture_in_flight` 为 False，截图正常调度

---

### BUG-A03：`_init_request_pipeline_state` 中 `_capture_in_flight = False` 重复赋值

- 严重等级：**P3**
- 影响功能：代码可维护性
- 证据文件：[main_lifecycle_mixin.py](file:///e:/test/danmu/app/main_lifecycle_mixin.py)
- 证据代码：
  ```python
  # line 146:
  self._capture_in_flight = False
  # line 156 (仅 10 行后):
  self._capture_in_flight = False
  ```
- 复现路径：静态代码审查即可确认
- 根因分析：复制粘贴错误，line 156 可能本应是其他字段的初始化
- 最小修复建议：删除 line 156 的重复赋值，或确认是否有遗漏的字段初始化
- 是否建议本次自动修复：否（需确认原意）
- 需要补充的测试：无

---

### BUG-B01：`FloatingPanelOverlay` 始终使用慢速 `QPainterPath.addText`，CJK 内容可导致帧率下降

- 严重等级：**P2**
- 影响功能：悬浮窗弹幕渲染性能
- 证据文件：[floating_panel_overlay.py](file:///e:/test/danmu/app/floating_panel_overlay.py)
- 证据代码：
  ```python
  # line 198-208 — 始终使用 QPainterPath.addText（慢路径）：
  text_path = QPainterPath()
  text_path.addText(text_x, baseline_y, self._font, draw_text)
  painter.drawPath(text_path)   # 描边
  painter.drawPath(text_path)   # 填充
  ```
  对比 `DanmuOverlay` 的优化路径（overlay.py:69-106）：
  ```python
  def _use_fast_danmu_render(content: str) -> bool:
      if len(content) >= _FAST_DANMU_RENDER_MIN_LEN:
          return True
      return any(ord(ch) > 127 for ch in content)  # CJK 走快路径
  ```
- 复现路径：
  1. 启用悬浮窗面板
  2. 使用中文 AI 模型，弹幕内容为 CJK
  3. 观察悬浮窗渲染帧率，CJK 内容多时可能出现掉帧
- 根因分析：`FloatingPanelOverlay._render_card_pixmap` 未采用 `DanmuOverlay` 的 `_use_fast_danmu_render` + `drawText` 快路径优化。`QPainterPath.addText` 对 CJK 字符的路径计算非常耗时。
- 最小修复建议：在 `FloatingPanelOverlay._render_card_pixmap` 中引入与 `DanmuOverlay` 相同的快路径判断，CJK/长文本使用 `drawText` 描边
- 是否建议本次自动修复：**是**
- 需要补充的测试：性能测试：CJK 内容悬浮窗渲染帧率对比

---

### BUG-B02：`FloatingPanelEngine.is_duplicate` 无 TTL 剪枝，去重窗口永不过期

- 严重等级：**P2**
- 影响功能：悬浮窗弹幕去重准确性
- 证据文件：[floating_panel_engine.py](file:///e:/test/danmu/app/floating_panel_engine.py)
- 证据代码：
  ```python
  # FloatingPanelEngine.is_duplicate (line 208-220) — 无 TTL 剪枝：
  def is_duplicate(self, content: str) -> bool:
      return is_duplicate_in_recent(
          content,
          self._recent,          # deque(maxlen=30)，无时间戳
          self._recent_exact_set,
          self.config,
      )

  # 对比 DanmuEngine._is_duplicate (danmu_engine.py:1019-1028)：
  def _is_duplicate(self, content: str) -> bool:
      self._prune_recent_by_ttl()   # ← 每次 dedup 前按 TTL 剪枝
      return is_duplicate_in_recent(...)
  ```
- 复现路径：
  1. 启用悬浮窗面板
  2. 长时间运行（>30 分钟），弹幕频率较低
  3. 早期出现过的弹幕内容因 `deque(maxlen=30)` 未满仍留在去重窗口中
  4. 相同内容在很久之后仍被去重拦截，即使场景已完全不同
- 根因分析：`FloatingPanelEngine` 缺少 `recent_timestamps` 字典和 `_prune_recent_by_ttl` 方法，去重窗口仅靠 deque 容量淘汰，无时间维度过期
- 最小修复建议：为 `FloatingPanelEngine` 添加 `recent_timestamps` 字典和 `_prune_recent_by_ttl` 方法
- 是否建议本次自动修复：**是**
- 需要补充的测试：测试悬浮窗去重窗口在 TTL 过期后允许重复内容通过

---

### BUG-B03：`reply_parser._try_parse_json_object` 对 `}{` 拼接只取第一段，可能丢弃有效弹幕

- 严重等级：**P2**
- 影响功能：AI 回复解析完整性
- 证据文件：[reply_parser.py](file:///e:/test/danmu/app/reply_parser.py)
- 证据代码：
  ```python
  # line 100-127：
  if "}{" in raw:
      head = raw.split("}{", 1)[0] + "}"  # 只取第一段
      try:
          parsed = json.loads(head)
      except json.JSONDecodeError:
          parsed = None
  ```
- 复现路径：
  1. 模型返回流式拼接的多个 JSON 对象，如 `{"comments":["A"]}{"comments":["B"]}`
  2. 解析只取第一段 `{"comments":["A"]}`，丢弃 `{"comments":["B"]}`
  3. 弹幕 B 永远不会显示
- 根因分析：流式 SSE 场景下模型可能返回多个 JSON 对象拼接，当前只解析第一段
- 最小修复建议：在 `}{` 拼接场景下，尝试解析每一段 JSON 对象并合并 comments
- 是否建议本次自动修复：否（需确认模型是否实际返回此格式）
- 需要补充的测试：测试 `}{"` 拼接的 JSON 输入是否完整解析所有弹幕

---

### BUG-C01：豆包 Responses 流 `response.output_text.done` 事件导致弹幕文本重复

- 严重等级：**P1**
- 影响功能：豆包 Responses API 路径的 AI 回复文本
- 证据文件：[doubao_responses_stream.py](file:///e:/test/danmu/app/doubao_responses_stream.py)
- 证据代码：
  ```python
  # 第 116-123 行
  if chunk_type == "response.output_text.delta":
      delta = chunk.get("delta", "")
      if delta:
          collected.append(str(delta))       # ← 增量追加
  elif chunk_type == "response.output_text.done":
      text = chunk.get("text", "") or chunk.get("delta", "")
      if text:
          collected.append(str(text))         # ← 再次追加完整/剩余文本
  ```
- 复现路径：
  1. 使用豆包 Responses API 模式（默认 doubao）
  2. AI 返回流式响应，先发若干 `response.output_text.delta` 事件，再发 `response.output_text.done` 事件
  3. 豆包 Responses API 的 `response.output_text.done` 事件的 `text` 字段包含**完整**文本
  4. `collected` 列表同时包含 delta 增量和 done 完整文本 → 最终 `"".join(collected)` 产生重复
- 根因分析：豆包 Responses API 的 `response.output_text.done` 事件语义是「输出文本完成，附带完整文本」，而代码将其当作增量追加。现有测试用例因 done 的 text 恰好只含增量部分而未暴露此问题。
- 最小修复建议：当已收到 delta 事件时，忽略 `response.output_text.done` 的 text 字段：
  ```python
  elif chunk_type == "response.output_text.done":
      if not collected:  # 仅在无 delta 时取 done 文本
          text = chunk.get("text", "") or chunk.get("delta", "")
          if text:
              collected.append(str(text))
  ```
- 是否建议本次自动修复：**是**
- 需要补充的测试：新增测试：先发 `delta:"hel"` 再发 `done.text:"hello"`（完整文本），断言结果为 `"hel"` 而非 `"helhello"`

---

### BUG-C02：豆包路径 `temperature=0` 时请求体缺少 temperature 字段

- 严重等级：**P2**
- 影响功能：豆包 Responses API 路径的 temperature 配置
- 证据文件：[ai_client_requests.py](file:///e:/test/danmu/app/ai_client_requests.py)
- 证据代码：
  ```python
  # 第 240-241 行
  if temperature:
      data["temperature"] = temperature
  ```
- 复现路径：
  1. 用户在 Web 控制台将 temperature 设为 0
  2. `config.get_float("temperature", 0.8)` 返回 `0.0`
  3. `if temperature:` 判断 `0.0` 为 falsy → temperature 字段不写入请求体
  4. 豆包 API 使用服务端默认 temperature（通常 1.0），与用户意图不符
- 根因分析：Python 中 `0.0` 为 falsy，`if temperature:` 无法区分「用户设为 0」和「未设置」。OpenAI 路径不受影响（第 448 行 `data["temperature"] = temperature` 无条件写入）。
- 最小修复建议：
  ```python
  if temperature is not None and temperature >= 0:
      data["temperature"] = temperature
  ```
- 是否建议本次自动修复：**是**
- 需要补充的测试：验证 `temperature=0.0` 时豆包请求体包含 `"temperature": 0.0`

---

### BUG-D01：TTS 播放线程 `playback_finished.emit()` 跨线程调用 Qt 信号

- 严重等级：**P1**
- 影响功能：读弹幕 TTS 播放完成后的状态恢复
- 证据文件：[danmu_tts_playback.py](file:///e:/test/danmu/app/danmu_tts_playback.py)
- 证据代码：
  ```python
  # 第 69-96 行
  def _play_worker(self, wav_bytes: bytes) -> None:
      try:
          ...
          sd.play(audio, samplerate=rate, blocking=True)
          sd.wait()
      except Exception as exc:
          ...
      finally:
          self._set_busy(False)
          self.playback_finished.emit()   # ← 在非 Qt 线程 emit
  ```
- 复现路径：
  1. 启用读弹幕模式，TTS 合成成功
  2. `play_wav_bytes` 在 `threading.Thread` 中执行 `_play_worker`
  3. 播放完成后在**非 Qt 线程**调用 `self.playback_finished.emit()`
  4. Qt 信号在非 owner 线程 emit → `DanmuReadService._on_playback_finished` 在播放线程而非主线程执行
- 根因分析：`DanmuTtsPlayback` 的 `_play_worker` 在 `threading.Thread` 中直接 emit Qt 信号。Qt 的自动连接机制仅在接收方所在线程有事件循环时生效；`threading.Thread` 无 Qt 事件循环，emit 变为直接调用。
- 最小修复建议：使用 `QMetaObject.invokeMethod` 或 `QTimer.singleShot(0, ...)` 将回调投递到主线程
- 是否建议本次自动修复：**是**（但需注意 Qt 线程模型兼容性）
- 需要补充的测试：验证 `_on_playback_finished` 始终在主线程执行

---

### BUG-D02：`MicCaptureService.try_snapshot_pcm_ms` 直接访问 `MicRingBuffer` 私有属性

- 严重等级：**P2**
- 影响功能：麦克风 utterance 轮询的 PCM 采集
- 证据文件：[mic_capture.py](file:///e:/test/danmu/app/mic_capture.py)
- 证据代码：
  ```python
  # 第 293-308 行
  def try_snapshot_pcm_ms(self, ms: int) -> bytes | None:
      buf = self._buffer
      if not buf._lock.acquire(blocking=False):   # ← 访问私有属性 _lock
          return None
      try:
          want = min(
              len(buf._data),                      # ← 访问私有属性 _data
              ms * buf.sample_rate * BYTES_PER_SAMPLE // 1000,
          )
          ...
          return bytes(buf._data[-want:])          # ← 访问私有属性 _data
      finally:
          buf._lock.release()                       # ← 访问私有属性 _lock
  ```
- 复现路径：
  1. 麦克风模式启用，utterance 检测器每 600ms 调用 `try_snapshot_pcm_ms`
  2. 直接操作 `MicRingBuffer` 的 `_lock` 和 `_data` 私有属性
  3. 如果 `MicRingBuffer` 未来重构内部实现，此方法将静默损坏
- 根因分析：为避免非阻塞锁获取，绕过了 `MicRingBuffer` 的公开 API `take_recent_ms`，直接操作内部属性
- 最小修复建议：在 `MicRingBuffer` 中添加 `try_take_recent_ms` 方法，封装非阻塞锁获取+读取逻辑
- 是否建议本次自动修复：**是**
- 需要补充的测试：验证 `try_take_recent_ms` 在锁忙时返回 None，锁空闲时返回正确数据

---

### BUG-D03：读弹幕 `run_probe` 在主线程同步执行 TTS HTTP 请求

- 严重等级：**P2**
- 影响功能：读弹幕试听功能
- 证据文件：[danmu_read_service.py](file:///e:/test/danmu/app/danmu_read_service.py)
- 证据代码：
  ```python
  # 第 273-321 行
  def run_probe(self, ...) -> dict[str, object]:
      self._tts_in_flight = True
      try:
          wav = synthesize_tts(           # ← 主线程同步 HTTP 请求
              api_key,
              TTS_PROBE_TEXT,
              ...
          )
  ```
- 复现路径：
  1. 在 Web 控制台点击「读弹幕」试听按钮
  2. `run_probe` 在主线程同步调用 `synthesize_tts`，内部执行 HTTP 请求
  3. 网络延迟或 API 慢响应时，Qt 主线程被阻塞，UI 冻结
- 根因分析：`run_probe` 为简化代码直接在主线程同步执行 TTS 请求，未走 QThreadPool 异步路径
- 最小修复建议：将 `run_probe` 改为与 `_on_tick` 相同的 QThreadPool 异步模式
- 是否建议本次自动修复：否（需较大重构）
- 需要补充的测试：验证试听请求不阻塞主线程 UI

---

### BUG-E01：`validate_pet_pack_dir` 中 QPixmap 验证用对象未释放，多次调用累积显存

- 严重等级：**P2**
- 影响功能：宠物素材包验证
- 证据文件：[pet_assets.py](file:///e:/test/danmu/app/pet/pet_assets.py)
- 证据代码：
  ```python
  # 第 192 行
  pixmap = QPixmap(str(sheet_path))
  if pixmap.isNull():
      raise ValueError(f"spritesheet 无法加载：{sheet_path}")
  if pixmap.width() % PET_FRAME_W or pixmap.height() % PET_FRAME_H:
      raise ValueError(...)
  # pixmap 在函数返回后由 Python GC 回收，但 PyQt6 的 QPixmap 底层资源依赖 Qt 事件循环释放
  ```
- 复现路径：
  1. 通过 Web API 反复切换不同 local 素材包
  2. 每次切换调用 `validate_pet_pack_dir` → 创建一个完整 spritesheet QPixmap
  3. 在 Qt 事件循环繁忙时，GC 回收延迟导致显存累积
- 根因分析：`validate_pet_pack_dir` 为纯验证函数，创建了 QPixmap 仅用于 `isNull()` / `width()` / `height()` 检查，但未显式释放
- 最小修复建议：改用 `QImageReader` 仅读取尺寸元数据而不解码全图：
  ```python
  from PyQt6.QtGui import QImageReader
  reader = QImageReader(str(sheet_path))
  size = reader.size()
  if not size.isValid():
      raise ValueError(...)
  ```
- 是否建议本次自动修复：否
- 需要补充的测试：验证连续调用 `validate_pet_pack_dir` 10 次后 QPixmap 缓存计数不增长

---

### BUG-E02：`PetBarrageController.show()` 在 barrage 未启用时调用 `hide()`，语义不清晰

- 严重等级：**P2**
- 影响功能：桌宠弹幕模式切换
- 证据文件：[pet_barrage.py](file:///e:/test/danmu/app/pet/pet_barrage.py)
- 证据代码：
  ```python
  # 第 127-132 行
  def show(self) -> None:
      if not self.is_enabled():
          self.hide()  # ← 隐藏所有 barrage 窗口
          return
      for window in self._windows:
          window.show_pet()
  ```
- 复现路径：
  1. 调用 `barrage.show()` 但 barrage 未启用
  2. `show()` 内部调用 `self.hide()` → 所有窗口被隐藏
  3. 调用方 `sync_pet_window_visibility` 已在后续逻辑中处理显隐，`show()` 内的 `hide()` 是冗余的防御性调用，可能导致窗口闪烁
- 根因分析：`show()` 方法在未启用时主动调用 `hide()`，语义不清晰
- 最小修复建议：将 `show()` 中 `self.hide()` 改为 `return`
- 是否建议本次自动修复：否
- 需要补充的测试：测试 barrage 未启用时调用 `show()` 不触发任何 `hide_pet()`

---

### BUG-E03：`_persist_position` 逐键写入位置，未用 `set_batch`

- 严重等级：**P3**
- 影响功能：宠物位置持久化
- 证据文件：[pet_window.py](file:///e:/test/danmu/app/pet/pet_window.py)
- 证据代码：
  ```python
  # 第 866-877 行
  def _persist_position(self) -> None:
      pos = self.pos()
      if self.slot_id > 0 or self._settings.barrage.enabled:
          ...
          return
      self._app.config.set("pet_position_x", str(pos.x()))   # ← 事务 1
      self._app.config.set("pet_position_y", str(pos.y()))   # ← 事务 2
      self._settings = PetSettings.from_config(self._app.config)
  ```
- 复现路径：
  1. 拖拽单宠物窗口释放
  2. 两次独立 `config.set()` → 两次 SQLite 事务
  3. 中间如果进程崩溃，位置数据半写入
- 根因分析：位置 x/y 应在同一事务中写入
- 最小修复建议：使用 `set_batch` 替代两次 `set`
- 是否建议本次自动修复：**是**
- 需要补充的测试：验证 `_persist_position` 只触发一次 `set_batch` 调用

---

### BUG-F01：`custom_danmu_list_for_store` 等读操作未持 `_write_lock`，并发时可能数据不一致

- 严重等级：**P2**
- 影响功能：自定义弹幕池 Web API 列表查询 / 热路径 contains 检查
- 证据文件：[danmu_pool.py](file:///e:/test/danmu/app/danmu_pool.py)
- 证据代码：
  ```python
  # 第 327-356 行 — custom_danmu_list_for_store
  def custom_danmu_list_for_store(store, page, page_size, search, source):
      # 无 with store._write_lock
      total_row = store.conn.execute(
          f"SELECT COUNT(*) FROM custom_danmu_pool_entries WHERE {where}",
          params,
      ).fetchone()

  # 第 455-463 行 — custom_danmu_contains_text_for_store
  def custom_danmu_contains_text_for_store(store, text: str) -> bool:
      # 无 with store._write_lock
      row = store.conn.execute(
          "SELECT 1 FROM custom_danmu_pool_entries WHERE text = ? LIMIT 1",
          (value,),
      ).fetchone()
  ```
  对比 `custom_danmu_count_for_store` 正确使用了 `with store._write_lock`（第 321 行）
- 复现路径：
  1. HTTP 线程调用 `custom_danmu_list_for_store` 执行 SELECT
  2. 同时主线程调用 `custom_danmu_insert_many_for_store` 持 `_write_lock` 执行 INSERT + commit
  3. Python `sqlite3` 连接对象不是线程安全的——同一 `conn` 上的并发操作可能导致内部状态损坏
- 根因分析：`custom_danmu_count_for_store` 正确地使用了 `with store._write_lock`，但 `custom_danmu_list_for_store`、`custom_danmu_contains_text_for_store`、`custom_danmu_random_sample_for_store`、`get_custom_danmu_pool_for_store` 均未持锁
- 最小修复建议：对所有读操作也使用 `with store._write_lock`
- 是否建议本次自动修复：否
- 需要补充的测试：多线程并发读写自定义弹幕池，验证无 `ProgrammingError` / `OperationalError`

---

### BUG-F02：`custom_danmu_list_for_store` 中 search 参数未转义 LIKE 通配符

- 严重等级：**P2**
- 影响功能：自定义弹幕池 Web API 搜索功能
- 证据文件：[danmu_pool.py](file:///e:/test/danmu/app/danmu_pool.py)
- 证据代码：
  ```python
  # 第 342-345 行
  query = str(search or "").strip()
  if query:
      clauses.append("text LIKE ?")
      params.append(f"%{query}%")  # ← 未转义 % 和 _
  ```
- 复现路径：
  1. 用户在 Web 界面搜索框输入 `100%` 或 `_test`
  2. 搜索参数被拼成 `%100%%` 或 `%_test%`
  3. SQL LIKE 中 `%` 和 `_` 是通配符，用户输入的 `%` 被当作通配符而非字面量
  4. 搜索结果可能包含不匹配的条目
- 根因分析：`search` 参数直接嵌入 LIKE 模式，未对 `%` 和 `_` 进行转义
- 最小修复建议：
  ```python
  escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
  clauses.append("text LIKE ? ESCAPE '\\'")
  params.append(f"%{escaped}%")
  ```
- 是否建议本次自动修复：**是**
- 需要补充的测试：搜索包含 `%`、`_`、`\` 字符的弹幕文本，验证精确匹配

---

### BUG-F03：`set_custom_danmu_pool_for_store` 全量 DELETE + INSERT 无上限检查

- 严重等级：**P2**
- 影响功能：自定义弹幕池 Web API 批量替换
- 证据文件：[danmu_pool.py](file:///e:/test/danmu/app/danmu_pool.py)
- 证据代码：
  ```python
  # 第 478-496 行
  def set_custom_danmu_pool_for_store(store, items: list[str]) -> None:
      ...
      with store._write_lock:
          store.conn.execute("DELETE FROM custom_danmu_pool_entries")  # ← 全量删除
          if params:
              store.conn.executemany(  # ← 全量插入，无 20000 上限
                  "INSERT INTO custom_danmu_pool_entries ...",
                  params,
              )
          store.conn.commit()
  ```
- 复现路径：
  1. 用户通过 Web API 导入 20000+ 条弹幕
  2. `set_custom_danmu_pool_for_store` 先 DELETE 全表，再 INSERT 全量
  3. 在 `_write_lock` 持有期间，主线程所有 `config.set` / `config.get` 操作被阻塞
  4. 且 `params` 列表无 `CUSTOM_DANMU_POOL_MAX` 上限检查，可超过 20000 限制
- 根因分析：`set_custom_danmu_pool_for_store` 是全量替换接口，未限制 `items` 数量
- 最小修复建议：在 `params` 构建循环中加入上限检查：
  ```python
  if len(params) >= CUSTOM_DANMU_POOL_MAX:
      break
  ```
- 是否建议本次自动修复：**是**
- 需要补充的测试：传入 25000 条弹幕，验证只写入 20000 条

---

### BUG-F05：`ConfigStore.close()` 后 `get()` 仍可读取 `_cache`，返回可能过期的数据

- 严重等级：**P2**
- 影响功能：应用退出期间配置读取
- 证据文件：[config_store.py](file:///e:/test/danmu/app/config_store.py)
- 证据代码：
  ```python
  # 第 818-822 行
  def close(self):
      self._closed = True
      try:
          self.conn.close()
      except sqlite3.ProgrammingError:
          pass

  # 第 222-223 行
  def get(self, key: str, default: str = "") -> str:
      return self._cache.get(key, default)  # ← 不检查 _closed
  ```
- 复现路径：
  1. 应用退出时 `ConfigStore.close()` 被调用，`conn` 关闭
  2. 退出期间 HTTP 线程仍在处理请求，调用 `config.get()`
  3. `get()` 从 `_cache` 返回值，但此时缓存可能与 DB 不一致
  4. 更严重的是：如果 `close()` 后有 `set()` 调用，会尝试在已关闭的 `conn` 上执行 SQL，抛出 `ProgrammingError`
- 根因分析：`get()` 不检查 `_closed` 标志，`set()` 虽然会因 `ProgrammingError` 失败但不会静默跳过
- 最小修复建议：在 `get()` 中加入 `_closed` 检查（返回缓存值是安全的，但应记录警告）；在 `set()` / `set_batch()` 中检查 `_closed` 并提前返回
- 是否建议本次自动修复：否
- 需要补充的测试：验证 `close()` 后 `get()` 仍返回缓存值且不抛异常；`set()` 不抛 `ProgrammingError`

---

### BUG-G01：烂梗远程 API 默认禁用 SSL 证书验证，存在中间人攻击风险

- 严重等级：**P1**
- 影响功能：烂梗公式化远程采集
- 证据文件：[client.py](file:///e:/test/danmu/app/meme_barrage/client.py)
- 证据代码：
  ```python
  # 第 59 行
  def __init__(self, base_url: str = API_BASE, *, verify_ssl: bool = False) -> None:
      self._verify = verify_ssl
  # 第 66 行
  self._client = httpx.Client(
      headers=DEFAULT_HEADERS,
      verify=self._verify,  # 默认 False
      ...
  )
  ```
- 复现路径：
  1. 启用烂梗功能 → 采集定时器触发 → `MemeBarrageApiClient()` 默认 `verify_ssl=False`
  2. 所有 HTTPS 请求不验证证书
- 根因分析：`verify_ssl` 默认值为 `False`，且所有调用点均使用默认值
- 最小修复建议：将 `verify_ssl` 默认值改为 `True`
- 是否建议本次自动修复：**是**
- 需要补充的测试：验证 `MemeBarrageApiClient()` 默认实例的 `httpx.Client` 的 `verify` 为 `True`

---

### BUG-G02：`_tags_cache` 模块级全局缓存永不过期且无法刷新

- 严重等级：**P2**
- 影响功能：烂梗标签列表展示
- 证据文件：[meme_barrage.py](file:///e:/test/danmu/app/web_api/meme_barrage.py)
- 证据代码：
  ```python
  # 第 27 行
  _tags_cache: list[dict[str, str]] | None = None

  # 第 139-148 行
  def get_tags() -> dict[str, Any]:
      global _tags_cache
      if _tags_cache:           # 一旦有值就永不刷新
          return {"tags": _tags_cache}
      try:
          client = MemeBarrageApiClient()
          _tags_cache = client.dict_list()
      except Exception:
          _tags_cache = list(FALLBACK_TAGS)  # 失败也永久缓存 FALLBACK_TAGS
      return {"tags": _tags_cache}
  ```
- 复现路径：
  1. 首次调用 `get_tags()` → 远程 API 不可用 → `_tags_cache = FALLBACK_TAGS`
  2. 远程 API 恢复 → 再次调用 `get_tags()` → 仍返回 `FALLBACK_TAGS`
  3. 远程标签新增/变更 → 永远无法看到
- 根因分析：`_tags_cache` 无 TTL、无刷新机制；异常时也写入缓存导致错误数据永久驻留
- 最小修复建议：添加 TTL 过期机制（如 5 分钟），或在 `save_settings` 时清除缓存
- 是否建议本次自动修复：**是**
- 需要补充的测试：验证首次失败后缓存 FALLBACK_TAGS，后续成功请求能刷新缓存

---

### BUG-G05：烂梗 AI 识别模式与主链路共用 `ai_worker_pool`，无优先级或隔离

- 严重等级：**P2**
- 影响功能：烂梗 AI 识别展示 + 主链路 AI 请求
- 证据文件：[main_meme_mixin.py](file:///e:/test/danmu/app/main_meme_mixin.py)
- 证据代码：
  ```python
  # 第 262-272 行
  runnable = MemeAiSelectRunnable(
      worker=self.ai_worker,       # 复用主链路 AiWorker
      ...
  )
  ai_worker_pool().start(runnable)  # 复用主链路 worker pool
  ```
- 复现路径：
  1. 主链路 AI 请求正在执行
  2. 烂梗 AI 识别同时触发
  3. 两者竞争 `ai_worker_pool` 的线程槽
- 根因分析：烂梗 AI 识别与主链路共用 `ai_worker_pool`，无优先级或隔离机制
- 最小修复建议：为烂梗 AI 识别使用独立的 `QThreadPool`
- 是否建议本次自动修复：否（需要架构决策）
- 需要补充的测试：并发场景下主链路 AI 请求延迟测试

---

### BUG-G06：`_meme_display_tick` 递归调度无批次数限制

- 严重等级：**P2**
- 影响功能：烂梗弹幕展示
- 证据文件：[main_meme_mixin.py](file:///e:/test/danmu/app/main_meme_mixin.py)
- 证据代码：
  ```python
  # 第 310-348 行
  def _meme_display_tick(self) -> None:
      ...
      if self._meme_display_backlog:
          QTimer.singleShot(0, self._meme_display_tick)  # 递归调度
  ```
- 复现路径：
  1. backlog 很大（如 50 条）
  2. 每次 `_meme_display_tick` 只处理 2 条（`_MEME_DISPLAY_MAX_PER_TICK=2`）
  3. 产生 25 次 `QTimer.singleShot(0, ...)` 调用，造成事件循环密集调度
- 根因分析：`_meme_display_backlog` 使用混合访问模式，且递归调度没有批次数限制
- 最小修复建议：统一使用 `__dict__` 访问，或限制递归深度
- 是否建议本次自动修复：否
- 需要补充的测试：大 backlog 场景下的事件循环调度测试

---

### BUG-H02：`upload_github_release.ps1` 硬编码旧日期文件，新版本发布会找不到文件而报错

- 严重等级：**P1**
- 影响功能：GitHub Release 发布
- 证据文件：[upload_github_release.ps1](file:///e:/test/danmu/scripts/upload_github_release.ps1)
- 证据代码：
  ```powershell
  # 第 58 行
  if (-not $NotesFile) {
      $NotesFile = "docs\release\2026-05-29.md"   # 硬编码旧日期
  }
  # 第 80-83 行
  if (-not (Test-Path -LiteralPath $notesFull)) {
      Write-Error "Missing release notes: $notesFull"   # 文件不存在则报错退出
  }
  ```
- 复现路径：
  1. 不传 `-NotesFile` 参数执行 `upload_github_release.ps1`
  2. `docs\release\2026-05-29.md` 不存在
  3. 脚本报错 `Missing release notes` 并退出
- 根因分析：`NotesFile` 默认值硬编码为特定日期文件，每次发布需手动传参
- 最小修复建议：改为基于版本号动态查找（如 `docs/release/v{version}.md`），或允许无 notes-file 时使用空 notes
- 是否建议本次自动修复：**是**
- 需要补充的测试：不传 `-NotesFile` 时脚本应能正常完成

---

### BUG-H03：`velopack_runtime.py` 中 `app.run()` 异常时 `raise` 重新抛出，可能导致应用无法启动

- 严重等级：**P1**
- 影响功能：Velopack 安装版启动
- 证据文件：[velopack_runtime.py](file:///e:/test/danmu/app/velopack_runtime.py)
- 证据代码：
  ```python
  # 第 26-34 行
  try:
      app = velopack.App()
      app.on_before_uninstall_fast_callback(delete_user_data_if_requested)
      app.run()
      log_startup("velopack.done")
  except Exception as exc:
      log_startup("velopack.error", detail=str(exc))
      raise   # 重新抛出异常 → 应用崩溃
  ```
- 复现路径：
  1. Velopack 安装版启动
  2. `velopack.App()` 或 `app.run()` 抛出异常（如 Velopack 运行时版本不兼容、`Update.exe` 缺失等）
  3. 异常被 `raise` 重新抛出 → 应用无法启动
- 根因分析：Velopack 启动钩子的异常不应阻止应用主流程。`app.run()` 的主要职责是处理待应用的更新和注册卸载回调，失败不应导致应用无法使用
- 最小修复建议：将 `raise` 改为 `log_startup("velopack.error", ...)` 并 `return`，让应用继续启动
- 是否建议本次自动修复：**是**
- 需要补充的测试：模拟 `velopack.App()` 抛出异常时应用仍能正常启动

---

### BUG-H04：`supabase-config.js` 被打包排除，打包版永远无法从文件读取 Supabase 凭证

- 严重等级：**P1**
- 影响功能：打包版的 Supabase 更新检查
- 证据文件：[DanmuAI.spec](file:///e:/test/danmu/DanmuAI.spec) + [supabase_config.py](file:///e:/test/danmu/app/supabase_config.py)
- 证据代码：
  ```python
  # DanmuAI.spec 第 66-70 行
  datas += _collect_dir_datas(
      root / "web" / "static",
      "web/static",
      exclude_names=frozenset({"supabase-config.js"}),  # 排除凭证文件
  )

  # supabase_config.py 第 42-47 行
  config_path = resource_path("web", "static", "supabase-config.js")
  if not config_path.is_file():
      return None   # 打包版永远走到这里
  ```
- 复现路径：
  1. 打包版启动
  2. `get_supabase_credentials()` 尝试读取 `web/static/supabase-config.js`
  3. 文件不存在（被 spec 排除）→ 返回 `None`
  4. 若未设置环境变量 `DANMU_SUPABASE_URL`/`DANMU_SUPABASE_ANON_KEY`，Supabase 更新检查完全失效
- 根因分析：安全设计（排除凭证文件）与功能设计（读取凭证文件）矛盾。打包版只能通过环境变量配置 Supabase 凭证，但文档未明确说明此限制
- 最小修复建议：在 `PACKAGING_WINDOWS.md` 中明确说明打包版必须通过环境变量配置 Supabase 凭证，或在安装后首次运行时引导用户配置
- 是否建议本次自动修复：否（需要产品决策）
- 需要补充的测试：打包版无环境变量时验证更新检查的回退行为

---

### BUG-H05：`update_service.py` 中 `_manager()` 每次调用都创建新的 `UpdateManager` 实例

- 严重等级：**P2**
- 影响功能：Velopack 更新检查与下载
- 证据文件：[update_service.py](file:///e:/test/danmu/app/update_service.py)
- 证据代码：
  ```python
  # 第 66-69 行
  def _manager():
      import velopack
      return velopack.UpdateManager(UPDATE_FEED_URL)  # 每次新建
  ```
- 复现路径：
  1. 用户点击"检查更新" → `check_for_updates()` 创建 `UpdateManager` 实例 A
  2. 用户点击"下载更新" → `download_updates()` 创建实例 B
  3. 两个实例可能持有不同的更新状态
- 根因分析：`UpdateManager` 未缓存，每次操作创建新实例
- 最小修复建议：缓存 `UpdateManager` 实例，或在模块级别创建
- 是否建议本次自动修复：**是**
- 需要补充的测试：连续调用 `_manager()` 应返回相同实例

---

### BUG-H07：`uninstall_service.py` 中 `delete_user_data_if_requested` 仅检查 marker 文件名，未验证内容

- 严重等级：**P2**
- 影响功能：卸载时用户数据删除
- 证据文件：[uninstall_service.py](file:///e:/test/danmu/app/uninstall_service.py)
- 证据代码：
  ```python
  # 第 81-88 行
  def delete_user_data_if_requested() -> None:
      marker = _delete_marker_path()
      if not marker.exists():   # 仅检查文件是否存在
          return
      data_dir = _appdata_dir()
      if data_dir.name != APPDATA_DIR_NAME:
          return
      shutil.rmtree(data_dir, ignore_errors=True)  # 删除整个 %APPDATA%/DanmuAI/
  ```
- 复现路径：
  1. 任何程序或用户在 `%APPDATA%/DanmuAI/` 下创建 `.delete_data_on_uninstall` 空文件
  2. 用户正常卸载（未选择删除数据）
  3. `delete_user_data_if_requested` 检测到 marker 文件存在 → 删除所有用户数据
- 根因分析：marker 文件仅检查存在性，不验证内容
- 最小修复建议：在 `delete_user_data_if_requested` 中读取 marker 文件内容并验证包含 `delete-user-data=1`
- 是否建议本次自动修复：**是**
- 需要补充的测试：空 marker 文件不应触发数据删除

---

### BUG-I01：Supabase 反馈/错误报告速率限制可被 client_id 伪造绕过

- 严重等级：**P1**
- 影响功能：Supabase 反馈与错误报告速率限制
- 证据文件：[001_announcements_feedback.sql](file:///e:/test/danmu/supabase/migrations/001_announcements_feedback.sql), [supabase-client.js](file:///e:/test/danmu/web/static/supabase-client.js)
- 证据代码：
  ```sql
  -- 001_announcements_feedback.sql:46-57
  create or replace function public.feedback_insert_allowed(p_client_id uuid)
  returns boolean as $$
    select count(*)::int < 2
    from public.feedback
    where client_id = p_client_id
      and created_at > now() - interval '3 hours';
  $$;
  ```
  ```javascript
  // supabase-client.js:61-78
  function getOrCreateClientId() {
      let id = global.localStorage.getItem(STORAGE_CLIENT_ID);
      if (id && /^[0-9a-f-]{36}$/i.test(id)) return id;
      id = global.crypto?.randomUUID?.() || null;
      global.localStorage.setItem(STORAGE_CLIENT_ID, id);
      return id;
  }
  ```
- 复现路径：
  1. 获取 Supabase anon key（前端公开）
  2. 对 `/rest/v1/feedback` 发送 POST，每次使用不同的随机 `client_id` UUID
  3. 速率限制函数按 `client_id` 计数，每次新 UUID 计数从 0 开始
  4. 可无限提交反馈/错误报告
- 根因分析：`client_id` 完全由客户端控制，服务端无独立身份验证机制
- 最小修复建议：增加基于请求来源 IP 的辅助限制，或引入 Turnstile/hCaptcha 验证码
- 是否建议本次自动修复：否（需 Supabase 侧架构变更）
- 需要补充的测试：集成测试：用不同 `client_id` 连续 POST 5 次，验证至少部分被拒绝

---

### BUG-I02：`listAnnouncements()` 未在查询中过滤 `published=true`，完全依赖 RLS

- 严重等级：**P2**
- 影响功能：公告列表获取
- 证据文件：[supabase-client.js](file:///e:/test/danmu/web/static/supabase-client.js)
- 证据代码：
  ```javascript
  // supabase-client.js:154-159
  async function listAnnouncements() {
    const query =
      '/rest/v1/announcements?select=id,title,body,level,pinned,created_at,starts_at,ends_at' +
      '&order=pinned.desc,created_at.desc';
    return supabaseFetch(query, { method: 'GET' });
  }
  ```
- 复现路径：
  1. 若 Supabase RLS 被意外禁用或 `service_role` key 泄露
  2. 前端 `listAnnouncements()` 将返回所有未发布公告
- 根因分析：前端查询未添加 `&published=eq.true` 过滤条件，纵深防御缺失
- 最小修复建议：在查询 URL 中追加 `&published=eq.true&starts_at=lte.now()&or=(ends_at.is.null,ends_at.gt.now())`
- 是否建议本次自动修复：**是**
- 需要补充的测试：验证 `listAnnouncements` 查询参数包含 `published=eq.true`

---

### BUG-I03：Live Overlay SSE 端点无鉴权，本地任意进程可订阅实时弹幕

- 严重等级：**P2**
- 影响功能：直播弹幕层 SSE 推送
- 证据文件：[live_overlay.py](file:///e:/test/danmu/app/web_api/live_overlay.py)
- 证据代码：
  ```python
  # live_overlay.py:66-67
  @app.get("/api/live-overlay/events")
  async def live_overlay_events():
      # 无 check_token 调用
      queue: asyncio.Queue = asyncio.Queue(maxsize=64)
      hub.register(queue)
  ```
  对比同文件第 56-64 行的 test 端点有鉴权：
  ```python
  @app.post("/api/live-overlay/test")
  def live_overlay_test(...):
      check_token(authorization)  # ← 有鉴权
  ```
- 复现路径：
  1. 任何本机进程执行 `curl http://127.0.0.1:18765/api/live-overlay/events`
  2. 收到 SSE 流，包含所有实时弹幕内容，无需任何 token
- 根因分析：SSE 端点为 OBS 集成设计，EventSource API 不支持自定义 Header，因此未加鉴权
- 最小修复建议：参考 `diagnostics_events` 的模式，增加 query 参数 token 鉴权
- 是否建议本次自动修复：**是**
- 需要补充的测试：无 token 连接 SSE 应被拒绝；有效 token 应正常接收数据

---

### BUG-I04：`/api/preview/compress` 端点 `max_width` 和 `quality` 参数无边界校验

- 严重等级：**P3**
- 影响功能：图像压缩预览
- 证据文件：[preview_compress.py](file:///e:/test/danmu/app/web_api/preview_compress.py)
- 证据代码：
  ```python
  @app.post("/api/preview/compress")
  async def preview_compress(
      max_width: int = Form(768),    # ← 无上限校验
      quality: int = Form(85),       # ← 无上限校验
  ):
  ```
- 复现路径：
  1. 发送 POST `/api/preview/compress`，`max_width=100000`、`quality=100`
  2. PIL 将尝试创建超大分辨率图像或极高 JPEG 品质输出
- 根因分析：`max_width` 和 `quality` 直接从 Form 参数传入 PIL，无 clamp
- 最小修复建议：clamp `max_width = max(1, min(max_width, 4096))`，`quality = max(1, min(quality, 95))`
- 是否建议本次自动修复：**是**
- 需要补充的测试：传入 `max_width=999999, quality=100`，验证返回值被 clamp 到合理范围

---

### BUG-I05：`.vercel/project.json` 含 Vercel 项目/组织 ID 并已提交到仓库

- 严重等级：**P3**
- 影响功能：官网部署安全
- 证据文件：[project.json](file:///e:/test/danmu/website/.vercel/project.json)
- 证据代码：
  ```json
  {
    "projectId": "prj_PovUWNjveXJ3JNQQXa6S1Izp3ZbB",
    "orgId": "team_zGkpguvpUkbixUFl2pPlEW6m",
    "projectName": "danmuai-website"
  }
  ```
- 复现路径：`git clone` 仓库即可获得项目 ID 和组织 ID
- 根因分析：`.vercel/` 目录未被 `.gitignore` 排除
- 最小修复建议：将 `.vercel/` 加入 `.gitignore`，并从 git 历史中移除该文件
- 是否建议本次自动修复：**是**
- 需要补充的测试：无需测试

---

### BUG-J01：`FakeConfig.get_json()` 对非法 JSON 值无容错

- 严重等级：**P2**
- 影响功能：测试基础设施稳定性
- 证据文件：[fakes.py](file:///e:/test/danmu/tests/fakes.py)
- 证据代码：
  ```python
  # fakes.py:155-159
  def get_json(self, key: str, default=None):
      val = self.get(key)
      if not val:
          return default if default is not None else {}
      return json.loads(val)  # ← 若 val 不是合法 JSON，抛 JSONDecodeError
  ```
- 复现路径：
  1. 创建 `FakeConfig({"announcements_read_state": "not-valid-json"})`
  2. 调用 `config.get_json("announcements_read_state")`
  3. 抛出 `json.decoder.JSONDecodeError`
- 根因分析：生产代码 `ConfigStore.get_json()` 使用 SQLite 存储的 JSON 字符串，始终合法。但 `FakeConfig` 的 `values` dict 可被测试代码直接写入非 JSON 字符串
- 最小修复建议：在 `FakeConfig.get_json()` 中 wrap `json.loads` 的 `JSONDecodeError`，返回 `default`
- 是否建议本次自动修复：**是**
- 需要补充的测试：`FakeConfig({"k": "not-json"}).get_json("k")` 应返回 `{}` 而非抛异常

---

### BUG-J02：`conftest.py` 的 `tmp_path` fixture 覆盖了 pytest 内置 `tmp_path`

- 严重等级：**P3**
- 影响功能：测试基础设施兼容性
- 证据文件：[conftest.py](file:///e:/test/danmu/tests/conftest.py)
- 证据代码：
  ```python
  # tests/conftest.py:109-112
  @pytest.fixture
  def tmp_path(workspace_tmp) -> Path:
      """Alias for pytest builtins/plugins that request tmp_path."""
      return workspace_tmp
  ```
- 复现路径：使用第三方 pytest 插件依赖内置 `tmp_path` 的 `pathlib.Path` 行为时可能冲突
- 根因分析：覆盖内置 `tmp_path` 破坏了 pytest 的契约
- 最小修复建议：将 fixture 重命名为 `workspace_tmp` 并移除对 `tmp_path` 的覆盖
- 是否建议本次自动修复：否（需评估对现有测试的影响）
- 需要补充的测试：验证所有使用 `tmp_path` 的测试仍正常工作

---

## 4. 高风险但未确认问题

### HR-A01：`SingleInstanceGuard._listen_primary` 中 `removeServer` 可能在超时场景下移除正常实例的命名管道

- 证据文件：[single_instance.py](file:///e:/test/danmu/app/single_instance.py)
- 风险描述：`_activate_existing_instance` 使用 `waitForConnected(500)` 超时探测。在系统负载高时，合法的主实例可能无法在 500ms 内响应。此时 `_listen_primary` 失败后调用 `QLocalServer.removeServer(self._name)`，在 Windows 上会移除主实例的命名管道。
- 需要人工确认：在高负载 Windows 环境下快速双击 exe 两次，观察是否出现两个实例

### HR-A02：`quit()` 中 overlay.hide() 被调用两次

- 证据文件：[main_lifecycle_mixin.py](file:///e:/test/danmu/app/main_lifecycle_mixin.py)
- 风险描述：`stop()` 调用 `self.overlay.hide()`，而 `quit()` 在调用 `self.stop()` 后又调用 `self.overlay.hide()`。第二次 `hide()` 时 overlay 可能已处于半销毁状态。
- 需要人工确认：检查 `quit()` 路径中 overlay 的 `hide()` 是否在 `stop()` 之后仍安全

### HR-B01：`probe_exclusive_fullscreen_risk` 仅检测不修复，独占全屏游戏中 Overlay 不可见

- 证据文件：[win32_overlay_zorder.py](file:///e:/test/danmu/app/win32_overlay_zorder.py)
- 风险描述：在 DirectX 独占全屏模式下，`SetWindowPos(HWND_TOPMOST)` 无法覆盖游戏窗口，弹幕 Overlay 完全不可见。这是 Windows DWM 的已知限制。
- 需要人工确认：在全屏 DirectX 游戏（如原神全屏模式）中验证 Overlay 是否可见

### HR-B02：`DanmuEngine._pick_track` 加权随机在所有轨道满时可能导致弹幕堆积延迟

- 证据文件：[danmu_engine.py](file:///e:/test/danmu/app/danmu_engine.py)
- 风险描述：当所有轨道的 `rightmost_edge()` 都远超屏幕右边界时，新弹幕的 `x` 坐标被设为 `tail_edge + random.uniform(50, 250)`，可能远在屏幕外。用户感知为"弹幕停了"。
- 需要人工确认：在高密度弹幕场景下观察新弹幕的入屏延迟

### HR-C01：豆包 Responses `response.completed` 事件与 BUG-C01 修复的联动验证

- 证据文件：[doubao_responses_stream.py](file:///e:/test/danmu/app/doubao_responses_stream.py)
- 风险描述：修复 BUG-C01 后，需确认 `response.completed` 兜底路径在「只有 delta 没有 done」和「只有 done 没有 delta」两种场景下均正常工作
- 需要人工确认：修复 BUG-C01 后的完整流式场景测试

### HR-D01：`sounddevice` 在 Windows 独占模式下回调可能抛异常导致 Python 崩溃

- 证据文件：[mic_capture.py](file:///e:/test/danmu/app/mic_capture.py)
- 风险描述：PortAudio 回调中的异常会导致整个进程崩溃
- 需要人工确认：在 Windows 独占模式音频设备环境下测试麦克风采集稳定性

### HR-D02：`QwenTtsRealtimeAdapter` WebSocket 连接未显式关闭

- 证据文件：[tts_providers.py](file:///e:/test/danmu/app/tts_providers.py)
- 风险描述：`synthesize` 方法没有 `try/finally` 确保 `client.close()` 被调用
- 需要人工确认：模拟 `append_text` 抛异常后检查 WebSocket 连接是否泄漏

### HR-E01：PetWindow 动画定时器在窗口隐藏后未停止

- 证据文件：[pet_window.py](file:///e:/test/danmu/app/pet/pet_window.py)
- 风险描述：如果窗口被系统或其他代码隐藏（非通过 `hide_pet()`），定时器不会停止
- 需要人工确认：检查是否有代码路径在未调用 `hide_pet()` 的情况下隐藏了 PetWindow

### HR-F01：`ConfigStore._write_lock` 不是可重入锁，嵌套调用会死锁

- 证据文件：[config_store.py](file:///e:/test/danmu/app/config_store.py)
- 风险描述：`_write_lock = threading.Lock()` 是不可重入锁。如果同一线程内嵌套调用 `set()` → `set_batch()` → `with_write_lock()`，会死锁。当前代码路径中没有这种嵌套，但未来维护者可能引入。
- 需要人工确认：检查所有 `_write_lock` 的获取路径，确认无嵌套调用

### HR-F02：Fernet 密钥丢失后 `_key_regenerated` 标志仅在 `__init__` 中设置

- 证据文件：[config_store.py](file:///e:/test/danmu/app/config_store.py)
- 风险描述：如果运行期间 `.key` 文件被外部删除或损坏，后续 `_encrypted_get` 调用会因 `self._fernet` 仍持有旧密钥对象而继续工作，但新进程启动后将无法解密
- 需要人工确认：确认文档中已明确说明 `.key` 文件不可删除

### HR-F03：`custom_danmu_random_sample_for_store` 使用 `ORDER BY RANDOM()`，20000 行时性能差

- 证据文件：[danmu_pool.py](file:///e:/test/danmu/app/danmu_pool.py)
- 风险描述：`ORDER BY RANDOM() LIMIT ?` 在 SQLite 中需要全表扫描并生成随机数排序。20000 行时每次调用约需 10-20ms
- 需要人工确认：在 20000 行数据上实测 `ORDER BY RANDOM() LIMIT 8` 的耗时

### HR-G01：烂梗远程 API 硬编码 URL 和认证头

- 证据文件：[client.py](file:///e:/test/danmu/app/meme_barrage/client.py)
- 风险描述：`API_BASE = "https://hguofichp.cn:10086"` 和 `DEFAULT_HEADERS` 中的 `"Dpahjdoiaw": "danmuAi"` 均为硬编码。若远程 API 地址变更或认证方式更新，需要发版才能修复
- 需要人工确认：远程 API 的稳定性与长期可用性

### HR-H01：PyInstaller spec 的 `hiddenimports` 列表需与代码同步维护

- 证据文件：[DanmuAI.spec](file:///e:/test/danmu/DanmuAI.spec)
- 风险描述：新增 `app.*` 模块时若忘记同步此列表，打包版运行时会 `ModuleNotFoundError`
- 需要人工确认：每次 PR 新增 `app/` 下模块时，检查 `DanmuAI.spec` 是否同步更新

### HR-I01：Supabase `feedback`/`error_reports` 表无 admin SELECT/DELETE 策略

- 证据文件：[001_announcements_feedback.sql](file:///e:/test/danmu/supabase/migrations/001_announcements_feedback.sql)
- 风险描述：无 `authenticated` 或 `admin` 角色的 SELECT/DELETE 策略。管理员查看/删除反馈需使用 `service_role` key
- 需要人工确认：确认 Supabase 项目是否已通过 Dashboard 手动创建了 admin 策略

### HR-I02：FastAPI 应用未配置 CORS 中间件或安全响应头

- 证据文件：[web_console_runtime.py](file:///e:/test/danmu/app/web_console_runtime.py)
- 风险描述：未配置 `CORSMiddleware`，也未添加安全响应头。由于服务绑定在 `127.0.0.1`，当前无 CORS 风险，但若未来改为 `0.0.0.0` 将完全暴露
- 需要人工确认：确认服务是否始终绑定 `127.0.0.1`

### HR-I03：`GET /api/config` 端点无鉴权，返回完整配置

- 证据文件：[web_console_runtime.py](file:///e:/test/danmu/app/web_console_runtime.py)
- 风险描述：`GET /api/config` 无需 Bearer token 即可获取完整配置快照（含掩码 API Key）
- 需要人工确认：确认这是否为有意设计

### HR-J01：`scripts/run_acceptance_gates.py` 无单命令超时

- 证据文件：[run_acceptance_gates.py](file:///e:/test/danmu/scripts/run_acceptance_gates.py)
- 风险描述：`subprocess.run(cmd, ...)` 未设置 `timeout` 参数。若某个测试命令挂起，脚本将无限阻塞
- 需要人工确认：在 CI 中运行 `run_acceptance_gates.py`，确认所有命令都能在合理时间内完成

---

## 5. 性能与卡顿风险

### 5.1 启动速度

- **pywebview 子进程启动**：`webview_shell.py` 中 WebView2 冷启动可达 12-25 秒（`_FROZEN_LOAD_TIMEOUT_SEC = 25.0`），期间用户看到托盘图标但无主窗口。`_SLOW_START_PROMPT_SEC = 5.0` 后才显示"正在启动"提示。
- **建议**：将慢启动提示提前到 2 秒，或在托盘图标出现时立即显示"正在启动"气泡。

### 5.2 截图与 AI 请求

- **截图压缩**：`app/image_compress.py` 使用 PIL JPEG 压缩，`max_width=768, quality=85`。单次压缩通常 <50ms，但在高分辨率截图（如 4K）下可能超过 100ms。
- **AI 请求超时**：`ai_client.py` 使用 `httpx.Timeout(30.0, connect=5.0)`，重试最多 2 次。最坏情况下单次请求耗时 65 秒。

### 5.3 Overlay 渲染

- **FloatingPanelOverlay 慢路径**：见 BUG-B01。CJK 内容始终使用 `QPainterPath.addText`，单条长文本可达数百毫秒。
- **弹幕预渲染**：`_prepare_pixmaps_near_visible` 设计合理，但大量弹幕同时进入可视区时可能批量预渲染。

### 5.4 SQLite

- **WAL 模式**：`config_store.py` 使用 WAL + `busy_timeout=5000`，写操作通过 `_write_lock` 串行化。设计合理，但 `_write_lock` 是 `threading.Lock`（不可重入），嵌套调用会死锁（代码注释已警告）。
- **自定义弹幕库全量加载**：见 BUG-F03（无上限检查）和 HR-F03（ORDER BY RANDOM() 性能）。
- **danmu_pool 读操作未持锁**：见 BUG-F01。

### 5.5 外部接口

- **Supabase 查询**：`supabase_app_updates.py` 使用 300 秒缓存 + 8 秒超时，设计合理。
- **烂梗远程 API**：见 BUG-G01（SSL 验证默认关闭）和 BUG-G02（标签缓存永不过期）。
- **烂梗 AI 识别**：见 BUG-G05（与主链路共用 worker pool）。

---

## 6. 发布与更新风险

### 6.1 PyInstaller 打包

- **hiddenimports 维护**：见 HR-H01。当前列表覆盖了所有已知模块，但未来新增模块时有遗漏风险。
- **supabase-config.js 排除**：见 BUG-H04。安全设计与功能设计矛盾，打包版 Supabase 更新检查失效。

### 6.2 Velopack 更新

- **启动异常**：见 BUG-H03。`velopack_runtime.py` 中 `app.run()` 异常时 `raise` 重新抛出，可能导致应用无法启动。
- **UpdateManager 未缓存**：见 BUG-H05。每次操作创建新实例，可能导致状态不一致。
- **更新源 URL**：`velopack_config.py` 中 `UPDATE_FEED_URL` 硬编码且无 fallback。

### 6.3 发布脚本

- **GitHub Release 脚本**：见 BUG-H02。硬编码旧日期文件，新版本发布会找不到文件而报错。
- **R2 缓存策略**：见 BUG-H01。`DanmuAI-Setup.exe` latest 别名使用 `no-cache`，增加不必要的 R2 流量成本。

### 6.4 卸载与用户数据

- **卸载 marker 验证**：见 BUG-H07。仅检查文件存在性，不验证内容，存在用户数据误删风险。
- **配置数据库**：`%APPDATA%/DanmuAI/config.db`，Velopack 更新不修改用户数据目录。
- **加密密钥**：`%APPDATA%/DanmuAI/.key`，密钥丢失导致配置不可恢复。

### 6.5 MSI vs Setup.exe

- 当前发布脚本生成 Setup.exe + Portable.zip + nupkg，未生成 MSI。MSI 相关文档描述了切换计划，但当前发布脚本尚未实现。

---

## 7. 安全与隐私风险

### 7.1 API Key 安全

- **加密存储**：`config_store.py` 使用 Fernet 加密 API Key，设计合理。
- **密钥丢失**：上一轮 BUG-02 已确认，需确认是否已修复提示逻辑。
- **GET 掩码**：`web_api/custom_models.py` 中 GET 请求返回掩码 `apiKey`，设计合理。
- **日志脱敏**：`_redact_config_value_for_log` 对敏感配置键返回 `***`，设计合理。

### 7.2 Supabase 凭据

- **速率限制绕过**：见 BUG-I01。`client_id` 完全由客户端控制，速率限制可被零成本绕过。
- **公告查询纵深防御**：见 BUG-I02。前端查询未过滤 `published=true`，完全依赖 RLS。
- **RLS 依赖**：`supabase_app_updates.py` 使用 anon key + PostgREST 读取 `app_updates` 表，依赖 Supabase RLS 策略限制访问。

### 7.3 Web 控制台鉴权

- **随机 token**：`web_console.py` 启动时生成随机 token，写操作需 `Authorization: Bearer <token>`。
- **仅本机访问**：默认 `127.0.0.1:18765`，仅本机可访问。
- **SSE 端点无鉴权**：见 BUG-I03。Live Overlay SSE 端点无鉴权。
- **GET /api/config 无鉴权**：见 HR-I03。返回完整配置快照。

### 7.4 SSL 证书验证

- **烂梗远程 API**：见 BUG-G01。默认禁用 SSL 证书验证，存在中间人攻击风险。

### 7.5 其他

- **Vercel 项目 ID 泄露**：见 BUG-I05。`.vercel/project.json` 含项目/组织 ID 并已提交到仓库。
- **卸载 marker 验证**：见 BUG-H07。仅检查文件存在性，不验证内容。

---

## 8. 建议新增的测试

| 测试文件 | 测试目标 | 断言内容 |
|----------|----------|----------|
| `tests/test_lifecycle_stale_error.py` | `_on_ai_error` 陈旧请求守卫 | stop→start 快速切换后旧 AiRunnable 错误信号到达时，`_failure_backoff_paused` 和 `screenshot_timer` 不受影响 |
| `tests/test_lifecycle_capture_in_flight.py` | `_capture_in_flight` 在 `start()` 中重置 | stop→start 快速切换后 `_capture_in_flight` 为 False，截图正常调度 |
| `tests/test_doubao_stream_done.py` | 豆包 Responses 流 done 事件文本重复 | 先发 `delta:"hel"` 再发 `done.text:"hello"`（完整文本），断言结果为 `"hel"` 而非 `"helhello"` |
| `tests/test_ai_client_temperature_zero.py` | 豆包路径 temperature=0 | `temperature=0.0` 时豆包请求体包含 `"temperature": 0.0` |
| `tests/test_tts_playback_thread.py` | TTS 播放完成回调线程 | `_on_playback_finished` 始终在主线程执行 |
| `tests/test_floating_panel_dedup_ttl.py` | 悬浮窗去重窗口 TTL 过期 | TTL 过期后允许重复内容通过 |
| `tests/test_floating_panel_render_perf.py` | 悬浮窗 CJK 渲染性能 | CJK 内容使用 `drawText` 快路径 |
| `tests/test_danmu_pool_concurrent.py` | 自定义弹幕池并发读写 | 多线程并发读写无 `ProgrammingError` / `OperationalError` |
| `tests/test_danmu_pool_like_escape.py` | 弹幕池搜索 LIKE 转义 | 搜索包含 `%`、`_`、`\` 字符的弹幕文本，验证精确匹配 |
| `tests/test_danmu_pool_max_limit.py` | 弹幕池批量替换上限 | 传入 25000 条弹幕，验证只写入 20000 条 |
| `tests/test_meme_client_ssl.py` | 烂梗客户端 SSL 验证 | `MemeBarrageApiClient()` 默认实例的 `verify` 为 `True` |
| `tests/test_meme_tags_cache_ttl.py` | 烂梗标签缓存 TTL | 首次失败后缓存 FALLBACK_TAGS，后续成功请求能刷新缓存 |
| `tests/test_velopack_runtime_error.py` | Velopack 启动异常 | 模拟 `velopack.App()` 抛出异常时应用仍能正常启动 |
| `tests/test_uninstall_marker_content.py` | 卸载 marker 内容验证 | 空 marker 文件不应触发数据删除 |
| `tests/test_live_overlay_auth.py` | Live Overlay SSE 鉴权 | 无 token 连接 SSE 应被拒绝；有效 token 应正常接收数据 |
| `tests/test_announcements_filter.py` | 公告查询过滤 | `listAnnouncements` 查询参数包含 `published=eq.true` |
| `tests/test_preview_compress_bounds.py` | 压缩预览参数边界 | 传入 `max_width=999999, quality=100`，验证返回值被 clamp 到合理范围 |
| `tests/test_fake_config_get_json.py` | FakeConfig.get_json 容错 | `FakeConfig({"k": "not-json"}).get_json("k")` 应返回 `{}` 而非抛异常 |
| `tests/test_reply_parser_concat_json.py` | `}{` 拼接 JSON 解析 | `{"comments":["A"]}{"comments":["B"]}` 解析出所有弹幕 |
| `tests/test_config_store_close_safety.py` | ConfigStore.close() 安全性 | `close()` 后 `get()` 返回缓存值且不抛异常；`set()` 不抛 `ProgrammingError` |

---

## 9. 本次可自动修复项

以下问题满足自动修复条件（证据明确、修复范围小、不改变功能设计、可补充测试、可说明修改前后行为差异）：

| 编号 | 标题 | 修复内容 |
|------|------|----------|
| BUG-A01 | `_on_ai_error` 缺少陈旧请求守卫 | 在 `_pop_request_meta` 后增加 `if not meta: return` |
| BUG-A02 | `_capture_in_flight` 在 `start()` 中未重置 | 在 `start()` 中增加 `self._capture_in_flight = False` |
| BUG-C01 | 豆包 Responses 流 done 事件文本重复 | 在 `response.output_text.done` 分支增加 `if not collected:` 守卫 |
| BUG-C02 | 豆包路径 temperature=0 丢失 | 将 `if temperature:` 改为 `if temperature is not None and temperature >= 0:` |
| BUG-E03 | `_persist_position` 逐键写入 | 使用 `set_batch` 替代两次 `set` |
| BUG-F02 | LIKE 通配符未转义 | 对 `%`、`_`、`\` 进行转义并使用 `ESCAPE '\\'` |
| BUG-F03 | 弹幕池批量替换无上限 | 在 `params` 构建循环中加入 `CUSTOM_DANMU_POOL_MAX` 上限检查 |
| BUG-G01 | 烂梗远程 API SSL 验证默认关闭 | 将 `verify_ssl` 默认值改为 `True` |
| BUG-G02 | 烂梗标签缓存永不过期 | 添加 TTL 过期机制（5 分钟） |
| BUG-H03 | Velopack 启动异常阻止应用 | 将 `raise` 改为日志记录并 `return` |
| BUG-H07 | 卸载 marker 不验证内容 | 读取 marker 文件内容并验证包含 `delete-user-data=1` |
| BUG-I02 | 公告查询未过滤 published | 在查询 URL 中追加 `&published=eq.true` |
| BUG-I04 | 压缩预览参数无边界 | clamp `max_width` 和 `quality` |
| BUG-I05 | .vercel/project.json 泄露 | 将 `.vercel/` 加入 `.gitignore` |
| BUG-J01 | FakeConfig.get_json 无容错 | wrap `json.loads` 的 `JSONDecodeError`，返回 `default` |

---

## 10. 最终建议

### 优先级 1：修复豆包 Responses 流文本重复（BUG-C01）

- **理由**：影响所有使用豆包 API 的用户，弹幕文本重复是最直接的用户体验问题。现有测试用例因 done 事件的 text 恰好只含增量部分而未暴露此问题，说明 bug 一直潜伏。修复仅需一行守卫代码。
- **修复方案**：在 `doubao_responses_stream.py` 的 `response.output_text.done` 分支增加 `if not collected:` 守卫

### 优先级 2：修复 `_on_ai_error` 陈旧请求守卫缺失（BUG-A01）

- **理由**：stop→start 快速切换后，旧 AiRunnable 的致命错误（401/403）会立即暂停新会话。用户修改 API Key 后重新启动，却发现新会话立即被暂停，体验极差。W-RACE-001 修复仅覆盖了成功路径，错误路径遗漏。
- **修复方案**：在 `_on_ai_error` 的 `_pop_request_meta` 调用后，增加与 `_on_ai_reply` 一致的 `if not meta: return` 守卫

### 优先级 3：修复烂梗远程 API SSL 验证默认关闭（BUG-G01）

- **理由**：所有 HTTPS 请求默认不验证证书，存在中间人攻击风险。修复仅需将默认值从 `False` 改为 `True`，零成本高收益。
- **修复方案**：将 `MemeBarrageApiClient.__init__` 中 `verify_ssl` 默认值改为 `True`
