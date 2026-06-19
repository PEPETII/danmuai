# W-REL-MSI-002 执行提示词

> 你只执行**当前工单**，不要实现未来功能，不要顺手重构无关代码，不要自行决定新架构。

---

## 当前工单

- **工单 ID**：W-REL-MSI-002
- **标题**：R2 线上 MSI 主入口切换与公网验收
- **前置依赖**：[W-REL-MSI-001](W-REL-MSI-001-MSI主入口切换.md)（打包/上传脚本与契约已落地）

## 执行前必须阅读

1. [WINDOWS_RELEASE_CONTRACT.md](WINDOWS_RELEASE_CONTRACT.md) §2–§3（MSI/Setup/Portable 别名）
2. [PACKAGING_WINDOWS.md](PACKAGING_WINDOWS.md) — WiX 5 与 `publish_windows_release.ps1`
3. [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) — R2 上传检查项
4. [reports/W-REL-MSI-001-completion-report.md](../../reports/W-REL-MSI-001-completion-report.md)

## 目标

在 Cloudflare R2 公网完成 MSI 主下载入口上线，并同步维护 Setup.exe 备用与 Portable.zip 便携版 latest 别名。

**本工单不**修改应用代码、不修改 Velopack feed 逻辑、不向仓库提交 R2 凭证。

## 必须遵守

1. R2 为主真源；GitHub Releases 仅镜像（上传可选，非本工单阻塞项）。
2. 上传前确认 `releases.win.json` 中 Full 版本与目标 `app.version` 一致。
3. MSI 缺失时不得仅上传 Setup 并宣称 MSI 主入口已切换。
4. R2 凭证仅通过环境变量：`R2_ACCOUNT_ID`、`R2_ACCESS_KEY_ID`、`R2_SECRET_ACCESS_KEY`、`R2_BUCKET`。

## 允许修改的区域

```
reports/W-REL-MSI-002-*.md
```

## 禁止修改的区域

```
app/
web/
scripts/（除非发现契约级 bug 且需另开工单）
tests/
.env / 密钥文件
```

## 具体需求

### 1. 构建环境准备

1. 安装 WiX 5：`dotnet tool install -g wix`，验证 `wix --version`
2. 确认 `.NET SDK`、`vpk` CLI 可用（见 PACKAGING_WINDOWS.md）

### 2. 本地打包

在仓库根目录执行：

```powershell
.\scripts\publish_windows_release.ps1
```

确认 `release/velopack/` 含：

| 文件 | 说明 |
|------|------|
| `PEPETII.DanmuAI-<version>-Installer.msi` | 版本化 MSI（必需） |
| `PEPETII.DanmuAI-<version>-Setup.exe` | 版本化 Setup |
| `PEPETII.DanmuAI-<version>-full.nupkg` | 全量包 |
| `releases.win.json` | 更新 feed |
| `PEPETII.DanmuAI-win-Portable.zip` | 便携版（若 Velopack 产出） |

### 3. R2 上传

预检（可选）：

```powershell
.\scripts\upload_r2_release.ps1 -DryRun
```

正式上传：

```powershell
.\scripts\upload_r2_release.ps1
# 或显式版本：.\scripts\upload_r2_release.ps1 -Version 0.3.1
```

上传脚本应完成：

- 版本化 MSI → `downloads/PEPETII.DanmuAI-<version>-Installer.msi`
- latest alias copy → `downloads/DanmuAI-Installer.msi`
- 版本化 Setup + alias → `downloads/DanmuAI-Setup.exe`
- Portable（若存在）+ alias → `downloads/PEPETII.DanmuAI-win-Portable.zip`
- feed + nupkg → `releases/win/stable/`

### 4. 公网验收

对以下 URL 执行 GET 或 HEAD，记录状态码与 `Content-Length`：

| 用途 | URL |
|------|-----|
| MSI 主入口 | `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi` |
| Setup 备用 | `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe` |
| Portable | `https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip` |
| 更新 feed | `https://updates.qiaoqiao.buzz/releases/win/stable/releases.win.json` |
| 版本化 MSI | `https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-<version>-Installer.msi` |

验收要点：

- `DanmuAI-Installer.msi` 与版本化 MSI 的 `Content-Length` 一致（alias copy 成功）
- `releases.win.json` 中最新 Full 版本 = 本次发布版本

## 非目标

- 不修改 Supabase 线上数据（见 W-REL-MSI-003）
- 不做 MSI 真机安装验收（见 W-REL-MSI-004）
- 不执行代码签名

## 验收标准

- [ ] 构建机已安装 WiX 5，`publish_windows_release.ps1` 成功产出 MSI
- [ ] `upload_r2_release.ps1` 无错误完成（或 DryRun 输出含 MSI + 三别名）
- [ ] 公网 `DanmuAI-Installer.msi` 返回 HTTP 200 且可下载
- [ ] 公网 `DanmuAI-Setup.exe` 备用入口仍可用
- [ ] `releases.win.json` 公网可访问且版本与本次发布一致
- [ ] 完成报告 `reports/W-REL-MSI-002-online-switch-report.md` 已撰写

## 手动验证步骤

1. 浏览器或 `curl -I` 检查四个公网 URL
2. 对比 alias 与版本化 MSI 文件大小
3. 解析 `releases.win.json` 确认 Full 资产版本
4. 全局确认未将 Setup.exe 作为「主入口」对外公告（官网应已指向 MSI）

## 已知风险

1. **latest alias 本地上传失败**：可参考 W-REL-R2V-011，使用 R2 服务端 copy 覆盖 alias
2. **WiX 5 缺失**：`velopack_pack.ps1` 会 `Write-Error`，不得跳过 MSI 产出
3. **Portable 可选**：若本次构建无 Portable.zip，Portable 别名步骤可跳过，但须在报告中注明

## 完成后必须给出

1. 发布版本号
2. 各公网 URL 的 HTTP 状态与 Content-Length 表
3. MSI alias 与版本化 MSI 是否一致
4. 未完成项与阻塞原因（若有）
