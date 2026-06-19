# W-REL-MSI-004 执行提示词

> 你只执行**当前工单**，不要实现未来功能，不要顺手重构无关代码，不要自行决定新架构。

---

## 当前工单

- **工单 ID**：W-REL-MSI-004
- **标题**：MSI 真机安装与 Velopack 更新通道验收
- **前置依赖**：
  - [W-REL-MSI-001](W-REL-MSI-001-MSI主入口切换.md)（`vpk pack --msi --instLocation Either`）
  - [W-REL-MSI-002](W-REL-MSI-002-R2线上MSI切换.md)（线上 `DanmuAI-Installer.msi` 可下载；或本地等价 MSI + 同版本 feed）

## 执行前必须阅读

1. [WINDOWS_RELEASE_CONTRACT.md](WINDOWS_RELEASE_CONTRACT.md) — 下载入口角色、用户数据目录
2. [PACKAGING_WINDOWS.md](PACKAGING_WINDOWS.md) §用户数据与更新/卸载（W-REL-R2V-008）
3. [WINDOWS_CODE_SIGNING.md](WINDOWS_CODE_SIGNING.md) — 未签名 SmartScreen 预期

## 目标

在 Windows 10/11 x64 真机或 VM 上，验证从 **MSI 主入口** 首装后的安装目录、启动、应用内更新检测、手动下载链接与卸载数据保留行为符合发布契约。

**本工单不**修改打包脚本；发现契约级 bug 时仅记录并另开工单。

## 必须遵守

1. 优先使用公网 `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi`；离线可用本地 `release/velopack/PEPETII.DanmuAI-<version>-Installer.msi` 并注明
2. 验收 MSI 与 Setup.exe 的安装路径差异（`--instLocation Either` vs Setup 默认 `%LocalAppData%`）
3. 未签名 SmartScreen「更多信息 → 仍要运行」为预期行为，不记为失败
4. 卸载后 `%APPDATA%\DanmuAI\` 用户数据应保留

## 允许修改的区域

```
reports/W-REL-MSI-004-msi-smoke-report.md
reports/W-REL-MSI-004-*.md
```

## 禁止修改的区域

```
app/
web/
scripts/
tests/
supabase/
```

## 具体需求

### 1. 测试环境

| 项 | 要求 |
|----|------|
| OS | Windows 10 或 11 x64 |
| 网络 | 可访问 `updates.qiaoqiao.buzz`（应用内更新检测） |
| 前置 | 干净 VM 或卸载旧版后测试（推荐） |

### 2. MSI 首装 — Program Files 路径

1. 下载并运行 `DanmuAI-Installer.msi`
2. 选择默认/Program Files 安装（若安装器提供选项）
3. 记录实际安装目录（预期在 `%ProgramFiles%` 或用户选择路径下的 Velopack 结构）
4. 确认存在 `Update.exe`、主程序可启动
5. 记录 SmartScreen 是否出现及绕过步骤

### 3. MSI 首装 — 自定义路径（可选但推荐）

1. 在干净环境重复安装，选择自定义目录（非 Program Files）
2. 确认应用可启动且 `Update.exe` 路径正确

### 4. 应用内更新通道

1. 启动 DanmuAI，打开 Web 控制台
2. `GET /api/update/status` 或托盘/设置中确认 feed 为 R2 stable
3. 若存在更高版本 feed：验证「检查更新」可发现新版本（不必完成全量安装，除非发布窗口需要）
4. 打开更新弹窗，确认 **R2 手动下载** 链接为 `DanmuAI-Installer.msi`（若 W-REL-MSI-003 已完成，Supabase 行也应一致）

### 5. 与 Setup.exe 对比（抽样）

在同一 VM 或另一快照上，可选安装 `DanmuAI-Setup.exe` 备用包，对比：

- 默认安装目录差异
- 安装后是否均能走同一 `releases.win.json` feed

### 6. 卸载与数据保留

1. 通过系统「应用和功能」或 Velopack 卸载 MSI 安装版
2. 确认 `%APPDATA%\DanmuAI\`（`config.db` 等）仍存在
3. 确认 `%LocalAppData%\PEPETII.DanmuAI\` 程序目录已移除或符合 Velopack 卸载行为

## 非目标

- 不验收代码签名（W-REL-R2V-SIGN-001）
- 不验收 GitHub Releases 镜像下载
- 不修改 R2 / Supabase 线上配置

## 验收标准

- [ ] MSI 从公网（或注明本地等价）完成至少一次成功首装
- [ ] 安装后应用可正常启动
- [ ] `Update.exe` 存在于 Velopack 安装目录
- [ ] 应用内更新 feed 指向 `https://updates.qiaoqiao.buzz/releases/win/stable`
- [ ] 更新弹窗 R2 下载链接为 MSI URL
- [ ] 卸载后用户数据目录保留
- [ ] `reports/W-REL-MSI-004-msi-smoke-report.md` 含上述结果表与截图/日志引用（如有）

## 手动验证步骤

1. 按 §2–§6 逐项执行并填报告模板
2. 若更新检测失败，抓取 `releases.win.json` 与本地 `app.version` 对比
3. 若安装失败，记录 WiX/MSI 日志路径与错误码

## 已知风险

1. **安装路径差异**：MSI `Either` 与 Setup 默认路径不同，可能影响用户文档与支持话术
2. **feed 版本未超前**：无法验收「有更新可装」时，仅验收 feed 可达与 check API 正常
3. **SmartScreen**：未签名 MSI 可能被 Defender/SmartScreen 拦截，需用户手动允许

## 发现问题时的处理

| 级别 | 处理 |
|------|------|
| 文档/支持话术 | 记入报告，可选小 PR 改 PACKAGING_WINDOWS FAQ |
| 打包脚本 bug | 停止扩大范围，新开 W-REL-MSI-00x 修复工单 |
| 更新通道断裂 | 高优先级，关联 W-REL-MSI-002 feed 与 nupkg 核对 |

## 完成后必须给出

1. 测试环境（OS 版本、是否 VM）
2. MSI 安装路径（两次安装若都测了）
3. feed / update check 结果
4. 卸载后 `%APPDATA%\DanmuAI\` 是否存在
5. 通过/失败项清单与阻塞问题
