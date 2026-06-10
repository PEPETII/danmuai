# DanmuAI 完整发布与更新方案设计

> **状态:** 设计阶段，尚未实现代码  
> **版本:** 基于 DanmuAI 0.3.0 (PyInstaller onedir)  
> **范围:** 覆盖安装器、下载入口、数据位置、启动体验、COS + Velopack 增量更新、Release 规范

---

## 目录

1. [总体架构](#1-总体架构)
2. [发布形态改造（安装器设计）](#2-发布形态改造安装器设计)
3. [下载入口改造（README 重构）](#3-下载入口改造readme-重构)
4. [数据保存位置说明](#4-数据保存位置说明)
5. [GitHub Releases 发布规范](#5-github-releases-发布规范)
6. [COS 分阶段规划](#6-cos-分阶段规划)
7. [启动体验改造](#7-启动体验改造)
8. [Velopack 增量更新设计](#8-velopack-增量更新设计)
9. [本地数据保护](#9-本地数据保护)
10. [打包与发布流水线](#10-打包与发布流水线)
11. [涉及文件清单](#11-涉及文件清单)
12. [验收标准](#12-验收标准)
13. [风险点](#13-风险点)
14. [不建议方案](#14-不建议方案)

---

## 1. 总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    用 户 端                                       │
│                                                                 │
│  ┌──────────────────────┐                                       │
│  │ DanmuAI-Setup.exe    │  ← 用户只下载这一个文件                │
│  │ (Inno Setup 安装器)  │                                       │
│  └──────────┬───────────┘                                       │
│             │ 安装                                              │
│             ▼                                                   │
│  ┌──────────────────────────────────────┐                       │
│  │ C:\Program Files\DanmuAI\            │  ← 安装目录            │
│  │  ├ DanmuAI.exe                       │  ← onedir 入口        │
│  │  ├ _internal\                        │  ← PyInstaller 依赖   │
│  │  │   ├ python312.dll                 │                       │
│  │  │   └ ... (PyQt6, uvicorn, etc.)    │                       │
│  │  ├ web\static\                       │  ← Web 控制台前端     │
│  │  ├ data\                             │  ← 内置数据           │
│  │  ├ velopack\                         │  ← 更新运行时分（P2） │
│  │  └ resources\                        │  ← 图标               │
│  └──────────────────────────────────────┘                       │
│                                                                 │
│  ┌──────────────────────────────────────┐                       │
│  │ %APPDATA%/DanmuAI/                   │  ← 用户数据（永不被更新│
│  │  ├ config.db                         │     覆盖）            │
│  │  ├ .key                              │                       │
│  │  └ startup.log                       │                       │
│  └──────────────────────────────────────┘                       │
│                                                                 │
│  桌面快捷方式 → DanmuAI.exe                                      │
│  开始菜单 → DanmuAI → DanmuAI.exe / 卸载 DanmuAI                 │
└─────────────────────────────────────────────────────────────────┘

                               │
                               │ 下载安装器 / 检查更新
                               ▼

┌─────────────────────────────────────────────────────────────────┐
│                    发 布 源                                       │
│                                                                 │
│  Phase 1（当前）:                                               │
│  ┌──────────────────────────┐                                   │
│  │ GitHub Releases          │  ← 主发布源                       │
│  │  ├ DanmuAI-Setup.exe     │  ← 普通用户下载入口               │
│  │  └ DanmuAI-Portable.zip  │  ← 可选（高级用户）               │
│  └──────────────────────────┘                                   │
│                                                                 │
│  Phase 2（国内加速）:                                            │
│  ┌──────────────────────────┐                                   │
│  │ COS (腾讯云)             │  ← 国内下载镜像                    │
│  │  └ DanmuAI-Setup.exe     │  ← 镜像 GitHub Releases          │
│  └──────────────────────────┘                                   │
│                                                                 │
│  Phase 3（自动更新）:                                            │
│  ┌──────────────────────────┐                                   │
│  │ COS (腾讯云)             │  ← 自动更新源                      │
│  │  ├ releases.win.json     │  ← Velopack 版本清单             │
│  │  ├ *.nupkg (full/delta)  │  ← Velopack 更新包               │
│  │  └ DanmuAI-Setup.exe     │  ← 完整安装器（兜底）             │
│  └──────────────────────────┘                                   │
│                                                                 │
│  GitHub Releases 在所有阶段保留为备用下载源                       │
└─────────────────────────────────────────────────────────────────┘
```

### 设计原则

| 原则 | 说明 |
|------|------|
| **用户只需一个 exe** | `DanmuAI-Setup.exe`，双击安装，不要源码、不要 Python、不要 CLI |
| **onedir 不动** | PyInstaller 打包方式不变，`DanmuAI.spec` 保持 onedir |
| **安装与更新分开** | 安装器解决首次安装；Velopack 解决后续更新 |
| **用户数据不可侵犯** | 安装目录与 `%APPDATA%` 物理隔离，更新只动安装目录 |
| **先 GitHub 后 COS** | Phase 1 只用 GitHub Releases，不依赖 COS；COS 后续补上 |
| **开发者路径保留** | `python main.py` 和 `build_exe.ps1` 不受影响 |

---

## 2. 发布形态改造（安装器设计）

### 2.1 工具选型

使用 **Inno Setup**，理由：
- 开源免费，Windows 生态标准
- 原生支持桌面快捷方式、开始菜单、卸载程序
- `.iss` 脚本即代码，可版本控制
- 支持中英文界面
- 中文安装向导支持好
- GitHub Actions `windows-latest` 可通过 `choco install innosetup` 安装

备选工具对比：

| 工具 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| Inno Setup | 免费、脚本化、轻量、中文好 | 需 Pascal Script 写自定义逻辑 | **推荐** |
| NSIS | 免费、插件生态大 | 脚本语法晦涩、中文支持弱 | 备选 |
| WiX Toolset | MSI 标准、企业级 | XML 配置复杂、学习曲线陡 | 不推荐 |
| Advanced Installer | GUI 友好 | 收费 | 不推荐 |

### 2.2 安装器行为设计

```
用户双击 DanmuAI-Setup.exe
    │
    ▼
┌─────────────────────────────────┐
│ 1. 欢迎页                       │
│    "欢迎使用 DanmuAI 安装向导"   │
├─────────────────────────────────┤
│ 2. 许可协议                     │
│    GPL-3.0-or-later             │
├─────────────────────────────────┤
│ 3. 安装目录选择                 │
│    默认: C:\Program Files\DanmuAI│
│    允许自定义                    │
├─────────────────────────────────┤
│ 4. 快捷方式选项                 │
│    ☑ 桌面快捷方式（默认勾选）    │
│    ☑ 开始菜单快捷方式（默认勾选）│
├─────────────────────────────────┤
│ 5. 准备安装                     │
│    显示摘要，用户确认            │
├─────────────────────────────────┤
│ 6. 安装进度                     │
│    解压 dist/DanmuAI/ 全部内容   │
│    创建快捷方式                  │
│    写入卸载信息                  │
├─────────────────────────────────┤
│ 7. 完成页                       │
│    ☑ 运行 DanmuAI（默认勾选）    │
└─────────────────────────────────┘
```

### 2.3 安装器包含内容

```
DanmuAI-Setup.exe 内部结构:
├ DanmuAI.exe              ← PyInstaller onedir 入口
├ _internal\               ← 完整的 PyInstaller 运行时
│   ├ python312.dll
│   ├ *.pyd / *.dll
│   └ ...
├ web\static\              ← Web 控制台前端
├ data\                    ← 内置人格、桌宠素材
├ resources\               ← 图标
└ velopack\                ← 更新运行时（Phase 3 添加）
    └ Update.exe
```

**关键约束:**
- 安装器不得创建或修改 `%APPDATA%/DanmuAI/`
- 安装器不得写入注册表（除了卸载信息路径——Inno Setup 必需）
- 安装器不得要求管理员权限（安装到 `%LOCALAPPDATA%\Programs\DanmuAI` 作为默认）

### 2.4 默认安装路径讨论

| 路径 | 是否需要管理员 | 优点 | 缺点 |
|------|:---:|------|------|
| `C:\Program Files\DanmuAI` | 是 | 传统 Windows 惯例 | 需要 UAC 弹窗 |
| `%LOCALAPPDATA%\Programs\DanmuAI` | 否 | 无需管理员，静默安装 | 非传统位置 |
| `%USERPROFILE%\DanmuAI` | 否 | 无需管理员 | 太不规范 |

**建议:** 两种都支持。默认 `%LOCALAPPDATA%\Programs\DanmuAI`（无需 UAC），用户可选 `C:\Program Files\DanmuAI`（需 UAC）。

---

## 3. 下载入口改造（README 重构）

### 3.1 README 第一屏布局（设计稿）

```markdown
# DanmuAI

> 为直播主播提供轻量、隐私友好的 AI 弹幕助手

## 📥 下载

| [**下载 Windows 安装版**](https://github.com/PEPETII/danmuai/releases/latest/download/DanmuAI-Setup.exe) |
|---|
| 支持 Windows 10/11 · 无需安装 Python · 双击即装 |

> ⚠️ **普通用户请注意：**
> - 请下载上面的 **DanmuAI-Setup.exe** 安装版
> - **不要**下载页面底部的 `Source code.zip`（那是源代码，不是程序）
> - **不需要**安装 Python
> - **不需要** Git clone
> - **不需要**运行 `python main.py`
> - 安装后从**桌面快捷方式**启动即可

## ✨ 功能特性
...（现有内容）...

---

<details>
<summary>🔧 开发者说明</summary>

## 环境要求
...（现有内容下移到这里）...

## 运行方式
...（现有内容）...

## 打包
...（现有内容）...

</details>
```

### 3.2 变更要点

| 项目 | 改造前 | 改造后 |
|------|--------|--------|
| 第一屏内容 | 技术栈、环境要求、`pip install` | **下载按钮** + 普通用户提示 |
| 下载入口 | 无（只有 clone 和 build 说明） | 大按钮指向 `DanmuAI-Setup.exe` |
| 开发者说明 | 放在最前面 | 折叠到 `<details>` 中 |
| 普通用户提示 | 无 | 明确列出"不要做什么" |

### 3.3 下载按钮 URL

```
https://github.com/PEPETII/danmuai/releases/latest/download/DanmuAI-Setup.exe
```

该 URL 是 GitHub 标准 latest release asset 跳转链接，只要每个 Release 都上传名为 `DanmuAI-Setup.exe` 的资产，链接永久有效，不需要随版本号改变。

---

## 4. 数据保存位置说明

### 4.1 数据位置一览

> 应在 README 或新增 `docs/DATA_LOCATIONS.md` 中说明以下内容。

| 数据 | 存储位置 | 说明 |
|------|----------|------|
| **程序本体** | `<安装目录>\` | `DanmuAI.exe` + `_internal\` + `web\static\` |
| **Web 静态资源** | `<安装目录>\web\static\` | 控制台 HTML/CSS/JS，随安装包发布 |
| **用户配置** | `%APPDATA%\DanmuAI\config.db` | SQLite 数据库，含所有设置项 |
| **API Key** | `%APPDATA%\DanmuAI\config.db`（加密字段） | Fernet 对称加密存储 |
| **加密密钥** | `%APPDATA%\DanmuAI\.key` | Fernet 密钥文件，权限 600 |
| **启动日志** | `%APPDATA%\DanmuAI\startup.log` | 每次启动的诊断日志 |
| **弹幕历史** | `%APPDATA%\DanmuAI\config.db`（history 表） | 生成的弹幕文本历史 |
| **会话统计** | `%APPDATA%\DanmuAI\config.db`（session_runs 表） | Token 用量、弹幕数量统计 |
| **烂梗库** | `%APPDATA%\DanmuAI\config.db`（meme_barrage_library 表） | 远程 API 拉取 + 本地缓存 |
| **公式化弹幕** | `%APPDATA%\DanmuAI\config.db`（config 表） | 用户自定义弹幕池 + 缓存 |
| **AI 模型** | 来自用户填写的模型服务商 API | 不存储模型本身，仅存配置和 key |

### 4.2 重要声明

> 以下内容必须写入 README 或文档：

- **DanmuAI-Setup.exe 不是数据源**，它只是安装入口
- **程序更新不会覆盖或删除** `%APPDATA%\DanmuAI\` 下的任何文件
- **卸载程序不会删除** `%APPDATA%\DanmuAI\`（用户数据需手动清理，或提供 `scripts/reset_local_data.ps1`）
- API Key **仅在本地加密存储**，不上传到任何服务器
- AI 模型调用走用户自己填写的模型服务商 API

### 4.3 与当前代码一致性验证

| 数据 | 代码位置 | 状态 |
|------|----------|:---:|
| config.db 路径 | `app/config_store.py:53-54` | ✓ 正确 |
| .key 路径 | `app/config_store.py:55` | ✓ 正确 |
| .key 权限 | `app/config_store.py:58-63` | ✓ `chmod 0o600` |
| startup.log 路径 | `app/bundle_paths.py:28-31` | ✓ 正确 |
| Fernet 加密 | `app/config_store.py:125-146` | ✓ 正确 |
| API Key 加密读 | `app/config_store.py:254-281` | ✓ 正确 |
| API Key 加密写 | `app/config_store.py:283-316` | ✓ 正确 |

**不需要代码变更**，只需文档化。

---

## 5. GitHub Releases 发布规范

### 5.1 资产命名

| 文件名 | 用途 | 稳定性要求 |
|--------|------|:---:|
| `DanmuAI-Setup.exe` | 安装器（普通用户下载） | **每次 Release 不变** |
| `DanmuAI-Portable.zip` | Portable 免安装版（高级用户可选） | 每次 Release 不变 |

### 5.2 Release 说明模板

```markdown
## DanmuAI v{version} (YYYY-MM-DD)

### 📥 下载

- **[DanmuAI-Setup.exe](下载链接)** ← 普通用户请下载这个
- [DanmuAI-Portable.zip](下载链接) ← 仅高级用户

> ⚠️ **不要下载下方的 Source code.zip** — 那是源代码，不是程序。

### ✨ 更新内容

- ...
- ...

### 🔧 开发者

构建方式见 `scripts/build_exe.ps1`。
完整打包说明见 `docs/PACKAGING_WINDOWS.md`。
```

### 5.3 现有脚本改造

当前 `scripts/upload_github_release.ps1` 只上传 `DanmuAI-windows-x64.zip`，需要改为上传 `DanmuAI-Setup.exe`（和可选 `DanmuAI-Portable.zip`）。

### 5.4 README 下载按钮指向

```
# 始终指向最新 Release 的 DanmuAI-Setup.exe
https://github.com/PEPETII/danmuai/releases/latest/download/DanmuAI-Setup.exe
```

只要每个 Release 的资产名保持为 `DanmuAI-Setup.exe`，该链接无需随着版本号更新。

---

## 6. COS 分阶段规划

### 6.1 阶段总览

| 阶段 | 发布源 | 更新方式 | 何时引入 |
|------|--------|----------|----------|
| **Phase 1** | GitHub Releases 唯一 | 用户手动下载安装器 | **当前，立刻** |
| **Phase 2** | GitHub Releases + COS 镜像 | 用户手动下载（COS 国内加速） | 国内用户反馈下载慢时 |
| **Phase 3** | COS 主源 + GitHub 备用 | Velopack 自动更新 | COS 稳定运行一个月后 |

### 6.2 Phase 1 — GitHub Releases（当前阶段）

```
发布流程:
  1. build_exe.ps1 → dist/DanmuAI/
  2. iscc scripts/installer.iss → DanmuAI-Setup.exe
  3. gh release create v0.3.0 DanmuAI-Setup.exe
  4. README 按钮指向 Releases

用户流程:
  访问 GitHub → 点下载 → DanmuAI-Setup.exe → 双击安装

COS: 不涉及
Velopack: 不涉及
```

### 6.3 Phase 2 — GitHub Releases + COS 国内镜像

```
发布流程:
  1-3 同上
  4. 将 DanmuAI-Setup.exe 同步上传到 COS 公开桶
  5. README 提供两个下载按钮：
     - [国内用户下载（更快）] → COS URL
     - [国外用户下载] → GitHub Releases

COS 配置:
  - 公开读桶，仅放 DanmuAI-Setup.exe
  - 不写 SecretId/SecretKey 到客户端
  - 客户端不直接访问 COS（用户手动下载）

Velopack: 不涉及
自动更新: 不涉及
```

### 6.4 Phase 3 — COS + Velopack 自动更新

```
发布流程:
  1. build_exe.ps1 → dist/DanmuAI/
  2. vpk pack → *.nupkg
  3. vpk delta → *-delta.nupkg
  4. 上传 full/delta/releases.win.json 到 COS
  5. iscc → DanmuAI-Setup.exe → 上传 COS + GitHub Releases

用户流程:
  首次: 下载 DanmuAI-Setup.exe
  后续: 应用启动时自动检查 COS → 下载 delta/full → 提示重启

详见第 8 节 Velopack 设计。
```

### 6.5 COS 要求（Phase 3 才会用到）

| 项目 | 要求 |
|------|------|
| 桶权限 | `releases/win/` 路径公开读 |
| 读写分离 | 上传用脚本（本地持有 Secret），下载用公开 HTTP GET |
| 客户端安全 | **不在客户端代码中写 SecretId / SecretKey** |
| 自定义域名 | 如果绑定 CDN 域名，需 ICP 备案；COS 默认域名无需备案 |
| 费用 | 公开读流量按量计费，初期极低（< 10 GB/月） |

---

## 7. 启动体验改造

### 7.1 当前启动链路分析

```
当前冷启动时序（双击 DanmuAI.exe 后）:
───────────────────────────────────────────────────────
 t=0ms   进程启动
 t=200ms Python 初始化、import 扫描
 t=500ms PyQt6 导入、QApplication 创建
 t=800ms ConfigStore 初始化 (SQLite WAL)
 t=900ms attach_web_console() → uvicorn 线程启动
 t=1200ms Web console HTTP 就绪 (正常情况)
 t=1500ms pywebview 子进程启动
 t=2000ms pywebview 窗口显示
 t=2500ms 用户可见完整界面
───────────────────────────────────────────────────────
 
问题: t=0 到 t=2500ms 之间用户看到什么？
  - PyInstaller console=False: 双击后 2.5 秒内**什么都看不到**
  - 用户可能以为没启动成功，重复双击
  - 启动失败时无视觉反馈，静默消失
```

### 7.2 启动反馈设计

```
双击 DanmuAI.exe
    │
    ▼ t=0ms
┌──────────────────────────────┐
│  ⚡ Splash Screen            │  ← 尽可能快显示
│                              │
│     DanmuAI 正在启动...      │
│                              │
│  [旋转加载图标 / 状态文本]    │
└──────────────────────────────┘
    │
    │ 后台执行:                  │
    │  ├ QApplication 创建       │
    │  ├ ConfigStore 初始化      │
    │  ├ uvicorn 启动            │
    │  ├ pywebview 启动          │
    │  ├ Overlay 初始化          │
    │  └ tray 创建               │
    │                            │
    ▼ t=2500ms 启动完成
┌──────────────────────────────┐
│  Splash 自动关闭              │
│  托盘图标出现                  │
│  pywebview 桌面窗显示          │
└──────────────────────────────┘
```

### 7.3 Splash Screen 技术方案

| 方案 | 最快显示时机 | 优点 | 缺点 |
|------|:---:|------|------|
| **Qt QSplashScreen** | 需等 QApplication 创建后（~500ms） | 简单、有现成 API | 有 500ms 空白期 |
| **Win32 CreateWindowEx** | import 前（~10ms） | 即刻显示 | 需 ctypes 手写 Win32 |
| **pyglet / pygame** | ~100ms | 跨平台 | 引入新依赖 |
| **subprocess 独立 exe** | ~200ms | 独立进程不阻塞 | 复杂，需打包额外 exe |

**建议:** 使用 Win32 `CreateWindowEx` + `ctypes` 方案：
- 在 `main.py` 最顶部（任何 heavy import 之前）用 ctypes 调 Win32 API 创建无边框窗口
- 显示程序图标和"正在启动..."文字
- QApplication 创建后用 `QTimer.singleShot(100, splash.close)` 关闭
- 若启动失败，splash 留在屏幕上直到错误弹窗出现

**不引入新依赖** — `ctypes` 是 Python 标准库，Win32 API 在所有 Windows 上都可用。

### 7.4 启动失败弹窗设计

```
启动失败时，splash 关闭后弹出此对话框:

┌─────────────────────────────────────────┐
│  ⚠ DanmuAI 启动失败                      │
├─────────────────────────────────────────┤
│                                         │
│  Web 控制台未能在 30 秒内启动。           │
│                                         │
│  可能原因：                              │
│  - 端口 18765 被其他程序占用             │
│  - PyInstaller 打包依赖缺失              │
│  - 磁盘空间不足                          │
│                                         │
│  日志位置：                              │
│  %APPDATA%/DanmuAI/startup.log          │
│                                         │
├─────────────────────────────────────────┤
│  [重试启动] [打开日志] [重置配置] [帮助]  │
└─────────────────────────────────────────┘
```

**按钮行为:**

| 按钮 | 行为 |
|------|------|
| **重试启动** | `QProcess.startDetached(DanmuAI.exe)` + `QApplication.quit()` |
| **打开日志** | `os.startfile("C:/Users/.../AppData/Roaming/DanmuAI/startup.log")` |
| **重置配置** | 弹确认框 → 删除 `%APPDATA%/DanmuAI/config.db` 和 `.key` → 弹提示"配置已重置，下次启动将创建新配置" → 退出 |
| **帮助** | 打开系统浏览器到 GitHub Issues 或帮助文档页面 |

### 7.5 启动失败触发条件

| 失败类型 | 触发条件 | 当前表现 | 改造后 |
|----------|----------|----------|--------|
| Web Console 启动超时 | `wait_ready(30s)` 未就绪 | 日志 + 继续启动（无视觉提示） | 弹窗，按钮如上 |
| pywebview 握手失败 | `handshake_deadline` 超时 | fallback 系统浏览器 | 托盘气泡提示，不弹窗 |
| 端口被占 | `bind_failed` | 日志 + 继续启动 | 弹窗"端口 18765 被占用" |
| Python 导入失败 | PyInstaller 缺少依赖 | 静默 crash | 全局异常钩子 → 弹窗 |
| 配置读取失败 | SQLite 文件损坏 | ConfigStore 新建 | 自动重建，不弹窗 |
| 磁盘空间不足 | 写 startup.log 失败 | OSError 捕获 | 弹窗"磁盘空间不足" |

---

## 8. Velopack 增量更新设计

> **本节仅在 Phase 3 实现。Phase 1/2 不涉及 Velopack，用户手动下载安装器更新。**

### 8.1 Velopack 简介

Velopack 是一个开源桌面应用更新框架（主 .NET 生态，提供 Python SDK）。核心能力：
- 从 HTTP 源检查版本
- 下载 delta（增量）或 full（全量）nupkg 包
- 重启时自动应用更新
- 支持 S3/COS 兼容后端

### 8.2 接入点：main.py

```python
# main.py 最顶部（在任何 heavy import 之前）
import sys
from velopack import App

def main():
    # Velopack 检查并应用待处理更新
    # 如有待更新 → 解压替换安装目录 → 重启进程 → 此行不返回
    # 如无待更新 → 立即返回（< 50ms）
    App().run()

    # 以下为原有启动逻辑
    check_deprecated_launch_args()
    web_launch = web_launch_mode_from_argv()
    ...
```

### 8.3 对启动流程的影响

```
时序图:

main.py 入口
    │
    ▼
velopack.App().run()
    │
    ├── [有待应用更新] 解压 nupkg → 替换文件 → 重启进程
    │        │
    │        └→ main.py 再次被执行（已更新版本）
    │
    └── [无待应用更新] 返回
             │
             ▼
        QApplication 创建
        ConfigStore 初始化
        Web Console 启动
        pywebview / tray
             │
             ▼
        启动完成 (2-3s)
             │
    QTimer.singleShot(10000)
             │
             ▼
    ┌─────────────────────────┐
    │ 后台检查 COS 更新        │
    │ (非阻塞，不影响使用)     │
    └────────┬────────────────┘
             │
         有更新 → 后台下载 delta/full → 托盘气泡提示 → 用户点重启
         无更新 → 静默
         网络错 → 静默，下次启动再试
```

### 8.4 对现有组件的影响评估

| 组件 | 影响 | 说明 |
|------|:---:|------|
| **单实例检查** | 低 | 重启前需释放锁文件 |
| **pywebview** | 低 | 重启前 `destroy()` 子进程，避免文件锁定 |
| **托盘** | 无 | tray 是纯 UI 组件，不影响更新 |
| **Overlay** | 无 | 同上 |
| **ConfigStore** | 无 | 在 `%APPDATA%`，不在更新范围内 |
| **Web Console** | 低 | 重启前正常 `stop()` uvicorn |
| **开发者模式** (`python main.py`) | 无 | velopack 通过 `is_frozen()` 判断是否启用 |

### 8.5 更新检查位置

| 检查点 | 触发方式 | 行为 |
|--------|----------|------|
| **启动后延迟检查** | `QTimer.singleShot(10000)` | 后台静默，有更新才托盘气泡 |
| **Web Console 设置页** | 用户点击"检查更新" | 即时返回，显示"已是最新"或"发现新版本" |
| **托盘菜单** | 用户点击"检查更新" | 同上 |
| **下载进度** | WebSocket 实时推送 | 前端进度条（见 8.7） |
| **更新完成** | 下载完毕后 | 托盘气泡 + Web Console 弹窗"是否重启？" |

### 8.6 增量更新 Fallback 规则

```
决策树:

存在当前版本 → 最新版本的 delta?
    │
    ├── 是 → delta 大小 < full 的 80%?
    │         │
    │         ├── 是 → 下载 delta → 校验成功? ── 是 → 完成 ✓
    │         │                          └── 否 → 重新下载 full
    │         └── 否 → 下载 full
    │
    └── 否 → 下载 full

下载 full → 校验成功? ── 是 → 完成 ✓
                       └── 否 → 重试一次 → 仍失败 → 弹窗"请手动下载"

整个流程中用户只看到:
  1. 托盘/Web 提示"发现新版本 0.3.1"
  2. 下载进度
  3. "是否立即重启？"
  
技术降级对用户**透明**。
```

### 8.7 COS 更新目录结构

```
COS 桶: danmuai-release-<appid>
└ releases/win/
    ├ releases.win.json              ← Velopack 版本清单
    ├ assets.win.json                ← 包元数据
    ├ PEPETII.DanmuAI-0.3.0-full.nupkg
    ├ PEPETII.DanmuAI-0.3.1-delta.nupkg    (0.3.0 → 0.3.1)
    ├ PEPETII.DanmuAI-0.3.1-full.nupkg
    ├ PEPETII.DanmuAI-0.4.0-delta.nupkg    (0.3.1 → 0.4.0)
    ├ PEPETII.DanmuAI-0.4.0-full.nupkg
    └ DanmuAI-Setup.exe               ← 始终最新（手动下载兜底）
```

**包保留策略:**
- 最新 full → 永久保留
- 最近 3 个版本的 full → 保留（用于生成 delta）
- 所有可用的 delta → 保留（直到对应 base 版本被清理）
- DanmuAI-Setup.exe → 始终最新版

### 8.8 发布流程（Phase 3）

```
Phase 3 完整发布命令序列:

# 1. PyInstaller 打包
.\scripts\build_exe.ps1                    → dist/DanmuAI/ (新版本)

# 2. vpk 打包 full
vpk pack ^
  --packId PEPETII.DanmuAI ^
  --packVersion 0.3.1 ^
  --packDir dist\DanmuAI ^
  --mainExe DanmuAI.exe ^
  --outputDir release\packages\
                                           → PEPETII.DanmuAI-0.3.1-full.nupkg

# 3. vpk 生成 delta（从上一版本）
vpk delta ^
  --packId PEPETII.DanmuAI ^
  --oldVersion 0.3.0 ^
  --newVersion 0.3.1 ^
  --packagesDir release\packages\
                                           → PEPETII.DanmuAI-0.3.1-delta.nupkg

# 4. 编译安装器（Inno Setup）
iscc scripts\installer.iss                 → release\DanmuAI-Setup.exe

# 5. 上传到 COS
.\scripts\upload_cos_release.ps1 0.3.1
  → 上传 full.nupkg + delta.nupkg + releases.win.json + Setup.exe

# 6. 上传到 GitHub Releases（备用）
gh release create v0.3.1 ^
  release\DanmuAI-Setup.exe ^
  --title "DanmuAI 0.3.1" ^
  --notes-file docs\release\0.3.1.md
```

### 8.9 Phase 3 前提条件

1. Velopack Python SDK POC 验证通过
2. COS 桶已创建，`releases/win/` 公开读配置正确
3. Inno Setup 安装器已稳定运行
4. Splash Screen 启动反馈已就绪
5. `%APPDATA%/DanmuAI/` 数据保护已验证

---

## 9. 本地数据保护

### 9.1 核心原则

```
┌──────────────────────────────────────────────┐
│                 根 本 原 则                    │
│                                              │
│  安装目录 (C:\Program Files\DanmuAI\)        │
│       ↓ 只放程序文件                           │
│       ↓ 更新 / 重装时**完全覆盖**               │
│       ↓ 用户不应写入这里                        │
│                                              │
│  用户数据目录 (%APPDATA%\DanmuAI\)             │
│       ↓ 放所有用户数据                          │
│       ↓ 更新 / 重装时**永不动**                 │
│       ↓ 卸载时**不自动删除**（可选手动清理）     │
└──────────────────────────────────────────────┘
```

### 9.2 Velopack 更新时的数据保护

Velopack 更新流程只操作安装目录，不动 `%APPDATA%`：

```
Velopack 更新步骤:
  1. 下载 nupkg 到临时目录
  2. 校验 SHA256
  3. 关闭当前进程
  4. Update.exe 解压 nupkg → 替换安装目录文件
  5. 启动新版本 DanmuAI.exe
  6. 新进程读取 %APPDATA%\DanmuAI\config.db（完好无损）

不触及的目录:
  %APPDATA%\DanmuAI\
  %TEMP%\ (仅下载临时文件)
  桌面\
  文档\
```

### 9.3 卸载行为

| 操作 | 卸载程序行为 |
|------|-------------|
| 安装目录 | **完全删除** |
| 桌面快捷方式 | **删除** |
| 开始菜单快捷方式 | **删除** |
| 注册表卸载信息 | **删除** |
| `%APPDATA%\DanmuAI\` | **保留**（用户需手动清理） |
| `%APPDATA%\DanmuAI\config.db` | **保留** |
| `%APPDATA%\DanmuAI\.key` | **保留** |

卸载程序应显示提示："您的个人数据和配置保留在 `%APPDATA%/DanmuAI/`，未被删除。"

### 9.4 验证方式

| 验证项 | 方法 |
|--------|------|
| 更新不丢配置 | 安装旧版 → 修改配置 → 更新到新版 → 确认配置保留 |
| 更新不丢 API Key | 安装 → 填写 Key → 更新 → 确认 Key 仍有效 |
| 更新不丢历史 | 运行生成弹幕 → 更新 → 确认弹幕历史保留 |
| 卸载不删数据 | 卸载 → 确认 `%APPDATA%/DanmuAI/` 存在 |
| 重装不丢数据 | 卸载 → 重装 → 启动 → 确认旧配置仍在 |

---

## 10. 打包与发布流水线

### 10.1 完整流水线（Phase 3 终态）

```
                    ┌──────────────────┐
                    │ main.py 源码      │
                    │ app/ 源码         │
                    │ web/static/       │
                    │ data/             │
                    │ requirements.txt  │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │ PyInstaller       │
                    │ DanmuAI.spec      │
                    │ build_exe.ps1     │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │ dist/DanmuAI/     │ ← onedir 产物（不变）
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
     ┌────────────┐  ┌────────────┐  ┌────────────┐
     │ vpk pack   │  │ vpk delta  │  │ Inno Setup │
     │ → full     │  │ → delta    │  │ → Setup    │
     │ .nupkg     │  │ .nupkg     │  │ .exe       │
     └─────┬──────┘  └─────┬──────┘  └──────┬─────┘
           │               │                │
           └───────┬───────┘                │
                   │                        │
                   ▼                        │
           ┌──────────────┐                 │
           │ 上传到 COS    │                 │
           │ + releases    │                 │
           │ .win.json     │                 │
           └──────────────┘                 │
                                            │
                   ┌────────────────────────┘
                   │
                   ▼
           ┌──────────────┐
           │ GitHub        │
           │ Releases      │  ← 备用源
           └──────────────┘
```

### 10.2 各阶段流水线对比

| 步骤 | Phase 1 | Phase 2 | Phase 3 |
|------|:---:|:---:|:---:|
| PyInstaller 打包 | ✓ | ✓ | ✓ |
| Inno Setup 安装器 | ✓ | ✓ | ✓ |
| 上传到 GitHub Releases | ✓ | ✓ | ✓ |
| 上传到 COS | ✗ | ✓（仅 Setup.exe） | ✓（Setup + nupkg + json） |
| vpk pack full | ✗ | ✗ | ✓ |
| vpk delta | ✗ | ✗ | ✓ |
| 自动更新检查 | ✗ | ✗ | ✓ |

### 10.3 GitHub Actions 建议

```yaml
# .github/workflows/release.yml
name: Release

on:
  push:
    tags: ['v*']

jobs:
  build-and-release:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: .\scripts\build_exe.ps1
      # Phase 1: 仅 Inno Setup
      - run: choco install innosetup
      - run: iscc scripts\installer.iss
      - run: |
          gh release create ${{ github.ref_name }} `
            release\DanmuAI-Setup.exe `
            --title "DanmuAI ${{ github.ref_name }}" `
            --generate-notes
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      # Phase 3 时扩展: vpk pack + vpk delta + COS 上传
```

---

## 11. 涉及文件清单

### 11.1 需新增

| 文件 | 用途 | 阶段 |
|------|------|:---:|
| `scripts/installer.iss` | Inno Setup 安装脚本 | Phase 1 |
| `docs/DATA_LOCATIONS.md` | 数据保存位置说明 | Phase 1 |
| `docs/COS_VELOPACK_UPDATE_DESIGN.md` | 本设计文档 | Phase 1（设计） |
| `scripts/upload_cos_release.ps1` | COS 上传脚本 | Phase 2 |
| `scripts/generate_vpk_packages.ps1` | vpk full + delta 生成脚本 | Phase 3 |
| `app/update_checker.py` | Velopack 更新检查模块 | Phase 3 |
| `app/splash_screen.py` | Win32 Splash Screen 实现 | Phase 1 |

### 11.2 需修改

| 文件 | 改动 | 阶段 | 影响 |
|------|------|:---:|:---:|
| `main.py` | 顶部加 Win32 Splash；Phase 3 加 `velopack.App().run()` | Phase 1/3 | 高 |
| `app/main_launch.py` | 增加启动失败增强弹窗函数 | Phase 1 | 中 |
| `app/webview_shell.py` | 启动失败回调增强（调用增强弹窗） | Phase 1 | 低 |
| `app/web_console.py` | Phase 3: 增加 `/api/update/*` 路由 | Phase 3 | 中 |
| `app/tray.py` | Phase 3: 托盘菜单"检查更新" | Phase 3 | 低 |
| `DanmuAI.spec` | Phase 3: datas 增加 velopack 运行时 | Phase 3 | 中 |
| `scripts/build_exe.ps1` | 增加 Inno Setup 编译步骤 | Phase 1 | 中 |
| `scripts/publish_windows_release.ps1` | 改为编译安装器而非生成 zip | Phase 1 | 中 |
| `scripts/upload_github_release.ps1` | 资产改为 Setup.exe | Phase 1 | 低 |
| `README.md` | 下载入口重构 + 数据位置链接 | Phase 1 | 低 |
| `requirements.txt` | Phase 3: 加 `velopack` | Phase 3 | 低 |

### 11.3 不受影响

| 文件 | 原因 |
|------|------|
| `app/config_store.py` | 数据路径不变，更新不触及 |
| `app/bundle_paths.py` | 路径解析逻辑不变 |
| `app/overlay.py` | Qt 渲染不受影响 |
| `app/danmu_engine.py` | 业务逻辑不受影响 |
| `app/ai_client.py` | AI 调用不受影响 |
| `web/static/` | 前端文件作为打包内容随 onedir 更新 |

---

## 12. 验收标准

### 12.1 安装器验收

- [ ] 用户访问 GitHub Releases，看到并下载 `DanmuAI-Setup.exe`（**唯一文件名，不含版本号**）
- [ ] 双击 `DanmuAI-Setup.exe` → 安装向导 → 选择目录 → 安装完成
- [ ] 安装后桌面出现 `DanmuAI` 快捷方式，双击可启动
- [ ] 开始菜单出现 `DanmuAI` 文件夹，含启动快捷方式和卸载入口
- [ ] 安装目录包含 `DanmuAI.exe` + `_internal/` + `web/static/` + `resources/`
- [ ] 安装过程中不创建 `%APPDATA%/DanmuAI/`（首次启动时由 ConfigStore 创建）
- [ ] **用户全程不需要** Python、Git、命令行、pip install

### 12.2 README 验收

- [ ] 第一屏有显眼的下载按钮，文案为"下载 Windows 安装版"
- [ ] 按钮链接指向 `https://github.com/.../releases/latest/download/DanmuAI-Setup.exe`
- [ ] 明确提示"不要下载 Source code.zip"
- [ ] 明确提示"不需要安装 Python、不需要 Git clone、不需要运行 main.py"
- [ ] 开发者运行方式移到折叠区域（`<details>`）
- [ ] 有数据保存位置说明（或链接到 `docs/DATA_LOCATIONS.md`）

### 12.3 启动体验验收

- [ ] 双击 `DanmuAI.exe`（或快捷方式）后 **1 秒内** 出现启动中窗口（Splash）
- [ ] Splash 启动完成后自动消失，桌面窗或浏览器打开
- [ ] 启动失败时弹出错误对话框（而非静默退出）
- [ ] 错误对话框提供"重试启动"按钮（有效）
- [ ] 错误对话框提供"打开日志"按钮（打开 startup.log）
- [ ] 错误对话框提供"重置配置"按钮（删除后提示重建）
- [ ] 错误对话框提供"帮助"按钮（打开帮助页面）

### 12.4 数据保护验收

- [ ] 更新应用后，`%APPDATA%/DanmuAI/config.db` 完整保留
- [ ] 更新应用后，`%APPDATA%/DanmuAI/.key` 完整保留
- [ ] 更新应用后，API Key 可正常解密使用
- [ ] 卸载应用后，`%APPDATA%/DanmuAI/` 保留不删
- [ ] 重装应用后，旧配置自动恢复

### 12.5 开发者模式验收

- [ ] `python main.py` 仍可正常运行
- [ ] `python main.py --web-browser` 仍可正常运行
- [ ] `.\scripts\build_exe.ps1` 仍可正常构建
- [ ] PyInstaller onedir 产物结构不变
- [ ] 环境变量 `DANMU_WEB_LAUNCH` 等不受影响

### 12.6 Phase 3 自动更新验收（Phase 3 时才验证）

- [ ] 新版本发布后，旧版本启动后 10 秒内检测到更新
- [ ] delta 包存在且小于 full 时，优先下载 delta
- [ ] delta 不可用时自动切换 full
- [ ] COS 不可达时应用正常启动，无错误弹窗
- [ ] 下载完成后提示重启，重启后新版本生效
- [ ] 客户端不包含 COS SecretId/SecretKey

---

## 13. 风险点

### 13.1 技术风险

| 风险 | 等级 | 说明 | 缓解 |
|------|:---:|------|------|
| **Velopack Python SDK 可用性** | 高 | 以 .NET 生态为主，Python SDK 可能功能受限 | Phase 3 前做 POC 验证 |
| **Inno Setup CI 环境** | 低 | `choco install innosetup` 在 GitHub Actions 上可用 | 提前测试 |
| **onedir 文件替换** | 中 | `_internal/` 下 1000+ 文件，Velopack 替换时可能卡 IO | 实际测试验证 |
| **Win32 Splash 兼容性** | 低 | Win32 API 在所有 Windows 10/11 上稳定 | 仅用作临时窗口，无复杂逻辑 |
| **Qt 与 velopack 启动竞态** | 中 | QApplication 创建后如果 Velopack 重启会崩溃 | 必须在 QApplication 前调用 |
| **pywebview 进程残留** | 低 | 子进程可能阻止文件替换 | 重启前 destroy 子进程 |

### 13.2 用户风险

| 风险 | 等级 | 说明 | 缓解 |
|------|:---:|------|------|
| **Windows SmartScreen 拦截** | 中 | 未签名的 exe 下载后 SmartScreen 弹警告 | 代码签名证书（$200-400/年），可选 |
| **杀毒软件误报** | 低 | PyInstaller 打包偶尔被误报 | 提交误报到各厂商 |
| **安装器被误删** | 低 | 安装完成后用户可能删除 Setup.exe | 安装器是一次性的，删除无影响 |
| **多次双击启动** | 中 | 冷启动无反馈期用户重复双击 | Splash Screen 解决 |

### 13.3 运维风险

| 风险 | 等级 | 说明 | 缓解 |
|------|:---:|------|------|
| **COS 费用失控** | 低 | CDN 流量费用不可预测 | 设置费用告警、流量上限 |
| **GitHub Release 被墙** | 中 | 国内用户可能无法访问 GitHub | Phase 2 COS 镜像解决 |
| **delta 跨版本过大** | 低 | 跨 5 个版本后 delta 可能比 full 大 | Fallback 规则自动处理 |
| **旧版用户无法更新到底** | 中 | 如果清理了旧 full，旧用户 delta 链断裂 | 至少保留最近 3 个 full |

---

## 14. 不建议方案

| 方案 | 否决理由 |
|------|----------|
| **PyInstaller onefile** | 冷启动慢（解压到 TEMP）、与 Velopack 更新模型冲突、已知 PyQt6 + uvicorn 文件锁定问题 |
| **自研更新器（下载 zip + 解压）** | 无 delta、需自行处理替换/校验/回滚、维护成本高 |
| **GitHub Releases 唯一源 + 自动更新** | 国内下载慢、API rate limit、不支持 delta |
| **强制自动更新（不询问用户）** | 桌面应用 UX 惯例应提示用户、强制重启体验差 |
| **Squirrel.Windows** | 已停止维护、仅支持 .NET |
| **直接分发 `dist/DanmuAI/` 目录** | 当前方式：普通用户不会操作 |
| **把用户配置写安装目录** | 卸载丢数据、更新丢数据、违反 Windows 最佳实践 |

---

> **版本记录:**
> - 0.3.0 — 初稿：涵盖安装器、下载入口、数据位置、启动体验、COS 分阶段、Velopack 增量更新
> - Phase 1 建议立即启动；Phase 2/3 待 Phase 1 稳定后逐步推进
