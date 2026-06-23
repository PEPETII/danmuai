# W-BILILIVE-DM-PLUGIN-MOCK-001 + W-BILILIVE-DM-PLUGIN-BRIDGE-002 + PUSH-004 — bililive_dm 独立 mock 插件 PoC + 本地旁路桥接 + 主动推送

> 构建/安装说明看本文件；当前模块结构、链路方向、扩展入口与约束总览见 [MODULE_OVERVIEW.md](./MODULE_OVERVIEW.md)。

> **目标**：
> - MOCK-001：验证 `bililive_dm` 插件框架的最小链路 `DMPlugin -> AddDM()` 在弹幕姬本地层正常工作。
> - BRIDGE-002/003：在 MOCK-001 基础上增加**本地旁路桥接** —— 插件收到评论事件后通过 `127.0.0.1:18765` HTTP POST 调用 DanmuAI 暴露的最小桥接 API，再把返回的文本逐条 `AddDM()` 到弹幕姬本地层。
> - PUSH-004：DanmuAI 主链路「生成弹幕」完成后，主动 POST 到插件本地 `HttpListener`（`127.0.0.1:18766`），侧边栏显示本次 AI 生成结果（**不**依赖直播评论事件）。
>
> **不**做：连接 DanmuAI 主链路调度（截图 / 视觉 AI / 弹幕库 / mic / pet / TTS）、向 B 站直播间自动发弹幕、做鉴权 / 重试 / 复杂降级。
>
> **依赖**：本机装好 .NET SDK 6.0 / 7.0 / 8.0 任一版本（**不需要** Visual Studio、不需要 MSBuild、不需要 .NET Framework Developer Pack；ref assemblies 由 NuGet 包 `Microsoft.NETFramework.ReferenceAssemblies.net461` 注入）。还需要一份能正常加载插件的 `bililive_dm` 客户端，以及一个已经启动并监听 `127.0.0.1:18765` 的 DanmuAI（`python main.py` 即可）。

---

## 1. 目录结构

```
tools/bililive_dm_plugin_mock/
├── README.md                            # 本文件
├── src/
│   ├── BililiveDmMockPlugin.csproj      # 插件工程（net461，HintPath 引用 SDK DLL）
│   ├── DanmuAiMockPlugin.cs             # DMPlugin 派生类（MOCK + BRIDGE + PUSH）
│   └── DanmuAiPushListener.cs           # PUSH-004 本地 HttpListener 接收端
└── sdk/                                 # 精简 SDK 子集（vendored from output/_bililive_dm_repo/）
    ├── BilibiliDM_PluginFramework.csproj
    ├── DMPlugin.cs
    ├── DanmakuModel.cs
    ├── Events.cs
    ├── GiftRank.cs
    └── Properties/
        ├── Annotations.cs
        └── AssemblyInfo.cs
```

> SDK 子集仅包含 `BilibiliDM_PluginFramework` 项目下编译所需的源文件，不带 `libwtfdanmaku`、`BilibiliDM_PluginFramework.Tests` 等无关项目。所有源码都保留了上游版权头。
>
> 没有 `.sln`：两个 csproj 是独立的 SDK-style 项目，**分别**用 `dotnet build` 构建即可，不需要 Solution 包装。

---

## 2. 构建 DLL

**只需 .NET SDK 6/7/8 任一版本**（不需要 Visual Studio、Build Tools、MSBuild.exe 或 .NET Framework Developer Pack）。NuGet 包 `Microsoft.NETFramework.ReferenceAssemblies.net461 1.0.3` 会在 `obj/` 缓存里自动展开 ref assemblies，绕开「机器缺 ref assemblies」的死结。

```bash
cd tools/bililive_dm_plugin_mock

# 第 1 步：先构建 SDK（产出 BilibiliDM_PluginFramework.dll 给插件引用）
dotnet build sdk/BilibiliDM_PluginFramework.csproj -c Release

# 第 2 步：再构建插件（会自动校验 SDK DLL 已存在，否则报明确错误）
dotnet build src/BililiveDmMockPlugin.csproj -c Release
```

构建产物（均在 `bin\Release\net461\` 下）：

```
sdk/bin/Release/net461/
├── BilibiliDM_PluginFramework.dll      # SDK 自身
├── BilibiliDM_PluginFramework.pdb
└── Newtonsoft.Json.dll                  # SDK 依赖，NuGet 自动拷入

src/bin/Release/net461/
├── BililiveDmMockPlugin.dll            # 插件主体
├── BililiveDmMockPlugin.pdb
├── BilibiliDM_PluginFramework.dll      # CopyLocal=true 也会带一份
└── Newtonsoft.Json.dll
```

> 已知测试：2026-06-21 在仅装 .NET SDK 8.0.422（无 VS）的 Windows 10 22631 机器上，0 警告 0 错误构建成功。

---

## 3. 安装到弹幕姬

`bililive_dm` 默认从「我的文档\弹幕姬\Plugins」加载插件。Windows 上路径示例：

```
%USERPROFILE%\Documents\弹幕姬\Plugins\
```

**最小部署**（2 个 DLL，宿主已自带 Newtonsoft.Json 13.x 时用这套）：

- `BililiveDmMockPlugin.dll`
- `BilibiliDM_PluginFramework.dll`

**安全部署**（再加 Newtonsoft.Json.dll，宿主版本不匹配或缺失时用这套）：

- `BililiveDmMockPlugin.dll`
- `BilibiliDM_PluginFramework.dll`
- `Newtonsoft.Json.dll`（13.0.1，**注意不要混版本**）

把全部 3 个 DLL 拷到上面的 Plugins 目录；如弹幕姬正在运行，先关掉再启动；首次安装无需重启系统。

---

## 4. 桥接端点

插件只在收到 `MsgTypeEnum.Comment` 事件时发起桥接请求，请求负载与端点如下（**硬编码在 `DanmuAiMockPlugin.cs` 中**）：

| 字段 | 值 |
|------|------|
| 端点 | `POST http://127.0.0.1:18765/api/plugin/bililive-dm/reply` |
| Content-Type | `application/json; charset=utf-8` |
| 超时 | 3 秒（`HttpClient.Timeout`） |

**请求载荷**（snake_case，Newtonsoft.Json 默认序列化）：

```json
{
  "room_id": 12345,
  "user_name": "小电视",
  "user_id": "67890",
  "text": "hello world"
}
```

**响应载荷**（DanmuAI 阶段 1 固定返回）：

成功：

```json
{
  "ok": true,
  "error": null,
  "items": [
    "收到 小电视: hello world",
    "DanmuAI bridge test ok"
  ]
}
```

失败（`text` 为空）：

```json
{
  "ok": false,
  "error": "empty_text",
  "items": []
}
```

> **不**调用 DanmuAI 主链路：截图 / 视觉 AI / 弹幕库 / mic / pet / TTS 都**不**接入；本路由是只读旁路桥接，仅在 `app/web_api/bililive_dm_bridge.py` 中实现。

### 4.2 PUSH-004 主动推送协议（DanmuAI → 插件）

DanmuAI 在主链路 AI 批次入队后，向插件本地接收端 POST 最终显示文本。与 §4.1 方向**相反**。

| 项 | 值 |
|----|-----|
| 方向 | DanmuAI → 插件 |
| 端点 | `POST http://127.0.0.1:18766/api/plugin/danmuai/push/` |
| Content-Type | `application/json; charset=utf-8` |
| 超时 | 3s（DanmuAI 侧 `httpx` 默认） |
| 实现 | `tools/bililive_dm_plugin_mock/src/DanmuAiPushListener.cs` |
| DanmuAI 契约 | `app/web_api/bililive_dm_push.py` |
| DanmuAI 执行 | `app/application/bililive_dm_push_service.py` |

**请求体**（snake_case）：

```json
{
  "source": "danmuai_main",
  "batch_id": 3,
  "items": ["人格A：这波操作可以", "笑死我了"],
  "persona": "人格A"
}
```

**成功响应**：

```json
{ "ok": true, "error": null, "displayed": 2 }
```

**失败响应**（校验失败）：

```json
{ "ok": false, "error": "empty_items", "displayed": 0 }
```

清洗规则（双方一致）：去空 / 去纯空白 / 单条 ≤60 字 / 最多 5 条。

**协议对照**

| 能力 | 触发源 | 方向 | 端口 |
|------|--------|------|------|
| BRIDGE-003 评论桥接 | 直播间 Comment | 插件 → DanmuAI | 18765 |
| PUSH-004 生成按钮 | Web「生成弹幕」主链路 | DanmuAI → 插件 | 18766 |
| 直播间发言 | — | **未实现** | — |

**自检**（需先启用插件，日志应出现 `push listener started`）：

```bash
python tools/bililive_dm_plugin_mock/scripts/repro_push_call.py
```

若 `HttpListener` 启动报 URL 预留错误，以管理员运行：

```bat
netsh http add urlacl url=http://127.0.0.1:18766/api/plugin/danmuai/push/ user=Everyone
```

---

## 5. 手动验证步骤

### 5.1 mock-001 最小本地显示

| # | 操作 | 预期结果 |
|---|------|----------|
| 1 | 启动 `bililive_dm`，进入「插件」页 | 看到 `DanmuAI Mock Plugin` 0.2.0-bridge，状态为「未启用」 |
| 2 | 勾选启用 | 弹幕姬日志出现 `DanmuAI Mock Plugin 插件已启动（Start）`；本地弹幕层出现一条 `【mock】插件已启动，本地显示验证。` |
| 3 | 插件列表里右键 → 「管理」/「Admin」/「设置」（视弹幕姬版本而定） | 弹幕姬日志继续；本地弹幕层连续出现 5 条预置测试弹幕，依次为：短中文 / 较长中文 / 带用户名前缀 / 模拟 AI 回复 / 降级提示 |
| 4 | 关闭插件 / 退出弹幕姬 | 日志出现 `插件已停止（Stop）` 与 `插件已 DeInit（弹幕姬主程序退出）`；未观察到 `bililive_dm` 异常弹窗 / 错误报告 |

### 5.2 bridge-002 本地旁路桥接（需先启动 DanmuAI）

> 前置：DanmuAI 已启动并监听 `127.0.0.1:18765`（`python main.py`）。可先用 `curl` 自检：
>
> ```bash
> curl -s -X POST http://127.0.0.1:18765/api/plugin/bililive-dm/reply ^
>      -H "Content-Type: application/json" ^
>      -d "{\"room_id\":1,\"user_name\":\"alice\",\"user_id\":\"u1\",\"text\":\"hello\"}"
> # 预期: {"ok":true,"error":null,"items":["收到 alice: hello","DanmuAI bridge test ok"]}
> ```

| # | 操作 | 预期结果 |
|---|------|----------|
| 1 | 在任意直播间发一条评论（如 `bridge test hello`） | 弹幕姬日志出现 `收到评论：<user> => bridge test hello`；本地弹幕层先出现 `【mock-回显】...`（来自 bridge 响应第一项）+ 1 条 `DanmuAI bridge test ok`（来自第二项） |
| 2 | 关闭 DanmuAI 主进程后再发一条评论 | 弹幕姬日志出现 `bridge http exception: ...` 或 `bridge timeout: 3s`；本地层**不**出现新桥接文本，但**不**崩溃 / 不假死 |
| 3 | 重启 DanmuAI 主进程后再发评论 | 桥接响应恢复，本地层重新出现桥接文本 |
| 4 | 关闭插件 / 退出弹幕姬 | 仍然按 5.1 步骤 4 收尾 |

> 步骤 5.1 步骤 3 的入口名称随弹幕姬版本略有差异；若找不到菜单，可通过 `DMPlugin.Admin()` 反射调用，或在插件代码里临时把触发点改成 `Start()` 内部自动跑一次（仅 PoC 验证用，不要提交）。

### 5.3 push-004 生成按钮主动推送（需 DanmuAI + 插件均已启动）

| # | 操作 | 预期结果 |
|---|------|----------|
| 1 | 启动 DanmuAI（`python main.py`），配置有效模型 | Web 控制台可用 |
| 2 | 启动弹幕姬并启用 `DanmuAI Mock Plugin` | 日志出现 `push listener started: http://127.0.0.1:18766/...` |
| 3 | **不连接任何直播间**，在 DanmuAI 点击「生成弹幕」 | DanmuAI 正常生成；日志出现 `bililive_dm_push: ok` 或 `failed`；侧边栏出现 AI 文本 |
| 4 | 关闭插件后再次点击「生成弹幕」 | DanmuAI 日志 `bililive_dm_push: failed ... connection_refused`；DanmuAI 自身仍正常上屏 |
| 5 | 重新启用插件，进入直播间发评论 | BRIDGE-003 评论桥接仍可用（§5.2） |

---

## 6. 明确边界（PoC 不做的事）

- **不**接入 DanmuAI 主链路调度（截图 tick / reply_queue 内部）：PUSH-004 仅在 `_enqueue_reply_batch` 末尾旁路 POST，**不**改主链时序。
- **不**实现「向 B 站直播间自动发弹幕」——`AddDM()` 写入的是弹幕姬本地层，仅供主播自己看见。
- **不**做鉴权 / 签名 / 复杂重试；端点 `127.0.0.1` 假定为本机受信调用方。
- **不**修改 `output/_bililive_dm_repo/`（只读参考）；SDK 子集已在新位置 `tools/bililive_dm_plugin_mock/sdk/` 单独维护。

PUSH-004 在 DanmuAI 侧修改了 `app/main_display_mixin.py` 与 `app/main_request_context_mixin.py`（极小挂钩），并新增 `app/web_api/bililive_dm_push.py` + `app/application/bililive_dm_push_service.py`。

---

## 7. 故障排查

| 现象 | 原因 / 处理 |
|------|------------|
| `dotnet build src/BililiveDmMockPlugin.csproj` 报 `error CS0234: 命名空间“System.Net”中不存在类型或命名空间名“Http”` 或 `error CS0246: 未能找到类型或命名空间名“HttpClient”` / `Newtonsoft` | 插件 csproj 缺 `System.Net.Http` 引用 + `Newtonsoft.Json` 包；MOCK-001 不需要这两个程序集，BRIDGE-002 加了 `HttpClient` 与 Newtonsoft 序列化，**必须**在 csproj 显式声明：`PackageReference Newtonsoft.Json 13.0.1` + `<Reference Include="System.Net.Http" />`。当前 csproj 已配好；如升级或回退后报错，核对 `src/BililiveDmMockPlugin.csproj` 的两个 ItemGroup |
| `dotnet build` 报 `error MSB3644: 找不到 .NETFramework,Version=v4.6.1 的引用程序集` | 极少数情况下 NuGet 还原失败；删 `sdk/obj` `sdk/bin` `src/obj` `src/bin` 后重试；若仍报，单独 `dotnet restore sdk/BilibiliDM_PluginFramework.csproj` 看错误 |
| 弹幕姬启动时报「找不到 Newtonsoft.Json.dll」 | 漏拷 §3 的 `Newtonsoft.Json.dll`；或在目标机器上没有匹配的 13.0.1 版本 |
| 插件 DLL 加载失败，提示「无法加载程序集」 | 目标机器 .NET Framework 版本低于 4.6.1；安装 KB3102467 / .NET 4.6.1 或更高 |
| `AddDM` 调用后本地层无任何显示 | 弹幕姬未处于「显示弹幕层」状态；检查弹幕姬设置中的「启用弹幕」开关 |
| 收到评论但 `OnReceivedDanmaku` 没触发 | 弹幕姬可能未连上直播间（`RoomId` 为 null）；先进入任意直播间再发评论 |
| `Log()` 写不进去 | 弹幕姬主窗口未创建完成；不要在 `Inited` 之前调用 `Log()`（本 PoC 已在 `Start` 之后才调用） |
| 评论事件后日志出现 `bridge http exception` / `bridge timeout` | DanmuAI 主进程未启动 / Web API 未就绪 / 端口冲突；先 `curl http://127.0.0.1:18765/api/version` 自检 |
| 评论事件后日志出现 `bridge empty or failed: empty_text` | 直播间评论内容为空（仅空白字符）；属正常降级，可忽略 |
| 评论事件后日志出现 `bridge json parse failed` | DanmuAI 主项目版本不匹配 `BRIDGE_PATH`；核对 `app/web_api/bililive_dm_bridge.py` 与 `BridgeEndpoint` 常量 |
| 插件启动报 `push listener start failed` | Windows URL 预留权限；见 §4.2 `netsh http add urlacl` |
| DanmuAI 日志 `bililive_dm_push: failed ... connection_refused` | 插件未启用 / listener 未启动；先确认弹幕姬日志有 `push listener started` |
| `repro_push_call.py` 成功但生成按钮无推送 | DanmuAI 版本过旧或未含 PUSH-004 mixin 挂钩；核对 `app/main_request_context_mixin.py` |

---

## 8. 相关工单

- 工单正文（MOCK-001）：[.local-ai/workorders/active/W-BILILIVE-DM-PLUGIN-MOCK-001.md](../../.local-ai/workorders/active/W-BILILIVE-DM-PLUGIN-MOCK-001.md)
- 完成报告（MOCK-001）：[reports/W-BILILIVE-DM-PLUGIN-MOCK-001-completion-report.md](../../reports/W-BILILIVE-DM-PLUGIN-MOCK-001-completion-report.md)
- 工单正文（BRIDGE-002）：[.local-ai/workorders/active/W-BILILIVE-DM-PLUGIN-BRIDGE-002.md](../../.local-ai/workorders/active/W-BILILIVE-DM-PLUGIN-BRIDGE-002.md)
- 完成报告（BRIDGE-002）：[reports/W-BILILIVE-DM-PLUGIN-BRIDGE-002-completion-report.md](../../reports/W-BILILIVE-DM-PLUGIN-BRIDGE-002-completion-report.md)
- 工单正文（PUSH-004）：[.local-ai/workorders/active/W-BILILIVE-DM-PLUGIN-PUSH-004.md](../../.local-ai/workorders/active/W-BILILIVE-DM-PLUGIN-PUSH-004.md)
- 完成报告（PUSH-004）：[reports/W-BILILIVE-DM-PLUGIN-PUSH-004-completion-report.md](../../reports/W-BILILIVE-DM-PLUGIN-PUSH-004-completion-report.md)
- 工单列表：[.local-ai/workorders/工单列表.md](../../.local-ai/workorders/工单列表.md)（登记行状态）
