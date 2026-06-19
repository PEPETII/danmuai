# W-REL-MSI-003 执行提示词

> 你只执行**当前工单**，不要实现未来功能，不要顺手重构无关代码，不要自行决定新架构。

---

## 当前工单

- **工单 ID**：W-REL-MSI-003
- **标题**：Supabase 线上 `app_updates.release_url` 迁移至 MSI 主入口
- **前置依赖**：[W-REL-MSI-001](W-REL-MSI-001-MSI主入口切换.md)（migration 源文件 DEFAULT 已改为 MSI）

## 执行前必须阅读

1. [supabase/README.md](../../supabase/README.md) — `app_updates` 表说明
2. [supabase/migrations/003_app_updates.sql](../../supabase/migrations/003_app_updates.sql)
3. [reports/W-REL-MSI-001-completion-report.md](../../reports/W-REL-MSI-001-completion-report.md) §8

## 目标

使**已部署** Supabase PostgreSQL 中 `public.app_updates` 的列级 DEFAULT 与所有 `enabled=true` 行的 `release_url` 指向 MSI 主下载 URL。

**本工单不**修改客户端 Velopack 更新 feed；**不**修改 `003_app_updates.sql` 以外的 migration 业务逻辑。

## 必须遵守

1. 目标 URL 固定为：`https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi`
2. 执行 SQL 前备份或记录当前 `enabled=true` 行（`SELECT` 截图或导出）
3. 使用 Supabase Dashboard SQL Editor 或 MCP `execute_sql`（需运维授权）；禁止将 service role key 写入仓库
4. 可与 W-REL-MSI-002 并行执行（仅影响应用内更新弹窗的手动下载链接）

## 允许修改的区域

```
reports/W-REL-MSI-003-*.md
```

## 禁止修改的区域

```
app/
web/
scripts/
tests/
supabase/migrations/（本工单为线上数据迁移，不改源 migration 文件）
.env / supabase-config.js 密钥
```

## 具体需求

### 1. 迁移前检查

```sql
-- 列默认
SELECT column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'app_updates'
  AND column_name = 'release_url';

-- 当前启用行
SELECT id, latest_version, release_url, enabled, updated_at
FROM public.app_updates
WHERE enabled = true
ORDER BY updated_at DESC;
```

记录迁移前 `release_url` 值（可能仍为 Setup.exe 或 GitHub）。

### 2. 执行迁移 SQL

```sql
ALTER TABLE public.app_updates
  ALTER COLUMN release_url SET DEFAULT
    'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi';

UPDATE public.app_updates
SET release_url = 'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi'
WHERE enabled = true;
```

### 3. 迁移后验证

```sql
SELECT column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'app_updates'
  AND column_name = 'release_url';

SELECT id, latest_version, release_url, enabled, updated_at
FROM public.app_updates
WHERE enabled = true
ORDER BY updated_at DESC
LIMIT 5;
```

预期：

- `column_default` 含 `DanmuAI-Installer.msi`
- 所有 `enabled=true` 行 `release_url` 为 MSI URL

### 4. 客户端行为说明（验收参考）

- Web 控制台更新弹窗通过 Supabase `fetchAppUpdate` 读取 `release_url` 作为手动下载链接之一
- 应用内 Velopack 自动更新仍走 `https://updates.qiaoqiao.buzz/releases/win/stable`，**不受**本迁移影响

## 非目标

- 不修改 R2 对象（见 W-REL-MSI-002）
- 不修改 `latest_version` 或 `message` 字段（除非运维同时发布新版本且属同一发布窗口）
- 不做 MSI 真机验收（见 W-REL-MSI-004）

## 验收标准

- [ ] 迁移前状态已记录在报告中
- [ ] `ALTER TABLE ... SET DEFAULT` 执行成功
- [ ] `UPDATE ... WHERE enabled = true` 影响行数符合预期（通常 ≥1）
- [ ] 迁移后 `SELECT` 确认 DEFAULT 与启用行均为 MSI URL
- [ ] 完成报告 `reports/W-REL-MSI-003-supabase-migration-report.md` 已撰写

## 手动验证步骤

1. Supabase Table Editor 打开 `app_updates`，确认 `release_url` 列
2. 本地启动客户端（配置 `supabase-config.js`），触发更新弹窗，确认 R2 下载链接为 MSI（需 `latest_version` 高于本地版本或 mock）

## 已知风险

1. **多行 enabled=true**：客户端按 `updated_at desc` 取第一条；建议只保留一行 `enabled=true`
2. **新 INSERT 省略 release_url**：迁移后 DEFAULT 生效；迁移前旧 DEFAULT 可能导致新行仍用 Setup URL
3. **回滚**：保留迁移前 `release_url` 值，必要时 `UPDATE` 回滚

## 完成后必须给出

1. 迁移前后 `column_default` 对比
2. `enabled=true` 行迁移前后 `release_url` 表
3. 执行的 SQL 与时间（UTC）
4. 是否建议合并/清理多余的 `enabled=true` 行
