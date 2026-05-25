# Windows exe 打包指南（PyInstaller + pywebview）

本文档记录 DanmuAI 在 Windows 上打包为可分发 exe 的完整流程，以及实际打包过程中遇到的问题与对应修复。以仓库当前代码为准。

## 架构简述

```text
DanmuAI.exe（主进程）
├─ PyQt6：弹幕 Overlay、系统托盘、截图
├─ 后台线程：uvicorn + FastAPI → http://127.0.0.1:18765
├─ 子进程：pywebview 桌面壳（WebView2 / edgechromium）
└─ 数据：%APPDATA%\DanmuAI\（配置库，与源码运行共用）

打包资源（PyInstaller datas）：
├─ web/static/          Web 控制台静态页
└─ data/danmu_pool_zh.json
```

默认 UI 为 **pywebview 桌面窗**，不是系统浏览器。仅当 pywebview 启动失败或用户显式指定时，才回退/改用系统浏览器。

---

## 环境要求

| 项目 | 说明 |
|------|------|
| 操作系统 | Windows 10/11（与产品目标一致） |
| Python | 建议 **3.12**（`README` / CI 约定）；当前仓库曾在 **3.14** 下打包通过，但 PyInstaller 对 3.14 仍有「Pydantic V1 不兼容」等警告 |
| 依赖 | `requirements.txt` + `requirements-dev.txt`（含 `pyinstaller`、`pyinstaller-hooks-contrib`） |
| 数据文件 | 构建前需存在 `data/danmu_pool_zh.json` |
| 应用图标 | `resources/icon.ico`（exe）、`resources/icon.png`（托盘）；缺失时 `build_exe.ps1` 会调用 `scripts/generate_app_icon.py` 生成 |
| 分发依赖 | 最终用户机器需 [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)（Win10/11 多数已预装） |

---

## 相关文件

| 路径 | 作用 |
|------|------|
| `DanmuAI.spec` | PyInstaller 规格：入口、`datas`、`hiddenimports`、`excludes`、`console=False` |
| `scripts/build_exe.ps1` | 一键构建：装依赖、结束占用进程、清空 `dist`、调用 PyInstaller |
| `app/bundle_paths.py` | 开发态 / 打包态资源路径（`sys._MEIPASS`） |
| `app/web_console.py` | uvicorn 线程；含打包环境专用日志与 asyncio/日志修复 |
| `app/webview_shell.py` | pywebview 子进程（Qt 主线程不能被 `webview.start()` 占用） |
| `%APPDATA%\DanmuAI\startup.log` | **仅打包运行**时写入的启动诊断日志 |

---

## 打包步骤

### 1. 准备仓库

```powershell
cd E:\test\danmu   # 换成你的仓库根目录
pip install -r requirements.txt -r requirements-dev.txt
```

确认存在 `data\danmu_pool_zh.json`（可由 `scripts/extract_danmu_pool.py` 生成）。

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

**分发时必须提供整个 `dist\DanmuAI\` 目录**（zip 或安装包），不能只拷贝单个 `DanmuAI.exe`。

### 5. 本地验证

```powershell
.\dist\DanmuAI\DanmuAI.exe
```

检查项：

- 系统托盘图标出现
- pywebview 窗口或（回退时）系统浏览器能打开 `http://127.0.0.1:18765`
- 弹幕 Overlay 正常
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
- 使用方：`web/static`、`data/danmu_pool_zh.json`、`resources/icon.png`

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
4. 全局快捷键在部分环境需**管理员身份**运行。
5. 故障时提供 `%APPDATA%\DanmuAI\startup.log`。

---

## 发布前检查（摘要）

完整清单见 [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)。打包相关：

- [ ] 干净 venv 或已排除 PyQt5 的环境构建成功
- [ ] 未运行中的 exe 不锁定 `dist`
- [ ] 无 Python 机器上 exe 能打开控制台且 Overlay 正常
- [ ] `startup.log` 无新崩溃栈
- [ ] 分发 zip 含完整 `dist\DanmuAI\` 目录

---

## 参考

- [docs/WEB_CONSOLE.md](WEB_CONSOLE.md) — Web API 与控制台
- [docs/ARCHITECTURE.md](ARCHITECTURE.md) — 线程模型
- [AGENTS.md](../AGENTS.md) — 开发约定
- [pywebview FAQ — main thread](https://pywebview.flowrl.com/guide/faq)
- [PyInstaller spec files](https://pyinstaller.org/en/stable/spec-files.html)
