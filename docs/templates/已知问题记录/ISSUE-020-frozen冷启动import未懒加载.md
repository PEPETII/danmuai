# 已知问题记录

## 问题 ID

ISSUE-020

## 发现时间

2026-05-30（W-STARTUP-001/002）

## 发现场景

exe 冷启动优化埋点实施后；若 `startup.log` 中 `danmu_app.init.begin` 之前或 `uvicorn.import.done` 阶段耗时仍很长。

## 影响范围

- 打包版首次/冷启动至托盘或 Web 控制台可见的等待时间
- 不影响运行中主链路截图与 AI 调度

## 严重程度

低～中（视实测 import 占比而定）

## 是否阻塞当前工单

否（W-STARTUP-001/002 仅埋点 + 主线程短等待，未做减包）

## 复现步骤

1. 构建 `dist\DanmuAI\DanmuAI.exe`  
2. 冷启动并查看 `%APPDATA%\DanmuAI\startup.log`  
3. 若 `[+Xms] uvicorn.import.done` 或 `main.begin` 前隐含 import 时间 X 仍 >10s，则属本问题

## 期望行为

frozen 启动仅加载启动必需模块；FastAPI/uvicorn 在 Web 线程内延迟 import 且 hiddenimports 最小化。

## 实际行为

`main.py` 顶层 import 较多；`DanmuAI.spec` 使用 `collect_submodules("uvicorn")` 扩大打包体积与 import 时间。

## 相关文件

- `main.py`
- `DanmuAI.spec`
- `app/web_console.py`

## 临时处理方式

使用 W-STARTUP-002 后的短 `wait_ready` + 非阻塞 pywebview；`--web-browser` 可绕过 WebView2 子进程。

## 建议后续工单

W-STARTUP-003：懒加载 Web 栈 import + 收紧 PyInstaller hiddenimports（需单独验收打包体积与 ISSUE-009 回归）。

## 状态

待处理
