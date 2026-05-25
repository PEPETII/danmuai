# Changelog

## Unreleased

### Removed

- 遗留 Qt 主窗（`ui/`）及启动方式 `--qt-ui`、`--legacy-ui`、`DANMU_QT_UI`、`DANMU_WEB_CONSOLE=0`；请使用默认 Web 控制台

### Changed

- `DanmuApp` 始终启动 Web 控制台；废弃启动参数将 `sys.exit(2)` 并打印迁移说明
- `docs/qt6_ui_redesign_plan.md` 移至 `docs/archive/`（只读历史）

### Documentation

- 文档：移除对已删除 `prototype/scheme-e-*` 的当前态引用；统一默认 Web 控制台叙事
- 新增 `prototype/README.md`；更新 `AGENTS.md`、`README*.md`、`docs/ROADMAP*.md`、`docs/RELEASE_CHECKLIST*.md`、`docs/ARCHITECTURE*.md`、`CONTRIBUTING*.md`
- `docs/qt6_ui_redesign_plan.md`：标注 Phase 0 / `scheme-e` 为历史；Qt 令牌以 `ui/theme.py` 为准
- 隐私/安全/审计：`screen_index` 所选显示器全屏（修正「主屏 / screens[0]」过时表述）
- 架构：恢复场景指纹与 `live_freshness` 文档；删除「场景指纹已禁用」错误描述
- 用户文档：README / WEB_CONSOLE 补充 `DANMU_IMAGE_METRICS`、`DANMU_SCENE_DEBUG`；JPEG 压缩双入口说明；`scripts/` 索引
- 合规：`OPEN_SOURCE_AUDIT*`、`THIRD_PARTY_NOTICES.md` 补充 fastapi、uvicorn、pywebview

## 2026-05-24（Web 控制台迁入）

- **默认启动**：`python main.py` → pywebview + 本地 Web 控制台（`127.0.0.1:18765`）+ Qt Overlay/托盘，不再默认加载 Qt 主窗
- 新增 `app/web_console.py`、`app/webview_shell.py`、`web/static/`、`app/web_api/`（人格、自定义模型、`POST /api/preview/compress`）
- Web 页面：运行概览、助手设置（含节奏/截图/图像参数）、人格工坊、弹幕日记（多级别过滤/复制/自动滚动）、隐私
- `ui/main_window.py` 仅 `--qt-ui` / `DANMU_QT_UI=1` 加载，标记 **deprecated**
- 文档：`docs/WEB_CONSOLE.md`、更新 `README.md`、`AGENTS.md`、`docs/ARCHITECTURE.md`
- 测试：`test_web_persona_api.py`、`test_web_custom_models.py`、`test_image_compress.py`、`test_ui_mode.py`

## 2026-05-24（方案 E Qt UI）

- 主窗口 UI 全面切换为**方案 E（玻璃浅色）**：渐变背景、浮动侧栏、`GlassTopBar`、右下角 `LogDock`
- 新增 `ui/glass_frame.py`、`ui/glass_top_bar.py`、`ui/log_dock.py`；`ui/theme.py` 增加 `USE_LEGACY_THEME` 回退开关
- 新增 HTML 原型 `prototype/scheme-e-*.html`、`scheme-e-tokens.css`；`ui_preview.html` 指向主壳预览
- 更新 `AGENTS.md`、`docs/ARCHITECTURE.md`、`README.md` 等文档以反映 UI 结构；详见 `docs/qt6_ui_redesign_plan.md`

## 2026-05-17

- 项目许可证从 MIT 更改为 GPL-3.0+，与 PyQt6 (GPL-3.0) 和 python-Levenshtein (GPL-2.0+) 的 copyleft 要求一致
- `LICENSE` 更新为 GPL v3 摘要 + 第三方依赖许可证声明
- `README.md` 补充项目状态、环境要求（Python ≥ 3.12、Windows）、已知限制；修复所有本地绝对路径为仓库相对路径
- `CONTRIBUTING.md` 修复本地绝对路径
- `docs/OPEN_SOURCE_AUDIT.md` 补充第三方依赖许可证审计表，更新许可证口径为 GPL-3.0+
- `.env.example` 明确标注为参考模板，桌面应用不自动加载
- `.gitignore` 补齐 `.agents/`、`.trae/`、`skills-lock.json`、`test_icon.png`
- 移除 `log/`、`.coverage`、`__pycache__/`、`.pytest_cache/`、`.npmcache/`、`scratchpad.md`、`skills-lock.json`、`test_icon.png` 等无关文件
- 初始化 Git 仓库
- 整理 `docs/`：移除 9 个内部过程文档（ISSUE_TRACKER、OPTIMIZATION_PLAN、产品需求文档、技术架构文档、技术问题解决方案、测试用例文档、需求文档、项目决策框架、项目管理文档），保留 5 个公开文档
- 新增 `.github/ISSUE_TEMPLATE/bug_report.md`、`.github/ISSUE_TEMPLATE/feature_request.md`、`.github/PULL_REQUEST_TEMPLATE.md`
- 新增 `THIRD_PARTY_NOTICES.md` 第三方依赖许可证声明
- 新增 `docs/RELEASE_CHECKLIST.md` 发布检查清单

## 2026-05-16

- 新增标准 MIT `LICENSE`
- 重写 `README.md`，补齐安装、运行、隐私、FAQ、贡献和许可证说明
- 新增 `CONTRIBUTING.md`、`SECURITY.md`、`.gitignore`、`.env.example`
- 新增 `docs/PRIVACY.md`、`docs/ROADMAP.md`、`docs/ARCHITECTURE.md`、`docs/OPEN_SOURCE_AUDIT.md`
- 修复默认截图逻辑，改为使用配置区域而非全屏
- 增加首启配置提示、退出清理、截图失败重调度、暂停时队列清理
- 引入 AI 回复解析与固定 5 条标准化逻辑
- 增补 pytest 测试覆盖回复约束、首启提示、异常释放和过期丢弃
