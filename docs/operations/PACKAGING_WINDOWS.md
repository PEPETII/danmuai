# Windows exe 打包指南（PyInstaller + pywebview）

本文档记录 DanmuAI 在 Windows 上打包为可分发 exe 的完整流程，以及实际打包过程中遇到的问题与对应修复。以仓库当前代码为准。

## 发布基线（v0.3.0 冻结）

| 维度 | 说明 |
|------|------|
| **冻结主链路** | `PyInstaller onedir` → **Velopack** → **Cloudflare R2**（`updates.qiaoqiao.buzz`）→ **GitHub Releases 镜像**。脚本顺序：`publish_windows_release.ps1` → `upload_r2_release.ps1` → `upload_github_release.ps1`。 |
| **主真源** | Cloudflare R2；用户主下载 `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe`（Setup.exe 主入口，支持自定义安装路径）；便携版 `https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip`；更新 feed `https://updates.qiaoqiao.buzz/releases/win/stable`。 |
| **镜像** | GitHub Releases **仅作备用**；不得重新定义为主真源。 |
| **应用内更新** | Velopack `UpdateManager` 已打通（v0.3.0 真机验收通过）；Web 控制台启动后主动弹出四渠道更新对话框（W-REL-R2V-010）。 |
| **已废弃** | 旧 `docs/COS_VELOPACK_UPDATE_DESIGN.md` 已删除；**不得**回退 COS、Inno Setup 双栈或 zip 主分发。 |
| **契约与基线** | 发布契约见 [WINDOWS_RELEASE_CONTRACT.md](WINDOWS_RELEASE_CONTRACT.md)；现状基线见 [WINDOWS_RELEASE_BASELINE.md](WINDOWS_RELEASE_BASELINE.md)；v0.3.0 实跑见 [reports/windows-release-final-check.md](../../reports/windows-release-final-check.md)。 |
| **代码签名** | 当前无签名预算，不承诺消除 Windows SmartScreen；见 [WINDOWS_CODE_SIGNING.md](WINDOWS_CODE_SIGNING.md)。 |

---

## 架构简述

```text
DanmuAI.exe（主进程）
├─ PyQt6：弹幕 Overlay、系统托盘、截图
├─ 后台线程：uvicorn + FastAPI → http://127.0.0.1:18765
├─ 子进程：pywebview 桌面壳（WebView2 / edgechromium）
└─ 数据：%APPDATA%\DanmuAI\（配置库，与源码运行共用）

打包资源（PyInstaller datas）：
├─ web/static/          Web 控制台静态页
└─ data/pet/default/    内置桌宠素材（可选）
```

默认 UI 为 **pywebview 桌面窗**，不是系统浏览器。仅当 pywebview 启动失败或用户显式指定时，才回退/改用系统浏览器。

---

## 环境要求

| 项目 | 说明 |
|------|------|
| 操作系统 | Windows 10/11（与产品目标一致） |
| Python | 建议 **3.12**（`README` / CI 约定）；当前仓库曾在 **3.14** 下打包通过，但 PyInstaller 对 3.14 仍有「Pydantic V1 不兼容」等警告 |
| 依赖 | `requirements.txt` + `requirements-dev.txt`（含 `pyinstaller`、`pyinstaller-hooks-contrib`） |
| 应用图标 | `resources/icon.ico`（exe）、`resources/icon.png`（托盘）；缺失时 `build_exe.ps1` 会调用 `scripts/generate_app_icon.py` 生成 |
| 分发依赖 | 最终用户机器需 [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)（Win10/11 多数已预装）；[Microsoft Visual C++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)（PyInstaller 打包的 `.pyd` 依赖 `msvcp140.dll` / `vcruntime140.dll`，Win10/11 多数已预装） |

---

## 相关文件

| 路径 | 作用 |
|------|------|
| `DanmuAI.spec` | PyInstaller 规格：入口、`datas`、`hiddenimports`、`excludes`、`console=False` |
| `scripts/build_exe.ps1` | 一键构建：装依赖、结束占用进程、清空 `dist`、调用 PyInstaller |
| `app/bundle_paths.py` | 开发态 / 打包态资源路径（`sys._MEIPASS`） |
| `app/web_console.py` | uvicorn 线程；含打包环境专用日志与 asyncio/日志修复 |
| `app/webview_shell.py` | pywebview 子进程（Qt 主线程不能被 `webview.start()` 占用） |
| `%APPDATA%\DanmuAI\startup.log` | **仅打包运行**时写入的启动诊断日志；W-STARTUP-001 起含 `[+毫秒] phase` 行（`app/startup_trace.py`）。开发环境可设 `DANMU_STARTUP_TRACE=1` 同步写该文件 |

---

## 打包步骤

### 1. 准备仓库

```powershell
cd E:\test\danmu   # 换成你的仓库根目录
pip install -r requirements.txt -r requirements-dev.txt
```

### 2. 关闭正在运行的 exe

若曾运行过 `dist\DanmuAI\DanmuAI.exe`，必须先结束，否则 PyInstaller 无法删除 `dist\DanmuAI\`（`PermissionError: 拒绝访问`）。

```powershell
Get-Process DanmuAI -ErrorAction SilentlyContinue | Stop-Process -Force
```

`build_exe.ps1` 也会自动尝试结束 `DanmuAI` 进程。

### 3. 执行构建

```powershell
.\scripts\build_exe.ps1
```

等价于：

```powershell
python -m PyInstaller --noconfirm --clean DanmuAI.spec
```

### 4. 产物与分发

| 输出 | 说明 |
|------|------|
| `dist\DanmuAI\DanmuAI.exe` | 主程序 |
| `dist\DanmuAI\_internal\` | 依赖与打包资源（PyInstaller 6 onedir 布局） |
| `build\DanmuAI\warn-DanmuAI.txt` | 构建警告（缺失模块提示，供排查） |

**开发/调试**：可直接运行 `dist\DanmuAI\DanmuAI.exe`（未经过 Velopack 安装器）。

**正式发布**：使用 Velopack 产物（见下文 §Velopack POC 与发布流水线）。

---

## Velopack POC 与发布流水线

### 前置：vpk CLI

Velopack 打包需要 **.NET SDK** 与 **vpk** 全局工具：

```powershell
dotnet tool install -g vpk
```

若 `vpk` 不在 PATH，确保 `%USERPROFILE%\.dotnet\tools` 已加入 PATH。

### POC（W-REL-R2V-003）

```powershell
.\scripts\build_exe.ps1
.\scripts\velopack_poc.ps1 -SkipBuild
```

| POC 输出（`release\velopack-poc\`） | 说明 |
|-------------------------------------|------|
| `PEPETII.DanmuAI-win-Setup.exe` | 一键安装器 |
| `PEPETII.DanmuAI-<version>-full.nupkg` | 全量更新包 |
| `releases.win.json` | Windows 更新 feed |
| `PEPETII.DanmuAI-<version>-win-Portable.zip` | 便携包（镜像用） |

已验证参数：`--packId PEPETII.DanmuAI`、`--mainExe DanmuAI.exe`、版本取自 `app.version.__version__`。

安装目录：`%LocalAppData%\PEPETII.DanmuAI\`（与 `%APPDATA%\DanmuAI\` 用户数据分离）。

### 用户数据与更新/卸载（W-REL-R2V-008）

| 路径 | 职责 |
|------|------|
| `%LocalAppData%\PEPETII.DanmuAI\` | Velopack 程序文件；更新时替换 `current/` |
| `%APPDATA%\DanmuAI\config.db` | 配置库 |
| `%APPDATA%\DanmuAI\.key` | API Key 加密密钥（丢失则密文不可恢复） |
| `%APPDATA%\DanmuAI\startup.log` | 启动诊断 |

**预期**：就地升级、卸载、重装均**不删除** `%APPDATA%\DanmuAI\`。卸载程序仅移除 `%LocalAppData%\PEPETII.DanmuAI\`。

### 应用内主动更新提示（W-REL-R2V-010 / W-UPDATE-METADATA）

Web 控制台在 UI 就绪后（`app.js` → `initAppVersionAndUpdateCheck()`）请求 **`GET /api/update/channels`**（公开、只读），由**后端**从 Supabase `app_updates` 组装 `latest_version` / `release_url` / `message` / `update_available`；前端不再直连 Supabase 拉版本，也不再本地 semver 比较。

| 入口 | 行为 |
|------|------|
| **应用内更新** | Bearer `POST /api/update/check` → `download` → `restart`；**仅 frozen 安装版**可用；**不**经 `/api/update/channels` 访问 Velopack feed |
| **主下载 / 更新弹窗** | `release_url` 来自 Supabase `app_updates`（空时回退 `R2_LATEST_INSTALLER_URL`） |
| **GitHub 更新** | 镜像备用：`https://github.com/PEPETII/danmuai/releases` |
| **夸克 / 百度网盘** | 链接与口令来自 `app/release_channels.py` 静态镜像目录（`GET /api/update/channels` 一并返回） |

**事实源分工**：

| 数据 | 权威来源 |
|------|----------|
| `latest_version`、`release_url`、`message` | Supabase `public.app_updates`（`enabled=true`，`updated_at desc`，limit 1） |
| `current_version` | `app/version.py::__version__` |
| 镜像 URL（GitHub / 夸克 / 百度 / `r2_latest_installer_url`） | `app/release_channels.py`（仅渠道目录；非发布版本事实） |
| Velopack 就地升级 | R2 feed `https://updates.qiaoqiao.buzz/releases/win/stable`（仅 Bearer 写接口触发检查） |

**Supabase 凭证**（后端与前端公告/反馈共用）：

1. 复制 [`web/static/supabase-config.example.js`](../../web/static/supabase-config.example.js) → `web/static/supabase-config.js`，填写 `url` + `anonKey`（gitignore，打包时随 `web/static` 分发）；或
2. 环境变量 `DANMU_SUPABASE_URL`、`DANMU_SUPABASE_ANON_KEY`（优先于 js 文件）。

未配置或远端不可达时，后端将 `latest_version` 对齐本地 `__version__`，避免虚假更新弹窗。详见 [`supabase/README.md`](../../supabase/README.md)。

主下载 latest 别名：`https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe`；便携版：`https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip`。

**去重**：用户点「暂不更新」写入 `dismissedLatestVersion`（localStorage + `config.db`）；关闭弹窗后在**本次运行**内不再重复提示同版本。托盘菜单与侧栏「检查更新」保留为手动入口。

### 正式发布脚本

```powershell
.\scripts\publish_windows_release.ps1    # build + vpk -> release\velopack\
.\scripts\upload_r2_release.ps1           # 主源：R2 自定义域（需环境变量）
.\scripts\upload_github_release.ps1       # 镜像：GitHub Releases
```

契约详见 [WINDOWS_RELEASE_CONTRACT.md](WINDOWS_RELEASE_CONTRACT.md)。

### 正式发布与代码签名（未默认启用）

当前 `publish_windows_release.ps1` **默认不签名**。SmartScreen「未知发布者」风险见 [README.md](../../README.md) 与 [WINDOWS_CODE_SIGNING.md](WINDOWS_CODE_SIGNING.md)。

证书就绪后，签名应在 **`velopack_pack.ps1` / `vpk pack` 过程中**完成（`--signParams` 或 `--azureTrustedSignFile`），而非仅签 PyInstaller 输出或最终 Setup。完整方案见 [reports/windows-code-signing-assessment.md](../../reports/windows-code-signing-assessment.md)。

可选草案（默认关闭）：

```powershell
# 仅当 DANMU_CODE_SIGN=1 且已配置 VPK_SIGN_PARAMS 或 VPK_AZURE_TRUSTED_SIGN_FILE
.\scripts\sign_windows_release.ps1 -VerifyOnly   # 验签 release\velopack\*-Setup.exe
```

### 5. 本地验证

```powershell
.\dist\DanmuAI\DanmuAI.exe
```

检查项：

- 系统托盘图标出现
- pywebview 窗口或（回退时）系统浏览器能打开 `http://127.0.0.1:18765`
- 弹幕 Overlay 正常
- 桌宠内置素材（`data/pet/default/pet.json` + `spritesheet.webp`）已随 `_internal/data/pet/default/` 分发（PET-009，桌宠窗口不再「宠物加载失败」）
- `%APPDATA%\DanmuAI\startup.log` 无新错误栈

可选：无 WebView2 或需排错时使用：

```powershell
.\dist\DanmuAI\DanmuAI.exe --web-browser
```

### 6. 可选：干净 venv 构建（推荐用于发布）

全局 Python 若同时安装 PyQt5、IPython、pytest 等，易导致 PyInstaller 分析冲突。发布建议在干净 venv 中构建：

```powershell
python -m venv .venv-build
.\.venv-build\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
.\scripts\build_exe.ps1
```

`.venv-build` 为本地构建环境，不得提交到 Git（已在 `.gitignore` 中忽略）。

---

## 打包形式说明

当前采用 **onedir**（`COLLECT` + `exclude_binaries=True`），**未**采用 onefile。

| 形式 | 优点 | 缺点 |
|------|------|------|
| onedir（当前） | 启动较快；pywebview 子进程 + 多 DLL 更稳定 | 需整目录分发 |
| onefile | 单文件好看 | 解压慢；多进程/Qt/WebView 更容易出问题 |

`DanmuAI.spec` 中 `console=False`：无黑框控制台，适合桌面应用；但会引发下文「stderr 为 None」问题（已在代码中处理）。

---

## 代码层打包适配（已实现）

### 资源路径 `app/bundle_paths.py`

- 开发：`Path(__file__).parent.parent`（仓库根）
- 打包：`sys._MEIPASS`（PyInstaller 解压目录）
- 使用方：`web/static`、`data/pet/default`、`resources/icon.png`

### Web 控制台 `app/web_console.py`

- 打包态：`loop=asyncio`、`http=h11`，避免 httptools/uvloop 自动探测在 frozen 环境中卡住
- 打包态：Web 服务线程 **`daemon=False`**，避免 Qt 初始化阶段线程被提前回收
- 打包态：Windows 使用 `WindowsSelectorEventLoopPolicy`
- 打包态：`stderr/stdout` 为 `None` 时重定向到 `os.devnull`，并 `log_config=None`（见问题 6）
- 失败诊断：`append_frozen_log()` → `%APPDATA%\DanmuAI\startup.log`

### pywebview `app/webview_shell.py`

- **必须在子进程**中调用 `webview.start()`（子进程主线程跑 GUI；主进程跑 Qt）
- 服务未就绪时**不再**自动打开系统浏览器（避免「拒绝连接」页）
- pywebview 失败时 `_fallback_to_system_browser()` 并写 `startup.log`

### 主程序 `main.py`

- `multiprocessing.freeze_support()`（PyInstaller 多进程）
- 打包态延迟约 **2s** 再 attach pywebview，等待 uvicorn 就绪

---

## 打包时遇到的问题与修复

以下按实际排错时间线整理。

### 问题 1：`datas` 目标路径类型错误

**现象**

```text
TypeError: unsupported operand type(s) for /: 'str' and 'str'
  (str(root / "web" / "static"), "web" / "static"),
```

**原因**：PyInstaller `datas` 元组第二项必须是 **字符串**路径（如 `"web/static"`），不能对两个 `str` 使用 `/`。

**修复**：`DanmuAI.spec` 中改为 `"web/static"`。

---

### 问题 2：PyQt5 与 PyQt6 冲突

**现象**

```text
ERROR: attempting to run hook for 'PyQt5', while hook for 'PyQt6' has already been run!
PyInstaller does not support multiple Qt bindings packages
```

**原因**：构建环境全局 site-packages 中同时存在 PyQt5（常由 IPython 等拉入）与项目使用的 PyQt6。

**修复**：

- `DanmuAI.spec` 的 `EXCLUDES` 排除 `PyQt5`、`PySide2/6`、`IPython`、`pytest`、`jedi` 等
- **不要**在已有 `.spec` 时传 CLI `--exclude-module`（会报 `makespec options not valid when a .spec file is given`）
- 发布构建建议使用干净 venv（见上文）

---

### 问题 3：构建成功误报 / `dist` 目录无法删除

**现象**

- 脚本打印 `Done: ...\DanmuAI.exe`，但 PyInstaller 在 `COLLECT` 阶段已失败
- `PermissionError: [WinError 5] 拒绝访问` 删除 `dist\DanmuAI\_internal\...`

**原因**：旧的 `DanmuAI.exe` 仍在运行，DLL 被锁定；脚本未检查 `$LASTEXITCODE`。

**修复**：`scripts/build_exe.ps1` 增加：

- 构建前 `Stop-Process DanmuAI`
- 构建前 `Remove-Item dist\DanmuAI`
- 检查 `PyInstaller` 退出码与 exe 是否存在

---

### 问题 4：exe 打开后 `127.0.0.1:18765` 拒绝连接

**现象**：pywebview / Edge 显示 `ERR_CONNECTION_REFUSED`。

**原因（阶段一）**：曾将打包版 pywebview 放在 **子线程** 运行；与 uvicorn 多进程/线程交互不当；且服务未就绪时逻辑混乱。

**修复（阶段一）**：改回 **子进程** 启动 pywebview；服务未就绪时不打开浏览器。

**原因（阶段二）**：uvicorn 在 frozen 环境中未成功监听（见问题 5、6）。

---

### 问题 5：误用系统浏览器 / 看起来像 Edge 网页

**现象**：用户以为打开了 Chrome/Edge「浏览器」，而非桌面壳。

**说明**：

| 情况 | 识别方式 |
|------|----------|
| pywebview 正常 | 窗口标题多为 DanmuAI，内嵌 WebView2，地址 `127.0.0.1:18765` |
| 回退系统浏览器 | 独立浏览器进程；`startup.log` 有 `fallback to system browser` |
| 强制浏览器模式 | 环境变量 `DANMU_WEB_LAUNCH=browser` 或 `DanmuAI.exe --web-browser` |

**原因**：pywebview 在**非主线程**调用 `webview.start()` 失败 → 代码回退 `webbrowser.open()`。pywebview 官方要求 `webview.start()` 在主线程执行；Qt 已占用主线程，故采用 **multiprocessing 子进程**。

---

### 问题 6：Web 控制台线程崩溃 — uvicorn 日志配置（已定位根因）

**现象**（`startup.log`）：

```text
DanmuWebConsole thread starting
Web console thread crashed (outer):
  File "uvicorn\logging.py", line 42, in __init__
AttributeError: 'NoneType' object has no attribute 'isatty'
ValueError: Unable to configure formatter 'default'
wait_ready timeout: thread_alive=False bind_failed=True
```

**原因**：`DanmuAI.spec` 使用 `console=False`（`runw.exe`），无控制台时 **`sys.stderr` 为 `None`**。`uvicorn.Config()` 默认配置 logging，`DefaultFormatter` 对 `stderr.isatty()` 调用导致崩溃，18765 从未监听。

**修复**（`app/web_console.py`）：

```python
# 打包或 stderr 为空时
_prepare_stdio_for_uvicorn()   # 将 stderr/stdout 指向 os.devnull
config_kwargs["log_config"] = None
```

修复后日志应出现 `uvicorn Config ready`、`uvicorn serve() starting`，且能访问 `/api/session`。

---

### 问题 8：exe / 托盘没有应用图标

**现象**：`DanmuAI.exe` 为通用 Windows 程序图标；托盘为灰色圆角「D」占位图。

**原因**：仓库原先**未提交** `resources/icon.ico` 与 `resources/icon.png`（仅有 `resources/check.svg`）。`DanmuAI.spec` 仅在文件存在时设置 exe 图标：

```python
icon=str(root / "resources" / "icon.ico") if (root / "resources" / "icon.ico").is_file() else None
```

`app/tray.py` 同样在找不到 `icon.png` 时回退到代码绘制的「D」图标。

**修复**：

```powershell
python scripts/generate_app_icon.py   # 生成 icon.png + icon.ico
.\scripts\build_exe.ps1             # 构建脚本也会在缺失时自动生成
```

重新打包后 exe 文件图标与托盘应一致（暖色圆角 + 白字 D）。

---

### 问题 9：有托盘、无 Web 控制台窗口

**现象**：`DanmuAI.exe` 或 `python main.py` 后托盘图标出现，但看不到设置/控制台窗口；有时托盘「设置」也无反应。

**原因**（叠加，见 [ISSUE-009](templates/已知问题记录/ISSUE-009-有托盘无Web控制台.md)）：

| 子原因 | 表现 |
|--------|------|
| Web 未监听 | `startup_ok=False`，仅日志 / `startup.log` |
| pywebview `hidden` + 未 `loaded` | 子进程有窗但不可见 |
| `ready` 信号过早（W-014 前） | 不回退系统浏览器 |
| 主进程 `open()` 访问 `webview.windows` | 托盘打开设置无反应 |
| 多实例占端口 | 第二个进程托盘在、18765 失败 |

**修复**（W-009～W-014）：`nav_queue` 跨进程导航；`QLocalServer` 单实例；失败时托盘提示 + 浏览器回退。pywebview 握手为 `hidden=True` → `put("created")` → `webview.start()` → `loaded` 时 `show()` + `put("loaded")`；父进程仅在收到 `loaded` 后判定成功，否则（`start()` 失败、子进程退出、loaded 超时）自动 `_fallback_to_system_browser()`（**禁止**在 `start()` 前 `show()`，见 ISSUE-010、ISSUE-011）。

**排查**：

1. `%APPDATA%\DanmuAI\startup.log`（`pywebview start failed` / `fallback to system browser` / `web console not ready`）
2. `netstat -ano | findstr 18765`
3. `DanmuAI.exe --web-browser` 或安装 [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)
4. 浏览器打开 `http://127.0.0.1:18765`

---

### 问题 10：Web 控制台空白、版本号不显示、按钮无响应

**现象**：托盘图标与右键菜单正常，但桌面壳或浏览器中的 Web 控制台为空白页；版本号缺失，所有按钮点不动。浏览器 DevTools 控制台报错：

```text
Failed to load module script: Expected a JavaScript-or-Wasm module script
but the server responded with a MIME type of "text/plain".
```

**原因**：部分 Windows 机器上 `HKCR\.js\Content Type` 被第三方软件改成 `text/plain`。Python `mimetypes` 读取该注册表后，Uvicorn 对 `/static/*.js` 返回错误 `Content-Type`，浏览器拒绝执行 `<script type="module">`。

**修复**（W-WEB-MIME-001，0.3.2+）：`app/web_console_runtime.py` 挂载 `StaticFiles` 前调用 `ensure_web_static_mime_types()`，强制 `.js` → `application/javascript`、`.css` → `text/css`，不依赖注册表。

**用户侧临时修复**（旧版本或未升级时）：

```bat
reg add HKCU\Software\Classes\.js /v "Content Type" /t REG_SZ /d "application/javascript" /f
```

重启 DanmuAI 后验证 DevTools → Network → `/static/app.js` 的 `Content-Type` 含 `javascript`。

---

### 问题 7：`startup.log` 仅「未就绪」无栈

**现象**：只有 `Web 控制台未在 http://127.0.0.1:18765 就绪`，没有崩溃详情。

**原因**：早期异常发生在 `uvicorn.Config` 之前或未写入 frozen 日志；或线程静默退出。

**修复**：`_run` 全段 try/except、`append_frozen_log` 覆盖 Config/serve/超时；`wait_ready` 超时记录 `thread_alive`、`bind_failed`。

---

## 运行时诊断

### 日志位置

```text
%APPDATA%\DanmuAI\startup.log
```

示例（**正常**）：

```text
DanmuWebConsole thread starting
uvicorn Config ready host=127.0.0.1 port=18765 frozen=True static=...
uvicorn serve() starting
```

### 端口占用

```powershell
netstat -ano | findstr 18765
```

若被占用，结束对应 PID 或关闭残留 `DanmuAI.exe`。默认端口定义在 `app/web_console.py` 的 `DEFAULT_PORT = 18765`。

### 构建警告

```text
build\DanmuAI\warn-DanmuAI.txt
```

「missing module」多数为可选模块；若运行时报 `ModuleNotFoundError`，将模块名加入 `DanmuAI.spec` 的 `hiddenimports`。

---

## 最终用户说明（可写入 Release）

1. 解压 **整个** `DanmuAI` 文件夹后运行 `DanmuAI.exe`。
2. 首次运行可在 Web「助手设置」配置 API；数据保存在 `%APPDATA%\DanmuAI\`。
3. 需 **WebView2 Runtime**；若无，安装 Runtime 或使用 `DanmuAI.exe --web-browser`。
4. 需 **Microsoft Visual C++ Redistributable**（Win10/11 多数已预装）；若启动报 `msvcp140.dll` 缺失，安装 [VC++ Redist](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) x64；
5. 全局快捷键在部分环境需**管理员身份**运行。
6. 故障时提供 `%APPDATA%\DanmuAI\startup.log`。

---

## 发布前检查（摘要）

完整清单见 [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)。打包相关：

- [ ] 干净 venv 或已排除 PyQt5 的环境构建成功
- [ ] 未运行中的 exe 不锁定 `dist`
- [ ] 无 Python 机器上 exe 能打开控制台且 Overlay 正常
- [ ] `startup.log` 无新崩溃栈
- [ ] `release\velopack\` 含 Setup、nupkg、`releases.win.json`（见 [WINDOWS_RELEASE_CONTRACT.md](WINDOWS_RELEASE_CONTRACT.md)）
- [ ] R2 契约路径已上传；`downloads/DanmuAI-Setup.exe`（主入口）、`downloads/PEPETII.DanmuAI-win-Portable.zip`（便携版）可公网访问
- [ ] Portable.zip 仅作 GitHub 镜像附件，非普通用户主入口

---

## 参考

- [docs/WEB_CONSOLE.md](WEB_CONSOLE.md) — Web API 与控制台
- [docs/core/ARCHITECTURE.md](../core/ARCHITECTURE.md) — 线程模型
- [AGENTS.md](../../AGENTS.md) — 开发约定
- [pywebview FAQ – main thread](https://pywebview.flowrl.com/guide/faq)
- [PyInstaller spec files](https://pyinstaller.org/en/stable/spec-files.html)

## Delta release notes

- `publish_windows_release.ps1` now keeps historical `release\velopack\*.nupkg` files instead of deleting the whole directory before every pack.
- When the local release directory does not contain a previous full package, the script bootstraps from `https://updates.qiaoqiao.buzz/releases/win/stable` so `vpk pack` can still generate `*-delta.nupkg`.
- `upload_r2_release.ps1` and `upload_github_release.ps1` upload both `*-full.nupkg` and `*-delta.nupkg`; `releases.win.json` remains the single feed contract for `UpdateManager`.

## Install path and uninstall notes

- First install custom path: Velopack officially supports `Setup.exe --installto <DIR>`.
- The app runtime does not hardcode `%LocalAppData%\PEPETII.DanmuAI\`; update location is still resolved by Velopack, so changing the install root does not require repository-side path keys.
- Uninstall entry remains the Windows ARP entry backed by Velopack. The app tray now exposes the same uninstall path explicitly.
- Default uninstall keeps `%APPDATA%\DanmuAI\`. Optional data deletion is only performed after user opt-in plus a second confirmation, then handled in `on_before_uninstall_fast_callback`.
