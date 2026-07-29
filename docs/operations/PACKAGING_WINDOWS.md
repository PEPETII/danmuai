# Windows 打包指南

本文档描述如何从源码构建 DanmuAI Windows 发布包（PyInstaller onedir + Velopack），并为 **Windows 发布的权威入口**。

> 历史文档 `WINDOWS_RELEASE_CONTRACT.md`、`RELEASE_CHECKLIST.md`、`WINDOWS_CODE_SIGNING.md`、`WINDOWS_RELEASE_BASELINE.md` 已从仓库移除，请勿再引用。补充事实见 `.agents/skills/danmu-windows-release-upload/references/release-flow.md` 与 `reports/W-REL-CLEANUP-001-completion-report.md`。`docs/operations/W-REL-MSI-*` 为 MSI 实验归档，不得作为当前流程。

## 环境要求

- **操作系统**：Windows 10/11 x64
- **Python**：3.12+（推荐 3.12，与 CI 对齐）
- **.NET SDK**：8.0.x（用于 Velopack `vpk` CLI）
- **vpk CLI**：安装命令 `dotnet tool install -g vpk`
- **Git**：用于提取构建版本和 commit hash

## 依赖锁定（Windows 发布）

日常开发与 CI 仍使用 [`requirements.txt`](../../requirements.txt) + [`requirements-dev.txt`](../../requirements-dev.txt) 中的**版本范围**约束。正式发布可选用仓库根目录的 **`requirements-release-win-lock.txt`**：在 Windows + Python 3.12 上由 `pip freeze` 冻结的**精确版本**列表（含传递依赖），用于降低「不同时间解析到不同版本」导致的不可复现构建风险。

| 文件 | 用途 |
|------|------|
| `requirements.txt` / `requirements-dev.txt` | 开发说明与范围约束；**不替代** |
| `requirements-release-win-lock.txt` | **仅** Windows release build；不用于日常 `pip install` |

### 何时使用锁文件

维护者执行**正式发布**构建时，建议设置环境变量后再跑打包链：

```powershell
$env:DANMU_BUILD_USE_RELEASE_LOCK = "1"
.\scripts\publish_windows_release.ps1
```

`build_exe.ps1` 在 `DANMU_BUILD_USE_RELEASE_LOCK=1` 时会：

- 安装 `requirements-release-win-lock.txt`（而非两个范围文件）
- **强制**执行 `pip install`（即使检测到 `.venv-build`，以确保与锁文件一致）

未设置该变量时，行为与历史一致：默认 `pip install -r requirements.txt -r requirements-dev.txt`；若使用预置 `.venv-build` / `.venv-build-312` 则仍可能跳过 pip。

> **CI 说明**：`.github/workflows/ci.yml` 当前仍安装范围文件；强制 CI 使用锁文件需另开工单。本锁文件不解决代码签名或 SmartScreen 问题。

### 刷新锁文件

在 **Windows x64、Python 3.12**（与 CI 对齐）的**干净虚拟环境**中生成，避免污染本机全局 site-packages：

```powershell
Set-Location "E:\path\to\danmu"
py -3.12 -m venv .venv-lock-refresh
.\.venv-lock-refresh\Scripts\python.exe -m pip install --upgrade pip
.\.venv-lock-refresh\Scripts\pip.exe install -r requirements.txt -r requirements-dev.txt
.\.venv-lock-refresh\Scripts\pip.exe freeze | Sort-Object | Set-Content -Encoding utf8 requirements-release-win-lock.txt.new
```

在 `requirements-release-win-lock.txt.new` **顶部**保留或更新注释头（用途、源文件、Python 版本、生成日期、本文档链接），确认每行均为 `name==version` 后替换 `requirements-release-win-lock.txt`，并删除临时 venv：

```powershell
Remove-Item -Recurse -Force .venv-lock-refresh
Remove-Item requirements-release-win-lock.txt.new  # 合并完成后
```

**禁止**在锁文件中写入本机私有路径、`file://` URL、`-e` editable 安装或任何凭据。

### 审查 diff

提交锁文件变更前：

1. 确认使用 **Python 3.12** 生成；若 diff 异常大，先排除误用其他 Python 版本。
2. 运行 `Select-String -LiteralPath requirements-release-win-lock.txt -Pattern ">=","<" -Encoding UTF8`，应无匹配（注释行亦勿写范围符号）。
3. 检查无意外的 major 跳变；本流程**不主动升级** `requirements*.txt` 中的范围，仅记录当前 resolver 在约束内的解析结果。
4. 确认核心包仍在列：`PyQt6`、`pyinstaller`、`pywebview`、`velopack`、`cryptography`、`fastapi`、`httpx` 等。
5. 无 `file:` 路径或可疑本地包名。

## 打包命令链

### 1. 构建可执行文件

```powershell
.\scripts\build_exe.ps1
```

- 输出：`dist\DanmuAI\DanmuAI.exe`
- 自动处理：停止运行中的 DanmuAI 进程、清理旧输出、生成图标（若缺失）
- 若使用预配置的构建虚拟环境（`.venv-build` / `.venv-build-312`），脚本会自动检测并跳过重复 pip install

### 2. 打包 Velopack 发布包

```powershell
.\scripts\publish_windows_release.ps1
```

- 内部调用 `build_exe.ps1` + `velopack_pack.ps1`
- 输出目录：`release\velopack\`

#### 输出产物

| 文件 | 说明 |
|------|------|
| `PEPETII.DanmuAI-win-Setup.exe` | Velopack 安装器（本地原始输出） |
| `PEPETII.DanmuAI-<version>-Setup.exe` | 版本化 Setup（R2 / GitHub 上传源） |
| `PEPETII.DanmuAI-<version>-full.nupkg` | 全量更新包 |
| `PEPETII.DanmuAI-<version>-delta.nupkg` | 增量更新包（当有旧版 nupkg 本地缓存时生成） |
| `PEPETII.DanmuAI-win-Portable.zip` | 便携版（PyInstaller onedir 直接压缩） |
| `releases.win.json` | Velopack 更新 feed |
| `SHA256SUMS.txt` | 发布产物 SHA256 完整性清单（发布验收证据，非代码签名） |
| `VERSION.txt` | 构建元数据（版本、Git SHA、构建时间、Changelog 路径） |

#### 增量更新（Delta）机制

- `publish_windows_release.ps1` **不会**删除整个 `release\velopack\` 目录，而是保留旧的 `*-full.nupkg`，以便 `vpk pack` 生成 `*-delta.nupkg`。
- 如果本地没有旧版 full 包，脚本默认从线上 feed `https://updates.qiaoqiao.buzz/releases/win/stable` bootstrap 旧版元数据。使用 `-SkipDeltaBootstrap` 可禁用此行为。

### 3. 上传到 R2（主真源，stable 通道）

> **默认生产通道为 stable**。预发布验证请先走 canary 路径，经负责人确认后再执行本节上传；见 [CANARY_RELEASE_CHANNEL.md](CANARY_RELEASE_CHANNEL.md)。

```powershell
.\scripts\upload_r2_release.ps1
# 或指定版本
.\scripts\upload_r2_release.ps1 -Version 0.3.7
# 干跑预览
.\scripts\upload_r2_release.ps1 -Version 0.3.7 -DryRun
```

- 环境变量（仅本地/CI secret，**禁止入库**）：`R2_ACCOUNT_ID`、`R2_ACCESS_KEY_ID`、`R2_SECRET_ACCESS_KEY`、`R2_BUCKET`
- 上传前自动校验 `releases.win.json` 最新 Full 版本与目标版本一致
- 上传前强制校验 `SHA256SUMS.txt`：manifest 存在且本地产物 hash 与清单一致（完整性证据，**不是** Authenticode 签名替代品）
- 上传后仍通过 `head-object` 校验远端 `ContentLength`（补充校验，非唯一手段）
- `downloads/DanmuAI-Setup.exe` 和 `downloads/PEPETII.DanmuAI-win-Portable.zip` 的 latest alias 通过 R2 服务端复制，避免大文件重复本地上传

上传完成后须按 [RELEASE_ONLINE_VERIFY_AND_ROLLBACK.md](RELEASE_ONLINE_VERIFY_AND_ROLLBACK.md) 做只读线上验证（stable）；**本地产物存在不等于线上 alias / feed 已切换**。canary 预发布流程见 [CANARY_RELEASE_CHANNEL.md](CANARY_RELEASE_CHANNEL.md)。

### 4. 上传到 GitHub Releases（镜像/备用）

```powershell
.\scripts\upload_github_release.ps1
```

## 安全与检查

### 凭据泄漏防护

`publish_windows_release.ps1` 与 `DanmuAI.spec` 均对 `web/static/` 实施 **default-deny**（BUG-005）：任何文件名包含 `supabase-config` 的文件都会阻断发布，除非在 allowlist 中：

| 允许保留 | 说明 |
|----------|------|
| `supabase-config.example.js` | 模板，无凭据 |
| `supabase-client.js` | 客户端代码，无凭据 |

**禁止**在 `web/static/` 内以任何变体名保留真实配置，包括 `supabase-config.js`、`.bak`、`.codex-release-backup`、`-local` 等。在目录内重命名备份**不能**绕过守卫。

本地开发者若存在 `web/static/supabase-config.js`，须在发布前将其**移出** `web/static/` 目录。完整三步流程（移出 → DryRun → 恢复）见 [IDE_WINDOWS_BUILD_PLAYBOOK.md §4.2](IDE_WINDOWS_BUILD_PLAYBOOK.md#42-源树阻断项supabase-本地配置)。

推荐临时路径：`.local-ai/release-local/supabase-config.js`（`.local-ai/` 已 gitignore，且不在 PyInstaller 收集范围内）。

DryRun 仅验证版本解析与守卫，不执行构建：

```powershell
.\scripts\publish_windows_release.ps1 -DryRun
```

CI 环境通常无 `supabase-config.js`，无需移出步骤。打包版运行时凭据应通过 `DANMU_SUPABASE_URL` / `DANMU_SUPABASE_ANON_KEY` 注入（见 `supabase/README.md`）。

### 代码签名（可选）

设置环境变量 `DANMU_CODE_SIGN=1` 启用：

- **Azure Artifact Signing**：设置 `VPK_AZURE_TRUSTED_SIGN_FILE`
- **signtool**：设置 `VPK_SIGN_PARAMS`

签名凭据仅通过环境变量传入，禁止提交 PFX、密码或 PIN 到仓库。

### SHA256 完整性清单（发布验收）

`publish_windows_release.ps1` 在 pack 完成后自动写入 `release\velopack\SHA256SUMS.txt`。也可单独生成或校验：

```powershell
.\scripts\write_release_hash_manifest.ps1 -ReleaseDir release\velopack
.\scripts\write_release_hash_manifest.ps1 -ReleaseDir release\velopack -VerifyOnly
```

清单采用 GNU `sha256sum` 兼容格式（小写 hex + 两空格 + 文件名），至少覆盖：

- `PEPETII.DanmuAI-<version>-Setup.exe`
- `PEPETII.DanmuAI-win-Setup.exe`
- `PEPETII.DanmuAI-win-Portable.zip`
- `PEPETII.DanmuAI-<version>-full.nupkg`
- 当前版本 `*-delta.nupkg`（若存在）
- `releases.win.json`

**说明：**

- manifest 仅含文件名与 SHA256，**不含任何凭据**。
- SHA256 用于验证文件在传输/存储过程中未被篡改，**不能替代** Windows Authenticode 代码签名或 SmartScreen 信任。
- 维护者上传 R2 前，`upload_r2_release.ps1` 会强制校验 manifest；发布报告可附上 `SHA256SUMS.txt` 作为验收证据。

用户或维护者校验已下载文件示例：

```powershell
Set-Location "path\to\download\folder"
$expected = (Select-String -Path .\SHA256SUMS.txt -Pattern 'PEPETII\.DanmuAI-win-Setup\.exe').Line.Split()[0]
$actual = (Get-FileHash -Algorithm SHA256 -LiteralPath .\PEPETII.DanmuAI-win-Setup.exe).Hash.ToLowerInvariant()
$expected -eq $actual
```

## CI 流程

`.github/workflows/ci.yml` 包含 `pack-windows` job：

1. 检出代码
2. 安装 Python 3.12 + .NET SDK 8.0.x
3. 安装 `vpk`：`dotnet tool install -g vpk`
4. 安装 Python 依赖
5. 运行 `build_exe.ps1`
6. 运行 `velopack_pack.ps1`
7. 验证产物：Setup.exe、full.nupkg、releases.win.json 必须存在

## 故障排查

### PyInstaller 构建失败

- 检查 `build\DanmuAI\warn-DanmuAI.txt` 中的警告
- 确认 `DanmuAI.spec` 的 `hiddenimports` 已包含所有运行时导入的模块
- 确认 `resources/icon.ico` 存在

### vpk 未找到

```powershell
dotnet tool install -g vpk
# 或手动添加到 PATH
$env:Path = "$env:USERPROFILE\.dotnet\tools;" + $env:Path
```

### 文件被锁定

若 `release\velopack\` 中的文件被杀毒软件、资源管理器或其他进程锁定：

1. 关闭所有 DanmuAI 实例
2. 关闭资源管理器窗口中的 `release\velopack\`
3. 等待几秒后重试

### 增量包未生成

- 确认本地 `release\velopack\` 中保留有旧版 `*-full.nupkg`
- 检查 `releases.win.json` 中是否包含 `Delta` 类型条目

## 相关文档

- [CANARY_RELEASE_CHANNEL.md](CANARY_RELEASE_CHANNEL.md) — canary 预发布通道（内部验证后再提升 stable）
- [IDE_WINDOWS_BUILD_PLAYBOOK.md](IDE_WINDOWS_BUILD_PLAYBOOK.md) — IDE / Codex 本地构建手册
- [RELEASE_ONLINE_VERIFY_AND_ROLLBACK.md](RELEASE_ONLINE_VERIFY_AND_ROLLBACK.md) — 发布后 R2 只读验证与回滚模板（stable）
- [.agents/skills/danmu-windows-release-upload/references/release-flow.md](../../.agents/skills/danmu-windows-release-upload/references/release-flow.md) — 发布链与用户可见更新行为
- [CHANGELOG.md](CHANGELOG.md)
- [scripts/README.md](../../scripts/README.md)
