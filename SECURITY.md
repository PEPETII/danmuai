# Security Policy

## 支持范围

当前仓库维护的是桌面端主干版本。安全修复会优先覆盖当前默认分支。

## 报告方式

- 不要在公开 Issue 中粘贴 API Key、请求头、截图原图或包含隐私内容的日志。
- 如果问题涉及凭据泄漏、截图隐私或可远程利用的漏洞，请私下联系维护者处理。

## 项目当前安全边界

- API Key 默认保存在 `%APPDATA%/DanmuAI/config.db`，优先使用 Fernet 加密（全局 `api_key`）。
- **自定义模型**的 `apiKey` 以 JSON 明文存入 SQLite；`GET /api/config` 与 `GET /api/custom-models` 返回掩码值 `********`。
- 日志会脱敏 API Key、`Authorization` 头、长 base64 图片数据和加密串；配置写入失败日志不会输出完整密钥字段。
- 默认不保存截图，不会把截图原文写入日志。
- 过期请求和旧场景回复会被丢弃，避免旧内容覆盖当前画面。

## 本地 Web API 威胁模型

Web 控制台仅监听 **`127.0.0.1`**，面向**单用户本机**场景，不是多用户网络服务。

| 能力 | 鉴权 | 说明 |
|------|------|------|
| `GET /api/session` | 无 | 返回当次启动的 Bearer token，供同源 UI 使用 |
| `GET /api/config` | 无 | 配置快照；API Key 已掩码 |
| `GET /api/update/channels` | 无 | 只读更新元数据：从 Supabase `app_updates` 读取 `latest_version` / `release_url` / `message`（镜像 URL 为静态目录）；**不**访问 Velopack feed |
| `GET /api/update/status` | Bearer | Velopack 应用内更新状态 |
| `POST /api/update/check`、`/download`、`/restart` | Bearer | 应用内检查、下载、重启更新 |
| `PUT /api/config`、启停、人格/模型写操作 | Bearer | 需 `Authorization: Bearer <token>` |
| `POST /api/personae/{name}/restore` | Bearer | 恢复内置人格默认 |
| `WS /ws/logs`、`/ws/status` | 首次消息认证或 Query `ws_token` | 需与 session token 一致（向后兼容） |

**假设**：信任本机用户；本机其他进程或恶意软件若可访问 `127.0.0.1:18765`，可能读取 session token 或连接 WebSocket。请勿将控制台端口暴露到局域网或公网，勿在不可信的多用户环境中运行。

DanmuAI **社区站**（注册守卫 CORS、Supabase 社区 Schema 等）已抽离为本地子项目 `community/`（不进本仓库 Git）；安全说明见该目录内 `README.md`。

## 使用建议

- 当前版本会按 `screen_index` 截取**所选显示器全屏**，请确保该屏幕上没有密码框、聊天窗口、支付页面、企业内网内容等敏感信息。
- 需要局部截图时，请关注路线图中的可视化选区功能；在实现前请自行隔离敏感窗口。
- 发布构建或共享代码前，确认仓库不包含 `log/`、`ph/`、本地数据库、`.key`、缓存目录。
