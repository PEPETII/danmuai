# DanmuAI 新手优先 UI/UX 原型

这是一个与现有应用完全隔离的静态交互原型，用来确认新的信息架构、首屏层级和高级功能入口。

## 如何查看

直接双击 `index.html` 即可。也可以在仓库根目录运行：

```powershell
python -m http.server 8765 --directory .\ui-ux-prototype
```

然后访问 `http://127.0.0.1:8765/`。

## 建议重点体验

1. 首屏是否能在 30 秒内说明“看画面 → 懂内容 → 发弹幕”。
2. 点击“30 秒快速设置”，体验模型、画面、弹幕感觉三步流程。
3. 点击“开始生成弹幕”，观察运行状态、预览和本场数据变化。
4. 展开侧栏“高级功能与工具”，确认专业能力仍然可达。
5. 打开“全部功能”，搜索“模型”“日志”“直播”“字体”等关键词。
6. 查看“设计说明与验收”，按建议脚本做首次用户测试。
7. 缩窄浏览器到手机宽度，检查抽屉导航；切换浅色 / 黑夜模式。

## 文件

- `index.html`：应用壳、首屏、功能中心、设置向导与功能详情弹窗。
- `styles.css`：独立视觉 token、响应式布局、浅色 / 黑夜模式和动效。
- `app.js`：24 项功能映射、筛选、导航和纯内存演示状态。
- `feature-map.md`：逐项功能分类、当前入口与建议入口。

## 设计原则

- 首屏只解决“这是什么、怎样开始、当前是否在运行”。
- 核心功能常驻；增强功能按需进入；专业参数放进明确的高级入口。
- “全部功能”作为完整性兜底，每项能力均可搜索并查看当前入口映射。
- 复用 DanmuAI 的暖色、圆角卡片和 paw 标记，但不引用生产样式或脚本。
- 不用网络依赖，不需要构建工具，可通过 `file://` 打开。

## 隔离边界

- 不修改、不加载 `web/static/` 下的生产页面、模块、locale 或样式。
- 不调用 `/api/*`、WebSocket、Supabase、模型服务、更新服务或文件操作。
- 不读取 API Key、session token、日志、截图或本地配置。
- 演示状态只存在于当前页面内；主题偏好使用专用键 `danmu_ux_prototype_theme`。
- “开始”“完成设置”等按钮都是演示，不会写入应用配置。

## 验收限制

原型已把 30 秒目标转化为可执行测试脚本，但仅凭静态评审不能证明真实新用户一定能在 30 秒内理解。正式结论仍应让 3–5 名未接触过 DanmuAI 的用户完成盲测并记录：

- 是否能准确复述用途；
- 是否能找到开始路径；
- 是否能找到指定高级功能；
- 完成时间和误点位置。

## 事实依据

分类以当前工作树中的真实 UI 与路由为准，主要核对：

- `web/static/partials/sidebar.html`
- `web/static/partials/overview.html`
- `web/static/partials/settings.html`
- `web/static/partials/style-generator.html`
- `web/static/partials/content-pages.html`
- `web/static/app.js`
- `app/web_api/routes.py` 及各子路由
- `README.md`
- `.local-ai/prompts/ai-project-context.md`

本目录不主张替代现有实现；它是下一轮用户评审和正式落地拆分的视觉依据。

