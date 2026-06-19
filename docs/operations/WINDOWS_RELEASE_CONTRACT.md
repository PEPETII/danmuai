# Windows 发布契约（R2 + Velopack 单栈）

> **决策基线**：后续所有发布脚本、R2 上传、应用内更新实现 **必须**遵守本文。禁止自行改回 COS、Inno Setup 双栈、zip 主分发、MSI 对外入口或 GitHub Releases 主真源。

**packId**：`PEPETII.DanmuAI`  
**主域名**：`qiaoqiao.buzz`（自定义域绑定 Cloudflare R2）  
**更新 feed 基址**：`https://updates.qiaoqiao.buzz/releases/win/stable`

---

## 1. 主发布架构

```text
scripts/build_exe.ps1          PyInstaller onedir → dist/DanmuAI/
        ↓
vpk pack (Velopack)            Setup.exe、*.nupkg、releases.win.json、Portable.zip
        ↓
scripts/upload_r2_release.ps1  主真源：Cloudflare R2 + 自定义域名
        ↓
scripts/upload_github_release.ps1   镜像：GitHub Releases（非主真源）
        ↓
客户端 UpdateManager           feed URL = https://updates.qiaoqiao.buzz/releases/win/stable
```

| 层级 | 职责 |
|------|------|
| PyInstaller onedir | 生成 `dist/DanmuAI/DanmuAI.exe` + `_internal/`；**保留**，不改为 onefile |
| Velopack (`vpk`) | 安装器（Setup.exe）、全量/增量 nupkg、更新清单、Portable 包 |
| Cloudflare R2 | **主下载与更新源**；仅通过 **自定义域名** 对外 |
| GitHub Releases | 镜像/备用；上传相同 Velopack 产物集合 |

**禁止**：

- 腾讯云 COS 作为主源
- Inno Setup 作为正式主链
- MSI 作为对外下载入口（W-REL-CLEANUP-001）
- `DanmuAI-windows-x64.zip` 等旧 zip 主分发
- `*.r2.dev` 作为面向用户的正式下载入口
- 仅 zip 作为普通用户唯一分发形态（Portable.zip 为便携入口，Setup.exe 为主入口）

---

## 2. 资产分类（W-REL-CLEANUP-001）

对外只保留两个用户可见入口，**不等于** R2 上只允许两个对象。发布、别名分发、自动更新、版本追溯所需的内部资产必须保留。

### 2.1 对外发布物（用户可见，仅 2 个）

| 文件 | 公开 URL | 角色 |
|------|----------|------|
| `DanmuAI-Setup.exe` | `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe` | **主入口**；官网主按钮；支持 `--installto` |
| `PEPETII.DanmuAI-win-Portable.zip` | `https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip` | **便携入口**；解压后直接运行 |

### 2.2 内部必需资产（保留，不对用户主推）

| 资产 | 路径 / 文件名 | 保留原因 |
|------|----------------|----------|
| 更新清单 | `releases/win/stable/releases.win.json` | Velopack `UpdateManager` 更新检查 |
| 全量更新包 | `releases/win/stable/PEPETII.DanmuAI-<version>-full.nupkg` | 客户端全量更新 |
| 增量更新包 | `releases/win/stable/PEPETII.DanmuAI-<version>-delta.nupkg` | 客户端增量更新（有则保留） |
| 版本化 Setup | `downloads/PEPETII.DanmuAI-<version>-Setup.exe` | latest 别名 copy 源；版本追溯 |
| Setup latest 别名 | `downloads/DanmuAI-Setup.exe` | 对外主入口；服务端 copy 自版本化 Setup |
| 版本化 Portable | `downloads/PEPETII.DanmuAI-<version>-win-Portable.zip` | Portable latest 别名 copy 源 |
| Portable latest 别名 | `downloads/PEPETII.DanmuAI-win-Portable.zip` | 对外便携入口 |
| 本地 Velopack 原始 Setup | `release/velopack/PEPETII.DanmuAI-win-Setup.exe` | 打包中间产物；上传前本地校验 |
| GitHub 镜像附件 | Setup、Portable、nupkg、feed | 镜像用途，非主 feed |

### 2.3 历史废弃资产（停止生成 / 上传 / 对外引用）

| 资产 | 说明 |
|------|------|
| `DanmuAI-windows-x64.zip` / `.sha256` | 旧 PyInstaller zip 主分发，已废弃 |
| `*.msi`、`DanmuAI-Installer.msi`、`PEPETII.DanmuAI-*-Installer.msi` | MSI 对外入口已移除（W-REL-CLEANUP-001） |
| 桶根路径旧兼容对象 | 如根目录 `PEPETII.DanmuAI-win-Setup.exe`、`releases.win.json`（契约主路径为 `downloads/` 与 `releases/win/stable/`） |

本地历史废弃产物归档至 `release/_legacy_local/`（Git 忽略，禁止提交）。

---

## 3. 资产命名

| 资产 | 路径 / 文件名 | 说明 |
|------|----------------|------|
| 版本化 Setup（真资产） | `downloads/PEPETII.DanmuAI-<version>-Setup.exe` | `<version>` = `app.version.__version__` |
| Setup.exe Latest 别名 | `downloads/DanmuAI-Setup.exe` | 始终指向当前 stable 最新版 Setup |
| 更新清单 | `releases/win/stable/releases.win.json` | Velopack feed |
| 更新包 | `releases/win/stable/PEPETII.DanmuAI-<version>-full.nupkg` | 全量包；增量 `*-delta.nupkg` 同目录 |
| Portable（版本化） | `downloads/PEPETII.DanmuAI-<version>-win-Portable.zip` | 便携版真资产 |
| Portable Latest 别名 | `downloads/PEPETII.DanmuAI-win-Portable.zip` | 便携版入口 |

Velopack 本地打包默认输出：`PEPETII.DanmuAI-win-Setup.exe`（脚本复制为版本化 Setup 后上传）。

---

## 4. R2 目录结构与 URL

**Bucket 内对象键**（与公开 URL 路径一致）：

```text
/releases/win/stable/releases.win.json
/releases/win/stable/PEPETII.DanmuAI-<version>-full.nupkg
/releases/win/stable/PEPETII.DanmuAI-<version>-delta.nupkg   # 若有
/downloads/PEPETII.DanmuAI-<version>-Setup.exe
/downloads/DanmuAI-Setup.exe                                  # Setup latest 别名（覆盖写入）
/downloads/PEPETII.DanmuAI-<version>-win-Portable.zip
/downloads/PEPETII.DanmuAI-win-Portable.zip                   # Portable latest 别名（覆盖写入）
```

**公开 URL 示例**（`updates.qiaoqiao.buzz` 为 R2 自定义域，以 Cloudflare 控制台实际绑定为准）：

| 用途 | URL |
|------|-----|
| 用户下载（主入口 Setup） | `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe` |
| 用户下载（便携版） | `https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip` |
| 用户下载（指定版本 Setup） | `https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-0.3.0-Setup.exe` |
| 客户端更新 feed | `https://updates.qiaoqiao.buzz/releases/win/stable` |

### 缓存策略

| 对象 | Cache-Control 建议 | 原因 |
|------|------------------|------|
| `releases.win.json` | `public, max-age=60` 或 `no-cache` | 客户端需尽快发现新版本 |
| `*.nupkg` | `public, max-age=3600` | 体积大；版本化文件名可长期缓存 |
| `downloads/PEPETII.DanmuAI-*-Setup.exe` | `public, max-age=86400` | 版本化，不可变 |
| `downloads/PEPETII.DanmuAI-*-win-Portable.zip` | `public, max-age=86400` | 版本化，不可变 |
| `downloads/DanmuAI-Setup.exe` | `no-cache` 或 `max-age=300` | Setup latest 别名会覆盖 |
| `downloads/PEPETII.DanmuAI-win-Portable.zip` | `no-cache` 或 `max-age=300` | Portable latest 别名会覆盖 |

### Latest 别名策略

发布新版本时：

1. 上传版本化 Setup 至 `downloads/PEPETII.DanmuAI-<version>-Setup.exe`
2. **同一对象内容**复制/覆盖至 `downloads/DanmuAI-Setup.exe`
3. 上传版本化 Portable 并复制/覆盖至 `downloads/PEPETII.DanmuAI-win-Portable.zip`
4. 上传 nupkg 与更新后的 `releases.win.json`

---

## 下载入口角色

| 入口 | 格式 | 角色 | 说明 |
|------|------|------|------|
| Setup.exe | `.exe` | **主入口** | 官网主按钮；支持 `--installto` 自定义路径 |
| Portable.zip | `.zip` | **便携入口** | 解压后直接运行，无需安装 |

- 应用内自动更新仍走 Velopack `Update.exe` + `releases.win.json`
- Setup 与 Portable 安装/解压后均通过同一 Velopack 更新通道接收后续版本
- 未签名情况下 Setup.exe 可能触发 SmartScreen

---

## 5. GitHub 镜像角色

- `upload_github_release.ps1` 上传：**Setup.exe**、**Portable.zip**、**releases.win.json** / **full.nupkg** / **delta.nupkg**
- Release 说明可链接 R2 主下载：`https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe`；便携版：`https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip`
- **不得**在文档或产品逻辑中将 GitHub 作为更新检查的主 feed
- **版本提醒与主下载 URL**：Supabase `public.app_updates`（`latest_version`、`release_url`、`message`）为权威源；桌面后端经 `GET /api/update/channels` 读取（模块 `app/supabase_app_updates.py`），前端不再直连 Supabase 拉版本
- `app/release_channels.py` 仅承载**镜像渠道目录**（GitHub / 夸克 / 百度 / R2 默认别名）；`release_url` 以 Supabase 行为准
- Frozen 就地升级仍以 Velopack `UpdateManager` + R2 feed 为准（Bearer `POST /api/update/check`）；`/api/update/channels` **不**触发 feed 检查（W-SEC-UPDATE-001）

---

## 6. 无代码签名边界

- **当前无代码签名预算**；主链实施 **不阻塞**于证书采购
- **未签名时无法承诺彻底消除 Windows SmartScreen / Defender 警告**
- 用户可能需点击「更多信息 → 仍要运行」；详见 [WINDOWS_CODE_SIGNING.md](WINDOWS_CODE_SIGNING.md)
- 未来签名接入点：vpk `--signParams`、发布前验签、RELEASE_CHECKLIST 补充项（W-REL-R2V-SIGN-001）

---

## 凭证与客户端边界

| 角色 | R2 凭证 |
|------|---------|
| 发布脚本（维护者本机 / CI secret） | `R2_ACCOUNT_ID`、`R2_ACCESS_KEY_ID`、`R2_SECRET_ACCESS_KEY`、`R2_BUCKET` — **仅环境变量，禁止入库** |
| DanmuAI 客户端 | **绝不**持有 R2 API 凭证；仅 HTTPS 读取公开 URL |

---

## 用户数据与安装目录

| 路径 | 内容 |
|------|------|
| `%LocalAppData%\PEPETII.DanmuAI\` | Velopack 安装目录（程序文件；更新时替换 `current/`） |
| `%APPDATA%\DanmuAI\` | 用户数据：`config.db`、`.key`、`startup.log` — **与安装目录分离**，更新/卸载默认保留 |

---

## 相关文档

- [WINDOWS_RELEASE_BASELINE.md](WINDOWS_RELEASE_BASELINE.md) — 历史 zip 基线事实
- [PACKAGING_WINDOWS.md](PACKAGING_WINDOWS.md) — PyInstaller 构建
- [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) — 发布检查
- [WINDOWS_CODE_SIGNING.md](WINDOWS_CODE_SIGNING.md) — 签名后续项
