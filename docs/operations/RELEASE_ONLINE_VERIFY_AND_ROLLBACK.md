# R2 线上验证与回滚 Runbook

> 用途：发布人员在 `upload_r2_release.ps1` 执行前后，区分「本地产物就绪」与「线上已切换」，并在错误发布时按步骤回退 alias / feed。  
> **本文档不含任何 R2 凭证**；环境变量名与 [PACKAGING_WINDOWS.md](PACKAGING_WINDOWS.md) 一致，值仅从本机 secret / CI 注入。

## 边界

- **主更新源**：Cloudflare R2（`https://updates.qiaoqiao.buzz/...`）
- **GitHub Releases**：仅镜像 / 备用下载，**不是**应用内 Velopack 更新源；验证与回滚以 R2 为准
- **主链**（不变）：`PyInstaller onedir -> Velopack -> R2 -> GitHub mirror`
- **对外入口**：`DanmuAI-Setup.exe`（主安装器）、`PEPETII.DanmuAI-win-Portable.zip`（便携版）
- 本 Runbook **不删除**历史版本化对象；不替代 `upload_r2_release.ps1` 自动上传逻辑

## 四种状态（必须分开判定）

| 状态 | 含义 | 如何判定 |
|------|------|----------|
| **本地产物已生成** | `release/velopack/` 含目标版本完整资产 | 本地文件清单（见 [PACKAGING_WINDOWS.md](PACKAGING_WINDOWS.md)） |
| **R2 feed 已切换** | 线上 `releases.win.json` 的 latest `Full` = 目标版本 | HTTP 拉 feed 或 R2 `head-object` |
| **Setup latest alias 已切换** | `downloads/DanmuAI-Setup.exe` 与目标版本化 Setup 内容一致 | `head-object` 比对 `ContentLength`（推荐）或 HTTP `Content-Length` |
| **Portable latest alias 已切换** | `downloads/PEPETII.DanmuAI-win-Portable.zip` 与目标版本化 zip 一致 | 同上 |

```text
本地产物就绪  ≠  feed 已切换  ≠  Setup alias 已切换  ≠  Portable alias 已切换
```

## R2 对象键（与 upload_r2_release.ps1 对齐）

将 `<version>` 替换为语义版本号（如 `0.3.8`）：

| 类型 | 对象 key |
|------|----------|
| 更新 feed | `releases/win/stable/releases.win.json` |
| 全量包 | `releases/win/stable/PEPETII.DanmuAI-<version>-full.nupkg` |
| 增量包（若有） | `releases/win/stable/PEPETII.DanmuAI-<version>-delta.nupkg` |
| 版本化 Setup | `downloads/PEPETII.DanmuAI-<version>-Setup.exe` |
| 版本化 Portable | `downloads/PEPETII.DanmuAI-<version>-win-Portable.zip` |
| Setup latest alias | `downloads/DanmuAI-Setup.exe` |
| Portable latest alias | `downloads/PEPETII.DanmuAI-win-Portable.zip` |

公开 URL（自定义域）：

- Feed：`https://updates.qiaoqiao.buzz/releases/win/stable`
- Setup alias：`https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe`
- Portable alias：`https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip`

## 上传前：回滚基线记录（只读准备）

在运行 `upload_r2_release.ps1` **之前**，由发布负责人记录：

1. **当前线上 latest Full 版本** → `$PrevVersion`（见下方「只读验证」Feed 小节）
2. **上一版对象 key 列表**（Setup / Portable / full.nupkg / feed）
3. **feed 备份**：将线上或本地上一版 `releases.win.json` 保存到安全位置，例如：
   - 上传前从 R2 下载：`aws s3 cp s3://$env:R2_BUCKET/releases/win/stable/releases.win.json .\rollback-backup\releases.win.json --endpoint-url "https://$($env:R2_ACCOUNT_ID).r2.cloudflarestorage.com"`
   - 或保留本地 `release/velopack/` 中**上一版**构建产出的 `releases.win.json` 副本

> **无 feed 备份则无法安全回滚 feed**；此时只能 forward-fix（重新上传正确版本），不得手工编辑线上 JSON 猜测内容。

填写模板（示例）：

```text
发布日期：
目标版本 TargetVersion：
上一版 PrevVersion：
Prev Setup key：downloads/PEPETII.DanmuAI-<PrevVersion>-Setup.exe
Prev Portable key：downloads/PEPETII.DanmuAI-<PrevVersion>-win-Portable.zip
feed 备份路径：
负责人签字：
```

## 发布后：只读验证

以下命令**不修改**线上状态。需要 R2 凭证时，仅在本机已配置环境变量后执行。

### 环境准备（只读）

```powershell
$Endpoint = "https://$($env:R2_ACCOUNT_ID).r2.cloudflarestorage.com"
$Bucket = $env:R2_BUCKET
$TargetVersion = "0.3.8"   # 替换为本次发布版本
```

### 1. Feed 可访问且 latest Full = 目标版本

```powershell
$FeedUrl = "https://updates.qiaoqiao.buzz/releases/win/stable"
$feed = Invoke-RestMethod -Uri $FeedUrl
$latestFull = ($feed.Assets | Where-Object { $_.Type -eq "Full" } |
    ForEach-Object { [version]$_.Version } |
    Sort-Object -Descending | Select-Object -First 1).ToString()
if ($latestFull -ne $TargetVersion) {
    throw "Feed latest Full is $latestFull, expected $TargetVersion"
}
Write-Host "OK: feed latest Full = $TargetVersion"
```

### 2. Setup alias 可访问

```powershell
$SetupAliasUrl = "https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe"
$r = Invoke-WebRequest -Uri $SetupAliasUrl -Method Head -UseBasicParsing
Write-Host "Setup alias HTTP status: $($r.StatusCode), Content-Length: $($r.Headers['Content-Length'])"
```

### 3. Portable alias 可访问

```powershell
$PortableAliasUrl = "https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip"
$r = Invoke-WebRequest -Uri $PortableAliasUrl -Method Head -UseBasicParsing
Write-Host "Portable alias HTTP status: $($r.StatusCode), Content-Length: $($r.Headers['Content-Length'])"
```

### 4. 版本化源对象存在（head-object）

```powershell
$keys = @(
    "downloads/PEPETII.DanmuAI-$TargetVersion-Setup.exe",
    "downloads/PEPETII.DanmuAI-$TargetVersion-win-Portable.zip",
    "releases/win/stable/PEPETII.DanmuAI-$TargetVersion-full.nupkg",
    "releases/win/stable/releases.win.json"
)
foreach ($key in $keys) {
    aws s3api head-object --bucket $Bucket --key $key --endpoint-url $Endpoint | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Missing object: $key" }
    Write-Host "OK: $key"
}
# 若有 delta：
# aws s3api head-object --bucket $Bucket --key "releases/win/stable/PEPETII.DanmuAI-$TargetVersion-delta.nupkg" --endpoint-url $Endpoint
```

### 5. Alias 与版本化对象大小一致（推荐）

```powershell
function Get-R2ContentLength([string]$Key) {
    $json = aws s3api head-object --bucket $Bucket --key $Key --endpoint-url $Endpoint | ConvertFrom-Json
    return [long]$json.ContentLength
}
$setupVersioned = "downloads/PEPETII.DanmuAI-$TargetVersion-Setup.exe"
$setupAlias = "downloads/DanmuAI-Setup.exe"
$lenV = Get-R2ContentLength $setupVersioned
$lenA = Get-R2ContentLength $setupAlias
if ($lenV -ne $lenA) { throw "Setup alias size mismatch: versioned=$lenV alias=$lenA" }
Write-Host "OK: Setup alias matches versioned object size"

$portableVersioned = "downloads/PEPETII.DanmuAI-$TargetVersion-win-Portable.zip"
$portableAlias = "downloads/PEPETII.DanmuAI-win-Portable.zip"
$lenV = Get-R2ContentLength $portableVersioned
$lenA = Get-R2ContentLength $portableAlias
if ($lenV -ne $lenA) { throw "Portable alias size mismatch: versioned=$lenV alias=$lenA" }
Write-Host "OK: Portable alias matches versioned object size"
```

> **CDN 缓存**：公开 URL 的 `Content-Length` 可能与 R2 `head-object` 短暂不一致。以 R2 `head-object` 为准；若 HTTP 与 R2 冲突，在负责人确认后重跑 `upload_r2_release.ps1` 同步 alias（见 `release-flow.md` §2.6）。

## 回滚步骤模板

> **危险边界**：下列凡涉及 `aws s3 cp`（含 server-side copy）、覆盖 feed、或删除对象的操作，**执行前必须由发布负责人书面确认**。本 Runbook 不提供自动回滚脚本。

建议顺序：**先回退 alias（影响下载页）→ 再回退 feed（影响应用内更新）**。

### 步骤 0：确认回滚目标

- 使用上传前记录的 `$PrevVersion` 与对象 key
- 明确回滚原因与影响范围（已下载用户、进行中的应用内更新）

### 步骤 1：head-object 验证上一版源对象存在

```powershell
$PrevVersion = "0.3.7"   # 替换为记录的上一版
$prevKeys = @(
    "downloads/PEPETII.DanmuAI-$PrevVersion-Setup.exe",
    "downloads/PEPETII.DanmuAI-$PrevVersion-win-Portable.zip",
    "releases/win/stable/PEPETII.DanmuAI-$PrevVersion-full.nupkg"
)
foreach ($key in $prevKeys) {
    aws s3api head-object --bucket $Bucket --key $key --endpoint-url $Endpoint | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Rollback aborted: missing source object $key"
    }
}
Write-Host "OK: all PrevVersion source objects exist"
```

**若任一头对象失败，停止回滚**；不得向 alias 复制不存在的源。

### 步骤 2：回退 Setup latest alias（需负责人确认）

```powershell
# ⚠️ 危险 — 执行前必须由负责人确认
aws s3 cp "s3://$Bucket/downloads/PEPETII.DanmuAI-$PrevVersion-Setup.exe" `
    "s3://$Bucket/downloads/DanmuAI-Setup.exe" `
    --endpoint-url $Endpoint `
    --cache-control "no-cache" `
    --metadata-directive REPLACE `
    --only-show-errors
if ($LASTEXITCODE -ne 0) { throw "Setup alias rollback failed" }
```

### 步骤 3：回退 Portable latest alias（需负责人确认）

```powershell
# ⚠️ 危险 — 执行前必须由负责人确认
aws s3 cp "s3://$Bucket/downloads/PEPETII.DanmuAI-$PrevVersion-win-Portable.zip" `
    "s3://$Bucket/downloads/PEPETII.DanmuAI-win-Portable.zip" `
    --endpoint-url $Endpoint `
    --cache-control "no-cache" `
    --metadata-directive REPLACE `
    --only-show-errors
if ($LASTEXITCODE -ne 0) { throw "Portable alias rollback failed" }
```

### 步骤 4：回退 feed（需负责人确认 + 必须有备份）

```powershell
# ⚠️ 危险 — 执行前必须由负责人确认；$FeedBackupPath 必须为上传前保存的上一版 releases.win.json
$FeedBackupPath = ".\rollback-backup\releases.win.json"
if (-not (Test-Path -LiteralPath $FeedBackupPath)) {
    throw "No feed backup — cannot safely rollback feed. Use forward-fix: re-upload correct version."
}
aws s3 cp $FeedBackupPath "s3://$Bucket/releases/win/stable/releases.win.json" `
    --endpoint-url $Endpoint `
    --cache-control "public, max-age=60" `
    --only-show-errors
if ($LASTEXITCODE -ne 0) { throw "Feed rollback failed" }
```

**无备份时的 forward-fix**：修复本地产物后重新运行 `upload_r2_release.ps1 -Version <correct>`，再执行本文「只读验证」。

### 步骤 5：回滚后只读验证

重复上文「发布后：只读验证」，将 `$TargetVersion` 设为 `$PrevVersion`，确认 feed 与 alias 均已回到上一版。

### 步骤 6：GitHub Releases（镜像，可选）

GitHub 为镜像，**不是**主更新源。R2 回滚完成后，负责人可择机手动同步 GitHub Release 资产；客户端 Velopack 更新不依赖 GitHub。

## 相关文档

- [PACKAGING_WINDOWS.md](PACKAGING_WINDOWS.md) — 打包、上传、代码签名
- [IDE_WINDOWS_BUILD_PLAYBOOK.md](IDE_WINDOWS_BUILD_PLAYBOOK.md) — 本地构建（默认不上传）
- [.agents/skills/danmu-windows-release-upload/references/release-flow.md](../../.agents/skills/danmu-windows-release-upload/references/release-flow.md) — 完整发布链与用户可见行为
- `reports/W-REL-CLEANUP-001-completion-report.md` — Setup + Portable 收敛事实
