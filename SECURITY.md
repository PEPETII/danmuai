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

| 能力 | 鉴权 | 说明 |
|------|------|------|
| `GET /api/session` | 同源 loopback 或 Bearer | 返回当次启动的 Bearer token；拒绝无 Origin/Referer 的 curl/第三方进程调用，已持有 token 的调用方不受来源限制 |
| `GET /api/config` | 无 | 配置快照；API Key 已掩码 |
| `GET /api/status`、`/api/logs/recent`、`/api/screens`、`/api/meta`、`/api/providers`、`/api/model-catalog`、`/api/config/defaults` | 无 | 只读状态、日志回放、元数据与模型目录 |
| `GET /api/personae` | 无 | 人格列表（含掩码后的绑定模型） |
| `GET /api/update/channels` | 无 | 只读更新元数据：从 Supabase `app_updates` 读取 `latest_version` / `release_url` / `message`（镜像 URL 为静态目录）；**不**访问 Velopack feed |
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

**假设**：信任本机用户；本机其他进程或恶意软件若可访问 `127.0.0.1:18765`，可能读取 session token 或连接 WebSocket。请勿将控制台端口暴露到局域网或公网，勿在不可信的多用户环境中运行。

DanmuAI **社区站**（注册守卫 CORS、Supabase 社区 Schema 等）已抽离为本地子项目 `community/`（不进本仓库 Git）；安全说明见该目录内 `README.md`。

## 使用建议

- 当前版本会按 `screen_index` 截取**所选显示器全屏**，请确保该屏幕上没有密码框、聊天窗口、支付页面、企业内网内容等敏感信息。
- 需要局部截图时，请关注路线图中的可视化选区功能；在实现前请自行隔离敏感窗口。
- 发布构建或共享代码前，确认仓库不包含 `log/`、`ph/`、本地数据库、`.key`、缓存目录。
