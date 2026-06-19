# W-REL-SETUP-003 完成报告：Supabase 线上 release_url 迁回 Setup.exe

> 工单 ID：W-REL-SETUP-003  
> 完成时间：2026-06-13（UTC）  
> 执行方式：Supabase MCP `execute_sql`（`user-supabase`）  
> 目标 URL：`https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe`

---

## 1. 迁移前后 column_default 对比

| 阶段 | `release_url` 列默认值 |
|------|------------------------|
| **迁移前** | `'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi'::text` |
| **迁移后** | `'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe'::text` |

---

## 2. enabled=true 行迁移前后对比

| 字段 | 迁移前 | 迁移后 |
|------|--------|--------|
| `id` | `ecda87a3-77db-4804-87fe-5d59e93ee94a` | `ecda87a3-77db-4804-87fe-5d59e93ee94a` |
| `latest_version` | `0.3.0` | `0.3.0`（本工单未修改） |
| `release_url` | `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi` | `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe` |
| `enabled` | `true` | `true` |
| `updated_at` | `2026-06-11 14:51:03.477335+00` | 未变（UPDATE 未改 `updated_at`） |

**表内 `enabled=true` 行数**：1

---

## 3. 执行的 SQL

```sql
ALTER TABLE public.app_updates
  ALTER COLUMN release_url SET DEFAULT
    'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe';

UPDATE public.app_updates
SET release_url = 'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe'
WHERE enabled = true;
```

**UPDATE 影响行数**：1（与预期一致）

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

结果：`'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe'::text` — **通过**

### 4.2 启用行

```sql
SELECT id, latest_version, release_url, enabled, updated_at
FROM public.app_updates
WHERE enabled = true
ORDER BY updated_at DESC;
```

| `release_url` | 状态 |
|---------------|------|
| `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe` | **通过** |

### 4.3 Setup 行计数

```sql
SELECT COUNT(*) AS enabled_setup_rows
FROM public.app_updates
WHERE enabled = true
  AND release_url = 'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe';
```

结果：**1** — 所有 `enabled=true` 行均已指向 Setup

---

## 5. 多余 enabled 行清理建议

当前仅 **1** 行 `enabled=true`，**无需**合并或清理。

---

## 6. 回滚 SQL

若需回滚至本工单执行前（MSI 主入口）：

```sql
ALTER TABLE public.app_updates
  ALTER COLUMN release_url SET DEFAULT
    'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi';

UPDATE public.app_updates
SET release_url = 'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi'
WHERE enabled = true;
```

---

## 7. 客户端行为说明

| 链路 | 行为 |
|------|------|
| Web 更新弹窗 | `fetchAppUpdate` 读取 Supabase `release_url` → 手动下载链接为 **Setup.exe** |
| `app-update-banner.js` 兜底 | `DEFAULT_RELEASE_URL` 已为 Setup（W-REL-SETUP-001） |
| `GET /api/update/channels` | `r2_latest_installer_url` = Setup（dev/新构建） |
| Velopack 自动更新 | 仍走 `https://updates.qiaoqiao.buzz/releases/win/stable`，**不受**本迁移影响 |

**注意**：已安装的 frozen **0.3.1** 客户端若内嵌常量仍为 MSI，需下一版发包后与 Supabase 完全一致；本迁移主要修复远程 `release_url` 驱动的弹窗链接。

---

## 8. 验收清单

- [x] 迁移前状态已记录
- [x] `ALTER TABLE ... SET DEFAULT` 执行成功
- [x] `UPDATE ... WHERE enabled = true` 影响 1 行
- [x] 迁移后 DEFAULT 与启用行均为 Setup URL
- [x] 回滚 SQL 已写入报告
- [x] 本报告已撰写

---

## 9. 收尾复验（W-REL-SETUP-003 计划执行）

**复验时间**：2026-06-13（UTC），Supabase MCP `execute_sql`

| 检查项 | 结果 |
|--------|------|
| `column_default` | `'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe'::text` — **通过** |
| `enabled=true` 行 `release_url` | Setup URL — **通过** |
| `enabled=true` 行 `latest_version` | `0.3.0`（未变） |
| Setup 行计数 | **1** — **通过** |

### `latest_version` 发布决策

**决策**：**暂不**将 `latest_version` 升为 `0.3.1`。

**理由**：R2 feed latest Full 已为 `0.3.1`，但 frozen 0.3.1 客户端内嵌常量可能仍为 MSI；在未完成下一版发包对齐前，不主动通过 Supabase 触发「发现新版本」弹窗。`release_url` 已指向 Setup，远程手动下载链接已正确。

**后续**：需推送更新提醒时，运维执行：

```sql
UPDATE public.app_updates
SET latest_version = '0.3.1', updated_at = now()
WHERE enabled = true;
```

（`release_url` 可保持 Setup 不变。）
