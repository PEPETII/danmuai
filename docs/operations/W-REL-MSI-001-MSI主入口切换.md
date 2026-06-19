# W-REL-MSI-001 执行提示词

> 你只执行**当前工单**，不要实现未来功能，不要顺手重构无关代码，不要自行决定新架构。

---

## 当前工单

- **工单 ID**：W-REL-MSI-001
- **标题**：将 DanmuAI Windows 主下载入口切换为 MSI，Setup.exe 改为备用入口

## 执行前必须阅读

1. [AGENTS.md](../AGENTS.md) §1–§10
2. [IDE_AGENT_RULES.md](../.local-ai/prompts/IDE_AGENT_RULES.md) §10（分批测试）、§11（发布 / R2 / 应用内更新）
3. [docs/operations/WINDOWS_RELEASE_CONTRACT.md](../docs/operations/WINDOWS_RELEASE_CONTRACT.md)
4. [docs/operations/PACKAGING_WINDOWS.md](../docs/operations/PACKAGING_WINDOWS.md)
5. [docs/ai-project-context.md](../docs/ai-project-context.md) §10 Windows 发布与应用内更新
6. 本提示词下方「具体需求」与「禁止修改的区域」

## 目标

将 Windows 发布策略调整为：

- **MSI**：官网主下载入口
- **Setup.exe**：备用下载入口
- **Portable.zip**：便携版入口

本工单**不**重写应用本体，**不**替换 Velopack 更新机制，**不**引入 Inno Setup / NSIS。

### 官方前提

Velopack 支持通过 `vpk pack --msi` 生成 MSI。MSI 与 Setup.exe 共用 Velopack 发布体系，安装后仍通过 `Update.exe` 和 `releases.win.json` 进行更新。

## 必须遵守

1. 不改 `app/` 业务逻辑，**除了** `app/release_channels.py` 中的 `R2_LATEST_INSTALLER_URL`（发现下载链接硬编码在应用内）。
2. 不删除 `DanmuAI-Setup.exe` 产物。
3. 不改变 `releases.win.json`、nupkg、delta 包的更新逻辑。
4. 不引入 Inno Setup / NSIS。
5. 不改动 R2、GitHub、Supabase 的密钥。
6. MSI 是主入口，但 Setup.exe 必须继续产出并上传，作为备用入口。

## 允许修改的区域

```
scripts/velopack_pack.ps1
scripts/upload_r2_release.ps1
scripts/upload_github_release.ps1
scripts/publish_windows_release.ps1
scripts/README.md
docs/operations/WINDOWS_RELEASE_CONTRACT.md
docs/operations/PACKAGING_WINDOWS.md
docs/operations/RELEASE_CHECKLIST.md
website/index.html
web/static/modules/app-update-banner.js
app/release_channels.py
supabase/migrations/003_app_updates.sql
supabase/README.md
README.md
docs/release/README.md
tests/test_release_channels.py
```

## 禁止修改的区域

```
app/（除 app/release_channels.py 外）
web/（除 web/static/modules/app-update-banner.js 外）
main.py
tests/（除 tests/test_release_channels.py 外）
requirements.txt
package.json
锁文件
配置文件（.env、supabase-config.js 等）
```

## 具体需求

### 1. 打包脚本（`scripts/velopack_pack.ps1`）

在现有 `vpk pack` 流程中增加 MSI 产物：

```powershell
--msi
--instLocation Either
```

要求：

- 保留现有 `DanmuAI-Setup.exe` 产出（不做任何改动）
- 保留现有 Portable.zip 产出
- 新增 `.msi` 产物（Velopack 输出的 MSI 文件）
- 新增 WiX 5 可用性检查：在调用 `vpk pack --msi` 之前，验证 WiX 5 工具链是否可用（`dotnet tool list -g` 中查找 `wix` 或检查 `wix` 命令可用性）。如果构建环境缺少 WiX 5，给出**明确错误提示**（Write-Error），不要静默失败
- 版本化 MSI 复制：仿照 Setup.exe 的做法，将 Velopack 输出的 MSI 复制为 `PEPETII.DanmuAI-<version>-Installer.msi`
- 返回值 Hashtable 新增字段：
  - `Msi`：MSI 原始文件完整路径
  - `VersionedMsi`：版本化 MSI 完整路径

### 2. 发布脚本（`scripts/publish_windows_release.ps1`）

- 清理旧版本文件时，增加 MSI 模式（`PEPETII.DanmuAI-*-Installer.msi`）
- 打印信息中增加 MSI 产物路径
- `VERSION.txt` 内容增加 MSI 文件名行
- 控制台输出中的主下载 URL 更新为 MSI

### 3. R2 上传策略（`scripts/upload_r2_release.ps1`）

R2 需要同时上传：

| 资产 | R2 Key | 说明 |
|------|--------|------|
| MSI 主安装包（版本化） | `downloads/PEPETII.DanmuAI-<version>-Installer.msi` | 版本化 MSI，长期缓存 |
| MSI 主安装包（别名） | `downloads/DanmuAI-Installer.msi` | latest alias，`no-cache`，服务端 copy |
| Setup.exe 备用安装包（版本化） | `downloads/PEPETII.DanmuAI-<version>-Setup.exe` | **保留现有逻辑** |
| Setup.exe 备用安装包（别名） | `downloads/DanmuAI-Setup.exe` | **保留现有逻辑** |
| Portable.zip（版本化） | `downloads/PEPETII.DanmuAI-<version>-win-Portable.zip` | 版本化 Portable，如果存在则上传 |
| Portable.zip（别名） | `downloads/PEPETII.DanmuAI-win-Portable.zip` | latest alias，`no-cache`，服务端 copy |
| 更新清单 | `releases/win/stable/releases.win.json` | **保留现有逻辑** |
| 全量/增量 nupkg | `releases/win/stable/*.nupkg` | **保留现有逻辑** |

别名策略（仿照现有 `Invoke-R2LatestAliasCopy`）：

- `DanmuAI-Installer.msi` 从 `PEPETII.DanmuAI-<version>-Installer.msi` 服务端 copy
- `PEPETII.DanmuAI-win-Portable.zip` 从 `PEPETII.DanmuAI-<version>-win-Portable.zip` 服务端 copy
- `DanmuAI-Setup.exe` 从 `PEPETII.DanmuAI-<version>-Setup.exe` 服务端 copy（**保留现有逻辑**）

控制台输出 URL 更新：

```text
Public URLs (custom domain):
  https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi       (主入口)
  https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe           (备用入口)
  https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip (便携版)
  https://updates.qiaoqiao.buzz/releases/win/stable                   (更新 feed)
```

### 4. GitHub Release 上传策略（`scripts/upload_github_release.ps1`）

GitHub Releases 附件中必须包含（按优先级排列）：

1. `PEPETII.DanmuAI-<version>-Installer.msi`（MSI 主安装包）
2. `PEPETII.DanmuAI-win-Setup.exe`（Setup.exe 备用安装包）
3. `PEPETII.DanmuAI-<version>-Setup.exe`（版本化 Setup）
4. `PEPETII.DanmuAI-win-Portable.zip`（便携版）
5. `PEPETII.DanmuAI-<version>-full.nupkg`
6. `PEPETII.DanmuAI-<version>-delta.nupkg`
7. `releases.win.json`

Release 说明中的下载区格式（如果 NotesFile 可控或脚本内拼接）：

```md
推荐下载：
- Windows 安装版 (MSI)：DanmuAI-Installer.msi

其他下载：
- 一键安装备用版 (Setup.exe)：DanmuAI-Setup.exe
- 便携版 (ZIP)：Portable.zip
```

控制台输出 URL 更新为主入口 MSI。

### 5. 官网下载区（`website/index.html`）

官网主按钮改为 MSI：

```html
<a href="https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi"
   class="btn-primary btn-pulse w-full justify-center mb-3">
  <svg class="ui-icon" aria-hidden="true"><use href="#i-download"></use></svg>
  下载 Windows 安装版 (MSI)
</a>
```

主按钮下方增加其他下载方式（替换当前单一的 GitHub Releases 备选链接）：

```html
<div class="text-center text-xs" style="color:var(--color-text-dim)">
  <p>其他下载方式：</p>
  <p>
    <a href="https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe">一键安装备用版 (Setup.exe)</a> ·
    <a href="https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip">便携版 ZIP</a> ·
    <a href="https://github.com/PEPETII/danmuai/releases" target="_blank" rel="noopener noreferrer">GitHub Releases 镜像</a>
  </p>
  <p>高级用户：Setup.exe 支持 --installto 自定义安装路径</p>
</div>
```

下载卡片的描述文案更新：

```html
<p class="text-sm mb-6" style="color:var(--color-text-dim)">
  Windows x64 安装程序（.msi），安装后即可运行。主下载源已同步至最新稳定版。
</p>
```

**不要**再把 Setup.exe 描述成"推荐下载"。

### 6. Supabase / app-update-banner 下载链接

以下文件中指向 `DanmuAI-Setup.exe` 的"用户手动下载最新版"链接需改为 `DanmuAI-Installer.msi`：

#### 6.1 `web/static/modules/app-update-banner.js`

```js
const DEFAULT_RELEASE_URL = 'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi';
```

**不要改**应用内自动更新 feed URL（`https://updates.qiaoqiao.buzz/releases/win/stable`）。

#### 6.2 `app/release_channels.py`

```python
R2_LATEST_INSTALLER_URL = "https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi"
```

#### 6.3 `supabase/migrations/003_app_updates.sql`

```sql
release_url text not null default 'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi',
```

**注意**：修改历史 migration 文件**不会**自动更新已部署的 PostgreSQL 表列默认值。需要在完成报告中明确提示：线上环境需运维另行执行 `ALTER TABLE` 才能生效。

#### 6.4 `supabase/README.md`

更新 INSERT 示例中的 `release_url` 为 MSI URL：

```sql
insert into public.app_updates (latest_version, release_url, message)
values (
  '0.3.0',
  'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi',
  null
);
```

更新 `release_url` 列说明：

```
| `release_url` | 下载页；默认 **R2 主下载 MSI**（`https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi`）；Setup.exe 为备用；GitHub Releases 仅备用 |
```

#### 6.5 `tests/test_release_channels.py`

将 `r2_latest_installer_url` 期望值改为 MSI URL，并与 `app.release_channels.R2_LATEST_INSTALLER_URL` 保持一致；`test_release_channels_api_route` 应断言 API 返回的 `r2_latest_installer_url` 与常量一致。

### 7. 发布契约文档（`docs/operations/WINDOWS_RELEASE_CONTRACT.md`）

更新以下章节：

#### §2 资产命名表

新增 MSI 相关行：

| 资产 | 路径 / 文件名 | 说明 |
|------|----------------|------|
| 版本化 MSI（真资产） | `downloads/PEPETII.DanmuAI-<version>-Installer.msi` | `<version>` = `app.version.__version__` |
| MSI Latest 别名 | `downloads/DanmuAI-Installer.msi` | 始终指向当前 stable 最新版 MSI；官网主按钮使用此链接 |
| Setup.exe Latest 别名 | `downloads/DanmuAI-Setup.exe` | 备用安装入口 |
| Portable Latest 别名 | `downloads/PEPETII.DanmuAI-win-Portable.zip` | 便携版入口 |

#### §3 R2 目录结构与 URL

新增：

```text
/downloads/PEPETII.DanmuAI-<version>-Installer.msi
/downloads/DanmuAI-Installer.msi                              # MSI latest 别名（覆盖写入）
/downloads/PEPETII.DanmuAI-win-Portable.zip                   # Portable latest 别名（覆盖写入）
```

公开 URL 表更新：

| 用途 | URL |
|------|-----|
| 用户下载（主入口 MSI） | `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi` |
| 用户下载（备用 Setup） | `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe` |
| 用户下载（便携版） | `https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip` |
| 用户下载（指定版本 MSI） | `https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-0.3.1-Installer.msi` |
| 客户端更新 feed | `https://updates.qiaoqiao.buzz/releases/win/stable` |

#### 新增章节：下载入口角色说明

```md
## 下载入口角色

| 入口 | 格式 | 角色 | 说明 |
|------|------|------|------|
| MSI | `.msi` | **主入口** | 官网主按钮；标准 Windows 安装体验 |
| Setup.exe | `.exe` | 备用入口 | 一键安装；支持 `--installto` 自定义路径 |
| Portable.zip | `.zip` | 便携入口 | 解压后直接运行，无需安装 |

- 应用内自动更新仍走 Velopack `Update.exe` + `releases.win.json`
- 三种入口安装后均通过同一 Velopack 更新通道接收后续版本
- 未签名情况下，MSI 和 Setup.exe 都可能触发 SmartScreen
```

### 8. 其他文档同步

#### 8.1 `README.md`

主下载链接从 Setup.exe 改为 MSI。

#### 8.2 `scripts/README.md`

- 更新 `upload_r2_release.ps1` 章节，说明现在同时上传 MSI、Setup.exe、Portable.zip 三种别名
- 更新 R2 为正式更新与主下载源的说明，标注 MSI 为主入口

#### 8.3 `docs/operations/PACKAGING_WINDOWS.md`

更新以下引用（已知出现位置）：

- 第 10 行：`| **主真源** | Cloudflare R2；用户主下载 ...` → 更新 URL 为 MSI，并注明 MSI 为主入口、Setup.exe 为备用
- 第 159 行：`latest 安装包别名仍为 .../DanmuAI-Setup.exe` → 更新为 `.../DanmuAI-Installer.msi`，并注明 Setup.exe 别名仍保留作为备用
- 第 482 行：`downloads/DanmuAI-Setup.exe 可公网访问` → 增加 MSI 别名和 Portable 别名的检查项

#### 8.4 `docs/operations/RELEASE_CHECKLIST.md`

- 第 30 行：R2 上传检查项增加 MSI 和 Portable.zip 别名
- 第 32 行：主下载 URL 检查项改为 `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi`，并增加 Setup.exe 备用 URL 检查项

#### 8.5 `docs/release/README.md`

- 第 3 行：主下载源 URL 从 `DanmuAI-Setup.exe` 改为 `DanmuAI-Installer.msi`
- 第 56 行：R2 安装包 URL 表格更新为主入口 MSI，并增加 Setup.exe 备用和 Portable.zip 行

## 非目标

- 不重写应用本体（`app/` 业务逻辑，`app/release_channels.py` 的 URL 常量除外）
- 不替换 Velopack 更新机制（`UpdateManager` + `releases.win.json` 不变）
- 不引入 Inno Setup / NSIS
- 不修改 `main.py` 冻结入口
- 不修改 `tests/` 中除 `tests/test_release_channels.py` 外的测试代码
- 不执行正式发布/上传脚本（除非工单明确授权；验证时只用 `-DryRun` 或只读检查产物目录）
- 不修改 R2、GitHub、Supabase 密钥
- 不修改应用内自动更新 feed URL（`https://updates.qiaoqiao.buzz/releases/win/stable`）
- 不执行 Supabase 线上 `ALTER TABLE`（仅改 migration 源文件）
- 不修改客户端 `UpdateManager` 配置

## 验收标准

- [ ] `scripts/velopack_pack.ps1` 中 `vpk pack` 命令包含 `--msi --instLocation Either`
- [ ] `scripts/velopack_pack.ps1` 包含 WiX 5 可用性检查，缺失时 `Write-Error` 明确报错
- [ ] `scripts/velopack_pack.ps1` 返回值 Hashtable 包含 `Msi` 和 `VersionedMsi` 字段
- [ ] `scripts/velopack_pack.ps1` 生成版本化 MSI 文件 `PEPETII.DanmuAI-<version>-Installer.msi`
- [ ] `scripts/upload_r2_release.ps1` 上传 MSI 版本化文件和 `DanmuAI-Installer.msi` 别名
- [ ] `scripts/upload_r2_release.ps1` 上传 Portable.zip 版本化文件和 `PEPETII.DanmuAI-win-Portable.zip` 别名
- [ ] `scripts/upload_r2_release.ps1` 保留现有 Setup.exe 上传和别名逻辑
- [ ] `scripts/upload_r2_release.ps1` 控制台输出包含三种入口 URL
- [ ] `scripts/upload_github_release.ps1` 资产列表包含 `.msi` 文件
- [ ] `scripts/upload_github_release.ps1` MSI 在资产列表中排在 Setup.exe 之前
- [ ] `website/index.html` 主按钮指向 `DanmuAI-Installer.msi`
- [ ] `website/index.html` 包含 Setup.exe 备用入口链接
- [ ] `website/index.html` 包含 Portable.zip 入口链接
- [ ] `website/index.html` 不再把 Setup.exe 描述为"推荐下载"
- [ ] `web/static/modules/app-update-banner.js` 的 `DEFAULT_RELEASE_URL` 指向 MSI
- [ ] `app/release_channels.py` 的 `R2_LATEST_INSTALLER_URL` 指向 MSI
- [ ] `supabase/migrations/003_app_updates.sql` 的 `release_url` DEFAULT 指向 MSI
- [ ] `supabase/README.md` 的 INSERT 示例指向 MSI
- [ ] `docs/operations/WINDOWS_RELEASE_CONTRACT.md` 包含 MSI 主入口、Setup.exe 备用入口、Portable.zip 便携入口的说明
- [ ] `docs/operations/WINDOWS_RELEASE_CONTRACT.md` R2 目录结构包含 MSI 和 Portable 别名路径
- [ ] `README.md` 主下载链接指向 MSI
- [ ] `scripts/README.md` 更新说明反映三种入口
- [ ] `scripts/publish_windows_release.ps1` 清理旧版本时包含 MSI 模式
- [ ] `scripts/publish_windows_release.ps1` 控制台输出主下载 URL 为 MSI
- [ ] `docs/operations/PACKAGING_WINDOWS.md` 中主下载 URL 引用已更新为 MSI
- [ ] `docs/operations/RELEASE_CHECKLIST.md` 中主下载 URL 检查项已更新为 MSI，并包含 Setup.exe 和 Portable.zip 检查项
- [ ] `docs/release/README.md` 中主下载源 URL 已更新为 MSI
- [ ] `tests/test_release_channels.py` 的 `r2_latest_installer_url` 断言指向 MSI，且 `pytest tests/test_release_channels.py` 通过
- [ ] 所有修改后的文件中，不存在将 `DanmuAI-Setup.exe` 描述为"推荐下载"或"主入口"的文案

## 手动验证步骤

1. 全局搜索 `DanmuAI-Setup.exe`，确认剩余出现仅属于以下合理场景：
   - 作为"备用入口"的描述
   - R2 别名 `downloads/DanmuAI-Setup.exe`（保留）
   - 版本化 Setup 文件名
   - 历史报告文件（`reports/` 目录下的已完成报告）
2. 全局搜索 `DanmuAI-Installer.msi`，确认所有新增引用一致
3. 阅读 `website/index.html` 下载区，确认主按钮指向 MSI、备用入口可找到 Setup.exe 和 Portable.zip
4. 阅读 `scripts/velopack_pack.ps1`，确认 `--msi --instLocation Either` 参数和 WiX 5 检查
5. 阅读 `scripts/upload_r2_release.ps1`，确认三种别名上传逻辑
6. 阅读 `docs/operations/WINDOWS_RELEASE_CONTRACT.md`，确认契约反映三种入口角色
7. 运行 `pytest tests/test_release_channels.py`，确认 MSI URL 断言通过
8. 使用 `git diff --stat` 确认修改文件列表仅包含允许区域

## 已知风险与注意事项

1. **WiX 5 工具链**：`vpk pack --msi` 依赖 WiX 5（`dotnet tool install -g wix`）。如果构建环境未安装 WiX 5，MSI 产物将无法生成。脚本必须做前置检查，不能静默跳过。
2. **MSI 安装路径**：`--instLocation Either` 允许用户选择安装到 Program Files 或自定义路径。与 Setup.exe 的行为有差异（Setup.exe 默认安装到 `%LocalAppData%`），需要验收时确认 MSI 安装后的目录结构和更新通道是否正常。
3. **Supabase 线上默认值**：修改 `supabase/migrations/003_app_updates.sql` 的 DEFAULT 值**不会**自动同步到已部署的 PostgreSQL 表。线上环境需运维另行执行：
   ```sql
   ALTER TABLE public.app_updates
     ALTER COLUMN release_url SET DEFAULT 'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi';
   ```
   同时建议运维 UPDATE 现有 `enabled=true` 行的 `release_url`。
4. **SmartScreen 警告**：未签名情况下，MSI 安装器同样会触发 Windows SmartScreen 警告，与 Setup.exe 一致。
5. **MSI 文件名约定**：本工单采用 `PEPETII.DanmuAI-<version>-Installer.msi` 作为版本化 MSI 命名，`DanmuAI-Installer.msi` 作为 latest 别名。如果需要调整命名约定，请在实施前明确。
6. **后续运维工单**：R2 线上 MSI 切换见 W-REL-MSI-002；Supabase 线上 `release_url` 见 W-REL-MSI-003；MSI 真机验收见 W-REL-MSI-004。

## 如果发现范围外问题

**不要修复。** 记录到完成报告的「发现但未处理的问题」章节，包括：

- `reports/` 目录下的历史报告文件中的旧 URL 引用（不影响功能，仅文档一致性）

需求不清楚时：**停止并向负责人提问**，禁止猜测实现。

## 完成后报告格式

按 [docs/templates/Codex完成报告/Codex完成报告模板.md](../.local-ai/prompts/templates/Codex完成报告/Codex完成报告模板.md) 输出完整报告。

### 完成后必须给出

1. 修改文件列表
2. MSI 主下载 URL：`https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi`
3. Setup.exe 备用下载 URL：`https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe`
4. Portable.zip 下载 URL：`https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip`
5. 官网下载区说明（主按钮 + 其他下载方式布局）
6. R2 上传策略变更说明
7. GitHub Release 附件变更说明
8. 是否发现仍有地方指向旧的 `DanmuAI-Setup.exe` 主链接（列出残留位置）
9. 分批测试报告（如涉及代码变更）
