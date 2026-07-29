# DanmuAI UI Design System

> **权威实现**：`web/static/warm-tokens-base.css`（Token 数值）  
> **入口加载**：`web/static/warm-tokens.css`（@import 链，见 W-UI-CSS-SPLIT-001）  
> **规范草稿来源**：`docs/danmuai_ui_repair_docs/03_UI_DESIGN_SYSTEM_SPEC.md`  
> **改 UI 检查清单**：[UI_CHANGE_CHECKLIST.md](UI_CHANGE_CHECKLIST.md)  
> **Agent 强制规则**：根目录 `AGENTS.md` →「UI 修改强制规则」

文档说明语义与用法；**冲突时以 CSS 为准**。

---

## 1. 设计目标

DanmuAI 控制台面向直播与游戏场景：温馨、柔和、信息清晰、长时间不疲劳、浅/深色一致、小窗口可用。

**关键词**：温馨 · 治愈 · 圆润 · 轻盈 · 清晰 · 稳定 · 可信  

**禁止**：赛博朋克、高饱和霓虹、纯黑大面积背景、夸张动效、每页不同风格、随机按钮尺寸。

---

## 2. 权威来源与文件地图

### 2.1 单一来源

```text
权威：CSS 语义 / 品牌 Token（warm-tokens-base.css :root + [data-theme="dark"]）
布局：Tailwind 工具类或 .ui-* 语义布局类
组件：warm-tokens-components.css（.ui-button / .ui-field / .ui-control …）
页面：warm-tokens-pages*.css / settings / feedback 等拆分文件
兼容：warm-tokens-compat.css（历史选择器；禁止在 partial 再堆 <style>）
禁止：页面另起品牌色、partial 内联 <style> 定义通用视觉
```

### 2.2 当前 CSS 拆分

| 文件 | 职责 |
|------|------|
| `warm-tokens.css` | 唯一 `<link>` 入口，@import 顺序固定 |
| `warm-tokens-base.css` | **Token + 通用 .card / .btn-primary** |
| `warm-tokens-layout.css` | 壳层 / 侧栏 / 主区 |
| `warm-tokens-components.css` | `.ui-button*` / `.ui-field*` / `.ui-control*` 等 |
| `warm-tokens-compat.css` | 兼容层（如 `.legacy-api-fields`） |
| `warm-tokens-dark.css` | 深色补充覆盖（Token 主体在 base） |
| `warm-tokens-feedback.css` | 反馈 / 公告 / 模态框 |
| `warm-tokens-pages.css` | 内容页壳层（弹幕池、人设、设置、指南等） |
| `warm-tokens-pages-overview.css` | 总览页 / session log / 状态 pill |
| `warm-tokens-pages-stylegen.css` | 样式生成器折叠面板 |
| `warm-tokens-settings.css` | 设置页 tabs / accordion / stepper |
| `warm-tokens-danmu-pool.css` | 弹幕池分类 / 采集配置 |
| `warm-tokens-live-output.css` | 直播伴侣设置 / 连接状态 |
| `warm-tokens-live-output-preview.css` | 弹幕样式预览 / overlay 步骤 |

修改 partial / template 后必须：

```bash
python web/static/build_index_html.py
```

---

## 3. Token（以 base.css 为准）

### 3.1 品牌与表面（浅色 `:root`）

当前仓库使用 **`--color-primary*`** 作为品牌主色名（规范草稿中的 `--color-brand*` 为别名目标，**实现以 primary 为准**）。

| Token | 当前值 | 用途 |
|-------|--------|------|
| `--color-primary` | `#ffa5a5` | 主品牌色 |
| `--color-primary-hover` | `#ff8585` | 主色悬停 |
| `--color-primary-light` | `#ffc8c8` | 主色浅底 |
| `--color-primary-rgb` | `255, 165, 165` | 阴影/rgba |
| `--color-secondary` | `#ffe5d9` | 次级暖色 |
| `--color-accent` | `#fff2cc` | 点缀 |
| `--color-bg` | `#fdfbf7` | 页面底 |
| `--color-bg-subtle` | `#faf6f0` | 浅底 |
| `--color-surface` | `#ffffff` | 卡片/控件面 |
| `--color-text` / `--color-text-primary` | `#5d5757` | 主文 |
| `--color-text-muted` | `#6b7280` | 次文 |
| `--color-text-dim` | `#9ca3af` | 弱文 |
| `--border` | `#e5e7eb` | 默认边框 |
| `--tooltip-bg` / `--tooltip-fg` | `#5d5757` / `#ffffff` | Tooltip |

**语义别名**（组件应优先引用）：

| 语义 Token | 映射 |
|------------|------|
| `--surface-page` | `var(--color-bg)` |
| `--surface-subtle` | `var(--color-bg-subtle)` |
| `--surface-card` | `var(--color-surface)` |
| `--surface-control` | `var(--input-bg)` |
| `--surface-overlay` | `rgba(253, 251, 247, 0.72)` |
| `--text-primary` | `var(--color-text-primary)` |
| `--text-secondary` | `var(--color-text-muted)` |
| `--text-muted` | `var(--color-text-dim)` |
| `--text-on-brand` | `#ffffff` |
| `--border-default` | `var(--border)` |
| `--border-soft` | `rgba(93, 87, 87, 0.12)` |
| `--border-brand` | `rgba(var(--color-primary-rgb), 0.35)` |

### 3.2 深色 `[data-theme="dark"]`（摘录）

| Token | 当前值 |
|-------|--------|
| `--color-bg` | `#1c1917` |
| `--color-bg-subtle` | `#231f1c` |
| `--color-surface` | `#292524` |
| `--color-text` / `--color-text-primary` | `#f5f0eb` |
| `--color-text-dim` / `--color-text-muted` | `#a8a29e` |
| `--border` | `#57534e` |
| `--tooltip-bg` / `--tooltip-fg` | `#3f3a36` / `#f5f0eb` |
| `--surface-overlay` | `rgba(28, 25, 23, 0.78)` |
| `--border-soft` | `rgba(255, 255, 255, 0.10)` |
| `--border-brand` | `rgba(var(--color-primary-rgb), 0.42)` |

状态色浅/深均有声明（`--color-success|warning|info|danger` 与 `--status-*-bg`）。新 Token **必须**同时定义浅色与深色。

### 3.3 间距 / 圆角 / 控件高 / 动效

与 base.css 一致（4px 网格）：

```text
--space-0 … --space-12
--radius-xs 0.375rem | sm 0.5rem | md 0.75rem | lg 1.5rem | full 9999px
--control-height-sm 2rem | md 2.5rem | lg 3rem
--motion-fast 120ms | normal 200ms | slow 300ms
--ease-standard cubic-bezier(0.4, 0, 0.2, 1)
```

阴影（实现名）：

```text
--shadow-warm / --shadow-warm-hover / --shadow-btn
```

（规范草稿中的 `--shadow-card*` 对应实现的 `--shadow-warm*`。）

### 3.4 规则

- 禁止纯黑 `#000` 作正文或大面积背景。
- 禁止页面级 `--pet-pink` 一类命名；用语义 Token。
- `var(--token)` 必须已声明或带 fallback；由 `tests/test_ui_token_contract.py` 门禁。
- 禁止无依据的随机 px（7/13/19…），除非光学校正并注释。

---

## 4. 布局与断点

| 宽度 | 壳层行为 |
|------|----------|
| ≥ 1200px | 完整侧栏 |
| 960–1199px | 窄侧栏 |
| < 960px | 抽屉导航 |
| < 720px | 主区 padding 收紧（`--space-4`） |

实现：`warm-tokens-layout.css` + `modules/responsive-shell.js`（任务 G）。

页面结构优先：

```html
<header class="ui-page-header">…</header>
<section class="ui-section">…</section>
```

---

## 5. 组件契约（摘要）

| 组件 | 类名 | 要点 |
|------|------|------|
| Button | `.ui-button` + `--primary/secondary/danger/ghost` + `--sm/md/lg` | 一区最多一个 primary；兼容 `.btn-primary` 双 class |
| Field | `.ui-field` / `__label` / `__hint` | 不用 placeholder 代替 label |
| Control | `.ui-control` + `.ui-input/.ui-select/.ui-textarea` | 高度走 control-height Token |
| Card | `.ui-card` / `.card` | **静态禁止 hover translateY** |
| Interactive card | `.ui-card--interactive` | 仅真可点击；允许轻微 `translateY(-2px)` |
| Tabs / Accordion / Toggle | 现有 settings / content 模式 | ARIA 与任务 E–F 约定 |

完整 ARIA / 深色验收见 03 规范 §5–§7；实现以 components + pages CSS 为准。

---

## 6. Tailwind 边界

**允许**：flex/grid、响应式、`min-width:0`、显隐、过渡期间距。  

**禁止新增**：用 `bg-warmPink` / `bg-blue-50` / `rounded-xl px-6 py-2` 等拼出完整业务按钮视觉——应使用 `.ui-button*`。

---

## 7. 构建与测试

```bash
python web/static/build_index_html.py
python -m pytest tests/test_ui_token_contract.py tests/test_ui_component_contract.py \
  tests/test_ui_partial_hygiene.py tests/test_ui_theme_init.py \
  tests/test_ui_responsive_shell.py tests/test_console_theme.py tests/test_ui_mode.py -q -x
```

- **禁止**本地全量 `pytest tests/`（见 `AGENTS.md` §7）。
- **Playwright / 浏览器 E2E**：可选独立 `ui-tests`，**不得**写入主 `requirements.txt`。

---

## 8. 组件预览页（后续）

建议开发向 `/components-preview`（Token 色板、按钮/表单/卡片/浅深色）。**当前未实现**；新组件可先靠契约测试 + 真机控制台验收。

---

## 9. Definition of Done（UI 任务）

- [ ] 未引入新视觉体系；语义 Token + 已有组件
- [ ] 浅色 / 深色；小窗口无横向溢出
- [ ] 改的是 partial/template，并已 `build_index_html`
- [ ] 定向 UI 测试通过
- [ ] 截图或明确 **NOT VERIFIED**
- [ ] 新增 Token/组件时同步本文件
