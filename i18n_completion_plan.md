# DanmuAI i18n 未翻译位置补全计划

> **库存日期**：2026-07-05（文档同步批次复核）
> **执行前须 grep 复核行号**——本文件是 i18n backlog，不是架构真相源；行号漂移时用 `rg`/Read 工具复算后再改代码。
> **工单登记**：新 i18n 工单须在 [.local-ai/workorders/工单列表.md](.local-ai/workorders/工单列表.md) 登记 ID；本计划 §3 的 WEB-xx / QT-xx 编号仅为计划内分组，**不**替代工单列表条目。

## 1. 上下文与目标

当前 DanmuAI 切换语言时，Web 控制台和 Qt/Python 侧均存在部分硬编码中文未走 i18n，导致切换到英文后仍显示中文。本项目已有 key-based i18n 基础设施：

- Web: `web/static/locales/{zh,en}/*.json` + `web/static/modules/i18n.js` 的 `t()` / `applyI18n()`。
- Qt/Python: `app/translations.py` + `app/translations_*.py` 的 `tr()` / `Translator.tr()`。

本计划将未翻译位置拆分为**独立小工单**，每个工单 5–10 分钟可手动验收，便于分批执行。

## 2. 已发现的未翻译位置汇总

### 2.1 Web 控制台

#### 2.1.1 HTML 硬编码（无 data-i18n / 无对应 key）

| 文件 | 位置 | 硬编码文本 | 状态 |
|------|------|------------|------|
| `web/static/index.template.html:6` | `<title>` | `DanmuAI - 你的温馨弹幕小助手` | 已有 `data-i18n="common.meta.title"`，确认 locale key 即可 |
| `web/static/live-overlay.html:19` | `<title>` | `DanmuAI Live Overlay` | 需补 key |
| `web/static/partials/overview.html:206` | 诊断面板 label | `Pending Timing` | 已有 `data-i18n="overview.text.Pending_Timing"` |
| `web/static/partials/settings.html:16-17` | 语言 select options | `中文` / `英语` | 已有 `data-i18n="common.langZh"` / `common.langEn` |
| `web/static/partials/settings.html:348` | 全局快捷键 placeholder | `Ctrl+Shift+B` | 可选，非关键 |

#### 2.1.2 JS 硬编码（未使用 t()，但 locale 中多数已有 key）

| 文件 | 位置 | 硬编码文本 | 对应 locale key |
|------|------|------------|-----------------|
| `web/static/modules/app-update-banner.js:319` | 版本状态 | `（缓存）` | 已用 `t('dynamic.appUpdateBanner.缓存')` |
| `web/static/modules/app-ai-butler-page.js:578` | 错误抛出 | `未知工具：${toolName}` | `dynamic.appAiButlerPage.未知工具_toolName` |
| `web/static/modules/diagnostics.js:55` | 诊断建议 | `检查调度阻塞原因：${reason}` | `dynamic.diagnostics.检查调度阻塞原因_scheduler_b` |
| `web/static/modules/transport.js:495` | WS 错误提示 | `可刷新页面或重启 DanmuAI。` | `dynamic.transport.可刷新页面或重启_DanmuAI` |
| `web/static/modules/settings-fonts.js:99-108` | 颜色名称 | 红/橙/黄/绿/蓝/靛/紫 | 需新增 key |
| `web/static/modules/settings-mic-tools.js:28,58` | 回退状态 | ` · 已回退默认输入` | 需新增 key |
| `web/static/modules/settings-mic-tools.js:29,59` | 状态详情拼接 | `pcm=... · rms=... · ...` | 部分需 i18n（如 "unknown"） |
| `web/static/modules/settings-model-catalog.js:74` | 价格单位 | `元` | 需新增 key |

#### 2.1.3 结构性问题

- `i18n.js:normalizeLanguage()` 硬编码 `value === 'en' ? 'en' : 'zh'`，新增语言时会失效。
- `applyTextNodeWalk()` 依赖中文源文本反向匹配，新字符串不应再依赖它。

### 2.2 Qt/Python 侧

#### 2.2.1 用户可见但尚未 `tr()` 的硬编码中文

| 文件 | 位置 | 文本 | 建议 key |
|------|------|------|----------|
| `app/tts_providers.py:40-51` | TTS 常量 | `冰糖`、`你好，这是一条读弹幕试听。`、不再支持... | `tts.defaultVoice`、`tts.probeText`、`tts.unsupportedCustom` 等 |
| `app/tts_providers.py:71-74` | 不支持音频提示 | `当前 provider/model...` | `tts.unsupportedProvider` |
| `app/tts_providers.py:285-560` | 各类错误 | `朗读文本为空`、`未配置 TTS API Key` 等 | `tts.error.*` |
| `app/mic_test.py:94-130` | 测试结果 | `麦克风正常...`、`已回退默认输入` 等 | `micTest.*` |
| `app/mic_test_send.py:21-222` | 测试发送 | `听得见吗？...`、`音频编码失败` 等 | `micTestSend.*` |
| `app/danmu_read_service.py:82-322` | 读弹幕服务 | `不再支持...`、`试听已提交...` 等 | `danmuRead.*` |
| `app/web_api/danmu_read.py:29-30` | API 错误 | 同 danmu_read_service | 复用 |
| `app/web_api/language.py:64-77` | 校验错误 | `language 必须为字符串` | `validation.languageMustBeString` 等 |
| `app/main_launch.py:31-58` | 启动弃用提示 | 经 `tr("mainLaunch.*")` | 已实现 i18n key |
| `app/webview_shell.py:197` | 桌面窗口提示 | `桌面窗口启动较慢...` | `tray.slowStartBody` |
| `app/pet/pet_assets.py:175-231` | 资源错误 | `桌宠资源路径不在允许范围内...` | `pet.error.*` |
| `app/pet/pet_barrage.py:88-109` | 资源标签 | `本地目录`、`默认桌宠`、`内置默认` | `pet.resourceLabel.*`、`pet.displayName.default` |
| `app/pet/pet_command_service.py:64` | 空指令 | `指令内容不能为空` | `pet.error.emptyCommand` |
| `app/web_api/persona.py:63-166` | 人格接口错误 | `人格不存在`、`人格名称已存在` 等 | `persona.*` |
| `app/web_api/custom_models.py:218-290` | 模型档案错误 | `模型索引无效`、`模型 ID 为空` | `customModel.*` |
| `app/web_api/danmu_pool.py:121-225` | 弹幕池接口错误 | `单次最多追加...`、`追加接口不可用` 等 | `danmuPool.*` |
| `app/web_api/ai_butler.py:55` | AI 管家校验 | `messages 不能为空` | `aiButler.messagesRequired` |
| `app/web_api/announcements_state.py:85-105` | 公告状态校验 | `readIds 必须为数组` 等 | `validation.*` |
| `app/web_api/console_theme.py:40-43` | 主题校验 | `theme 必须为字符串` 等 | `validation.*` |
| `app/web_api/font_registry.py:34-63` | 字体注册超时 | `主线程操作超时，请稍后重试。` | `common.mainThreadTimeout` |
| `app/web_console_runtime.py:55-297` | 运行时错误 | `未安装 websockets...`、`需要登录令牌` 等 | `webConsoleRuntime.*`、`auth.*`、`config.saveFailed` |
| `app/web_console_support.py:87-120` | 显示器标签 | `显示器 1` | `display.label` |
| `app/font_registry.py:58-172` | 字体注册错误 | `字体注册表不可用`、`文件为空` 等 | `fontRegistry.*` |
| `app/main_display_mixin.py:465-467` | 测试弹幕 | `请至少提供一条弹幕` 等 | `overlay.test.*` |
| `app/live_overlay_hub.py:914` | 测试弹幕 | `DanmuAI 测试弹幕` 等 | `liveOverlay.*` |
| `app/release_channels.py:16-17` | 夸克分享 | `我用夸克网盘给你分享了...` | `releaseChannels.quarkShareText` |
| `app/ai_butler_service.py` | 配置标签/回复 | `弹幕速度`、`好的，我帮你把弹幕速度调快一些。` | `aiButler.*` |
| `app/web_api/meme_barrage.py` | 分类标签 | `喷玩机器`、`木柜子` 等 | `memeBarrage.categories.*` |

## 3. 工单拆分

> **与 [.local-ai/workorders/工单列表.md](.local-ai/workorders/工单列表.md) 的关系**：本计划 WEB-xx / QT-xx 为 backlog 分组；正式执行须在工单列表登记独立工单 ID（如 `I18N-WEB-API-HARDCODED-CHINESE-001`），避免重复登记。已完成项在工单列表标「已完成」，本计划仅作 inventory 参考。

### 3.1 Web 控制台

#### WEB-01：全局标题与语言下拉
- **允许修改**：
  - `web/static/index.template.html`
  - `web/static/live-overlay.html`
  - `web/static/partials/settings.html`
  - `web/static/locales/{zh,en}/common.json`
- **内容**：
  - 给 `<title>` 加 `data-i18n="common.meta.title"`（已存在 key，确认即可）。
  - 新增 `common.liveOverlayTitle`，给 live-overlay title 使用。
  - settings 页语言 select options 加 `data-i18n="common.langZh"` / `data-i18n="common.langEn"`。
- **验收**：切换 zh/en，首页/overlay 标题与语言下拉显示正确。
- **预估**：5 分钟。

#### WEB-02：概览页诊断面板
- **允许修改**：
  - `web/static/partials/overview.html`
  - `web/static/locales/{zh,en}/overview.json`
- **内容**：
  - 新增 `overview.text.pendingTiming`，替换 `Pending Timing` 硬编码。
- **验收**：切换 zh/en，诊断面板 `Pending Timing` 正确翻译。
- **预估**：5 分钟。

#### WEB-03：JS 动态文案（已有 key 但未使用）
- **允许修改**：
  - `web/static/modules/app-update-banner.js`
  - `web/static/modules/app-ai-butler-page.js`
  - `web/static/modules/diagnostics.js`
  - `web/static/modules/transport.js`
- **内容**：
  - `app-update-banner.js:319`：将 `（缓存）` 替换为 `t('dynamic.appUpdateBanner.缓存')`。
  - `app-ai-butler-page.js:578`：将 `未知工具...` 替换为 `t('dynamic.appAiButlerPage.未知工具_toolName', { toolName })`。
  - `diagnostics.js:55`：将 `检查调度阻塞原因...` 替换为 `t('dynamic.diagnostics.检查调度阻塞原因_scheduler_b', { scheduler })`。
  - `transport.js:495`：将 `可刷新页面...` 替换为 `t('dynamic.transport.可刷新页面或重启_DanmuAI')`。
- **验收**：触发对应功能，切换 zh/en 后上述文案显示对应语言。
- **预估**：10 分钟。

#### WEB-04：设置-字体颜色名称
- **允许修改**：
  - `web/static/modules/settings-fonts.js`
  - `web/static/locales/{zh,en}/settings.json`
- **内容**：
  - 新增 `settings.colors.{red,orange,yellow,green,blue,indigo,purple}`。
  - `DANMU_COLOR_SWATCHES` 中使用 `t()` 读取。
- **验收**：字体设置页颜色 swatch label 切换语言正常。
- **预估**：5 分钟。

#### WEB-05：设置-Mic 状态
- **允许修改**：
  - `web/static/modules/settings-mic-tools.js`
  - `web/static/locales/{zh,en}/settings.json` 或 `dynamic.json`
- **内容**：
  - 新增 mic 状态相关 key：`mic.fallbackToDefaultInput`、`mic.unknownInputDevice` 等。
  - 替换 ` · 已回退默认输入` 等硬编码拼接。
- **验收**：执行 mic 测试并触发回退，切换 zh/en 状态文本正确。
- **预估**：8 分钟。

#### WEB-06：设置-模型目录价格单位
- **允许修改**：
  - `web/static/modules/settings-model-catalog.js`
  - `web/static/locales/{zh,en}/settings.json`
- **内容**：
  - 新增 `settings.modelCatalog.currencyUnit = "元" / "CNY"`。
  - 替换硬编码 `元`。
- **验收**：模型目录价格单位切换语言正常。
- **预估**：5 分钟。

#### WEB-07：i18n.js 结构优化
- **允许修改**：
  - `web/static/modules/i18n.js`
- **内容**：
  - `normalizeLanguage()` 改为读取 `SUPPORTED_LANGUAGES` 列表判断，而非硬编码 `value === 'en'`。
  - 保持当前 zh/en 行为不变。
- **验收**：切换 zh/en 仍然正确；伪造 `ja` 请求时 fallback 到默认语言。
- **预估**：5 分钟。

### 3.2 Qt/Python 侧

#### PY-01：TTS 提供商错误与默认值
- **允许修改**：
  - `app/tts_providers.py`
  - `app/translations_settings.py`（或新建 `app/translations_tts.py` 并在 `translations.py` 引入）
- **内容**：
  - 将 `DEFAULT_TTS_VOICE`、`TTS_PROBE_TEXT`、`_UNSUPPORTED_CUSTOM_TTS_MSG`、`_UNSUPPORTED_DOUBAO_TTS_MSG`、`tts_audio_unsupported_message`、各 `DanmuTtsError` 中文替换为 `tr()`。
- **验收**：触发对应 TTS 错误，切换语言后提示为英文。
- **预估**：10 分钟。

#### PY-02：麦克风测试与发送
- **允许修改**：
  - `app/mic_test.py`
  - `app/mic_test_send.py`
  - `app/translations_ui.py`
- **内容**：
  - 将测试结果、提示、错误消息替换为 `tr()`。
- **验收**：执行 mic 测试/发送，切换语言后状态消息正确。
- **预估**：10 分钟。

#### PY-03：读弹幕服务与 API
- **允许修改**：
  - `app/danmu_read_service.py`
  - `app/web_api/danmu_read.py`
  - `app/translations_settings.py`（或 `translations_tts.py`）
- **内容**：
  - 将不支持平台提示、试听状态提示、API 错误消息替换为 `tr()`。
- **验收**：触发读弹幕相关错误/提示，切换语言正常。
- **预估**：10 分钟。

#### PY-04：语言 API 校验错误
- **允许修改**：
  - `app/web_api/language.py`
  - `app/translations_ui.py`
- **内容**：
  - 将 `language 必须为字符串`、`language 仅允许 {allowed}` 改为 `tr()`。
- **验收**：调用 `PUT /api/language` 传非法值，返回对应语言错误。
- **预估**：5 分钟。

#### PY-05：Web API 通用错误（人格/模型/弹幕池/AI 管家/公告/主题/字体）
- **允许修改**：
  - `app/web_api/persona.py`
  - `app/web_api/custom_models.py`
  - `app/web_api/danmu_pool.py`
  - `app/web_api/ai_butler.py`
  - `app/web_api/announcements_state.py`
  - `app/web_api/console_theme.py`
  - `app/web_api/font_registry.py`
  - `app/translations_ui.py`
- **内容**：
  - 将各模块用户可见错误消息统一改为 `tr()`。
- **验收**：调用各 API 触发错误，切换语言后错误消息正确。
- **预估**：10 分钟。

#### PY-06：字体注册与显示器标签
- **允许修改**：
  - `app/font_registry.py`
  - `app/web_console_support.py`
  - `app/translations_ui.py`
- **内容**：
  - 字体注册错误改为 `tr()`。
  - 显示器 fallback label `显示器 1` 改为 `tr('display.label', {n: 1})`。
- **验收**：触发字体注册错误、查看显示器列表，切换语言正常。
- **预估**：8 分钟。

#### PY-07：运行时/启动/托盘/Live Overlay
- **允许修改**：
  - `app/main_launch.py`
  - `app/webview_shell.py`
  - `app/web_console_runtime.py`
  - `app/live_overlay_hub.py`
  - `app/main_display_mixin.py`
  - `app/translations_tray.py`、`app/translations_ui.py`
- **内容**：
  - 启动弃用提示、托盘提示、运行时错误、Live Overlay 测试弹幕、测试注入限制提示改为 `tr()`。
- **验收**：触发启动提示/托盘消息/Live Overlay 测试，切换语言正常。
- **预估**：10 分钟。

#### PY-08：桌宠/AI 管家/Meme 弹幕
- **允许修改**：
  - `app/pet/pet_assets.py`
  - `app/pet/pet_barrage.py`
  - `app/pet/pet_command_service.py`
  - `app/ai_butler_service.py`
  - `app/web_api/meme_barrage.py`
  - `app/translations_pet.py`、`app/translations_ui.py`、`app/translations_danmu.py`
- **内容**：
  - 桌宠资源错误、资源标签、指令错误；AI 管家配置标签与回复；Meme 弹幕分类标签改为 `tr()`。
- **验收**：触发对应功能，切换语言正常。
- **预估**：10 分钟。

## 4. 通用验收标准

1. 每个工单完成后，相关页面/功能在 zh 下显示中文，在 en 下显示英文。
2. 新增 key 必须同时存在于 `zh` 和 `en` 对应 locale 中。
3. 新增/修改的字符串必须显式通过 `data-i18n` 或 `t()` / `tr()` 绑定，不再依赖 text-node walk。
4. 不引入新的 i18n 库或架构改动。
5. 每个工单完成后，基础功能无报错。

## 5. 验证方法

| 验证项 | 操作 |
|--------|------|
| Web 文案 | 启动 Web 控制台，切换 zh/en，人工检查对应区域 |
| Web JS 动态文案 | 触发对应功能（mic 测试、AI 管家调用、诊断面板等），切换语言观察 |
| Python API 错误 | 直接调用相关 API 或触发异常，检查返回消息 |
| Tray/启动消息 | 实际运行应用，切换语言，观察托盘和启动日志 |
| 数据一致性 | 检查新增 key 是否同时存在于 zh/en |

## 6. 风险与注意事项

- **text-node walk 仍保留**：仅作为旧字符串兜底，新增字符串不再依赖。
- **key 命名冲突**：各工单按 `模块.子模块.含义` 命名，避免重复。
- **动态插值格式**：
  - Web 侧 `t(key, params)` 支持 `{name}` 插值，可直接使用。
  - Python 侧 `tr()` 目前**不支持**参数插值；对于含变量文案，先用 `tr('key')` 取出模板后使用 f-string 拼接，或在本计划范围内扩展 `Translator.tr()` / `tr()` 支持 `**kwargs` 插值。
- **英文长度**：英文通常比中文长，需关注按钮/标签截断（超出本计划范围，可记录）。
- **范围外问题**：如发现其他未翻译位置，按项目规则记录到 `.local-ai/workorders/已知问题与后续事项.md`，不在当前工单中修复。
