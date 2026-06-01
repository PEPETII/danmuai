# Supabase — 公告、反馈、错误报告与版本更新

Apply migrations in order (or use Supabase MCP `apply_migration`):

1. `migrations/001_announcements_feedback.sql`
2. `migrations/002_error_reports.sql`
3. `migrations/003_app_updates.sql`
4. `migrations/004_community_schema.sql` — **DanmuAI 社区**（`community_*` 表；供 `community-site/` 使用，与桌面 `supabase-config.js` 无关）
5. `migrations/005_community_registration_guard.sql` — 注册审计表 + Edge Function `community-register-guard`（见 [docs/community/REGISTRATION-GUARD.md](../docs/community/REGISTRATION-GUARD.md)）
6. `migrations/006_community_moderation.sql` — 举报 + 管理 RLS + 封禁（见 [docs/community/MODERATION.md](../docs/community/MODERATION.md)）

Copy `../web/static/supabase-config.example.js` to `../web/static/supabase-config.js` and set `url` + `anonKey`.

社区站环境变量见 [`../docs/community/SUPABASE-SCHEMA.md`](../docs/community/SUPABASE-SCHEMA.md) 与 [`../community-site/.env.example`](../community-site/.env.example).

## `app_updates`（版本更新提醒）

| 列 | 说明 |
|----|------|
| `latest_version` | 最新发布版本（semver `vx.x.x`，如 `0.3.0` 或 `v0.3.0`，与 `app/version.py` 一致） |
| `release_url` | 下载页，默认 GitHub Releases |
| `enabled` | `false` 时客户端不读取该行 |
| `message` | 可选，更新弹窗副文案 |

**运维**：发布 GitHub Release 并确认安装包无误后，在 Table Editor 插入或更新**一条** `enabled=true` 记录（通常只保留最新一行；客户端按 `updated_at desc` 取第一条）。

```sql
insert into public.app_updates (latest_version, release_url, message)
values (
  '0.3.0',
  'https://github.com/PEPETII/danmuai/releases',
  null
);
```
