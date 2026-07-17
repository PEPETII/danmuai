# Scripts

## `scan_i18n.py` / `scan_dynamic.py`

i18n 扫描辅助（原根目录临时脚本，已归位至此）。

```bash
python scripts/scan_i18n.py      # 报告写入 scripts/output/i18n_scan_report.txt
python scripts/scan_dynamic.py   # 对比 zh/en dynamic 键
```

Backlog 计划见 `.local-ai/workorders/i18n_completion_plan.md`（本地协作文档）。

## `generate_app_icon.py`

生成 `resources/icon.png`（托盘）与 `resources/icon.ico`（PyInstaller exe 图标）。`build_exe.ps1` 在图标缺失时会自动调用。

```bash
python scripts/generate_app_icon.py
```

## `build_exe.ps1`

Windows 发布包（PyInstaller onedir，`DanmuAI.spec`）。

```powershell
.\scripts\build_exe.ps1
```

输出 `dist\DanmuAI\DanmuAI.exe`。完整说明见 [docs/operations/PACKAGING_WINDOWS.md](../docs/operations/PACKAGING_WINDOWS.md)。构建前由发布脚本检查带凭据的 `supabase-config*` 文件，默认不允许打包。

## `velopack_poc.ps1` / `velopack_pack.ps1`

Velopack 打包（需 .NET SDK + `dotnet tool install -g vpk`）：

```powershell
.\scripts\velopack_poc.ps1
.\scripts\velopack_poc.ps1 -SkipBuild
```

## `publish_windows_release.ps1`

`build_exe.ps1` + Velopack → `release\velopack\`：

```powershell
.\scripts\publish_windows_release.ps1
.\scripts\publish_windows_release.ps1 -DryRun   # version parse + Supabase guard only (no build)
```

| 输出 | 说明 |
|------|------|
| `release\velopack\PEPETII.DanmuAI-win-Setup.exe` | Velopack 安装器（本地原始输出） |
| `release\velopack\PEPETII.DanmuAI-<version>-Setup.exe` | 版本化 Setup（R2 上传源） |
| `release\velopack\PEPETII.DanmuAI-win-Portable.zip` | 便携版 |
| `release\velopack\PEPETII.DanmuAI-<version>-full.nupkg` | 全量更新包 |
| `release\velopack\PEPETII.DanmuAI-<version>-delta.nupkg` | 可选增量包（有上一版 Full 时生成） |
| `release\velopack\releases.win.json` | 更新 feed |
| `release\velopack\SHA256SUMS.txt` | 发布前完整性清单（不是代码签名） |

发布后上传前先运行本地门禁：

```powershell
.\scripts\verify_windows_release_artifacts.ps1
.\scripts\write_release_hash_manifest.ps1 -ReleaseDir release\velopack -VerifyOnly
```

## `upload_r2_release.ps1`

上传至 Cloudflare R2（**主真源**）。环境变量：`R2_ACCOUNT_ID`、`R2_ACCESS_KEY_ID`、`R2_SECRET_ACCESS_KEY`、`R2_BUCKET`（仅本机/CI secret，**禁止入库**）。

```powershell
.\scripts\upload_r2_release.ps1
.\scripts\upload_r2_release.ps1 -Version 0.3.1
.\scripts\upload_r2_release.ps1 -Version 0.3.1 -DryRun
```

- 未传 `-Version` 时，优先读 `release/velopack/VERSION.txt`，再回退 `app.version.__version__`。
- 上传前校验 `releases.win.json` 最新 Full 版本与目标版本一致。
- `downloads/DanmuAI-Setup.exe`（Setup 主入口）、`downloads/PEPETII.DanmuAI-win-Portable.zip`（便携版）latest alias 均通过 R2 服务端复制对应版本化文件，避免大文件重复本地上传。

R2 为正式更新与主下载源（Setup.exe 为主入口）；不得改回 COS 或 Inno Setup。

## `upload_github_release.ps1`

上传 Velopack 资产至 GitHub Releases（**镜像 / 备用**，非主真源）。

推荐顺序是先完成 `upload_r2_release.ps1`，再上传 GitHub 镜像；最后用 `check_release_endpoints.ps1` 验证线上 feed、Setup 和 Portable alias。

## `check_release_endpoints.ps1`

只读检查稳定频道的在线 HTTP 状态、Content-Length 和版本标识；不会上传或修改 R2。

```powershell
.\scripts\check_release_endpoints.ps1
.\scripts\check_release_endpoints.ps1 -Version 0.3.9
```

## `verify_windows_release_artifacts.ps1` / `write_release_hash_manifest.ps1`

前者检查本地 Setup、Full、Delta（如有）、Portable 根目录和 `releases.win.json` 的版本一致性，并拒绝 MSI；后者生成或核对 `SHA256SUMS.txt`。两者都只操作本地 `release\velopack`，不能证明线上 alias 已切换。

## `sign_windows_release.ps1` / `resolve_build_python.ps1`

`sign_windows_release.ps1 -VerifyOnly` 只验证已有 Setup 的 Authenticode 签名；签名默认关闭，配置由环境变量传给 `velopack_pack.ps1`。`resolve_build_python.ps1` 为各发布脚本选择 `.venv-build`、`.venv-build-312` 或显式 `DANMU_BUILD_PYTHON`，不要把凭据写入脚本。

## `bench_jpeg_quality.py`

Local benchmark for `main.compress_screenshot()` (production path). Does **not** call AI APIs or write images into the repository.

### Requirements

- Project dependencies installed (`pip install -r requirements.txt`)
- Run from repo root (or any cwd; the script adds the repo to `sys.path`)

### Qt / Windows note

`--source file` tries an inline `QApplication` first. If Qt fails to initialize in this process (common in some terminals), it **automatically falls back** to a subprocess worker (`_bench_jpeg_worker.py`) that runs `main.compress_screenshot()` in a clean process. Force subprocess with `--subprocess`.

### Usage

```bash
# Real screenshot file (recommended for T0 decisions)
python scripts/bench_jpeg_quality.py --source file --path "C:\path\to\screenshot.png"

# Live screen grab
python scripts/bench_jpeg_quality.py --source screen --screen-index 0

# Synthetic pattern (regression / smoke only)
python scripts/bench_jpeg_quality.py --source synthetic --width 1920 --height 1080

# Optional: custom max width, skip JSON file, force subprocess worker
python scripts/bench_jpeg_quality.py --source file --path "..." --max-width 768 --runs 3 --no-json
python scripts/bench_jpeg_quality.py --source file --path "..." --subprocess
```

### Output

- Table on stdout: qualities **100 / 90 / 85 / 80**, JPEG size, Base64/URI length, median compress time, savings vs quality 100
- JSON (default): `%TEMP%\danmu_jpeg_bench_<utc>.json` — use `--json-out` or `--no-json` to control

Keep screenshot files outside the repo. Do not commit benchmark JSON under `scripts/output/`.

## `extract_danmu_pool.py`（历史数据管线）

Build `data/danmu_pool_zh.json` (1000 overlay-safe lines) from `开源项目/**/sorted_danmaku.txt` or GitHub DDmkTCCorpus。当前仓库没有 `data/danmu_pool_zh.json`、`data/danmu_pool_zh_bootstrap.txt`，也没有保留 `docs/DANMAKU_FORMULA.md`；这些脚本不是默认运行链路，执行前需先准备输入并确认后续消费者。

```bash
python scripts/extract_danmu_pool.py --target 1000
python scripts/extract_danmu_pool.py --corpus "开源项目/DDmkTCCorpus-main/data/sorted_danmaku.txt"
```

若未来恢复公式库源文件，才可用 `write_formula_bootstrap.py` 生成 bootstrap；在当前 checkout 直接运行会因缺少 `docs/DANMAKU_FORMULA.md` 退出。

```bash
python scripts/write_formula_bootstrap.py
```

## `filter_pool_sensitive.py`

Post-process `data/danmu_pool_zh.json` to drop lines matching the built-in sensitive-word list。仅在先生成该 JSON 后运行；默认路径当前不存在。

## Windows release delta notes

- `publish_windows_release.ps1` no longer deletes the whole `release\velopack\` directory. It keeps older `*.nupkg` files so `vpk pack` can emit `*-delta.nupkg`.
- If no previous full package exists locally, `publish_windows_release.ps1` bootstraps from `https://updates.qiaoqiao.buzz/releases/win/stable`. Use `-SkipDeltaBootstrap` to disable that behavior.
- `upload_r2_release.ps1` and `upload_github_release.ps1` now upload `*-delta.nupkg` alongside `releases.win.json`, `*-full.nupkg`, Setup, and Portable (when present).
