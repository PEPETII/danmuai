# Supabase — 公告、反馈、错误报告与版本更新

Apply migrations in order (or use Supabase MCP `apply_migration`):

1. `migrations/001_announcements_feedback.sql`
2. `migrations/002_error_reports.sql`
3. `migrations/003_app_updates.sql`
4. `migrations/004_community_schema.sql` — **DanmuAI 社区**（`community_*` 表；供 `community-site/` 使用，与桌面 `supabase-config.js` 无关）
5. `migrations/005_community_registration_guard.sql` — 注册审计表 + Edge Function `community-register-guard`（见 [docs/community/REGISTRATION-GUARD.md](../docs/community/REGISTRATION-GUARD.md)）
6. `migrations/006_community_moderation.sql` — 举报 + 管理 RLS + 封禁（见 [docs/community/MODERATION.md](../docs/community/MODERATION.md)）
7. `migrations/007_community_site_maintenance.sql` — 社区站维护页开关（`community_site_status`，anon 只读）
8. `migrations/008_error_reports_user_note.sql` — 错误报告可选 `user_note`（补充说明）与 `contact`
9. `migrations/009_tutorial_links.sql` — 教程页视频链接（`tutorial_links`，anon 只读）

Copy `../web/static/supabase-config.example.js` to `../web/static/supabase-config.js` and set `url` + `anonKey`. The desktop **backend** reads the same credentials (or `DANMU_SUPABASE_URL` / `DANMU_SUPABASE_ANON_KEY`) for `GET /api/update/channels` → Supabase `app_updates`.

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

社区站环境变量见 [`../docs/community/SUPABASE-SCHEMA.md`](../docs/community/SUPABASE-SCHEMA.md) 与 [`../community-site/.env.example`](../community-site/.env.example).

## `app_updates`（版本更新提醒）

| 列 | 说明 |
|----|------|
| `latest_version` | 最新发布版本（semver `vx.x.x`，如 `0.3.0` 或 `v0.3.0`，与 `app/version.py` 一致） |
| `release_url` | 下载页；默认 **R2 主下载 Setup.exe**（`https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe`）；便携版见 `PEPETII.DanmuAI-win-Portable.zip`；GitHub Releases 仅备用 |
| `enabled` | `false` 时客户端不读取该行 |
| `message` | 可选，更新弹窗副文案 |

**运维**：发布 GitHub Release 并确认安装包无误后，在 Table Editor 插入或更新**一条** `enabled=true` 记录（通常只保留最新一行；客户端按 `updated_at desc` 取第一条）。Web 控制台版本区与更新弹窗通过后端 `GET /api/update/channels` 读取本表，不再维护 `app/release_channels.py` 中的发布版本常量。

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
