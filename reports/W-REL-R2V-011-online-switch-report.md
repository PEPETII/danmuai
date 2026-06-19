# W-REL-R2V-011 完成报告：线上下载源切换与 latest alias 核对

> 工单 ID：W-REL-R2V-011  
> 完成时间：2026-06-13  
> 目标版本：**0.3.1**

---

## 1. 本地目标版本

| 项目 | 值 |
|------|-----|
| 目标版本 | **0.3.1** |
| `release/velopack/VERSION.txt` | `Version: 0.3.1` |
| `app/version.py` | `0.3.0`（本工单未改；产物与源码版本 intentionally 分离） |
| `releases.win.json` | `0.3.1 Full`、`0.3.1 Delta`、`0.3.0 Full` |
| `PEPETII.DanmuAI-0.3.1-Setup.exe` | 92,384,119 bytes |
| `PEPETII.DanmuAI-0.3.1-full.nupkg` | 87,922,039 bytes；SHA256 `9D86501CEAE61DA7BC05BC1BF721B3C71949357FF8FCB3EAB6555BE90F4C1882` |
| `PEPETII.DanmuAI-0.3.1-delta.nupkg` | 448,721 bytes；SHA256 `590195027D7FE04FC6EDB64B8BB3354C3974596A7860427420AC664942A5F632` |

**本地完成**：是。`release/velopack/` 已与 0.3.1 目标一致。

---

## 2. 线上 `releases.win.json` 实际内容

URL：`https://updates.qiaoqiao.buzz/releases/win/stable/releases.win.json`

| Version | Type | FileName | Size |
|---------|------|----------|------|
| 0.3.1 | Full | PEPETII.DanmuAI-0.3.1-full.nupkg | 87922039 |
| 0.3.1 | Delta | PEPETII.DanmuAI-0.3.1-delta.nupkg | 448721 |
| 0.3.0 | Full | PEPETII.DanmuAI-0.3.0-full.nupkg | 87916642 |

**线上 feed 切换**：是。已从仅含 `0.3.0 Full` 切换到含 `0.3.1 Full + Delta`。

---

## 3. 线上 `DanmuAI-Setup.exe` latest alias 核对

| 检查项 | 切换前 | 切换后 |
|--------|--------|--------|
| URL | `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe` | 同上 |
| HTTP | 200 | 200 |
| Content-Length | 92,378,722（0.3.0） | **92,384,119（0.3.1）** |
| Last-Modified | Thu, 11 Jun 2026 13:43:24 GMT | **Sat, 13 Jun 2026 07:14:03 GMT** |
| ETag | `60d59ea3cb7a3110f04ed50bd6df1fe7-12` | `7a93afa454cc0b4c65a43d9129d5d2a8-12` |

版本化安装包：`https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-0.3.1-Setup.exe` → HTTP 200，92,384,119 bytes。

**线上 latest alias 切换**：是。

---

## 4. 用户现在下载到的是旧版还是新版？

**新版（0.3.1）**。

用户通过 `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe` 现在下载到的是 **0.3.1 Setup**（92,384,119 bytes），不再是 0.3.0（92,378,722 bytes）。

应用内更新 feed（`https://updates.qiaoqiao.buzz/releases/win/stable`）也已指向 0.3.1 Full + Delta。

---

## 5. 「本地完成」与「线上切换」状态

| 状态 | 是否完成 |
|------|----------|
| 本地 `release/velopack` 已生成 0.3.1 产物 | 是（工单开始前已完成） |
| 线上 `releases.win.json` 已切换 | 是 |
| 线上 `DanmuAI-Setup.exe` latest alias 已切换 | 是 |
| GitHub Releases 镜像 `v0.3.1` | **否**（本机 `gh auth login` 未配置，未执行） |

---

## 6. 执行摘要

### 脚本改动

- `scripts/upload_r2_release.ps1`：新增 `-Version`、从 `VERSION.txt` 解析版本、feed 版本断言、上传后 `head-object` 大小校验；latest alias 改为 **R2 服务端复制**（自 `downloads/PEPETII.DanmuAI-<version>-Setup.exe`），避免大文件二次本地上传失败。
- `scripts/upload_github_release.ps1`：新增 `-Version` 与 `VERSION.txt` 回退解析。

### 上传过程说明

1. 首次 `aws s3 cp` 批量上传时，大文件 multipart 在约 50MB 处连接中断，仅 `releases.win.json` 与 `delta` 成功。
2. 后续通过 boto3 / 重试完成 `0.3.1-full.nupkg` 与版本化 Setup 上传。
3. latest alias 对本地上传反复失败，最终通过 **R2 服务端 copy** 自 `PEPETII.DanmuAI-0.3.1-Setup.exe` 覆盖 `DanmuAI-Setup.exe` 成功。

### 验收对照

- [x] 本地产物与目标版本 0.3.1 一致
- [x] 线上 `releases.win.json` 含 0.3.1 Full
- [x] 线上 `releases.win.json` 含 0.3.1 Delta
- [x] 线上 `DanmuAI-Setup.exe` latest alias = 0.3.1 Setup
- [x] 完成报告区分「本地完成」与「线上切换」

---

## 7. 后续建议

1. 维护者执行 `gh auth login` 后运行：`.\scripts\upload_github_release.ps1 -Version 0.3.1 -Tag v0.3.1`
2. 另开工单将 `app/version.py` 与 Git tag 对齐到 `0.3.1`（本工单禁止改 `app/`）
3. 运维确认 Supabase `app_updates` 线上 `latest_version` / `release_url` 是否需同步为 0.3.1
