# DanmuAI Windows 打包与本地发布

本文是当前仓库的 Windows 打包说明。适用版本由 `app/version.py` 提供；本次本地发布目标为 `0.4.1`。

本地正式产物链路固定为：

```text
当前源码 + release lock → PyInstaller onedir → dist\DanmuAI\ → Velopack → release\velopack\
```

本地打包不等于线上发布。本任务范围内不执行 R2/GitHub 上传、不创建 Release、不打 tag、不推送。

## 1. 版本与工具

版本唯一来源是 `app/version.py:__version__`。`scripts/version_parse.ps1`、`publish_windows_release.ps1` 和 `velopack_pack.ps1` 都从构建 Python 导入该值；不要在脚本、spec 或产物名中另行硬编码版本。

建议在仓库根目录的 PowerShell 中执行：

```powershell
Get-ChildItem .venv-build\Scripts\python.exe, .venv-build-312\Scripts\python.exe -ErrorAction SilentlyContinue
dotnet --version
vpk --version
```

当前构建脚本按以下顺序选择 Python：可用的 `.venv-build`、可用的 `.venv-build-312`、`DANMU_BUILD_PYTHON`，最后才尝试系统 launcher。正式构建应使用 Python 3.12 x64，并设置 `DANMU_BUILD_USE_RELEASE_LOCK=1`。

发布锁 `requirements-release-win-lock.txt` 是由 `requirements.txt`、`requirements-dev.txt` 和 Windows 构建工具组成的精确版本集合。修改运行时依赖后必须检查：直接依赖是否全部进入锁文件、锁文件是否可安装、`pip check` 是否通过；不要仅凭文件头部日期判断锁仍然有效。

## 2. 打包覆盖范围

`DanmuAI.spec` 是唯一的 PyInstaller 入口，当前覆盖以下内容：

- `web/static/` 全部静态资源，包括 HTML、CSS、JS、locale、JSON、预览图和截图；任何含 `supabase-config` 的文件默认排除，只保留 `supabase-config.example.js` 与 `supabase-client.js`。
- `data/personae_builtin.json`、内置桌宠 `data/pet/default/` 和 `resources/icon.*`。
- 当前 `app.application`、`app.config_store`、`app.knowledge`、`app.live2d`、`app.meme_barrage`、`app.pet`、`app.providers`、`app.tts`、`app.virtual_host`、`app.web_api` 包的源码子模块。这样覆盖了启动后才装配的知识库、虚拟主播、Live2D、TTS、provider 和 Web API 路由。
- `live2d-py` 的 `live2d` 子模块、包内 `.pyd/.dll` 和 shader 数据；`OpenGL.GL` 核心模块与 platform 适配模块。可选的 Tk/Togl、GLES、GLUT 全树不收集；Windows 系统的 `opengl32.dll` 仍由系统提供，Qt6 的 OpenGL/QtOpenGLWidgets 二进制由 PyInstaller Qt hooks 收集。
- Velopack 的 `velopack.pyd`，以及 `sounddevice`、NumPy、PyQt6、pywebview、WebView2 检测模块等由依赖和 spec 共同收集。

外部 Live2D 模型不是发布包内置资源。用户通过设置页导入后，应用会复制到 `%APPDATA%\DanmuAI\live2d-models`（以当前 `app.live2d.model_storage` 实现为准）；打包验收应使用一个完整的 `.model3.json` 模型目录，而不是把用户模型写入 dist。

审计命令：

```powershell
\.venv-build-312\Scripts\python.exe scripts\audit_hiddenimports.py
```

该审计同时检查延迟 import 和 spec 中的 `collect_submodules(...)` 包覆盖；不能只看旧的 hiddenimports 字符串清单。

## 3. 先构建 PyInstaller onedir

正式构建前确认没有正在运行的 `DanmuAI.exe`、pywebview 子进程或占用 dist 文件的资源管理器窗口。脚本只清理 `dist\DanmuAI`，不会重置仓库或删除用户配置。

```powershell
$env:DANMU_BUILD_USE_RELEASE_LOCK = "1"
\.\scripts\build_exe.ps1
```

成功条件：

- `dist\DanmuAI\DanmuAI.exe` 存在；
- `dist\DanmuAI\_internal\` 存在；
- `dist\DanmuAI\web\static\index.html`、关键 locale 和静态预览资源存在；
- `dist\DanmuAI\data\personae_builtin.json`、`dist\DanmuAI\data\pet\default\pet.json`、`spritesheet.webp` 存在；
- `web/static` 中没有被禁止的 Supabase credential config；
- `build\DanmuAI\warn-DanmuAI.txt` 中没有本次运行路径所需的未解决模块。POSIX-only optional imports 可以保留，但要逐项判断，不能把 warn 文件为空当作要求。

当前构建仍会在 warn 文件中报告 `app.window_capture`：`app.snipper` 保留了一个延迟导入，但仓库中没有对应模块；当前设置页使用屏幕/区域捕获，不暴露该旧窗口捕获模式，因此本次不把不存在的模块伪装成 hidden import。若重新启用窗口捕获模式，必须先修复源码调用链并增加运行验收。

## 4. dist EXE 本地冒烟

先用浏览器模式验证本地 Web 服务，避免把 WebView2 冷启动问题误判成服务或静态资源缺失：

```powershell
Start-Process -FilePath (Resolve-Path .\dist\DanmuAI\DanmuAI.exe) -ArgumentList "--web-browser"
```

随后检查 `%APPDATA%\DanmuAI\startup.log` 和本地控制台，至少覆盖：

1. Web 控制台首页、设置页、模型/provider/TTS 配置页、Live2D/虚拟主播页能加载；
2. `/api/status`、`/api/version`、`/api/live2d/model`、虚拟主播和 TTS 相关接口返回，不出现静态 404 或 frozen import error；
3. 弹幕主链路能启动；没有 API key 时只验证配置/错误路径，不伪造真实 provider 成功；
4. 麦克风探针、TTS 播放和音频错误路径可观察。真实麦克风设备与真实 TTS provider 必须单独标记为已验证或未验证；
5. 导入完整 Live2D 模型后，模型窗口可创建、OpenGL 帧可显示、动作/表情/参数反馈可用；
6. 虚拟主播运行时能读取独立配置并连接 Live2D feedback；
7. 桌宠资源和显示/隐藏路径可用；
8. 通过托盘“退出应用”后 `DanmuAI.exe`、`Update.exe`、pywebview 子进程均结束；仅关闭主窗口可能按当前产品语义隐藏到托盘，不能把它当作进程退出证据。再次启动能正常建立单实例和 Web 服务。

`--web-browser` 的启动成功只证明服务和浏览器入口，不代表 pywebview 窗口、Live2D GPU、麦克风设备或 TTS provider 已通过；这些必须有实际界面/设备证据。

## 5. Velopack 本地打包

确认 dist EXE 正常后：

```powershell
$env:DANMU_BUILD_USE_RELEASE_LOCK = "1"
\.\scripts\publish_windows_release.ps1
```

脚本内部依次运行 `build_exe.ps1` 和 `velopack_pack.ps1`。它只清理当前目标版本和 MSI 文件，保留已有旧版 full nupkg 作为 delta 基线；当本地没有旧 full 包时，默认从 stable feed 下载历史包到本地。完全不需要 delta 时可使用 `-SkipDeltaBootstrap`，但这会改变增量产物预期。

代码签名默认关闭。只有明确设置 `DANMU_CODE_SIGN=1` 且提供 `VPK_AZURE_TRUSTED_SIGN_FILE` 或 `VPK_SIGN_PARAMS` 时才启用；凭据只能来自环境变量，不能写入仓库或产物。

本地输出目录 `release\velopack\` 至少应包含：

| 产物 | 用途 |
|---|---|
| `PEPETII.DanmuAI-win-Setup.exe` | Velopack 原始 Setup 输出 |
| `PEPETII.DanmuAI-0.4.1-Setup.exe` | 当前版本化 Setup |
| `PEPETII.DanmuAI-0.4.1-full.nupkg` | full 更新包 |
| `PEPETII.DanmuAI-0.4.1-delta.nupkg` | 有上一版 full 元数据时的 delta 包 |
| `PEPETII.DanmuAI-win-Portable.zip` | PyInstaller onedir 便携包，根目录含 `DanmuAI.exe` |
| `releases.win.json` | Velopack feed，至少含当前 full，若生成 delta 还应含 delta |
| `VERSION.txt` | 版本、时间、Git SHA 和本地打包说明 |
| `SHA256SUMS.txt` | 本地产物 SHA256 清单，不是代码签名 |

MSI 不属于当前链路；`*.msi` 出现即失败。`velopack_poc.ps1` 只用于隔离 POC，不是正式 0.4.1 发布入口。

`velopack_pack.ps1` 在生成 Portable ZIP 前会对 `dist` 便携包源目录和 `release\velopack\` 递归执行 `Unblock-File`，并检查输出目录及重新解压的 Portable ZIP 不含 `Zone.Identifier`。`verify_windows_release_artifacts.ps1` 会重复该检查；任一依赖 DLL（包括 `Python.Runtime.dll`、`Microsoft.Web.WebView2.Core.dll`）或其他文件残留 Mark-of-the-Web 时，构建/校验失败。

该检查只保证本地产物没有 Mark-of-the-Web。Windows 可能在用户下载 ZIP 后给 ZIP 重新添加该标记，并在解压时传播到文件；这属于下载渠道/Windows 信任策略，不能由 ZIP 内部文件元数据预先消除。

## 6. 产物校验

```powershell
\.\scripts\verify_windows_release_artifacts.ps1 -ReleaseDir .\release\velopack -Version 0.4.1
\.\scripts\write_release_hash_manifest.ps1 -ReleaseDir .\release\velopack -Version 0.4.1 -VerifyOnly
```

校验脚本检查 Setup、full、delta/feed 一致性、Portable ZIP 根目录布局、`_internal`、当前版本和 MSI 排除。`SHA256SUMS.txt` 的校验只能证明本地产物在生成后未被修改，不能证明 R2 或 GitHub 上的文件已更新。

## 7. 线上发布边界

以下命令本地打包任务禁止执行：

```powershell
\.\scripts\upload_r2_release.ps1
\.\scripts\upload_github_release.ps1
```

只有单独获得正式上传授权后，才按 `PyInstaller → Velopack → inspect → R2 → GitHub mirror → online GET verification` 顺序执行。R2 是主更新源，GitHub 仅是镜像；本地 `release\velopack\` ready 不代表线上下载别名或 update feed 已切换。

## 8. 已废弃/修正的旧流程

- 不再使用 MSI 作为主入口；当前入口是 Velopack `Setup.exe`，便携入口是 PyInstaller onedir ZIP。
- 不再使用旧的 `DanmuAI-windows-x64.zip` 作为主分发物。
- 不再用旧 hiddenimports 列表推断完整性；新增包必须由源码扫描和 spec 包覆盖共同确认。
- 不再把 `docs/operations/CHANGELOG.md` 写入 `VERSION.txt`，因为仓库没有该文件；当前产物记录引用本打包指南。
- 不把外部 Live2D 模型、用户配置、API key、Supabase credential config 或本地数据库打入发布包。
- 不把“PyInstaller 构建成功”当作功能验收；Web、WebView2、音频、Live2D、虚拟主播和退出/重启必须分别验证。
