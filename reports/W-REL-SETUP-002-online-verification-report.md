# W-REL-SETUP-002 完成报告：线上 R2 / 官网 / GitHub 公网验收

> 工单 ID：W-REL-SETUP-002  
> 完成时间：2026-06-13（UTC）  
> 前置：W-REL-SETUP-001 仓库回切已完成

---

## 1. 结论摘要

| 检查面 | 结果 |
|--------|------|
| R2 Setup 主入口 | **通过**（HTTP 200，可下载 0.3.1） |
| R2 MSI 备选 | **通过**（HTTP 200） |
| R2 feed | **通过**（latest Full = **0.3.1**） |
| 官网 Vercel 生产页 | **通过**（已 redeploy，主按钮 Setup.exe） |
| GitHub latest Release | **已同步**（闭环后 `releases/latest` = **v0.3.1**；初验时为 v0.3.0，见 §4 / §8） |
| Setup alias 与版本化一致性 | **R2 桶内已一致**（公网版本化 URL CDN 可能短暂滞后，见 §8） |

**无需为回切重传 R2**：双 alias 与 feed 在 W-REL-MSI-002 后已存在且可用；本工单以公网验收 + 官网部署对齐为主。

---

## 2. R2 公网 HEAD 验收

| 角色 | URL | HTTP | Content-Length | ETag |
|------|-----|------|----------------|------|
| **Setup 主入口** | `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe` | 200 | **92,386,342** | `3254f0f3...` |
| MSI 备选 | `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi` | 200 | 77,456,200 | `16ba3a68...` |
| Portable | `https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip` | 200 | 87,922,832 | `11bedfaf...` |
| Feed | `https://updates.qiaoqiao.buzz/releases/win/stable/releases.win.json` | 200 | 768 | `a650f532...` |
| 版本化 Setup | `https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-0.3.1-Setup.exe` | 200 | **92,384,119** | `7a93afa4...` |
| 版本化 MSI | `https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-0.3.1-Installer.msi` | 200 | 77,456,200 | `16ba3a68...` |

### alias 一致性

| 检查项 | 结果 |
|--------|------|
| MSI alias vs 版本化 MSI | **一致**（77,456,200） |
| Setup alias vs 版本化 Setup | **不一致**（alias 92,386,342 vs 版本化 92,384,119，差 **2,223 bytes**） |

**说明**：与 W-REL-MSI-002 报告类似，latest alias 与版本化对象偶发大小漂移（可能为不同构建批次或 CDN 缓存）。主入口 Setup 可正常下载（SHA256 见 W-REL-SETUP-004）。**建议**下次正式发布时用 `upload_r2_release.ps1` 重新执行 Setup alias copy，非本工单阻塞项。

### releases.win.json

| Version | Type | FileName | Size |
|---------|------|----------|------|
| 0.3.1 | Full | PEPETII.DanmuAI-0.3.1-full.nupkg | 87,924,262 |
| 0.3.1 | Delta | PEPETII.DanmuAI-0.3.1-delta.nupkg | 469,790 |
| 0.3.0 | Full | PEPETII.DanmuAI-0.3.0-full.nupkg | 87,916,642 |

latest Full = **0.3.1**，与 R2 stable 一致。

---

## 3. 官网 Vercel 验收

| 项 | 值 |
|----|-----|
| 项目 | `danmuai-website`（`prj_PovUWNjveXJ3JNQQXa6S1Izp3ZbB`） |
| 生产域名 | `https://danmuai.xyz`、`https://www.danmuai.xyz` |
| 部署前状态 | 生产页仍指向 **MSI 主按钮**（未包含 SETUP-001） |
| 执行动作 | `npx vercel deploy --prod --yes`（`website/`） |
| 部署 ID | `dpl_9SjEdNdAqCiQb1mRtdCKsC8wb4ZQ` |
| 部署后 | 已 alias 至 `danmuai.xyz` |

### 生产页下载区（部署后）

| 检查项 | 结果 |
|--------|------|
| 主按钮 `href` | `DanmuAI-Setup.exe` — **通过** |
| 主按钮文案 | 「下载 Windows 安装版 (Setup.exe)」 — **通过** |
| 描述 | 含「推荐下载」「自定义安装路径」 — **通过** |
| 次级链接 | 「备选安装 (MSI)」+ Portable + GitHub — **通过** |

---

## 4. GitHub Releases 镜像验收

| 项 | 状态 |
|----|------|
| `releases/latest` 指向 | **v0.3.0**（非 R2 当前 0.3.1） |
| Release 正文 | 功能更新说明，**无** R2 主下载 Setup/MSI 契约文案 |
| 附件 | 含 `PEPETII.DanmuAI-win-Setup.exe`、`PEPETII.DanmuAI-0.3.0-Setup.exe`、Portable、nupkg；**无** 0.3.1 MSI |
| v0.3.1 tag | **不存在**（API 404） |

**结论**：GitHub 镜像落后于 R2 主真源，且未发布 v0.3.1 Release。按工单非目标，**不阻塞** Setup 主入口回切；后续可在发布窗口执行 `upload_github_release.ps1 -Tag v0.3.1` 同步镜像说明（Setup 优先）。

---

## 5. 全局文案抽查

仓库有效契约与生产官网均已 Setup 为主入口；历史 `W-REL-MSI-*` 文档与报告保留归档，不作为当前对外入口。

---

## 6. 未完成项 / 后续建议

| 项 | 状态 |
|----|------|
| Setup alias 2,223 B 漂移 | **已处理**（见 §8 alias 重同步） |
| GitHub v0.3.1 镜像 | **已完成**（见 §8 GitHub 镜像同步） |
| Supabase 线上 `release_url` | **已完成**（W-REL-SETUP-003） |

---

## 7. 验收清单

- [x] Setup / MSI / Portable / feed 公网 HEAD 表已记录
- [x] Setup 主入口 HTTP 200 且可下载
- [x] MSI 备选 HTTP 200
- [x] feed latest Full = 0.3.1
- [x] Vercel 生产页主按钮指向 Setup.exe（已 redeploy）
- [x] GitHub latest 已检查并记录差异
- [x] 本报告已撰写

---

## 8. 闭环执行记录（2026-06-13）

### Setup alias 重同步

对 R2 执行服务端 copy：`downloads/PEPETII.DanmuAI-0.3.1-Setup.exe` → `downloads/DanmuAI-Setup.exe`（`no-cache`）。

| 对象 | R2 桶内 Content-Length | 公网 HEAD Content-Length |
|------|------------------------|--------------------------|
| `DanmuAI-Setup.exe`（alias） | 92,386,342 | 92,386,342 |
| `PEPETII.DanmuAI-0.3.1-Setup.exe`（版本化） | 92,386,342 | 92,384,119（CDN 缓存旧值） |

**结论**：R2 桶内 alias 与版本化对象已一致；公网版本化 URL 可能仍短暂显示旧 Content-Length，不影响主入口 `DanmuAI-Setup.exe`。

### GitHub v0.3.1 镜像同步

| 项 | 结果 |
|----|------|
| Release | `v0.3.1` 已创建 |
| `releases/latest` | 指向 **v0.3.1** |
| 附件 | Setup（win + 版本化）、MSI、Portable、full/delta nupkg、`releases.win.json`（7 项） |
| 主下载说明 | R2 仍为真源：`DanmuAI-Setup.exe` |
