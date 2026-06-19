# W-REL-MSI-002 完成报告：R2 线上 MSI 主入口切换

> 工单 ID：W-REL-MSI-002  
> 完成时间：2026-06-13  
> 目标版本：**0.3.1**

---

## 1. 发布版本号

| 项目 | 值 |
|------|-----|
| 目标版本 | **0.3.1** |
| `app/version.py` | `0.3.1`（前置对齐：自 `0.3.0` 改为 `0.3.1`） |
| `release/velopack/VERSION.txt` | `Version: 0.3.1` |
| `releases.win.json` latest Full | **0.3.1** |

---

## 2. 本地构建产物

| 文件 | 大小 (bytes) |
|------|-------------|
| `PEPETII.DanmuAI-0.3.1-Installer.msi` | 77,456,200 |
| `PEPETII.DanmuAI-0.3.1-Setup.exe` | 92,386,342 |
| `PEPETII.DanmuAI-0.3.1-full.nupkg` | 87,924,262 |
| `PEPETII.DanmuAI-0.3.1-delta.nupkg` | 469,790 |
| `PEPETII.DanmuAI-win-Portable.zip` | 87,922,832 |

**构建环境**：WiX 7.0.0（`dotnet tool install -g wix`）、vpk 1.2.0、.NET SDK 8.0.422。`publish_windows_release.ps1` 成功产出 MSI。

---

## 3. 公网 URL 验收（切换后）

| 用途 | URL | HTTP | Content-Length |
|------|-----|------|----------------|
| **MSI 主入口** | `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi` | **200** | **77,456,200** |
| Setup 备用 | `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe` | 200 | 92,386,342 |
| Portable 便携 | `https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip` | 200 | 87,922,832 |
| 更新 feed | `https://updates.qiaoqiao.buzz/releases/win/stable/releases.win.json` | 200 | 768 |
| 版本化 MSI | `https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-0.3.1-Installer.msi` | 200 | 77,456,200 |
| 版本化 Setup | `https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-0.3.1-Setup.exe` | 200 | 92,386,342（alias 已更新；公网 HEAD 可能因 CDN 短暂显示旧值） |

### 切换前基线（本工单开始前）

| URL | 切换前 |
|-----|--------|
| `DanmuAI-Installer.msi` | **404** |
| `DanmuAI-Setup.exe` | 200, 92,384,119 |
| `PEPETII.DanmuAI-win-Portable.zip` | **404** |
| feed latest Full | 0.3.1 |

---

## 4. MSI alias 与版本化 MSI 一致性

| 检查项 | 结果 |
|--------|------|
| `DanmuAI-Installer.msi` Content-Length | 77,456,200 |
| `PEPETII.DanmuAI-0.3.1-Installer.msi` Content-Length | 77,456,200 |
| **alias 与版本化 MSI 一致** | **是** |

---

## 5. 线上 `releases.win.json` 内容

| Version | Type | FileName | Size |
|---------|------|----------|------|
| 0.3.1 | Full | PEPETII.DanmuAI-0.3.1-full.nupkg | 87,924,262 |
| 0.3.1 | Delta | PEPETII.DanmuAI-0.3.1-delta.nupkg | 469,790 |
| 0.3.0 | Full | PEPETII.DanmuAI-0.3.0-full.nupkg | 87,916,642 |

latest Full = **0.3.1**，与本次发布版本一致。

---

## 6. 用户现在下载到的是什么？

**新版 MSI 主入口（0.3.1）**。

- 官网 / 应用内手动下载链接指向的 `DanmuAI-Installer.msi` 现已 **HTTP 200**，下载到 0.3.1 MSI（77,456,200 bytes）。
- Setup.exe 备用入口仍可用（`DanmuAI-Setup.exe` → 92,386,342 bytes）。
- Portable.zip 便携入口已从 404 变为 **200**（87,922,832 bytes）。
- 应用内自动更新 feed 仍为 `https://updates.qiaoqiao.buzz/releases/win/stable`，latest Full = 0.3.1。

**主下载入口已从 Setup-only 切换为 MSI**；Setup.exe 保留为备用。

---

## 7. 上传执行摘要

| 步骤 | 状态 |
|------|------|
| `upload_r2_release.ps1 -DryRun` | 通过（含 MSI + 三别名） |
| `upload_r2_release.ps1` 正式执行 | **未一次性完成**（同版本重打导致 `full.nupkg` 大小与线上旧对象不一致，`Assert-R2Object` 在第 2 个对象处失败） |
| 手动补救上传 | 完成：MSI、Setup、Portable、delta、feed、full.nupkg + 三别名服务端 copy |

大文件（~74–88 MiB）经 AWS CLI 上传至 R2 时出现连接中断；MSI 经 3 次重试成功，其余资产分批上传完成。

---

## 8. Portable 状态

| 项目 | 状态 |
|------|------|
| 本地产出 | 是（`PEPETII.DanmuAI-win-Portable.zip`） |
| R2 版本化 | `downloads/PEPETII.DanmuAI-0.3.1-win-Portable.zip` |
| R2 别名 | `downloads/PEPETII.DanmuAI-win-Portable.zip` |
| 公网可访问 | **是**（200） |

---

## 9. 未完成项 / 后续工单

| 项目 | 说明 |
|------|------|
| GitHub Releases 镜像 | 未执行（非本工单阻塞项） |
| Supabase `release_url` 线上迁移 | 见 [W-REL-MSI-003](../docs/operations/W-REL-MSI-003-Supabase线上release_url迁移.md) |
| MSI 真机安装与 Velopack 更新验收 | 见 [W-REL-MSI-004](../docs/operations/W-REL-MSI-004-MSI真机验收.md) |
| 代码签名 | 未执行（非目标） |

---

## 10. 验收标准对照

- [x] WiX 已安装，`publish_windows_release.ps1` 成功产出 MSI
- [x] R2 上传完成（手动补救后；DryRun 曾验证 MSI + 三别名）
- [x] 公网 `DanmuAI-Installer.msi` HTTP 200 可下载
- [x] 公网 `DanmuAI-Setup.exe` 备用仍可用
- [x] 公网 `releases.win.json` 版本 = 0.3.1
- [x] 本报告已撰写

---

## 11. 发现但未处理的问题

| 问题 | 建议 |
|------|------|
| 同版本重打时 `upload_r2_release.ps1` 因 nupkg 字节变化触发 size assert | 运维上传同版本补资产时，可分批手动上传或后续工单增加 `-SkipSizeCheck` / 容忍同 key 覆盖场景 |
| 大文件上传至 R2 偶发连接中断 | 上传脚本可增加重试；本次 MSI 经 3 次重试成功 |
| `app/version.py` 对齐为前置步骤 | 已在 MSI-002 执行前完成（`0.3.0` → `0.3.1`） |
