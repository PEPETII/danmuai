# IDE Windows 构建手册

> 用途：以后把 DanmuAI 的 Windows 本地构建任务交给 IDE / Codex 时，直接让它按这份手册执行。  
> 默认边界：**只构建、校验、汇报，不上传、不提交、不改线上**，除非我明确追加要求。

---

## 1. 先读哪些文件

执行前先阅读并遵守：

- `AGENTS.md`
- `.local-ai/prompts/IDE_AGENT_RULES.md`
- `docs/operations/PACKAGING_WINDOWS.md`（权威打包与发布指南）
- `.agents/skills/danmu-windows-release-upload/references/release-flow.md`
- `reports/W-REL-CLEANUP-001-completion-report.md`（当前发布链收敛事实）

> **历史资料（不得作为当前流程）**：`docs/operations/W-REL-MSI-*` 与 `reports/W-REL-MSI-*` 为 MSI 实验归档。当前主链固定为 `PyInstaller onedir -> Velopack -> R2 -> GitHub mirror`；主入口 `DanmuAI-Setup.exe`，便携入口 `PEPETII.DanmuAI-win-Portable.zip`。

---

## 2. 当前正式发布链

固定主链：

```text
PyInstaller onedir -> Velopack -> release/velopack
```

构建顺序固定为：

1. `.\scripts\build_exe.ps1`
2. `.\scripts\publish_windows_release.ps1`
3. 检查 `release\velopack\`

不要自行改回：

- 旧 zip 主分发
- Inno Setup
- MSI 主入口
- 自研增量补丁

---

## 3. 执行目标

当我说“构建 Windows 版本”时，IDE 默认应做到：

1. 读取当前版本号（`app/version.py`）
2. 执行正式构建
3. 校验 `release/velopack/` 产物
4. 汇报构建结果

默认**不要**做：

- `git commit`
- `git push`
- R2 上传
- GitHub Releases 上传
- Supabase `app_updates` 修改

---

## 4. 构建前检查

### 4.1 版本

确认：

- `app/version.py::__version__`
- `docs/operations/CHANGELOG.md` 已记录本次版本

### 4.2 源树阻断项（Supabase 本地配置）

`publish_windows_release.ps1` 在构建前扫描 `web/static/`，对**文件名包含 `supabase-config`** 且不在 allowlist 的文件一律中止（default-deny，BUG-005）。allowlist 仅含：

- `supabase-config.example.js`（模板，无凭据）
- `supabase-client.js`（客户端代码，无凭据）

**禁止**：在 `web/static/` 内保留任何含 `supabase-config` 的文件名，包括 `supabase-config.js` 本体以及 `.bak`、`.codex-release-backup`、`-local` 等变体。在目录内重命名备份**不能**绕过守卫。

若本机没有 `web/static/supabase-config.js`，可跳过移出步骤，直接执行 DryRun 或正式构建。

#### 步骤 1：发布前移出

将真实配置**移出** `web/static/` 到 gitignored 临时目录（不会被 PyInstaller 收集）：

```powershell
$destDir = ".local-ai/release-local"
New-Item -ItemType Directory -Force -Path $destDir | Out-Null
Move-Item -LiteralPath "web/static/supabase-config.js" `
  -Destination (Join-Path $destDir "supabase-config.js")
```

- `.local-ai/` 已在 `.gitignore` 中整目录忽略，不会误提交。
- 不要删除 `supabase-config.example.js`。

#### 步骤 2：DryRun 验证守卫

```powershell
.\scripts\publish_windows_release.ps1 -DryRun
```

预期输出包含 `[DryRun] App version: <version>` 与 `[DryRun] Supabase guard passed. Skipping build/pack.`，退出码 `0`。

#### 步骤 3：正式构建与发布后恢复

正式构建：

```powershell
.\scripts\publish_windows_release.ps1
```

构建完成后，将配置移回以便本地开发：

```powershell
Move-Item -LiteralPath ".local-ai/release-local/supabase-config.js" `
  -Destination "web/static/supabase-config.js"
```

打包版运行时凭据应通过 `DANMU_SUPABASE_URL` / `DANMU_SUPABASE_ANON_KEY` 注入（见 `supabase/README.md`），而非 `web/static/supabase-config.js`。

### 4.3 进程占用

若 `DanmuAI.exe` 正在运行，`dist/DanmuAI/` 可能被锁住。  
`build_exe.ps1` 会自动尝试结束进程，但 IDE 仍应在报告中注明是否发生过锁文件清理。

### 4.4 正式发布依赖锁（可选）

对外发版构建时，维护者应设置：

```powershell
$env:DANMU_BUILD_USE_RELEASE_LOCK = "1"
```

再执行 §5 的 `publish_windows_release.ps1`。这会令 `build_exe.ps1` 从 `requirements-release-win-lock.txt` 安装精确版本（详见 `PACKAGING_WINDOWS.md`「依赖锁定」章节）。

日常 IDE 本地试构建**可不**设该变量；未设置时仍安装 `requirements.txt` + `requirements-dev.txt`（与历史行为一致）。

---

## 5. 正式执行命令

在仓库根目录执行：

```powershell
.\scripts\publish_windows_release.ps1
```

这会自动调用：

- `.\scripts\build_exe.ps1`
- `.\scripts\velopack_pack.ps1`

---

## 6. 构建成功的判定标准

至少确认 `release/velopack/` 中存在：

- `PEPETII.DanmuAI-win-Setup.exe`
- `PEPETII.DanmuAI-<version>-Setup.exe`
- `PEPETII.DanmuAI-<version>-full.nupkg`
- `releases.win.json`

升级版本时还应存在：

- `PEPETII.DanmuAI-<version>-delta.nupkg`

如果存在 Portable 产物，还要检查：

- `PEPETII.DanmuAI-win-Portable.zip`

---

## 7. Portable 额外校验

当前仓库的便携版要求是：

- `Portable.zip` 解压后，用户直接运行根目录 `DanmuAI.exe`
- 便携包根目录应直接包含：
  - `DanmuAI.exe`
  - `_internal/`

不应再出现作为对外运行入口的 Velopack portable stub 结构，例如：

- `.portable`
- `Update.exe`
- `current/DanmuAI.exe`

如果解压包根目录仍是上面这种 stub 结构，视为**构建缺陷**，不得报告为成功。

---

## 8. 结果汇报模板

IDE 完成后按以下结构汇报：

### 8.1 构建结果

- 成功 / 失败

### 8.2 执行的命令

- 实际执行过的 PowerShell 命令

### 8.3 产物清单

- `release/velopack/` 中本次版本相关文件

### 8.4 关键校验

- `VERSION.txt` 中的版本
- `releases.win.json` 中 latest Full / Delta
- Portable 根目录结构是否正确

### 8.5 未解决问题

- 如果构建日志中出现依赖解析告警、PyInstaller 警告、版本冲突等，必须单列说明
- 不能把“有告警但产物已生成”伪装成“完全无问题”
- 若使用了 `DANMU_BUILD_USE_RELEASE_LOCK=1`，汇报中应注明锁文件路径；若出现依赖冲突，对照 `requirements-release-win-lock.txt` 与 `git diff` 审查是否需刷新锁基线（见 `PACKAGING_WINDOWS.md`）

---

## 9. 给 IDE 的可直接口令

以后我可以直接对 IDE 说：

```text
按 docs/operations/IDE_WINDOWS_BUILD_PLAYBOOK.md 执行一次当前仓库的 Windows 本地构建，只构建和校验，不上传、不提交。
```

如果我要连上传一起做，我会明确补一句：

```text
构建完成后继续按正式发布链上传到 R2。
```
