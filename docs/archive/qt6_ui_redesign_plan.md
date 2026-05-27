> **归档说明**：Qt 主窗（`ui/`、`--qt-ui`）已于 2026-05 从仓库移除，仅供历史查阅。当前 UI 见 [WEB_CONSOLE.md](../WEB_CONSOLE.md)。

# DanmuAI Qt6 UI 重设计计划 — 方案 E（玻璃浅色）

> **注意**：生产默认 UI 已改为 **Web 控制台**（`web/static/`、`docs/WEB_CONSOLE.md`）。本文档仅描述 **已移除的遗留 Qt 主窗**，供历史对照。

**状态**：Qt 方案 E 已实现；Web 为当前标准 UI  
**约束**：仅 UI / 布局 / QSS；不改核心业务、API、弹幕生成；不删功能入口。

### 文档状态 / 仓库事实（2026-05）

- `prototype/` 现仅保留 Qwen Web 原型（`Qwen_html_*.html`、`Qwen_markdown_*.md`）；索引见 [prototype/README.md](../../prototype/README.md)。
- **`prototype/scheme-e-*`、`scheme-e-tokens.css`、`scheme-e-app.css`、`prototype/README.md`（旧版）、根目录 `ui_preview.html` 已从仓库移除**（历史见 git）。
- 原 Qt 设计令牌曾以 **`ui/theme.py`** 为准；`ui/` 目录已删除。
- 下文 Phase 0 及附录中的 `scheme-e` 路径为**历史记录**，勿当作当前待创建文件。

---

## 设计锚点（方案 E）

| 元素 | 表现 | Qt 落地 |
|------|------|---------|
| 工作区背景 | 浅紫/粉/蓝渐变 | `paintEvent` + `QLinearGradient` |
| 侧栏 | 浮动圆角玻璃面板，与内容区间隙 | `QHBoxLayout` 外边距 + `GlassSidebar` |
| 顶栏 | 人格名 + 运行时长 + 胶囊开始/停止 | `ui/glass_top_bar.py` |
| 卡片 | 半透明白 + 圆角 16px + 轻阴影 | QSS + 可选 `QGraphicsDropShadowEffect` |
| 主按钮 | 深色胶囊 `#0f172a` | 替换 `#175cd3` 企业蓝 |
| 日志 | 右下角半透明浮窗 | `ui/log_dock.py` |
| 强调色 | `#4f46e5` | 选中态 / 链接 |

**限制**：QSS 无 `backdrop-filter`；先「伪玻璃」（半透明 + 边框），Phase 6 可选真模糊。

### 设计令牌（历史：`prototype/scheme-e-tokens.css`，曾以 `ui/theme.py` 为准）

```css
--e-bg-gradient: linear-gradient(135deg, #e0e7ff 0%, #fce7f3 40%, #dbeafe 100%);
--e-glass-bg: rgba(255, 255, 255, 0.72);
--e-glass-border: rgba(255, 255, 255, 0.85);
--e-text: #0f172a;
--e-accent: #4f46e5;
--e-pill-bg: #0f172a;
--e-radius-lg: 16px;
--e-sidebar-w: 220px;
--e-dock-bg: rgba(15, 23, 42, 0.78);
```

---

## 当前 UI 结构（历史）

```
MainWindow (main.py)
├── SidebarNavigation (240px 深色贴边)
└── QStackedWidget (#f4f7fb)
    ├── [0] ControlPanel      — start/stop 信号
    ├── [1] SettingsPanel     — config + ApiProbeController
    ├── [2] LogPanel          — SanitizedLogger
    └── [3] TemplateEditor    — PersonaManager
```

**不可破坏契约**（移除前）：

- 四页索引 0–3 与 `tests/test_main_window_navigation.py` 一致
- `control_panel.start_clicked` / `stop_clicked` → `DanmuApp`
- `sidebar.set_active(1)` 触发 `settings_panel.refresh()`

---

（下文 Phase 0–6 及附录为原始实施记录，未改写。）
