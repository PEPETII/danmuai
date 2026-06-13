# W-REL-SETUP-004 Setup 真机验收报告

> 工单 ID：W-REL-SETUP-004  
> 执行时间：2026-06-13  
> 环境：**本机**（非 VM）  
> 前置：W-REL-SETUP-002（公网 Setup 可下载）、W-REL-SETUP-003（Supabase `release_url` = Setup）

---

## 0. 测试环境

| 项 | 值 |
|----|-----|
| OS | Windows 10/11 x64 — `Microsoft Windows NT 10.0.22631.0` |
| 是否 VM | 否 |
| 网络 | 可访问 `updates.qiaoqiao.buzz` |
| 安装包来源 | 公网 `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe` |
| 安装包大小 | 92,386,342 bytes |
| 安装包 SHA256 | `84631AB25DB7EAC4E48E14E37BC892CDE3815124DD56891419A14A882280525A` |
| Feed latest Full | **0.3.1** |

### 公网预检

| URL | HTTP | Content-Length |
|-----|------|----------------|
| `downloads/DanmuAI-Setup.exe` | 200 | 92,386,342 |
| `releases/win/stable/releases.win.json` | 200 | latest Full = 0.3.1 |

---

## 1. Setup 默认路径首装

### 1.1 前置清理

机器上存在此前 **MSI** 安装残留（`%LocalAppData%\PEPETII.DanmuAI\` 含 `.msi-installed`）。通过 `msiexec /x DanmuAI-Installer.msi /qn`（提权）卸载，exit **0**；程序目录移除，`%APPDATA%\DanmuAI\` 保留。

### 1.2 默认路径静默安装

```powershell
DanmuAI-Setup.exe --silent
```

| 步骤 | 结果 |
|------|------|
| 安装 exit code | **0** |
| 安装根目录 | `%LocalAppData%\PEPETII.DanmuAI\` |
| `Update.exe` | **存在** |
| `current\DanmuAI.exe` | **存在** |
| `.msi-installed` 标记 | **不存在**（确认为 Setup 安装） |

### 1.3 卸载（Velopack）

```powershell
%LocalAppData%\PEPETII.DanmuAI\Update.exe uninstall --silent
```

| 步骤 | 结果 |
|------|------|
| 卸载 | **成功**（非 MSI 路径，Update.exe 可卸载） |
| 程序目录 | 已调度移除（数秒后不存在） |
| `%APPDATA%\DanmuAI\config.db` | **保留** |

---

## 2. Setup 自定义路径首装（本单核心）

### 2.1 安装命令

```powershell
DanmuAI-Setup.exe --silent --installto "D:\Apps\DanmuAI"
```

| 步骤 | 结果 |
|------|------|
| 安装 exit code | **0** |
| 安装根目录 | `D:\Apps\DanmuAI\` |
| `D:\Apps\DanmuAI\Update.exe` | **存在** |
| `D:\Apps\DanmuAI\current\DanmuAI.exe` | **存在** |
| Velopack 结构 | `current\`、`packages\`、根级 `Update.exe` — **符合契约** |

**结论**：`--installto` 自定义安装路径 — **通过**。

### 2.2 卸载与数据保留

```powershell
D:\Apps\DanmuAI\Update.exe uninstall --silent
```

| 步骤 | 结果 |
|------|------|
| 卸载 | **成功** |
| `D:\Apps\DanmuAI\` | 已调度移除 |
| `%APPDATA%\DanmuAI\` | **保留**（含 `config.db`） |

---

## 3. 应用内更新通道

| 检查项 | 结果 | 备注 |
|--------|------|------|
| R2 feed 可达 | **通过** | latest Full = 0.3.1 |
| `GET /api/update/channels`（dev 构建） | **通过** | `r2_latest_installer_url` = `DanmuAI-Setup.exe` |
| Supabase `release_url`（003 后） | **通过** | 线上 enabled 行 = Setup URL |
| 更新弹窗 UI 实测 | **未测** | `latest_version` 仍为 0.3.0，未高于本机；远程链接已由 003 保证 |

**说明**：完整弹窗 UI 需 `latest_version` 高于本地或 mock；本工单以安装路径 + API/Supabase 链路为主验收。

---

## 4. 与 MSI 对比（抽样）

| 维度 | Setup 默认 | Setup `--installto` | MSI（W-REL-MSI-004 已测） |
|------|------------|---------------------|---------------------------|
| 默认/常见路径 | `%LocalAppData%\PEPETII.DanmuAI\` | 用户指定（本测 `D:\Apps\DanmuAI`） | Program Files（需提权） |
| 自定义路径 | **`--installto` 支持** | 本工单核心验证点 | `VELOPACK_INSTALLDIR` / UI |
| 卸载入口 | `Update.exe uninstall` | 同左 | `msiexec /x` |
| `.msi-installed` | 无 | 无 | 有 |
| 共用 feed | 是（0.3.1 stable） | 是 | 是 |

---

## 5. 验收结果总表

| # | 验收项 | 结果 |
|---|--------|------|
| 1 | 公网 Setup.exe 下载并校验 | **通过** |
| 2 | 默认路径 Setup 首装 | **通过** |
| 3 | **`--installto` 自定义路径首装** | **通过** |
| 4 | `Update.exe` 存在 | **通过** |
| 5 | feed 指向 R2 stable 0.3.1 | **通过** |
| 6 | 手动下载链接（API + Supabase）为 Setup | **通过** |
| 7 | 卸载后用户数据保留 | **通过** |
| 8 | SmartScreen 交互式绕过 | **未测**（全程 `--silent`；契约预期非失败） |

---

## 6. 发现问题

| 级别 | 描述 | 处理 |
|------|------|------|
| 低 | R2 Setup alias 与版本化 Setup 大小差 2,223 B（见 SETUP-002） | 下次发布重跑 alias copy |
| 信息 | GitHub latest 仍为 v0.3.0 | 非阻塞，见 SETUP-002 |
| 信息 | frozen 0.3.1 客户端内嵌常量可能仍为 MSI | 下一版发包对齐 SETUP-001 |

**无契约级阻塞问题。**

---

## 7. 验收清单

- [x] 公网 Setup 至少一次成功首装（默认路径）
- [x] `--installto` 自定义路径首装成功
- [x] `Update.exe` 存在且 Velopack 结构正确
- [x] feed = R2 stable
- [x] Supabase / API 手动下载链接为 Setup URL
- [x] 卸载后 `%APPDATA%\DanmuAI\` 保留
- [x] 本报告已撰写
