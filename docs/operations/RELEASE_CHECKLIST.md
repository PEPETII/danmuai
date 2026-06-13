# Release Checklist

发布新版本前的检查清单。

## 代码与测试

- [ ] 按 `IDE_AGENT_RULES.md` 执行与本次改动相关的分批测试，未执行全量 `pytest`
- [ ] `ruff check app main.py tests scripts` 通过
- [ ] 无硬编码 API Key、Token、R2 Secret 或敏感本地路径

## 文档

- [ ] `README.md`、`docs/operations/PACKAGING_WINDOWS.md`、`docs/release/README.md` 与实际发布链一致
- [ ] `WINDOWS_RELEASE_CONTRACT.md`、`WINDOWS_RELEASE_BASELINE.md` 未被破坏
- [ ] `docs/CHANGELOG.md` 已更新本次版本说明

## Web 控制台

- [ ] `python main.py` 能打开 `http://127.0.0.1:18765`
- [ ] 与本次改动相关的 Web/API 测试通过

## Windows exe / Velopack 发布

- [ ] `.\scripts\build_exe.ps1` 可独立成功
- [ ] `.\scripts\publish_windows_release.ps1` 生成 `release\velopack\`
- [ ] `release\velopack\` 至少包含 `PEPETII.DanmuAI-win-Setup.exe`、`PEPETII.DanmuAI-<version>-Setup.exe`、`PEPETII.DanmuAI-<version>-full.nupkg`、`releases.win.json`
- [ ] 升级发布时，`release\velopack\` 还包含 `PEPETII.DanmuAI-<version>-delta.nupkg`
- [ ] 升级发布时，`releases.win.json` 同时包含当前版本的 Full 和 Delta 资产
- [ ] 若本地没有上一版 full 包，已确认 `publish_windows_release.ps1` 的稳定 feed bootstrap 行为符合预期，或显式使用 `-SkipDeltaBootstrap`
- [ ] `.\scripts\upload_r2_release.ps1` 会上传 `releases.win.json`、`*-full.nupkg`、`*-delta.nupkg`、版本化 MSI、版本化 Setup、`downloads/DanmuAI-Installer.msi`、`downloads/DanmuAI-Setup.exe`，以及 Portable.zip 别名（若存在）（可用 `-Version` 覆盖 `app.version`；产物版本以 `VERSION.txt` 或显式参数为准）
- [ ] `.\scripts\upload_github_release.ps1` 仅作为镜像上传 Velopack 资产，不重新定义主真源
- [ ] 主下载 URL 为 `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe`
- [ ] 备选 MSI 下载 URL 为 `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Installer.msi`
- [ ] 便携版下载 URL 为 `https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip`（若已上传 Portable）
- [ ] 更新 feed 仍为 `https://updates.qiaoqiao.buzz/releases/win/stable`

## 数据保护回归

- [ ] 就地升级后 `%APPDATA%\DanmuAI\config.db`、`.key` 保留
- [ ] 卸载后 `%APPDATA%\DanmuAI\` 默认保留
- [ ] 程序目录与用户数据目录仍保持分离：`%LocalAppData%\PEPETII.DanmuAI\` vs `%APPDATA%\DanmuAI\`

## Git 与发布

- [ ] `git add -n .` 预演无意外文件
- [ ] GitHub Release 描述与对应版本一致

## Setup 主入口回切后续工单（W-REL-SETUP-001 之后）

| 工单 | 状态 | 说明 |
|------|------|------|
| W-REL-SETUP-002 | 已完成 | R2 / 官网 / GitHub 文案核对与切换验收 — [报告](../../reports/W-REL-SETUP-002-online-verification-report.md) |
| W-REL-SETUP-003 | 已完成 | Supabase 线上 `app_updates.release_url` 从 MSI 迁回 Setup.exe — [报告](../../reports/W-REL-SETUP-003-supabase-migration-report.md) |
| W-REL-SETUP-004 | 已完成 | Windows 真机验收：Setup.exe 安装流程与自定义路径体验 — [报告](../../reports/W-REL-SETUP-004-setup-smoke-report.md) |

**`app_updates.latest_version` 发布决策（003 收尾）**：线上仍为 `0.3.0`（R2 feed latest Full 已为 `0.3.1`）。**暂不**将 Supabase `latest_version` 升为 `0.3.1`，避免在未完成 frozen 客户端内嵌常量对齐前主动触发更新弹窗；需推送更新提醒时，运维在 Table Editor 单独执行 `UPDATE`（`release_url` 可保持 Setup 不变）。

## 发布链收敛（SETUP 系列完成后）

| 工单 | 状态 | 说明 |
|------|------|------|
| W-REL-CLEANUP-001 | 待执行 | 对外收敛为 Setup.exe + Portable.zip，归档 MSI / 旧 zip 链路 — [工单](W-REL-CLEANUP-001-发布链收敛Setup与Portable.md) |
