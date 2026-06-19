# app_updates release_url 迁移默认值修正核查

**日期**：2026-06-11  
**工单**：修正 `supabase/migrations/003_app_updates.sql` 中 `release_url` 列默认值

## 1. 修复前问题

[`supabase/migrations/003_app_updates.sql`](../supabase/migrations/003_app_updates.sql) 第 7 行 `release_url` 列默认值为：

```text
https://github.com/PEPETII/danmuai/releases
```

与已对齐的 R2 主下载入口（[`supabase/README.md`](../supabase/README.md)、[`web/static/modules/app-update-banner.js`](../web/static/modules/app-update-banner.js)、[`README.md`](../README.md)）不一致。未来在新环境跑 migrations，或有人 `INSERT` 时省略 `release_url`，会默认回到 GitHub Releases 而非 R2 主下载。

线上 `app_updates` 行数据此前已单独修正（见 [release-url-consistency-check.md](./release-url-consistency-check.md)），本工单仅改 migration 源文件默认值，不触碰线上数据。

## 2. 修改了哪个文件

| 文件 | 变更 |
|------|------|
| [`supabase/migrations/003_app_updates.sql`](../supabase/migrations/003_app_updates.sql) | `release_url` 列 `DEFAULT` 由 GitHub Releases 改为 R2 主下载 URL（1 行） |
| [`reports/release-url-migration-default-check.md`](./release-url-migration-default-check.md) | 本报告（新建） |

未修改：发布脚本、`web/`、`app/`、其他 migration、R2/Cloudflare 配置。

## 3. 修改后的默认值

```sql
release_url text not null default 'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe',
```

公开 URL：

```text
https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe
```

## 4. 是否发现其他 GitHub Releases 主入口残留

**核查命令**（已执行）：

```powershell
rg "github.com/PEPETII/danmuai/releases|updates.qiaoqiao.buzz|release_url" supabase web README.md docs scripts
```

**`supabase/` 目录**：修复后 **无** `github.com/PEPETII/danmuai/releases` 匹配；`003_app_updates.sql` 默认值为 R2 URL。

**其余命中（非主入口冲突）**：

| 位置 | 用途 |
|------|------|
| [`README.md`](../README.md) L81 | GitHub Releases 标注为「镜像/备用」链接 |
| [`docs/release/README.md`](../docs/release/README.md) | 明确 GitHub Releases 仅为镜像 |
| [`docs/operations/PACKAGING_WINDOWS.md`](../docs/operations/PACKAGING_WINDOWS.md) | 发布链路 R2 → GitHub 镜像 |
| [`docs/operations/WINDOWS_RELEASE_BASELINE.md`](../docs/operations/WINDOWS_RELEASE_BASELINE.md) | R2 主真源；GitHub 镜像 |
| [`docs/operations/WINDOWS_RELEASE_CONTRACT.md`](../docs/operations/WINDOWS_RELEASE_CONTRACT.md) | R2 为主；Supabase `release_url` 可指向 R2 或 GitHub 镜像页 |
| [`scripts/upload_github_release.ps1`](../scripts/upload_github_release.ps1) | 脚本输出提示主下载为 R2 URL（未改脚本） |

**未发现** 将 GitHub Releases 作为用户主下载入口的代码或 SQL 默认值残留（migration 修复后）。

## 5. 是否确认 GitHub Releases 仍只是镜像

是。文档与脚本输出一致：

- [`README.md`](../README.md)：**主下载** R2；GitHub Releases 为镜像/备用。
- [`docs/operations/WINDOWS_RELEASE_BASELINE.md`](../docs/operations/WINDOWS_RELEASE_BASELINE.md)：R2 为主真源；`upload_github_release.ps1` 为镜像。
- [`docs/release/README.md`](../docs/release/README.md)：主下载源为 R2；GitHub Releases 仅为镜像。
- 应用内 Velopack 更新 feed 仍为 `https://updates.qiaoqiao.buzz/releases/win/stable`（与公告/手动下载链路独立）。

## 6. 是否发现密钥泄露风险

**否。** 本工单 diff 仅含公开 HTTPS URL，无 R2 访问密钥、Cloudflare API token、Supabase service role key 等。

`rg` 在 `supabase/` 内命中 `service_role` 仅见于社区 Edge Function 迁移/代码（[`005_community_registration_guard.sql`](../supabase/migrations/005_community_registration_guard.sql)、[`community-register-guard/index.ts`](../supabase/functions/community-register-guard/index.ts)），与本工单变更无关，且为环境变量引用而非硬编码密钥。

## 7. 是否存在未处理的后续风险

| 风险 | 说明 |
|------|------|
| **已部署线上库的列级 DEFAULT 未变** | 修改历史 migration 文件 **不会** 自动更新 PostgreSQL 中已存在表的列默认。若线上有人 `INSERT INTO app_updates (latest_version, ...)` 且省略 `release_url`，数据库仍可能使用旧默认（GitHub），除非运维另行执行 `ALTER TABLE public.app_updates ALTER COLUMN release_url SET DEFAULT 'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe';`。本工单按范围 **不** 执行该 ALTER、不 UPDATE 现有行。 |
| **新环境 / 从零 migrations** | 将正确获得 R2 默认。 |
| **运维习惯** | [`supabase/README.md`](../supabase/README.md) INSERT 示例已显式填写 R2 URL；建议发布时继续显式指定 `release_url`，不依赖默认值。 |

## 验收摘要

| 项 | 结果 |
|----|------|
| migration 默认值 | R2 `DanmuAI-Setup.exe` |
| 线上 Supabase 数据 | 未修改 |
| 新增 migration | 无 |
| 发布脚本 | 未改 |
| 全量 pytest | 未执行（按工单要求） |
