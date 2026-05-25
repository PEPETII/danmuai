# AGENTS.md — DanmuAI 桌面弹幕工具

## 当前 UI 事实

- 默认 `python main.py` → Web 控制台 + pywebview + Qt Overlay/托盘
- **新功能仅加在** `web/static/` 与 `app/web_api/`（`routes.py` 注册）
- 已移除遗留 Qt 主窗；`--qt-ui` / `--legacy-ui` / `DANMU_QT_UI` / `DANMU_WEB_CONSOLE=0` → `sys.exit(2)`
- Overlay (`app/overlay.py` + `app/danmu_engine.py`) 始终运行，与控制台 UI 无关

## 架构

```text
python main.py
├─ DanmuApp（main.py）          — 单例 QObject，状态机、截图、AI、回复队列、托盘
├─ uvicorn 线程                 — app/web_console.py（127.0.0.1:18765）
├─ pywebview 线程               — app/webview_shell.py（桌面壳）
├─ web/static/                  — 默认控制台 UI（index.html、app.js、warm-tokens.css）
├─ app/web_api/                 — 人格、自定义模型、压缩预览、麦克风测试路由
└─ DanmuOverlay（app/overlay.py）— Qt 透明置顶弹幕（始终启用）
```

**线程模型**（agent 容易搞错）：
- 截图在**主线程**（`QTimer` 1s）
- AI 请求在 `QThreadPool`（`MAX_IN_FLIGHT=1`）
- HTTP 线程写 Qt 对象**必须**走 `WebConsoleBridge` 信号或 `QTimer.singleShot(0, ...)` 到主线程
- `keyboard` 回调经 `_ToggleBridge` 到主线程

**扩展 API**：`app/web_api/routes.py` 在 `web_console` 上注册；人格/模型逻辑复用 `PersonaManager`、`TemplateManager`、`validate_model_config`

## 核心模块速查

| 模块 | 职责 |
|------|------|
| `app/ai_client.py` | 双 API：`doubao` → `/responses` 流式；`openai` → `/chat/completions` SSE |
| `app/danmu_engine.py` | 多轨道 Track；`_pick_track` 加权随机（非轮询） |
| `app/overlay.py` | Qt 透明置顶渲染；16ms QTimer 有动画时 60fps |
| `app/live_freshness.py` | 过时丢弃、截图退避、本地兜底批次 |
| `app/scene_fingerprint.py` | 灰度 hash 场景代际；freshness TTL loose 12s / medium 8s / strict 5s |
| `app/memory/` + `app/memory_prompt_builder.py` | 场景状态记忆 + 弹幕去重；`memory_mode`: off / dedup_only / scene_card / strong |
| `app/scene_memory.py` | 兼容 re-export（`SceneMemoryStore`、`memory_window_from_config`） |
| `app/reply_parser.py` | AI 回复 JSON 解析与标准化 |
| `app/reply_queue.py` | `AIReplyFIFOBuffer` + 自适应延迟 100–1000ms |
| `app/config_store.py` | SQLite `%APPDATA%/DanmuAI/config.db`，Fernet 加密 Key，WAL + 写锁 |
| `app/mic_service.py` | 麦克风模式门面；`mic_mode_enabled` / `MicService` |
| `app/mic_utterance.py` | RMS 语音端点检测（无 VAD 库），4 状态机 |
| `app/mic_capture.py` | `sounddevice` 录音；`mic_encode.py` → WAV data URI |
| `app/mic_prompt.py` | 麦克风插入提示词组装 |
| `app/model_providers.py` | 服务商预设与校验；`is_doubao_mode`、`model_likely_supports_mic_audio` |
| `app/model_catalog.py` | 模型目录与定价元数据（Web 控制台模型选择器） |
| `app/translations.py` | 中英翻译表；`Translator.set_language()` 在 `DanmuApp.__init__` 调用 |
| `app/image_compress.py` | PIL + JPEG + Base64，max_width 768 quality 85，无临时文件 |
| `app/danmu_pool.py` | 本地弹幕库 `data/danmu_pool_zh.json`（1000 条，见 `scripts/extract_danmu_pool.py`） |
| `app/lifetime_stats.py` | 持久累计统计（弹幕/运行时长/Token），`stop()` 时并入 |

## 运行与测试

```bash
pip install -r requirements.txt
python main.py                         # Web + pywebview + Overlay
python main.py --web-browser           # 系统浏览器打开控制台
python -m pytest tests/ -v --tb=short  # 全量测试
```

### 提交前分批验证（来自 CONTRIBUTING.md）

```bash
python -m pytest tests/test_reply_parser.py tests/test_p0_main_flow.py tests/test_danmu_engine.py tests/test_config_store.py tests/test_ai_client.py -q
python -m pytest tests/test_web_console.py tests/test_web_persona_api.py tests/test_web_custom_models.py tests/test_image_compress.py tests/test_ui_mode.py -q
python -m pytest tests/ -q
```

### 测试约定

- **临时目录**：项目根 `.pytest_tmp/`（`conftest.py` 重定向 `TMP`/`TEMP`，避免 `%TEMP%\pytest-of-*` 权限问题；根 `conftest.py` 先执行，`tests/conftest.py` 再细分 per-test 子目录）
- **共享假对象**：`tests/fakes.py`（`FakeTimer`、`FakeEngine`、`FakeConfig`、`FakeLogger` 等）
- **最小 DanmuApp**：`DanmuApp.__new__(DanmuApp)` + `bind_minimal_danmu_app(app, **overrides)`（`tests/conftest.py`）
- **勿** `from test_p0_main_flow import ...`（无包前缀 collection 时报 `ModuleNotFoundError`）
- **轨道选择**：`_pick_track` 为加权随机，需 `monkeypatch` `random.choices` 才能断言确定性轨道
- **Overlay 单测**：需 `QApplication` + `overlay.show()` + `processEvents()`；`_target_interval_ms()` 在不可见时返回 `0`
- **pytest `basetemp`**：`pytest.ini` 未设；实际目录取自 `tests/conftest.py` 的 `pytest_configure`

CI：`.github/workflows/ci.yml` — Python 3.12 `windows-latest`

## 关键陷阱

- **加密锁死**：丢失 `%APPDATA%/DanmuAI/.key` → 已加密 Key 不可恢复
- **弹幕截断**：15 中文字 / 40 英文字 + `...`
- **本地公式化弹幕库**：`danmu_pool_enabled=0` 时全应用禁用 `danmu_pool_zh.json`（AI 补齐、轻量兜底、同屏补足）；`min_on_screen` 默认 5，仅开关开启时生效，**0** 关闭补足
- **去重**：`deque(30)` + `recent_exact_set` + Levenshtein `dedup_threshold=0.5`
- **失败退避**：连续 5 次暂停；401/403/402 立即暂停
- **输出 token 下限**：普通 ≥512，thinking ≥1024
- **全屏截图**：`ScreenCapturer.grab()` 按 `screen_index` 截全屏；`region_*` 未参与裁剪
- **Web 写配置**：`PUT /api/config` → bridge 信号 → 主线程 `apply_config_patch`；**勿在 HTTP 线程直接改 Qt 对象**
- **GET 自定义模型**：返回掩码 `apiKey`
- **Overlay 窗口标志**：`FramelessWindowHint | WindowStaysOnTopHint | Tool | BypassWindowManagerHint` + Win32 `WS_EX_LAYERED | WS_EX_TRANSPARENT`
- **无 Qt 主窗**：`setQuitOnLastWindowClosed(False)`；托盘退出 → `DanmuApp.quit()`

## 环境变量速查

| 变量 | 作用 |
|------|------|
| `DANMU_API_SCHEDULE_DEBUG=1` | API 调度日志 |
| `DANMU_MIN_API_INTERVAL_MS` | 防 API 冷启动连打（默认 800） |
| `DANMU_IMAGE_METRICS=1` | 压缩指标 debug 日志 |
| `DANMU_SCENE_DEBUG=1` | 场景探测与丢弃日志 |
| `DANMU_DEDUP_PROFILE=1` | 去重统计 `/api/status.dedup_profile` |
| `DANMU_WEB_LAUNCH=browser` | 等同 `--web-browser` |

## 改动决策树

```text
配置、人格、模型、日志 UI → web/static/ + app/web_api/
弹幕显示、轨道、性能      → app/overlay.py + app/danmu_engine.py
麦克风、语音              → app/mic_*.py
视觉稿                    → prototype/Qwen_*（Web only）
```

视觉规范：`prototype/Qwen_markdown_20260525_4vyxmv819.md`、`prototype/Qwen_html_20260524_481u8vlmv.html`

## 文档

- [docs/WEB_CONSOLE.md](docs/WEB_CONSOLE.md) — Web API 与页面地图
- [docs/MEMORY_SYSTEM_PLAN.md](docs/MEMORY_SYSTEM_PLAN.md) — 记忆系统四档与场景切换策略
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 架构细节
- 文档与源码不一致时，以 `main.py` 与 `app/` 源码为准
