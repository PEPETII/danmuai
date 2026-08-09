# Security Policy

## 支持范围

当前仓库维护的是桌面端主干版本。安全修复会优先覆盖当前默认分支。

## 报告方式

- 不要在公开 Issue 中粘贴 API Key、请求头、截图原图或包含隐私内容的日志。
- 如果问题涉及凭据泄漏、截图隐私或可远程利用的漏洞，请私下联系维护者处理。

## 项目当前安全边界

- API Key 默认保存在 `%APPDATA%/DanmuAI/config.db`，优先使用 Fernet 加密（全局 `api_key`）。
- **自定义模型**的 `apiKey` 以 Fernet 密文写入 `custom_models` JSON（与全局 `api_key_encrypted` 共用 `.key`）；读取时解密，legacy 明文会在读路径自动升级；`GET /api/config` 与 `GET /api/custom-models` 返回掩码值 `********`。
- 日志会脱敏 API Key、`Authorization` 头、长 base64 图片/音频数据和加密串；配置写入失败日志不会输出完整密钥字段。
- 默认不保存截图，不会把截图原文写入日志。
- 过期请求和旧场景回复会被丢弃，避免旧内容覆盖当前画面。

## 本地 Web API 威胁模型

Web 控制台仅监听 **`127.0.0.1`**，面向**单用户本机**场景，不是多用户网络服务。
loopback 绑定限制网络暴露面，但不提供进程级身份隔离；本机其他进程仍可
访问端口，因此 `Host`、`Origin`、`Referer` 不作为 session 身份凭据。

桌面启动器把短时、一次性的 bootstrap secret 放入 URL fragment（不会随 HTTP
请求发送），页面立即用 `X-DanmuAI-Bootstrap` 换取本次进程的 Bearer token，随后
移除 fragment 并仅在当前 tab 的内存/sessionStorage 中复用 token。bootstrap secret、
Bearer token 都不得写入日志或 URL query。

| 能力 | 鉴权 | 说明 |
|------|------|------|
| `GET /api/health` | 无 | 最小健康检查，仅返回 `ok/service` |
| `GET /api/session` | 一次性 bootstrap 或 Bearer | 返回当次启动的 Bearer token；不接受伪造的 Host/Origin/Referer |
| `/api/*` 其余 HTTP API | Bearer | 状态、日志、配置、人格、知识包/任务/条目及其他控制台 API 默认私有 |
| `GET /api/live-overlay/status`、`/api/live-overlay/events` | 无 | 明确允许的直播 overlay 连接状态/SSE；不返回配置或凭据 |
| `GET /api/live-overlay/config` | 无 | 仅返回 Overlay 字号 `font_size`；不返回其他配置或凭据 |
| `GET /api/pet/barrage-slots/{slot_id}/preview` | 无 | 明确允许的静态预览图，供 `<img>` 使用 |
| `GET /api/update/status` | Bearer | Velopack 应用内更新状态 |
| `POST /api/update/check`、`/download`、`/restart` | Bearer | 应用内检查、下载、重启更新 |
| `PUT/POST /api/config`、`POST /api/start`、`/api/stop`、`/api/toggle` | Bearer | 全局配置保存与启停控制 |
| 人格写操作（`PUT/POST/DELETE /api/personae/*`、active、model、label、rollback、restore） | Bearer | 人格模板、活跃列表、模型绑定与回滚 |
| 自定义模型写操作（`POST/PUT/DELETE /api/custom-models/*`、default、probe） | Bearer | 模型档案增删改与连接探测 |
| `GET /api/diagnostics` | Bearer | 诊断快照（含调度、计时、invoke 超时计数） |
| 弹幕池写操作（`PUT /api/danmu-pool/settings`、`POST/DELETE /api/danmu-pool/custom`、`POST /api/test/danmu`） | Bearer | 公式化弹幕池配置、自定义句库与测试注入 |
| 烂梗弹幕写操作（`PUT /api/meme-barrage/settings`、`POST /api/meme-barrage/clear`） | Bearer | 烂梗配置与库清理 |
| 朗读写操作（`PUT /api/danmu-read/config`、`POST /api/danmu-read/probe`） | Bearer | TTS 配置与探测 |
| 麦克风写操作（`POST /api/mic/test`、`/api/mic/test-send`） | Bearer | 麦克风测试 |
| 截图区域写操作（`POST /api/capture-region/select`、`/reset`） | Bearer | 触发可视化选区与重置 |
| 桌宠写操作（`POST /api/pet/*`） | Bearer | 桌宠设置、显隐、指令、资源导入与弹幕槽操作 |
| 知识库写操作（`POST/PATCH/DELETE /api/knowledge/*`、`POST /api/knowledge/retrieval/preview`） | Bearer | 知识包、条目、导入任务管理与检索预览 |
| 字体写操作（`POST /api/fonts/import`、**`GET /api/fonts`**、`DELETE /api/fonts/{sha256}`） | Bearer | 字体导入、列表、删除（读操作同样需 Bearer） |
| 直播 overlay 写操作（`POST /api/live-overlay/test`） | Bearer | 测试弹幕推送 |
| `WS /ws/logs`、`/ws/status`、`/ws/panel` | 首次消息认证或 Query `ws_token` | 需与 session token 一致（向后兼容） |

**假设**：信任本机用户；本机其他进程或恶意软件若可访问 `127.0.0.1:18765`，仍可能尝试请求 API，但没有启动器 bootstrap 或当前 Bearer 不能通过私有 API 鉴权。请勿将控制台端口暴露到局域网或公网，勿在不可信的多用户环境中运行。

DanmuAI **社区站**（注册守卫 CORS、Supabase 社区 Schema 等）已抽离为本地子项目 `community/`（不进本仓库 Git）；安全说明见该目录内 `README.md`。

## 使用建议

- 当前版本会按 `screen_index` 截取**所选显示器全屏**，请确保该屏幕上没有密码框、聊天窗口、支付页面、企业内网内容等敏感信息。
- 需要局部截图时，请关注路线图中的可视化选区功能；在实现前请自行隔离敏感窗口。
- 发布构建或共享代码前，确认仓库不包含 `log/`、`ph/`、本地数据库、`.key`、缓存目录。
