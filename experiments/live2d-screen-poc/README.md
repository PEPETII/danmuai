# Live2D 隔离式桌面显示 POC

> 工单：`W-LIVE2D-SCREEN-POC-PLAN-001`  
> **仅实验目录**。不接入 DanmuAI、`app/pet/`、Web 控制台或浏览器显示。

## 目标

在 Windows 上用**原生透明无边框窗口**加载本地 `.model3.json`，验证置顶、拖动、缩放、透明度、鼠标穿透、动作/表情触发。

## 渲染后端（已选用）

| 项 | 值 |
|---|---|
| 绑定 | [`live2d-py`](https://github.com/EasyLive2D/live2d-py) / PyPI `live2d-py` |
| 版本（本机验证） | `0.7.0.4` |
| 模块 | `live2d.v3`（Cubism Native C 扩展，**非** WebView） |
| 窗口 | PyQt6 `QOpenGLWidget`（与 DanmuAI 同系 GUI，但独立进程） |
| OpenGL | PyOpenGL |
| 绑定许可证 | **MIT**（`live2d-py` LICENSE） |
| Cubism Core | 预编译 wheel 内嵌；源码构建需从 [Live2D 官网](https://www.live2d.com/en/sdk/download/native/) 自行下载 SDK |
| 随 DanmuAI 分发风险 | **高 / 需法务确认**：Live2D Cubism SDK 有独立商业许可；MIT 绑定 ≠ 可免费再分发 Core；BOOTH 模型通常禁止二次分发与商业变现 |

**禁止**：用浏览器 / pywebview / 控制台页面当角色载体。

## 安装（仅 POC）

```powershell
cd experiments\live2d-screen-poc
pip install -r requirements-poc.txt
# 若尚未安装 PyQt6（DanmuAI 环境通常已有）：
pip install "PyQt6>=6.6,<7"
```

**不要**改仓库根 `requirements.txt`。

## 运行

```powershell
# 校验模型路径与依赖文件（不弹窗）
.\run_poc.ps1 -Model "E:\test\PB\Poblanc.model3.json" -ValidateOnly

# 显示窗口；约 12 秒后自动关闭（自动化冒烟）
.\run_poc.ps1 -Model "E:\test\PB\Poblanc.model3.json" -DemoSeconds 12

# 或
python -m src.main --model "E:\test\PB\Poblanc.model3.json" --demo-seconds 12

# 本地配置（勿提交真实路径/密钥）
copy config.example.json config.local.json
# 编辑 model_path 后：
.\run_poc.ps1 -Config ".\config.local.json"
```

模型路径**必须**由 CLI / 本地配置传入；业务代码不写死 `E:\test\PB` 或模型名。

## 热键

| 键 | 作用 |
|---|---|
| 左键拖动 | 移动窗口 |
| 滚轮 / Ctrl+ / Ctrl- | 缩放 |
| Ctrl+[ / Ctrl+] | 透明度 |
| Ctrl+T | 切换鼠标穿透 |
| **Ctrl+Shift+F8** | 穿透开启后恢复可点（全局轮询） |
| Ctrl+M / Ctrl+E | 触发动作 / 表情（从模型运行时枚举） |
| Esc / Ctrl+Q | 退出 |

## 本机测试模型依赖（不入库）

以 `Poblanc.model3.json` 为例（路径仅文档说明）：

- `Poblanc.moc3`
- `Poblanc.8192/texture_00.png`, `texture_01.png`
- `Poblanc.physics3.json`
- `Poblanc.cdi3.json`
- **注意**：该 model3 **未声明** `Motions` / `Expressions`；POC 会对参数做 soft-idle，并尝试 `StartRandomMotion` / `SetRandomExpression` / 嘴部参数作为可见替代，并在报告中标明。

模型与纹理**禁止**复制进 Git。

## 目录

```text
experiments/live2d-screen-poc/
├─ README.md
├─ requirements-poc.txt
├─ config.example.json
├─ run_poc.ps1 / run_poc.bat
├─ src/          # POC 源码
├─ docs/         # 计划、验收、执行报告
└─ artifacts/    # 本地日志（可不提交）
```

## 回滚

删除本目录即可；不修改 `app/` / `main.py` / `web/`。

## 验收报告

见 [`docs/POC执行报告.md`](docs/POC执行报告.md)。
