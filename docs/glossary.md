# DanmuAI 术语表

> 适用范围：当前源码、维护者登记表、工单与完成报告。历史文档中的同名术语可能对应旧实现，使用前须核对日期和源码。

## 核心运行时术语

| 术语 | 定义 | 当前来源 | 最小示例 |
|------|------|----------|----------|
| façade | 对外公开的窄接口，用于阻止 Web/API 或服务直接读取 `DanmuApp._*` 私有字段 | `app/main_web_facade_mixin.py` | Web 路由调用 `build_status_snapshot()`，不读 `danmu_app._scene_generation` |
| GenerationPipeline / GP | 承载视觉回复解析、入队、消费和显示分发的应用服务；`reply_timer`、`reply_buffer` 所有权仍在 `DanmuApp` | `app/application/generation_pipeline.py` | `_on_ai_reply()` → `_dispatch_visual_reply_to_pipeline()` → GP |
| `scene_generation` | 当前场景代际版本。回复代际小于当前值时会被判为过期 | `app/main_request_context_mixin.py:_visual_reply_stale_reason` | `reason=scene_generation_lagged` |
| `screenshot_id` | 截图序号，用于关联请求、日志与运行态；它不等同于场景代际 | `app/application/generation_pipeline_state.py` | `request_round=12 screenshot_id=47 scene_generation=8` |
| `request_round` | 请求轮次。视觉请求通常为非负数；麦克风请求可使用负数区分元数据键 | `main.py`、`app/main_request_context_mixin.py` | `request_round=-3` 表示麦克风轨请求 |
| in-flight | 已发出但尚未完成释放的请求状态；视觉和麦克风分别计数 | `main.py`、`app/main_request_context_mixin.py` | `ai_in_flight=1` 时普通视觉 tick 不再启动第二个请求 |
| `inflight_watchdog_recover` | 视觉 in-flight 超过 `VISUAL_INFLIGHT_RECOVER_SEC` 时强制释放（扣减 `ai_in_flight`）；与仅告警的 `inflight_watchdog_warn` 不同 | `app/main_request_context_mixin.py:_try_recover_stale_visual_inflight` | `reason=inflight_watchdog_recover` |
| `use_thinking` | 配置键；默认关闭。开启且模型目录声明可切换时，经 `app/providers/thinking.py` 注入平台思考参数 | `app/config_defaults.py`、`app/ai_client_requests.py` | `"use_thinking": "0"` |
| `reason=` | 结构化日志中的机器可检索原因码，不应只看自然语言消息 | `main.py`、`app/application/generation_pipeline.py` | `reason=empty_parse`、`reason=scene_generation_lagged` |
| Boundary Guard | 读取源码与三份登记表，检查线程、状态、Web 私有访问和架构基线的仓库工具 | `scripts/boundary_guard.py`、`scripts/boundary_guard/` | `python scripts/boundary_guard.py` |

## 发布术语

| 术语 | 定义 | 当前来源 |
|------|------|----------|
| frozen | PyInstaller/Velopack 打包后的安装版运行态；与源码 `python main.py` 路径不同 | `app/bundle_paths.py`、`app/velopack_runtime.py` |
| `full.nupkg` | 包含完整应用版本的 Velopack 包 | `docs/operations/PACKAGING_WINDOWS.md` |
| `delta.nupkg` | 由发布侧 Velopack 根据版本产物生成的增量包；客户端不得自研二进制补丁 | `docs/operations/PACKAGING_WINDOWS.md` |
| stable / canary | 独立更新通道。stable 面向正式用户，canary 用于小范围验证 | `docs/operations/CANARY_RELEASE_CHANNEL.md` |

## 状态示例

```json
{
  "running": true,
  "queue_count": 3,
  "generation_pipeline": {
    "scene_generation": 8,
    "latest_screenshot_id": 47
  }
}
```

该示例只说明字段关系，不是完整 `/api/status` 契约；实际字段以 `app/application/runtime_state.py` 和 `status_snapshot.py` 为准。

## 维护规则

1. 新增跨文档术语时，先给出一句可判定定义，再列源码来源。
2. 同一术语在历史报告中含义不同，应在报告顶部标注快照日期，不覆盖当前定义。
3. 日志原因码、配置键和 API 字段使用代码原名，不翻译成新的别名。

## 文档治理术语

| 术语 | 定义 | 判定规则 |
|------|------|----------|
| 现行权威 | 当前可用于指导实现或验收的事实来源 | 按“源码事实 > 三份 Boundary Guard 登记表 > `AGENTS.md` > 项目上下文 > 当前工单/状态 > 历史报告”排序 |
| 历史快照 | 只记录某个日期或工单时点的状态，不自动代表当前行为 | 必须保留日期/工单身份；复用前重新核对源码和当前状态 |
| 本地断链 | Markdown 链接的目标在当前工作树中不存在 | 目标可唯一迁移时修复；历史目标无法唯一映射时登记“未保留”，不伪造替代文件 |
| active 工单 | 当前协作目录中的工单或历史混放材料 | 目录索引须区分工单、完成报告和状态简报；不要因目录位置把历史报告当待办 |
| 导入材料 | 从上游项目、工具或生成流程复制到工作树的只读文档 | 保留原文和来源，不强制套用本项目 H1/模板契约；在索引中标注来源 |
| 不可移植链接 | 绑定本机盘符或 `file:///` 的链接 | 目标仍存在时改为仓库相对链接；历史删除目标保留证据并标注不可恢复 |
| Setext 标题 | 使用下一行 `===` 或 `---` 表示标题的 Markdown 语法 | 结构扫描必须和 `#` ATX 标题一起识别，不能把上游 README 的 Setext 误报为无标题 |
| 凭据占位符 | 文档中的 `<..._API_KEY>` 等非秘密示例值 | 只允许出现在模板/示例中；真实值必须从文档、日志和命令行中移除并在供应商侧轮换 |
