# W-REL-MSI-003 完成报告：Supabase 线上 release_url 迁移至 MSI

> 工单 ID：W-REL-MSI-003  
> 完成时间：2026-06-13 09:23:03 UTC  
> 执行方式：Supabase MCP `execute_sql`（`user-supabase`）  
> 目标 URL：`https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi`

---

## 1. 迁移前后 column_default 对比

| 阶段 | `release_url` 列默认值 |
|------|------------------------|
| **迁移前** | `'https://github.com/PEPETII/danmuai/releases'::text` |
| **迁移后** | `'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi'::text` |

---

## 2. enabled=true 行迁移前后对比

| 字段 | 迁移前 | 迁移后 |
|------|--------|--------|
| `id` | `ecda87a3-77db-4804-87fe-5d59e93ee94a` | `ecda87a3-77db-4804-87fe-5d59e93ee94a` |
| `latest_version` | `0.3.0` | `0.3.0`（本工单未修改） |
| `release_url` | `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe` | `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi` |
| `enabled` | `true` | `true` |
| `updated_at` | `2026-06-11 14:51:03.477335+00` | `2026-06-11 14:51:03.477335+00`（UPDATE 未改 `updated_at`） |

**表内总行数**：1（`enabled=true` 1 行，无 `enabled=false` 行）

---

## 3. 执行的 SQL 与时间

**执行时间（UTC）**：2026-06-13 09:23:03 UTC

```sql
ALTER TABLE public.app_updates
  ALTER COLUMN release_url SET DEFAULT
    'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi';

UPDATE public.app_updates
SET release_url = 'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi'
WHERE enabled = true;
```

**UPDATE 影响行数**：**1**（与预期一致）

---

## 4. 迁移后验证

### 4.1 列默认

```sql
SELECT column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'app_updates'
  AND column_name = 'release_url';
```

结果：`'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi'::text` — **通过**

### 4.2 启用行

```sql
SELECT id, latest_version, release_url, enabled, updated_at
FROM public.app_updates
WHERE enabled = true
ORDER BY updated_at DESC
LIMIT 5;
```

| `release_url` | 状态 |
|---------------|------|
| `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi` | **通过** |

### 4.3 MSI 行计数

```sql
SELECT COUNT(*) AS enabled_msi_rows
FROM public.app_updates
WHERE enabled = true
  AND release_url = 'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi';
```

结果：**1** — 所有 `enabled=true` 行均已指向 MSI

---

## 5. 多余 enabled 行清理建议

当前仅 **1** 行 `enabled=true`，**无需**合并或清理。

---

## 6. 回滚 SQL

若需回滚至本工单执行前状态：

```sql
ALTER TABLE public.app_updates
  ALTER COLUMN release_url SET DEFAULT
    'https://github.com/PEPETII/danmuai/releases';

UPDATE public.app_updates
SET release_url = 'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe'
WHERE id = 'ecda87a3-77db-4804-87fe-5d59e93ee94a';
```

---

## 7. 客户端行为说明

| 链路 | 行为 |
|------|------|
| Web 更新弹窗 | `fetchAppUpdate` 读取 Supabase `release_url` → 手动下载链接为 MSI |
| `app-update-banner.js` 兜底 | `DEFAULT_RELEASE_URL` 已为 MSI（W-REL-MSI-001） |
| Velopack 自动更新 | 仍走 `https://updates.qiaoqiao.buzz/releases/win/stable`，**不受**本迁移影响 |

---

## 8. 手动验证步骤

1. Supabase Dashboard → Table Editor → `app_updates`，确认 `release_url` 列为 MSI URL
2. 本地启动客户端（配置 `supabase-config.js`），在 `latest_version` 高于本地版本时触发更新弹窗，确认「前往下载」指向 `DanmuAI-Installer.msi`

> 注：当前 `latest_version` 仍为 `0.3.0`；R2 已发布 `0.3.1`（见 W-REL-MSI-002）。若需弹窗提示新版本，需在后续发布窗口单独 UPDATE `latest_version`。

---

## 9. 验收对照

- [x] 迁移前状态已记录在报告中
- [x] `ALTER TABLE ... SET DEFAULT` 执行成功
- [x] `UPDATE ... WHERE enabled = true` 影响 1 行
- [x] 迁移后 `SELECT` 确认 DEFAULT 与启用行均为 MSI URL
- [x] 完成报告已撰写

---

## 10. 后续工单

| 工单 | 说明 |
|------|------|
| [W-REL-MSI-004](../docs/operations/W-REL-MSI-004-MSI真机验收.md) | MSI 真机验收（Velopack 更新通道） |
| 运维（范围外） | 视发布窗口将 `latest_version` 同步为 `0.3.1` 并更新 `message` |
