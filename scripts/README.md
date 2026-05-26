# Scripts

## `generate_app_icon.py`

生成 `resources/icon.png`（托盘 / macOS app 图标源）与 `resources/icon.ico`（PyInstaller exe 图标）。`build_exe.ps1` 在图标缺失时会自动调用。

```bash
python scripts/generate_app_icon.py
```

## `build_exe.ps1`

Windows 发布包（PyInstaller onedir，`DanmuAI.spec`）。

```powershell
.\scripts\build_exe.ps1
```

输出 `dist\DanmuAI\DanmuAI.exe`。需已存在 `data\danmu_pool_zh.json`。完整说明与问题记录见 [docs/PACKAGING_WINDOWS.md](../docs/PACKAGING_WINDOWS.md)。

## `build_macos.sh`

macOS `.app` 发布包（PyInstaller onedir + BUNDLE，`DanmuAI-macOS.spec`）。

```bash
./scripts/build_macos.sh
```

输出 `dist/DanmuAI.app`。完整说明见 [docs/PACKAGING_MACOS.md](../docs/PACKAGING_MACOS.md)。

## `bench_jpeg_quality.py`

Local benchmark for `main.compress_screenshot()` (production path). Does **not** call AI APIs or write images into the repository.

### Requirements

- Project dependencies installed (`pip install -r requirements.txt`)
- Run from repo root (or any cwd; the script adds the repo to `sys.path`)

### Qt note

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

## `extract_danmu_pool.py`

Build `data/danmu_pool_zh.json` (1000 overlay-safe lines) from `开源项目/**/sorted_danmaku.txt` or GitHub DDmkTCCorpus.

```bash
python scripts/extract_danmu_pool.py --target 1000
python scripts/extract_danmu_pool.py --corpus "开源项目/DDmkTCCorpus-main/data/sorted_danmaku.txt"
```

Bootstrap 400 lines live in `data/danmu_pool_zh_bootstrap.txt` (from `docs/DANMAKU_FORMULA.md`). Regenerate:

```bash
python scripts/write_formula_bootstrap.py
```

## `filter_pool_sensitive.py`

Post-process `data/danmu_pool_zh.json` to drop lines matching the built-in sensitive-word list. Run after `extract_danmu_pool.py` when refreshing the pool.

## `_probe_mic_audio.py` (dev only)

Ad-hoc microphone capture + API probe for local debugging. Not used by the desktop app; may print HTTP error bodies from providers. Do not run in shared logs.
