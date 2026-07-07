# Supabase — 公告、反馈、错误报告与版本更新

Apply migrations in order (or use Supabase MCP `apply_migration`):

1. `migrations/001_announcements_feedback.sql`
2. `migrations/002_error_reports.sql`
3. `migrations/003_app_updates.sql`
4. `migrations/008_error_reports_user_note.sql` — 错误报告可选 `user_note`（补充说明）与 `contact`
5. `migrations/009_tutorial_links.sql` — 教程页视频链接（`tutorial_links`，anon 只读）
6. `migrations/010_feedback_context.sql` — 反馈 `context_json` / `logs_excerpt`
7. `migrations/011_anon_table_grants.sql` — 显式 REVOKE/GRANT，anon 仅 insert 或 select（BUG-021）

Copy `../web/static/supabase-config.example.js` to `../web/static/supabase-config.js` and set `url` + `anonKey`. The desktop **backend** reads the same credentials (or `DANMU_SUPABASE_URL` / `DANMU_SUPABASE_ANON_KEY`) for `GET /api/update/channels` → Supabase `app_updates`.

## 桌面端凭证配置

| 方式 | 适用场景 |
|------|----------|
| `web/static/supabase-config.js` | 本地开发（**不**打入 Velopack/PyInstaller 发布包） |
| `DANMU_SUPABASE_URL` + `DANMU_SUPABASE_ANON_KEY` | 打包版、CI / 运维脚本启动（**推荐发布环境**） |

- 仅使用 **anon / publishable** key；勿将 `service_role` 写入客户端或仓库。
- **打包版不含 `supabase-config.js`**：`DanmuAI.spec` 对含 `supabase-config` 的文件 default-deny（仅保留 `supabase-config.example.js`）；运行时由 `app/supabase_config.py` 读取环境变量或开发用 js 文件。
- 未配置或 PostgREST 不可达时，后端 `GET /api/update/channels` 将 `latest_version` 回退为本地 `app/version.py`，避免误报更新。
- 实现：`app/supabase_config.py`、`app/supabase_app_updates.py`；缓存 5 分钟。

发版检查清单见 [`docs/operations/PACKAGING_WINDOWS.md`](../docs/operations/PACKAGING_WINDOWS.md) 与本 README § `app_updates`。

## `feedback`（问题反馈）

| 列 | 说明 |
|----|------|
| `content` | 用户填写的反馈内容（必填，≤2000 字） |
| `contact` | 联系方式（可选，≤200 字） |
| `context_json` | 结构化运行上下文（`jsonb`，固定含 `current_model_name`、`api_endpoint`、`provider_id`、`api_mode`、`recent_logs`、`app_version`、`reported_at`、`error_message`） |
| `logs_excerpt` | 最近日志摘录（可选，`text`，≤8000 字） |
| `client_id` | 本机匿名 client_id，用于额度去重 |
| `app_version` | 客户端版本 |
| `platform` | 平台（如 `windows`） |
| `locale` | 用户语言（如 `zh-CN`） |

普通「问题反馈」页仅要求用户填写反馈内容；`context_json` 与 `logs_excerpt` 由前端自动采集并附带，便于开发者直接定位现场。`api_endpoint` 已做轻度脱敏，只保留 `scheme + host + path`，不含 query、fragment、userinfo 或 token/key 片段。

额度：每 `client_id` 每 3 小时最多 2 条（RLS + `feedback_quota` RPC）。

## `error_reports`（自动错误反馈）

| 列 | 说明 |
|----|------|
| `summary` | 错误摘要（≤500 字） |
| `logs_excerpt` | 脱敏日志摘录（≤8000 字） |
| `diagnostics_json` | 调度 / RTT / 配置上下文 |
| `error_fingerprint` | SHA-256，用于客户端 24h 去重提示 |
| `user_note` | 用户补充说明（可选，≤1000 字） |
| `contact` | 联系方式（可选，≤200 字） |
| `app_version` | 客户端版本 |

额度：每 `client_id` 每 3 小时最多 3 条（RLS + `error_reports_quota` RPC）。

## `app_updates`（版本更新提醒）

| 列 | 说明 |
|----|------|
| `latest_version` | 最新发布版本（semver `vx.x.x`，如 `0.3.0` 或 `v0.3.0`，与 `app/version.py` 一致） |
| `release_url` | 下载页；默认 **R2 主下载 Setup.exe**（`https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe`）；便携版见 `PEPETII.DanmuAI-win-Portable.zip`；GitHub Releases 仅备用 |
| `enabled` | `false` 时客户端不读取该行 |
| `message` | 可选，更新弹窗副文案 |

**运维**：发布 GitHub Release 并确认安装包无误后，在 Table Editor 插入或更新**一条** `enabled=true` 记录（通常只保留最新一行；客户端按 `updated_at desc` 取第一条）。Web 控制台版本区与更新弹窗通过后端 `GET /api/update/channels` 读取本表（Supabase `app_updates` 为版本元数据主源）。[`app/release_channels.py`](../app/release_channels.py) **仍用于**镜像下载 URL（如夸克网盘分享文案等），不再维护发布版本常量。

```sql

insert into public.app_updates (latest_version, release_url, message)

values (

  '0.3.0',

  'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe',

  null

);

```

## `tutorial_links`（教程视频链接）

| 列 | 说明 |
|----|------|
| `kind` | 固定 `video`（图文教程仍为客户端硬编码飞书链接） |
| `url` | 视频页 URL；占位时为 `正在紧急赶制中...`（客户端显示不可点击文案） |
| `enabled` | `false` 时客户端不读取该行 |

**运维**：视频就绪后，在 Table Editor 将 `kind=video` 且 `enabled=true` 的行的 `url` 改为完整 `https://...` 链接即可，无需发版。

```sql

update public.tutorial_links

set url = 'https://example.com/your-video', updated_at = now()

where kind = 'video' and enabled = true;

```
