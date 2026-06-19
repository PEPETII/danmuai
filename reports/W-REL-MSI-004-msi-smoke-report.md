# W-REL-MSI-004 MSI 真机验收报告

> 工单 ID：W-REL-MSI-004  
> 执行时间：2026-06-13  
> 环境：**本机**（非 VM）  
> 依据：[docs/operations/W-REL-MSI-004-MSI真机验收.md](../docs/operations/W-REL-MSI-004-MSI真机验收.md)

---

## 0. 测试环境

| 项 | 值 |
|----|-----|
| OS | Windows 10/11 x64 — `Microsoft Windows NT 10.0.22631.0`（23H2） |
| 是否 VM | 否（物理/本机 Windows） |
| 网络 | 可访问 `updates.qiaoqiao.buzz` |
| 安装前状态 | **干净**：`%LOCALAPPDATA%\PEPETII.DanmuAI`、`%ProgramFiles%\PEPETII.DanmuAI` 均不存在；`%APPDATA%\DanmuAI\` 无历史安装残留 |
| 安装包来源 | 公网 `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi` |
| 安装包大小 | 77,456,200 bytes |
| 安装包 SHA256 | `E5FCF2F227157E775FD945E9038E64264BD10380A830E03F7E8CCC76E40BB5DC` |
| Feed latest Full | **0.3.1**（与安装版本一致） |

### 公网预检

| URL | HTTP | Content-Length |
|-----|------|----------------|
| `downloads/DanmuAI-Installer.msi` | 200 | 77,456,200 |
| `releases/win/stable/releases.win.json` | 200 | latest Full = 0.3.1 |

---

## 1. MSI 首装 — Program Files

### 1.1 安装过程

| 步骤 | 结果 | 备注 |
|------|------|------|
| 下载公网 MSI | 通过 | `C:\Users\KING\AppData\Local\Temp\DanmuAI-Installer.msi` |
| 非提权静默安装 Program Files | **失败** | `msiexec` exit **1603**；日志 Error **1303**（权限不足，无法写入 `C:\Program Files\PEPETII.DanmuAI`） |
| 提权静默安装 Program Files | **通过** | `msiexec /i ... VELOPACK_INSTALLDIR="C:\Program Files\PEPETII.DanmuAI" /qn` + `-Verb RunAs`，exit **0** |
| SmartScreen 交互 | 未触发 | 静默 + 提权路径未出现 UI；未签名 MSI **交互式**安装时预期需「更多信息 → 仍要运行」（契约预期，非失败） |

### 1.2 安装路径与 Velopack 结构

| 项 | 值 |
|----|-----|
| 实际安装根目录 | `C:\Program Files\PEPETII.DanmuAI\` |
| `Update.exe` | `C:\Program Files\PEPETII.DanmuAI\Update.exe` — **存在** |
| 主程序 | `C:\Program Files\PEPETII.DanmuAI\current\DanmuAI.exe` — **存在** |
| 目录结构 | `current\`、根级 `Update.exe`、`.msi-installed` 标记文件 |

### 1.3 启动验收

| 项 | 结果 |
|----|------|
| 启动 `DanmuAI.exe` | 通过 |
| `GET /api/version` | `{"current_version":"0.3.1"}` |
| `%APPDATA%\DanmuAI\startup.log` | 有写入（34,755 bytes） |
| 首次运行生成用户数据 | `config.db`、`.key` 已创建 |

**备注**：从非提权 shell 直接执行 Program Files 下 `DanmuAI.exe` 时，Velopack 目录探测可能报 `os error 5`（拒绝访问）；以正常 `Start-Process` 启动后 Web 控制台与 API 正常。

---

## 2. MSI 自定义路径（§3 可选）

| 项 | 结果 |
|----|------|
| 状态 | **跳过** |
| 原因 | 本机单次验收聚焦公网 MSI Program Files 主路径；自定义路径未在本轮重复安装 |

---

## 3. 应用内更新通道（§4）

应用运行中（`http://127.0.0.1:18765`）API 抽检：

### 3.1 `GET /api/update/status`

```json
{
  "ok": true,
  "frozen": true,
  "current_version": "0.3.1",
  "latest_version": "",
  "update_available": false,
  "download_ready": false,
  "pending_restart": false,
  "feed_url": "https://updates.qiaoqiao.buzz/releases/win/stable",
  "message": "",
  "error": null
}
```

### 3.2 `POST /api/update/check`

```json
{
  "ok": true,
  "frozen": true,
  "current_version": "0.3.1",
  "latest_version": "0.3.1",
  "update_available": false,
  "download_ready": false,
  "pending_restart": false,
  "feed_url": "https://updates.qiaoqiao.buzz/releases/win/stable",
  "message": "已是最新版本",
  "error": null
}
```

**说明**：feed latest = 0.3.1，与已装版本相同，`update_available: false` 为**正常**（工单已知风险 §feed 版本未超前）。

### 3.3 `GET /api/update/channels`

```json
{
  "r2_latest_installer_url": "https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi",
  "github_releases_url": "https://github.com/PEPETII/danmuai/releases",
  ...
}
```

### 3.4 Web 弹窗 / Supabase

| 检查项 | 结果 |
|--------|------|
| `r2_latest_installer_url` 为 MSI | **通过** |
| `web/static/modules/app-update-banner.js` 默认 `DEFAULT_RELEASE_URL` | `DanmuAI-Installer.msi` |
| Supabase `release_url`（MSI-003 已迁移） | 见 [W-REL-MSI-003-supabase-migration-report.md](W-REL-MSI-003-supabase-migration-report.md)；本机无 `/api/app-version` 路由（404），版本横幅走客户端 Supabase + channels API fallback |

---

## 4. Setup.exe 对比（§5 可选）

| 项 | 结果 |
|----|------|
| 状态 | **跳过**（本机降级） |
| 文档对照 | MSI（本次）→ `C:\Program Files\PEPETII.DanmuAI\`；Setup 默认 → `%LOCALAPPDATA%\PEPETII.DanmuAI\` |
| Feed 一致性 | MSI 安装后 `feed_url` 已验证为 `https://updates.qiaoqiao.buzz/releases/win/stable`；与 Setup 安装后预期相同 |

---

## 5. 卸载与数据保留（§6）

### 5.1 卸载前指纹

| 文件 | SHA256 |
|------|--------|
| `%APPDATA%\DanmuAI\config.db` | `2267C4F79DEF7DF754009B7040E448CD737A7C65C4E6FC165FC803112AF437DD` |
| `%APPDATA%\DanmuAI\.key` | `D38CBAFA5E906D9E2B22A2F86AB9986F6E40EAFF69BCFEBF59013CE724D33B40` |

未勾选「删除用户数据」。

### 5.2 卸载方式

| 方式 | 结果 |
|------|------|
| `Update.exe uninstall --silent`（提权） | exit **1**，`C:\Program Files\PEPETII.DanmuAI` 仍存在 |
| `msiexec /x DanmuAI-Installer.msi /qn`（提权） | exit **0**，Program Files 安装目录**已移除** |

**记录**：MSI 安装版通过 **msiexec /x** 卸载成功；Velopack `Update.exe uninstall` 在本环境未单独完成卸载（可另开工单跟进，非本工单阻塞项）。

### 5.3 卸载后验证

| 路径 | 卸载后存在 | 预期 | 结果 |
|------|-----------|------|------|
| `C:\Program Files\PEPETII.DanmuAI\` | **否** | 程序目录移除 | **通过** |
| `%APPDATA%\DanmuAI\config.db` | **是** | 保留 | **通过** |
| `%APPDATA%\DanmuAI\.key` | **是** | 保留 | **通过** |
| `%APPDATA%\DanmuAI\startup.log` | **是** | 保留 | **通过** |
| `config.db` SHA256 | 与卸载前一致 | 不变 | **通过** |
| `.key` SHA256 | 与卸载前一致 | 不变 | **通过** |
| `%LOCALAPPDATA%\PEPETII.DanmuAI\` | **是**（残留） | 见备注 | **观察项** |

**LocalAppData 残留备注**：卸载后 `%LOCALAPPDATA%\PEPETII.DanmuAI\` 仍存在，含 `Update.exe`（3.8 MB）与 `packages\.betaId`（36 B），无 `current\` 主程序。推测为 Velopack 运行/更新缓存，**非** `%APPDATA%\DanmuAI\` 用户数据；不影响 `config.db` / `.key` 保留结论。支持话术可记入 PACKAGING_WINDOWS FAQ（可选小 PR）。

---

## 6. 验收标准对照

| # | 标准 | 结果 |
|---|------|------|
| 1 | 公网 MSI 至少一次成功首装 | **通过**（提权静默 Program Files） |
| 2 | 安装后应用可正常启动 | **通过** |
| 3 | `Update.exe` 存在于 Velopack 安装目录 | **通过** |
| 4 | Feed = `https://updates.qiaoqiao.buzz/releases/win/stable` | **通过** |
| 5 | 更新弹窗 / channels R2 链接 = `DanmuAI-Installer.msi` | **通过** |
| 6 | 卸载后 `%APPDATA%\DanmuAI\` 保留 | **通过** |
| 7 | 本报告含结果表与关键输出 | **通过** |

**总评**：**通过**（含已知观察项，无契约级阻塞）

---

## 7. 问题与后续

| 级别 | 发现 | 建议 |
|------|------|------|
| 文档/支持 | Program Files 安装需管理员权限；非提权 msiexec 报 1303 | FAQ：MSI 默认路径需 UAC/管理员 |
| 文档/支持 | 交互式未签名 MSI SmartScreen 为预期 | 已有 WINDOWS_CODE_SIGNING.md |
| 观察 | `Update.exe uninstall --silent` exit 1，需 msiexec /x | 可选跟进：MSI 卸载路径与 ARP 一致性 |
| 观察 | 卸载后 LocalAppData 少量 Velopack 残留 | 可选 FAQ；非用户数据 |
| 跳过 | Setup.exe 并行对比、MSI 自定义路径 | 建议干净 VM 快照补测 §3/§5 |

---

## 8. 关键命令日志（摘要）

```powershell
# 预检
Invoke-WebRequest -Method Head "https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi"
Invoke-WebRequest "https://updates.qiaoqiao.buzz/releases/win/stable/releases.win.json"

# 安装（提权）
msiexec /i "$env:TEMP\DanmuAI-Installer.msi" /qn VELOPACK_INSTALLDIR="$env:ProgramFiles\PEPETII.DanmuAI"

# 更新 API
Invoke-RestMethod http://127.0.0.1:18765/api/update/status
Invoke-RestMethod -Method Post http://127.0.0.1:18765/api/update/check
Invoke-RestMethod http://127.0.0.1:18765/api/update/channels

# 卸载（有效路径）
msiexec /x "$env:TEMP\DanmuAI-Installer.msi" /qn
```

MSI 安装详细日志：`%TEMP%\DanmuAI-MSI-install.log`（非提权失败）、`%TEMP%\DanmuAI-MSI-install-admin.log`（提权成功）。
