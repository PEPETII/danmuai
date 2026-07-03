# bililive_dm 模块总览

本文档用于收拢当前仓库内与 `bililive_dm` / 弹幕姬插件接入相关的实现、能力边界、扩展入口和风险点。后续继续做扩展时，优先从本文档和相关源码入口开始，而不是重新翻工单。

## 1. 当前能力边界

当前已经落地的能力有 3 条，方向不同，必须分开理解：

1. `MOCK-001`
   - 触发源：弹幕姬插件右键「管理」
   - 方向：插件内部自测
   - 作用：直接 `AddDM()` 打 5 条预置测试弹幕
   - 用途：验证插件已加载、`Admin()` 可调用、本地显示链路正常

2. `BRIDGE-002/003`
   - 触发源：弹幕姬收到 `MsgTypeEnum.Comment`
   - 方向：插件 -> DanmuAI
   - 作用：插件把评论 POST 到 DanmuAI，再把 AI 返回的 `items` 逐条 `AddDM()`
   - 用途：评论事件驱动的真实 AI 本地回显

3. `PUSH-004`
   - 触发源：DanmuAI Web 控制台点击「生成弹幕」后的主链路结果
   - 方向：DanmuAI -> 插件
   - 作用：DanmuAI 把本次最终显示文本主动 POST 到插件本地 `HttpListener`
   - 用途：不依赖直播评论事件，也能把 DanmuAI 生成结果显示到弹幕姬侧边栏

统一边界：

- 以上 3 条都只是**弹幕姬本地显示**
- 都不是向 B 站直播间自动发言
- 当前没有实现直播间自动发弹幕能力

## 2. 当前链路图

### 2.1 评论事件桥接

```text
直播间评论
  -> bililive_dm 宿主触发 ReceivedDanmaku(Comment)
  -> DanmuAI Mock Plugin
  -> POST http://127.0.0.1:18765/api/plugin/bililive-dm/reply
  -> DanmuAI 旁路 AI 生成
  -> 返回 { ok, error, items }
  -> 插件逐条 AddDM()
  -> 弹幕姬侧边栏本地显示
```

### 2.2 DanmuAI 主动推送

```text
DanmuAI Web「生成弹幕」
  -> POST /api/start
  -> DanmuAI 主链路正常生成
  -> _enqueue_reply_batch() 完成 AI 批次入队
  -> _schedule_bililive_dm_push(...)
  -> POST http://127.0.0.1:18766/api/plugin/danmuai/push/
  -> 插件本地 HttpListener 收到 items
  -> 插件逐条 AddDM()
  -> 弹幕姬侧边栏本地显示
```

## 3. 关键文件

### 3.1 插件侧

- [DanmuAiMockPlugin.cs](src/DanmuAiMockPlugin.cs)
  - 主插件类
  - `Start()`：启动日志、本地测试弹幕、启动 push listener
  - `Admin()`：打 5 条 mock 弹幕
  - `OnReceivedDanmaku()`：评论事件 -> `CallDanmuAiAsync()`

- [DanmuAiPushListener.cs](src/DanmuAiPushListener.cs)
  - `HttpListener` 本地接收端
  - 监听 `http://127.0.0.1:18766/api/plugin/danmuai/push/`
  - 校验并清洗 `items`
  - 对每条文本执行 `AddDM()`

- [BililiveDmMockPlugin.csproj](src/BililiveDmMockPlugin.csproj)
  - 插件工程
  - 目标框架 `net461`

- [README.md](README.md)
  - 构建、部署、联调说明

### 3.2 DanmuAI 侧：评论桥接

- [bililive_dm_bridge.py](../../app/web_api/bililive_dm_bridge.py)
  - `POST /api/plugin/bililive-dm/reply`
  - 评论事件桥接路由

- [bililive_dm_bridge_service.py](../../app/application/bililive_dm_bridge_service.py)
  - 旁路真实 AI 生成
  - 不读截图、不走 `reply_queue`、不触达 Qt 主链路对象

- [routes.py](../../app/web_api/routes.py)
  - 注册 `register_bililive_dm_bridge_route(...)`
  - 另有现成测试入口 `POST /api/test/danmu`

### 3.3 DanmuAI 侧：主动推送

- [bililive_dm_contracts.py](../../app/application/bililive_dm_contracts.py)
  - 定义主动推送 schema 与常量
  - `DEFAULT_PUSH_URL = http://127.0.0.1:18766/api/plugin/danmuai/push/`

- [bililive_dm_push_service.py](../../app/application/bililive_dm_push_service.py)
  - `schedule_push_batch(...)`
  - 后台线程 fire-and-forget 发 HTTP
  - 失败只记日志，不影响主链路

- [main_display_mixin.py](../../app/main_display_mixin.py)
  - `_schedule_bililive_dm_push(...)`
  - 负责把主链路文本规范化后交给 push service

- [main_request_context_mixin.py](../../app/main_request_context_mixin.py)
  - `_enqueue_reply_batch(...)`
  - 当前在 AI 批次入队完成后调用 `_schedule_bililive_dm_push(...)`

### 3.4 DanmuAI Web 按钮入口

- [app.js](../../web/static/app.js:621)
  - `btnToggle`
  - 只调用 `/api/start` 或 `/api/stop`

- [web_console_runtime.py](../../app/web_console_runtime.py:197)
  - `/api/start`
  - 只是发 `start_requested.emit()`

## 4. 当前协议

### 4.1 评论桥接协议

请求：

```json
{
  "room_id": 12345,
  "user_name": "alice",
  "user_id": "u1",
  "text": "hello"
}
```

响应：

```json
{
  "ok": true,
  "error": null,
  "items": ["xxx", "yyy"]
}
```

### 4.2 主动推送协议

请求：

```json
{
  "source": "danmuai_main",
  "batch_id": 3,
  "items": ["这波有点秀", "哈哈哈节目效果"],
  "persona": "高压吐槽型"
}
```

响应：

```json
{
  "ok": true,
  "error": null,
  "displayed": 2
}
```

## 5. 当前版本下的推荐扩展点

如果你之后要继续扩展，优先从下面几个方向加，而不是直接碰宿主核心：

1. 插件侧显示增强
   - 例如加来源前缀
   - 区分 `mock` / `comment bridge` / `push main`
   - 在 [DanmuAiMockPlugin.cs](src/DanmuAiMockPlugin.cs) 和 [DanmuAiPushListener.cs](src/DanmuAiPushListener.cs) 做

2. 推送协议增强
   - 例如加 `topic`、`session_id`、`source_kind`
   - 优先在 [bililive_dm_contracts.py](../../app/application/bililive_dm_contracts.py) 统一 schema，再同步插件 DTO

3. DanmuAI 侧推送策略调整
   - 例如只推首条、按人格过滤、限制节流
   - 优先改 [bililive_dm_push_service.py](../../app/application/bililive_dm_push_service.py) 或 [main_display_mixin.py](../../app/main_display_mixin.py)

4. 评论桥接 prompt / 输出风格
   - 改 [bililive_dm_bridge_service.py](../../app/application/bililive_dm_bridge_service.py)
   - 不要把它和主链路 persona / screenshot 逻辑混起来，除非明确要扩大范围

5. 插件侧配置化
   - 例如桥接 URL、push 监听端口、开关项
   - 当前还没做配置化，后续要做建议先单开工单

## 6. 不建议直接碰的点

这些地方容易把“弹幕姬模块扩展”变成“主链路重构”，非必要不要动：

- [main.py](../../main.py)
- [reply_queue.py](../../app/reply_queue.py)
- [overlay.py](../../app/overlay.py)
- [danmu_engine.py](../../app/danmu_engine.py)
- `web/static/**`

原因：

- 当前接入已经通过旁路方式完成
- 再碰这些核心文件，很容易引入与弹幕姬无关的回归

## 7. 关键约束

1. `bililive_dm` 插件必须是 `.NET Framework 4.6.1`
2. 插件目录里不要放错宿主依赖，尤其避免类型身份冲突
3. `AddDM()` 只是本地显示，不是直播间发言
4. DanmuAI 侧推送失败不能中断主链路
5. 插件侧网络失败不能拖慢宿主
6. 任何涉及 Qt 对象的主链路结果获取，都要走主线程安全边界

## 8. 当前实用排查法

### 8.1 按钮触发后弹幕姬没显示

先看 3 个点：

1. DanmuAI 是否真的生成了 AI 批次
2. DanmuAI 日志里是否有 `bililive_dm_push: ok` / `failed`
3. 弹幕姬日志里是否有 `push listener started`

### 8.2 评论桥接没显示

先看 3 个点：

1. 弹幕姬日志是否有 `收到评论：...`
2. 是否有 `bridge http failed` / `bridge timeout`
3. DanmuAI `/api/plugin/bililive-dm/reply` 是否还在监听

## 9. 推荐阅读顺序

后续继续扩展时，建议按这个顺序读：

1. [MODULE_OVERVIEW.md](MODULE_OVERVIEW.md)
2. [README.md](README.md)
3. [DanmuAiMockPlugin.cs](src/DanmuAiMockPlugin.cs)
4. [DanmuAiPushListener.cs](src/DanmuAiPushListener.cs)
5. [bililive_dm_bridge.py](../../app/web_api/bililive_dm_bridge.py)
6. [bililive_dm_bridge_service.py](../../app/application/bililive_dm_bridge_service.py)
7. [bililive_dm_contracts.py](../../app/application/bililive_dm_contracts.py)
8. [bililive_dm_push_service.py](../../app/application/bililive_dm_push_service.py)
9. [main_display_mixin.py](../../app/main_display_mixin.py)
10. [main_request_context_mixin.py](../../app/main_request_context_mixin.py)

## 10. 当前工单对应关系

- `W-BILILIVE-DM-PLUGIN-MOCK-001`
- `W-BILILIVE-DM-PLUGIN-BRIDGE-002`
- `W-BILILIVE-DM-PLUGIN-BRIDGE-003`
- `W-BILILIVE-DM-PLUGIN-PUSH-004`

如果后续要继续扩展，建议新工单命名继续沿用：

- `W-BILILIVE-DM-PLUGIN-*`
- 把“评论桥接”和“按钮主动推送”分成两条独立能力线维护
