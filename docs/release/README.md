# Release notes

GitHub Release 正文可从此目录复制。主下载源为 Cloudflare R2：`https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe`；便携版：`https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip`；GitHub Releases 仅作为镜像。

| 版本 | 文档 | 建议 tag | Windows 附件（镜像） |
|------|------|----------|----------------------|
| 0.3.0+ | 见 CHANGELOG | `v0.3.0` | `release/velopack/` 中的 Velopack 产物 |

## Windows x64 构建（Velopack）

在仓库根目录执行，要求 Windows + Python 3.12+ + .NET SDK + `vpk`：

```powershell
.\scripts\publish_windows_release.ps1
```

产物位于 `release/velopack/`，不入库：

| 路径 | 说明 |
|------|------|
| `PEPETII.DanmuAI-win-Setup.exe` | Velopack 安装器（本地原始输出） |
| `PEPETII.DanmuAI-<version>-Setup.exe` | 版本化 Setup（主入口） |
| `PEPETII.DanmuAI-<version>-full.nupkg` | 全量更新包 |
| `PEPETII.DanmuAI-<version>-delta.nupkg` | 增量更新包；仅在存在上一版 full 包时生成 |
| `releases.win.json` | 更新 feed |
| `PEPETII.DanmuAI-win-Portable.zip` | 便携包 |

### Delta 发布说明

- `publish_windows_release.ps1` 会保留 `release/velopack/` 中的历史 `*.nupkg`，避免每次构建前清空目录导致 Velopack 无法生成 `*-delta.nupkg`。
- 当本地没有上一版 full 包时，脚本会默认从 `https://updates.qiaoqiao.buzz/releases/win/stable` 预拉取上一版 feed 资产；需要纯本地打包时可传 `-SkipDeltaBootstrap`。
- R2 与 GitHub 上传脚本都会上传 `releases.win.json`、`*-full.nupkg`、`*-delta.nupkg`、Setup、Portable（若存在）；客户端继续沿用 Velopack `UpdateManager`，不引入自研补丁逻辑。

### 发布到 R2（主源）

```powershell
# 环境变量：R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
.\scripts\upload_r2_release.ps1
```

### 镜像到 GitHub

```powershell
.\scripts\upload_github_release.ps1 -Tag v0.3.0 -NotesFile docs\release\2026-05-29.md
```

发布前检查见 [RELEASE_CHECKLIST.md](../operations/RELEASE_CHECKLIST.md)。

## 用户可见更新路径（应用内）

安装版启动后，Web 控制台经 **`GET /api/update/channels`** 获取更新元数据（后端读取 Supabase `app_updates`），并弹出四渠道对话框（见 [PACKAGING_WINDOWS.md](../operations/PACKAGING_WINDOWS.md)）：

| 渠道 | 角色 |
|------|------|
| **应用内更新（Velopack）** | 主路径；Bearer `POST /api/update/check` 访问 R2 feed `https://updates.qiaoqiao.buzz/releases/win/stable` |
| **主下载（`release_url`）** | 来自 Supabase `app_updates`（通常 `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe`） |
| **R2 便携版** | `https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip`（镜像目录常量） |
| **GitHub Releases** | 镜像备用：`https://github.com/PEPETII/danmuai/releases` |
| **夸克 / 百度网盘** | 国内网络回退；链接与口令在 `app/release_channels.py`（镜像目录） |

**发版运维**：同步 `app/version.py` + Supabase `app_updates` 启用行；网盘/GitHub 镜像链接变更时改 `app/release_channels.py` 并发新客户端。GitHub Releases **不是** Velopack 更新 feed。
