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
- [ ] `.\scripts\upload_r2_release.ps1` 会上传 `releases.win.json`、`*-full.nupkg`、`*-delta.nupkg`、版本化 Setup、`downloads/DanmuAI-Setup.exe`，以及 Portable.zip 别名（若存在）（可用 `-Version` 覆盖 `app.version`；产物版本以 `VERSION.txt` 或显式参数为准）
- [ ] `.\scripts\upload_github_release.ps1` 仅作为镜像上传 Velopack 资产，不重新定义主真源
- [ ] 主下载 URL 为 `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe`
- [ ] 便携版下载 URL 为 `https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip`（若已上传 Portable）
- [ ] 更新 feed 仍为 `https://updates.qiaoqiao.buzz/releases/win/stable`

## 数据保护回归

- [ ] 就地升级后 `%APPDATA%\DanmuAI\config.db`、`.key` 保留
- [ ] 卸载后 `%APPDATA%\DanmuAI\` 默认保留
- [ ] 程序目录与用户数据目录仍保持分离：`%LocalAppData%\PEPETII.DanmuAI\` vs `%APPDATA%\DanmuAI\`

## Git 与发布

- [ ] `git add -n .` 预演无意外文件
- [ ] GitHub Release 描述与对应版本一致

## Supabase 更新元数据（`app_updates`）

发版后除 R2 / GitHub 上传外，须同步 Supabase 表（运维主路径，见 [`supabase/README.md`](../../supabase/README.md)）：

- [ ] `app/version.py::__version__` 与 Git tag 一致
- [ ] Supabase `public.app_updates` 存在**一条** `enabled=true` 记录，`latest_version`、`release_url`、`message` 已更新（`updated_at` 最新）
- [ ] `release_url` 指向当前主下载（Setup.exe：`https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe`，除非运维刻意改链）
- [ ] 开发/打包环境已配置 `web/static/supabase-config.js` 或 `DANMU_SUPABASE_URL` + `DANMU_SUPABASE_ANON_KEY`
- [ ] 可选验收：启动应用后 `GET http://127.0.0.1:18765/api/update/channels` 的 `latest_version` / `release_url` 与表一致
- [ ] **无需**再维护 `app/release_channels.py` 中的发布版本常量（镜像 URL 变更时才改该文件）

```sql
-- 示例：发布 0.3.1 后插入或更新启用行
insert into public.app_updates (latest_version, release_url, message)
values (
  '0.3.1',
  'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe',
  null
);
```

## Setup 主入口回切后续工单（W-REL-SETUP-001 之后）

| 工单 | 状态 | 说明 |
|------|------|------|
| W-REL-SETUP-002 | 已完成 | R2 / 官网 / GitHub 文案核对与切换验收 — [报告](../../reports/W-REL-SETUP-002-online-verification-report.md) |
| W-REL-SETUP-003 | 已完成 | Supabase 线上 `app_updates.release_url` 从 MSI 迁回 Setup.exe — [报告](../../reports/W-REL-SETUP-003-supabase-migration-report.md) |
| W-REL-SETUP-004 | 已完成 | Windows 真机验收：Setup.exe 安装流程与自定义路径体验 — [报告](../../reports/W-REL-SETUP-004-setup-smoke-report.md) |

> **说明**：Web 更新弹窗版本号以 Supabase `app_updates` 为准（经 `GET /api/update/channels`）。发版时须同步该表与 `app/version.py`；勿依赖客户端内嵌静态版本常量。

## 发布链收敛（SETUP 系列完成后）

| 工单 | 状态 | 说明 |
|------|------|------|
| W-REL-CLEANUP-001 | 已完成 | 对外收敛为 Setup.exe + Portable.zip，归档 MSI / 旧 zip 链路 — [工单](W-REL-CLEANUP-001-发布链收敛Setup与Portable.md) / [报告](../../reports/W-REL-CLEANUP-001-completion-report.md) |
