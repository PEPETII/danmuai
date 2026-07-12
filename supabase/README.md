# Supabase — 公告、反馈、错误报告与版本更新

Apply the checked-in migrations in filename order to the intended hosted project. For a linked local/CI workflow use the current Supabase CLI commands discovered with `supabase --help`; for a hosted project the Dashboard SQL editor or an approval-gated migration runner is acceptable. Do not treat a successful local migration as proof that the hosted Data API exposes the tables.

1. `migrations/001_announcements_feedback.sql`
2. `migrations/002_error_reports.sql`
3. `migrations/003_app_updates.sql`
4. `migrations/008_error_reports_user_note.sql` — 错误报告可选 `user_note`（补充说明）与 `contact`
5. `migrations/009_tutorial_links.sql` — 教程页视频链接（`tutorial_links`，anon 只读）
6. `migrations/010_feedback_context.sql` — 反馈 `context_json` / `logs_excerpt`
7. `migrations/011_anon_table_grants.sql` — 显式 REVOKE/GRANT，anon 仅 insert 或 select（BUG-021）

执行后核对迁移历史和 Data API 暴露设置。Supabase 自 2026-04-28 起不再保证新建 public 表自动暴露给 Data API；RLS 与角色 GRANT 都通过后，还要在项目 Data API 设置中确认所需 schema/table 已暴露。

## 部署后最小验证

1. 在 SQL Editor 或受控 SQL 客户端确认所有 7 个 migration 已按顺序执行。
2. 用只读查询确认 `public.announcements`、`public.app_updates`、`public.tutorial_links` 的 `anon` SELECT 与 `feedback`、`error_reports` 的 `anon` INSERT 权限符合 `011_anon_table_grants.sql`。
3. 用前端实际使用的 publishable/anon key 做一次只读公告、版本和教程请求；不要用 `service_role` 模拟客户端。
4. 分别提交一条脱敏测试反馈与错误报告，确认额度 RPC 生效，再按项目保留策略清理测试数据。
5. 运行当前 CLI 支持的 `supabase db advisors`（先用 `supabase --help` 确认版本）并记录结果；线上状态须另行记录，不能由本 README 推断。

> **已确认的代码侧注意项（线上状态未确认）**：`001`/`002` 创建了 `public` schema 下的 `SECURITY DEFINER` 函数，`011` 只显式收紧表权限。当前迁移文本没有显式 `REVOKE EXECUTE ... FROM PUBLIC`；部署前应检查函数执行权限和默认权限策略，必要时另开安全工单，不要把文档中的“anon 仅 insert/select”误读为函数权限也已收紧。

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

## `announcements`（公告）

| 列 | 说明 |
|----|------|
| `title` | 公告标题 |
| `body` | 公告正文 |
| `level` | `info` / `warning` / `critical` |
| `published` | 是否对 `anon` 可见；还受 `starts_at` / `ends_at` 限制 |
| `pinned` | 是否置顶排序 |

客户端只读取满足发布时间窗口且 `published=true` 的公告；维护者在 Table Editor 发布或撤回，不应直接把未审核内容设为公开。

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

**运维**：先完成本地打包校验，再上传 R2 主源并验证 Setup、Portable 和 feed；GitHub Release 只作镜像。确认线上资产无误后，在 Table Editor 插入或更新**一条** `enabled=true` 记录（通常只保留最新一行；客户端按 `updated_at desc` 取第一条）。Web 控制台版本区与更新弹窗通过后端 `GET /api/update/channels` 读取本表（Supabase `app_updates` 为版本元数据主源）。[`app/release_channels.py`](../app/release_channels.py) **仍用于**镜像下载 URL（如夸克网盘分享文案等），不再维护发布版本常量。

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
