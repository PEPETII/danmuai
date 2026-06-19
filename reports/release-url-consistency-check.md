# 更新入口一致性核查（release_url）

日期：2026-06-11  
仓库：`E:/test/danmu`  
目标 R2 主下载：`https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe`

## 核查范围

1. Supabase 线上 `public.app_updates.release_url`（`enabled=true` 最新一行）
2. `web/static/modules/app-update-banner.js` 中 `DEFAULT_RELEASE_URL`

**未执行**：`publish_windows_release.ps1`、`upload_r2_release.ps1`、`upload_github_release.ps1`；未改动发布脚本；未涉及 R2 凭证。

---

## 核查结果（修复前）

| 检查项 | 修复前值 | 是否对齐 R2 |
|--------|----------|-------------|
| Supabase `app_updates`（`latest_version=0.3.0`，`enabled=true`） | `https://github.com/PEPETII/danmuai/releases` | **否** |
| `app-update-banner.js` `DEFAULT_RELEASE_URL` | `https://github.com/PEPETII/danmuai/releases` | **否** |

**结论（修复前）**：线上公告链路与 Web 兜底 URL 均仍指向 GitHub Releases 列表页，与冻结发布契约（R2 主下载）不一致。

---

## 已实施的最小修复

### 1. Supabase 线上数据

```sql
UPDATE public.app_updates
SET release_url = 'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe',
    updated_at = now()
WHERE id = 'ecda87a3-77db-4804-87fe-5d59e93ee94a'
  AND enabled = true;
```

**修复后复核**（`enabled=true` 最新一行）：

| 字段 | 值 |
|------|-----|
| `latest_version` | `0.3.0` |
| `release_url` | `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe` |
| `enabled` | `true` |
| `updated_at` | `2026-06-11 14:51:03+00` |

### 2. Web 兜底常量

`web/static/modules/app-update-banner.js`：

- `DEFAULT_RELEASE_URL` → `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe`

当 Supabase 未配置或拉取失败时，用户点击「前往下载」将落到 R2 主安装包，而非 GitHub Releases 页。

---

## 修复后结论

| 检查项 | 状态 |
|--------|------|
| Supabase 线上 `release_url` | **已对齐 R2** |
| `DEFAULT_RELEASE_URL` | **已对齐 R2** |

---

## 剩余说明（非本次必改）

- `supabase/migrations/003_app_updates.sql` 列默认值仍为 GitHub Releases URL；仅影响**未显式填写 `release_url` 的新 INSERT**。运维后续插入行时应显式使用 R2 URL（见 [supabase/README.md](../supabase/README.md)）。
- 应用内 Velopack 自动更新仍走 `https://updates.qiaoqiao.buzz/releases/win/stable`（[app/velopack_config.py](../app/velopack_config.py)），与本核查的「公告/手动下载」链路相互独立。
- GitHub Releases 仍为镜像/备用，不作为 `release_url` 主入口。

---

## 变更文件

| 文件 | 动作 |
|------|------|
| `web/static/modules/app-update-banner.js` | 更新 `DEFAULT_RELEASE_URL` |
| Supabase `public.app_updates` | 线上 `release_url` UPDATE |
| `reports/release-url-consistency-check.md` | 本报告 |
