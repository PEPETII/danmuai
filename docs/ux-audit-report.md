# DanmuAI UX 审计报告

> 审计日期：2026-06-19
> 审计范围：Web 控制台前端（`web/static/`）、Web API（`app/web_api/`）、Overlay（`app/overlay.py`、`app/danmu_engine.py`）、桌面壳（`app/webview_shell.py`）、托盘（`app/tray.py`）
> 审计方法：基于 Nielsen 启发式评估与 WCAG 2.1 标准，对现有代码进行静态分析

---

## UX 问题列表

### 问题1：主按钮文字对比度严重不足

- **文件/组件**：`web/static/warm-tokens-base.css`（`--color-primary: #ffa5a5`）、`warm-tokens-components.css`（`.btn-primary`）
- **严重程度**：高
- **问题描述**：主操作按钮（"生成弹幕"、"保存配置"、"保存设置"等）使用白色文字（#fff）叠加暖粉背景（#ffa5a5），对比度仅约 1.9:1，远低于 WCAG AA 要求的 4.5:1（正常文字）和 3:1（大文字）。hover 状态（#ff8585）下白色文字对比度约 2.2:1，同样不合格。低视力用户几乎无法辨认按钮文字。
- **改进建议**：将主按钮文字色改为深色（如 `#5d5757` 项目主文字色或 `#4a3f3f`），或将按钮背景显著加深至满足 4.5:1 对比度的暖色调。

### 问题-2：模态框无焦点陷阱与 Escape 关闭

- **文件/组件**：`web/static/partials/modals.html`（5 个模态框）、`web/static/app.js`（模态框控制逻辑）
- **严重程度**：高
- **问题描述**：所有 5 个模态框（modelModal、restoreDefaultsModal、errorReportModal、appUpdateModal、rewardModal）均无 JavaScript 焦点陷阱，Tab 键可跳出模态框聚焦背景元素，违反 WCAG 2.1 SC 2.4.3 和 ARIA dialog pattern。同时，所有模态框均不支持 Escape 键关闭，用户必须点击特定按钮，键盘用户操作受阻。仅 errorReportModal 支持点击背景关闭。
- **改进建议**：为每个模态框添加焦点陷阱（拦截 Tab/Shift+Tab 使焦点循环在模态框内），添加 Escape 键关闭处理，打开时将焦点移至模态框首个交互元素，关闭时将焦点归还触发元素。

### 问题3：破坏性操作无确认对话框

- **文件/组件**：`web/static/modules/persona.js`（删除人格）、`web/static/modules/danmu-pool-page.js`（删除自定义弹幕）、`web/static/modules/meme-barrage.js`（清除梗弹幕库）
- **严重程度**：高
- **问题描述**：删除人格、清除梗弹幕库、删除选中自定义弹幕三项操作均为不可逆破坏性操作，但点击按钮后直接执行，无确认对话框或二次确认机制。一次误点击即可永久删除用户数据。
- **改进建议**：对所有破坏性操作添加确认对话框，包含操作说明与"确认/取消"选项。可复用 restoreDefaultsModal 的确认模式（含取消选项的专用模态框）或使用浏览器原生 `confirm()`。

### 问题4：侧边栏无移动端折叠机制

- **文件/组件**：`web/static/partials/sidebar.html`、`web/static/warm-tokens-layout.css`
- **严重程度**：高
- **问题描述**：侧边栏固定 256px 宽（`w-64 shrink-0`），无汉堡菜单、无响应式折叠断点。在小于约 1024px 的屏幕上，侧边栏占据大部分视口宽度，主内容区被挤压或溢出。CSS 中无任何 `@media` 规则处理侧边栏折叠。整个布局假设桌面视口。
- **改进建议**：添加 768px 断点折叠侧边栏，在移动端显示汉堡按钮切换展开/收起。使用 `@media` 规则或 Tailwind `md:hidden` / `md:flex` 控制。初始状态移动端侧边栏默认收起。

### 问题-5：504 错误 dict-detail 在前端渲染为 `[object Object]`

- **文件/组件**：`app/web_api/routes.py`（504 超时错误）、`web/static/modules/transport.js`（`formatApiError`）
- **严重程度**：高
- **问题描述**：routes.py 中的 504 超时错误使用 `detail={"ok": False, "error": "main_thread_timeout", "detail": "主线程操作超时..."}` dict 格式，这是全项目唯一使用 dict-detail 的错误。前端的 `formatApiError()` 仅处理字符串和数组两种格式，收到 dict 时 `String(detail)` 产出无意义的 `[object Object]`，用户看到的是乱码而非中文提示。
- **改进建议**：将 504 错误 detail 改为普通字符串 `"主线程操作超时，请稍后重试。"`，与项目其他错误格式保持一致；或在 `formatApiError` 中增加 dict 类型处理逻辑（提取 `detail.detail` 字段）。

### 问题-6：保存配置超时错误丢失中文消息

- **文件/组件**：`app/web_console_runtime.py`（`JSONResponse` 直接返回）、`web/static/modules/transport.js`（`apiFetch` 错误解析）
- **严重程度**：高
- **问题描述**：保存配置超时/错误通过 `JSONResponse` 直接返回 `{"ok": False, "error": "save_timeout", ...}`，绕过了 FastAPI 的标准 `HTTPException` 包装（无 `detail` 键）。前端 `apiFetch` 读取 `err.detail` 时得到 `undefined`，最终回退到 `res.statusText`（英文 "Gateway Timeout"），丢失了原本包含的可操作中文消息。
- **改进建议**：将 `JSONResponse` 错误改为标准 `HTTPException`，使 detail 字段存在；或在前端 `apiFetch` 中增加兜底逻辑：当 `err.detail` 缺失时检查 `err.error` 或 `err.message` 字段。

### 问题7：Toast 通知无 ARIA live region 与动画

- **文件/组件**：`web/static/index.html`（`<div id="toast">`）、`web/static/app.js`（`showToast`）
- **严重程度**：中
- **问题描述**：Toast 元素 `<div id="toast">` 无 `role="status"` 或 `aria-live="polite"` 属性。屏幕阅读器不会播报 Toast 中的成功/错误消息，用户可能错过关键操作反馈。此外 Toast 无入场/退场动画，出现和消失都很突兀；多条 Toast 互相覆盖，无堆叠机制。
- **改进建议**：为 Toast 元素添加 `role="status" aria-live="polite"`。添加 CSS transition（淡入/淡出或滑入）。支持多条 Toast 堆叠显示（设置不同延迟或使用 Toast 容器队列）。

### 问题8：modelModal 缺少 ARIA dialog 属性

- **文件/组件**：`web/static/partials/modals.html`（`#modelModal`）
- **严重程度**：中
- **问题描述**：模型配置模态框 `#modelModal` 缺少 `role="dialog"` 和 `aria-modal="true"`，与其他 4 个模态框不一致。屏幕阅读器无法将其识别为对话框，用户无法理解当前交互上下文已切换到模态框。
- **改进建议**：为 `#modelModal` 添加 `role="dialog"` 和 `aria-modal="true"` 属性，以及 `aria-labelledby` 指向模态框标题元素。

### 问题9：灰色辅助文字对比度不足

- **文件/组件**：`web/static/warm-tokens-base.css`（`--color-text-dim: #9ca3af`）、`web/static/warm-tokens-pages.css`（`.log-line.DEBUG`）
- **严重程度**：中
- **问题描述**：`text-dim` 色 #9ca3af（gray-400）叠加暖白背景 #fdfbf7，对比度仅约 3.0:1，不满足 WCAG AA 对正常文字的 4.5:1 要求。此色用于统计卡片标签、辅助描述文字、DEBUG 日志行等大量场景。`text-muted` #6b7280 对比度约 4.2:1，对小字体仍可能不合格。
- **改进建议**：将 `--color-text-dim` 调深至满足 4.5:1（如 #737373 即 gray-500 偏深或 #6b7280），或将背景色微调降低亮度。日志 DEBUG 行可使用与 INFO 行相同的文字色。

### 问题10：多数保存/操作按钮无加载状态

- **文件/组件**：`web/static/app.js`（各保存按钮）、`web/static/modules/settings.js`、`web/static/modules/persona.js`
- **严重程度**：中
- **问题描述**：除错误报告提交按钮（有"发送中..."文字变更）和弹幕朗读试听按钮（有状态提示）外，所有保存/操作按钮（保存配置、保存主题、保存昵称、保存人格、测试连接、保存弹幕库设置等）在异步操作期间无任何视觉反馈——无 spinner、无文字变更、无禁用态。用户可能重复点击或误以为操作未生效。
- **改进建议**：建立统一的按钮加载态模式：点击后显示 spinner 或文字变更为"保存中..."，同时设置 `disabled` 防止重复点击。可抽取为 `withLoadingState(btn, promise)` 通用函数。

### 问题11：设置标签栏无键盘箭头导航

- **文件/组件**：`web/static/partials/settings.html`（标签栏 `role="tablist"`）、`web/static/modules/settings-tabs.js`（标签切换逻辑）
- **严重程度**：中
- **问题描述**：设置标签栏使用 `role="tablist"` + `role="tab"` ARIA 模式，但不支持箭头键导航（ARIA tabs pattern 要求左/右箭头在标签间移动焦点）。用户必须逐个 Tab 跳过所有标签才能到达目标标签。
- **改进建议**：添加 ArrowLeft/ArrowRight 键盘事件监听，按 ARIA tabs pattern 在相邻标签间移动焦点；Home/End 键跳至首/末标签；激活标签可通过 Enter/Space 触发导航。

### 问题12：侧边栏 hover 与 active 状态视觉相同

- **文件/组件**：`web/static/warm-tokens-layout.css`（侧边栏按钮样式）
- **严重程度**：低
- **问题描述**：侧边栏按钮的 hover 和 `.active` 状态使用相同的背景色和文字色（`var(--color-accent)` 背景 + `var(--color-primary-hover)` 文字），用户 hover 当前激活项时无法区分 hover 反馈和已选中状态。
- **改进建议**：为 `.active` 状态添加额外的视觉区分，如左侧指示条、更深的背景色、或加粗文字。hover 状态可使用更浅的背景色。

### 问题13：统计卡片 hover 动画创造虚假可点击暗示

- **文件/组件**：`web/static/warm-tokens-base.css`（`.card:hover` translateY + shadow）
- **严重程度**：低
- **问题描述**：统计卡片 hover 时上浮 4px 并增强阴影，这是典型的可交互元素视觉暗示。但统计卡片本身不可点击，hover 动画误导用户认为卡片有交互功能。
- **改进建议**：移除统计卡片的 hover 上浮动画，仅保留微弱阴影变化；或将 hover 动画仅应用于真正可交互的卡片（如人格卡片）。

### 问题14：CSS transition 使用 `all` 关键字

- **文件/组件**：`web/static/warm-tokens-base.css`（`.btn-primary`、`.card`）
- **严重程度**：低
- **问题描述**：按钮和卡片使用 `transition: all 0.3s ease` / `transition: all 0.3s cubic-bezier(...)`，而非指定具体属性。`all` 会监听所有 CSS 属性变更（包括 layout 属性），可能触发不必要的重排动画和性能开销。
- **改进建议**：将 `transition: all` 改为 `transition: transform, box-shadow, background-color, border-color` 等具体属性列表。

### 问题15：Google Fonts 缺少 `display=swap`

- **文件/组件**：`web/static/index.html`（Nunito 字体 `<link>` 第18行）
- **严重程度**：低
- **问题描述**：Google Fonts 加载链接未包含 `&display=swap` 参数。在字体下载完成前，文字可能使用不可见替代（FOIT - Flash of Invisible Text），而非先显示系统字体再替换（FOT - Flash of Unstyled Text），导致页面初始短暂空白文字区。
- **改进建议**：在 Google Fonts URL 末尾添加 `&display=swap`。

### 问题16：暗色模式覆盖不完整

- **文件/组件**：`web/static/warm-tokens-dark.css`（暗色覆盖规则）
- **严重程度**：中
- **问题描述**：多个 Tailwind 色值类缺少暗色模式覆盖：
  - `bg-blue-50`（统计卡片图标底色，overview.html 第82行等）
  - `bg-amber-50`（提示/麦克风区域）
  - `text-amber-700` / `text-amber-900`（提示文字）
  - `text-sky-700`（麦克风活动源横幅）
  - `text-red-600`（桌宠资产错误）
  - `border-amber-200`
  
  暗色模式下这些区域仍显示亮色背景或浅色文字，造成视觉冲突和对比度问题。
- **改进建议**：为所有遗漏的色值类添加 `[data-theme="dark"]` 覆盖规则，或使用 CSS 自定义属性统一管理（避免 Tailwind 色值类与自定义属性的双轨维护风险）。

### 问题17：浏览器前进/后退导航不工作

- **文件/组件**：`web/static/app.js`（`navigate` 函数，第386-451行）
- **严重程度**：中
- **问题描述**：页面导航基于 hash（`location.hash`），初始化时读取 hash 定位页面（第542-543行），但未注册 `hashchange` 事件监听。浏览器前进/后退按钮改变 hash 后不会触发页面切换，用户无法用浏览器导航回到之前查看的页面。
- **改进建议**：注册 `window.addEventListener('hashchange', () => navigate(location.hash.replace('#', '')))`，使浏览器前进/后退按钮生效。考虑使用 History API（`pushState`）替代 hash 路由以获得更干净的 URL。

### 问题-18：桌面窗口关闭被静默阻断

- **文件/组件**：`app/webview_shell.py`（`on_closing` 返回 `True`）
- **严重程度**：中
- **问题描述**：pywebview 窗口的 `on_closing` 处理器始终返回 `True`，阻止窗口关闭。用户点击窗口关闭按钮后没有任何反馈——窗口不关闭、无提示、无解释。这是设计意图（应用在托盘继续运行），但缺乏用户沟通。
- **改进建议**：在 `on_closing` 中注入 JS 弹出一个非阻断式提示（如 Toast）："窗口已最小化到系统托盘，右键托盘图标可退出"，然后隐藏窗口而非阻止关闭事件。或改为 `on_closing` 隐藏窗口并返回 `False`。

### 问题-19：弹幕文字截断过短且无预览

- **文件/组件**：`app/danmu_engine.py`（`DEFAULT_DANMU_MAX_CHARS_ZH = 15`）、`app/reply_parser.py`
- **严重程度**：中
- **问题描述**：AI 回复弹幕默认截断为 15 个中文字符 + "..." 后缀，对有意义的回复内容截断过于激进。截断后仅显示 "..." 无任何关于被省略内容的信息。公式化弹幕虽不受截断限制，但 AI 生成的回复几乎总是被截断。
- **改进建议**：考虑将默认截断上限从 15 提升至 20-25（可在 Web 设置中调整当前 5-80 范围已支持）；或为截断弹幕添加"展开查看完整内容"的交互机制（如长按/右键显示原文）。

### 问-题20：Overlay 在独占全屏模式下可能静默消失

- **文件/组件**：`app/win32_overlay_zorder.py`（`probe_exclusive_fullscreen_risk`）
- **严重程度**：中
- **问题描述**：当游戏使用独占全屏模式（DirectX）时，OS 可能抑制 Overlay 的置顶窗口。`probe_exclusive_fullscreen_risk` 能检测此风险，但检测结果未向用户通报——Overlay 静默消失，用户无法理解为何弹幕不再显示。
- **改进建议**：当检测到独占全屏风险时，通过托盘气泡或 Web 控制台通知用户："当前检测到独占全屏模式，弹幕 Overlay 可能无法显示。建议切换为窗口化/无边框全屏模式。"

### 问题-21：弹幕入区过载时静默丢弃

- **文件/组件**：`app/danmu_engine.py`（`entry_zone_overloaded`、`add_text` 返回 None）
- **严重程度**：低
- **问题描述**：当弹幕入区（右侧入口区）排队数超过 300 条上限时，新弹幕直接被丢弃（`add_text` 返回 None），无任何视觉或日志反馈给用户。高峰期间弹幕数量突然减少，用户无法得知原因。
- **改进建议**：在入区过载时向 Web 控制台 `/api/status` 报告丢弃计数（如 `dropped_by_cap`），前端统计面板可显示丢弃量；或在日志中记录丢弃事件。

### 问题-22：托盘更新流程无下载进度

- **文件/组件**：`app/tray.py`（`_on_check_update`）
- **严重程度**：低
- **问题描述**：更新流程使用连续 QMessageBox 对话框（发现新版本→确认下载→下载完成→确认重启），下载期间无进度指示，用户面对空白等待对话框无反馈。
- **改进建议**：下载期间显示进度对话框（带进度条和取消按钮），而非静默等待后弹窗。可使用 QProgressDialog 或自定义进度界面。

### 问题-23：卸载流程连续 3 个确认对话框

- **文件/组件**：`app/tray.py`（`_on_uninstall`）
- **严重程度**：低
- **问题描述**：卸载流程依次弹出 3 个模态确认对话框：确认卸载→是否删除用户数据→再次确认删除数据不可逆。连续模态对话框交互疲劳，用户体验繁琐。
- **改进建议**：合并为单步对话框，包含"卸载（保留数据）"和"卸载并删除数据"两个选项按钮加"取消"，一步完成所有决策。

### 问题-24：WebView 冷启动 10 秒无持续反馈

- **文件/组件**：`app/webview_shell.py`（`_maybe_prompt_slow_webview_start`）
- **严重程度**：中
- **问题描述**：WebView2 冷启动时，用户面对 10 秒空白等待后才弹出"桌面窗口启动较慢，是否改用系统浏览器？"的提示。期间仅有一个托盘气泡"Web 控制台正在启动"（3 秒后消失），无持续进度指示。
- **改进建议**：在等待期间显示持续性进度提示（如托盘气泡持续显示 + 倒计时更新），或在主窗口背景上渲染"正在加载..."文字。5 秒时提前提示而非 10 秒。

### 问题-25：英文错误标识泄漏给中文用户

- **文件/组件**：`app/font_registry.py`（`font_registry_disabled`、`font_not_found`）、`app/web_api/routes.py`（`main_thread_timeout`）
- **严重程度**：低
- **问题描述**：部分后端错误标识以英文字符串直接返回前端：`"font_registry_disabled"`（503）、`"font_not_found"`（404）、`"main_thread_timeout"`（504 dict key）。中文用户看到这些英文标识无法理解含义。
- **改进建议**：所有用户可见错误信息统一使用中文描述；或在前端维护错误码→中文消息映射表。

### 问题-26：Overlay 安全过滤器仅接受 CJK 字符

- **文件/组件**：`app/danmu_pool_overlay.py`（`is_overlay_safe`）
- **严重程度**：低
- **问题描述**：Overlay 安全过滤要求弹幕包含 CJK 字符才放行，纯英文或中英混合的自定义公式化弹幕可能被拒绝显示，即使用户有意添加。这对国际用户或双语场景不合理。
- **改进建议**：放宽 CJK 要求，改为"至少包含 2 个非空白字符"（当前已有最小长度检查），或允许用户在设置中切换安全过滤级别。

### 问题27：Opacity 设置为 0 时 Overlay 完全隐形无警告

- **文件/组件**：`app/overlay.py`（`_global_opacity_factor`）
- **严重程度**：低
- **问题描述**：用户将 Overlay 透明度设为 0% 时，弹幕完全隐形但 Overlay 窗口仍在运行（消耗资源）。无任何警告提示用户此设置会导致弹幕不可见。
- **改进建议**：在 Web 设置中，当 opacity 输入值接近 0 时显示提示："透明度为 0 时弹幕将完全不可见"；或在保存配置时检测 opacity=0 并弹出确认。

### 问题28：启动异常对话框显示原始异常信息

- **文件/组件**：`main.py`（`global_exception_hook`）、`app/main_launch.py`
- **严重程度**：低
- **问题描述**：全局异常钩子使用 `QMessageBox.critical` 显示原始异常值，对普通用户而言技术性过强、难以理解。已做 API key 脱敏处理，但 traceback 本身仍可能暴露内部模块名和行号。
- **改进建议**：异常对话框分为两层：用户层显示友好中文描述（如"程序遇到意外错误，已自动保存运行状态"），并提供"查看技术详情"折叠按钮；技术层仅对高级用户或开发者展开。

### 问题29：Toast 通知无入场/退场动画

- **文件/组件**：`web/static/index.html`（Toast 元素）、`web/static/app.js`（`showToast` 函数）
- **严重程度**：低
- **问题描述**：Toast 通知通过 `classList.add/remove('show')` 切换 `display:none/block`，无淡入/滑入/淡出动画。出现和消失都很突兀，缺乏视觉过渡，降低感知流畅度。
- **改进建议**：使用 CSS `transition` 或 `@keyframes` 动画实现 Toast 入场（从顶部滑入 + 淡入）和退场（淡出 + 向上滑出），替代 `display` 切换。

### 问题30：设置表单缺乏自定义验证反馈样式

- **文件/组件**：`web/static/partials/settings.html`、`web/static/modules/settings.js`
- **严重程度**：低
- **问题描述**：设置表单依赖浏览器原生验证（`type="number"` 的 `min/max/step`），无自定义错误样式（如红色边框、错误提示文字）。`required` 字段为空时仅显示浏览器默认验证气泡，风格与项目整体设计不协调。
- **改进建议**：为表单输入添加自定义验证反馈 CSS 类（`.field-error` 红色边框 + 下方提示文字），在 JS 中实现字段级验证逻辑与视觉反馈。

### 问题31：侧边栏无 skip-nav 链接

- **文件/组件**：`web/static/partials/sidebar.html`、`web/static/index.html`
- **严重程度**：中
- **问题描述**：页面无 "跳至主内容"（skip-nav）链接。键盘用户必须逐个 Tab 穿过所有侧边栏按钮（约 11 个导航项 + 底部版本信息区）才能到达主内容区，操作效率极低。
- **改进建议**：在 `<body>` 开头添加隐藏的 skip-nav 链接 `<a href="#main" class="skip-nav">跳至主内容</a>`，CSS 默认隐藏、聚焦时显示（`position:absolute; left:-9999px; focus:left:0; z-index:999`）。

### 问题32：双轨颜色定义维护风险

- **文件/组件**：`web/static/warm-tokens-base.css`（CSS 自定义属性）、`web/static/index.html`（Tailwind config 扩展，第20-36行）
- **严重程度**：低
- **问题描述**：颜色值同时在 CSS 自定义属性（`--color-primary` 等）和 Tailwind config 扩展（`warmPink` 等）中定义，形成双轨维护。修改一处时需同步修改另一处，否则不一致。当前两者值一致，但长期维护风险存在。
- **改进建议**：统一为单一轨道。优先使用 CSS 自定义属性，Tailwind config 通过 `theme.extend.colors` 引用 CSS 变量值而非硬编码；或反过来只使用 Tailwind config，CSS 组件类引用 Tailwind 类名。

### 问题33：侧边栏导航项使用 `<button>` 而非 `<a>`

- **文件/组件**：`web/static/partials/sidebar.html`
- **严重程度**：低
- **问题描述**：导航项使用 `<button>` 元素而非 `<a>`，不支持右键"在新标签页打开"、鼠标悬停链接预览、浏览器历史等标准链接行为。因当前使用 hash 路由无真实 URL，`<button>` 在功能上可行，但不符合 Web 导航惯例。
- **改进建议**：改用 `<a href="#page-name">` 并在 JS 中拦截 click 事件执行导航（`preventDefault` + `navigate`），保留链接语义和浏览器标准交互。

### 问题34：错误横幅关闭按钮缺少 `aria-label`

- **文件/组件**：`web/static/partials/overview.html`（errorBanner `×` 按钮，第31行）
- **严重程度**：低
- **问题描述**：错误横幅的关闭按钮仅包含 `×` 字符，无 `aria-label` 属性。屏幕阅读器用户可能听到无意义的"times"或空内容，无法理解按钮功能。
- **改进建议**：添加 `aria-label="关闭错误提示"` 或等效中文描述。

### 问题35：WebSocket 连接数上限导致无限重连循环

- **文件/组件**：`app/web_console_ws.py`（`_WS_MAX_*_CONSUMERS = 10`）、`web/static/modules/transport.js`
- **严重程度**：中
- **问题描述**：WebSocket 消费者上限为 10，超出时以 close code 1008（"连接数已满"）拒绝。前端收到 1008 后执行刷新 session + 重连（transport.js 第487-489行），但重连立即再次撞到同一上限，形成无限重连循环且无用户可见消息解释原因。
- **改进建议**：前端收到 1008 时停止自动重连，改为显示用户可见提示："WebSocket 连接数已达上限，请关闭其他控制台窗口后刷新"；或在后端实现连接排队/共享机制而非硬上限拒绝。

### 问题36：API 后端静默钳位值无反馈

- **文件/组件**：`app/web_api/danmu_pool.py`（`min_on_screen` 钳位 0-50）、`app/web_api/meme_barrage.py`（间隔/批量钳位）
- **严重程度**：中
- **问题描述**：`min_on_screen` 等设置值在后端被静默钳位到合法范围（如用户输入 100 变为 50），无任何反馈告知用户实际保存的值与输入不同。用户可能认为自己的设置已保存，实际值已被修改。
- **改进建议**：API 返回中包含实际保存的值（当前部分接口已返回 `get_meta()` 对象含实际值），前端在保存后刷新显示为实际值而非用户输入值；或在响应中增加 `clamped_fields` 信息提示哪些字段被调整。

### 问题37：PermissionError 映射为 400 而非 403

- **文件/组件**：`app/web_api/routes.py`（异常处理）
- **严重程度**：低
- **问题描述**：`PermissionError` 被捕获并返回 `status_code=400`（Bad Request），而非 HTTP 语义正确的 403（Forbidden）。前端对 401/403 自动刷新 session 并重试，而 400 仅显示错误消息。真正的权限问题应告知用户"权限不足"而非"请求无效"。
- **改进建议**：将 `PermissionError` 映射为 `status_code=403`，前端相应区分处理（不重试，显示权限不足提示）。

---

## 综合建议

1. **最优先：修复主按钮对比度（问题1）**。白色文字叠加 #ffa5a5 背景的 1.9:1 对比度是全 UI 最严重的可用性问题，直接影响所有用户的操作体验。修复成本低（改色值），收益高。

2. **次优先：建立模态框交互规范（问题2+3+8）**。当前 5 个模态框的交互行为不一致（有的支持背景点击关闭、有的不支持；有的有 ARIA 属性、有的没有），且均无焦点陷阱和 Escape 关闭。破坏性操作无确认对话框是数据安全风险。建议统一模态框交互标准：焦点陷阱 + Escape 关闭 + 打开/关闭焦点管理 + ARIA dialog 属性，并为所有破坏性操作添加确认步骤。

3. **第三优先：修复 API 错误格式断裂（问题5+6）**。504 dict-detail 和 JSONResponse bypass 两处错误格式不一致导致用户看到 `[object Object]` 或英文状态码而非中文提示，是最直接的功能性 UX bug，修复确定性高。
