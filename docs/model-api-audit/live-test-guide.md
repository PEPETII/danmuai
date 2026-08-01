# Batch6 Live Test 指南

> 默认策略：**关闭**。
> 文档日期：2026-08-01。
> 本文件不包含 API Key，不要求 CI 配置 secret，也不把真实 API/UI 结果写成已验证。

## 1. 当前状态

工单 05 规定 live smoke test 必须显式开启、一次只测一个 provider、限制输出和费用，并且默认测试不能发真实付费请求。当前仓库检查未发现可直接执行的 `DANMUAI_LIVE_*` 测试 harness、live pytest 文件或 CI secret gate；当前已验证的是 `app/api_probe.py` 的分级探活实现和离线 mock/契约测试。

因此：

- 不设置显式 live 开关时，不得发起真实 API 请求；
- 当前 Batch6 不声称 live runner 已实现；
- 真实 provider、账号模型可见性、费用、限流和完整 API/UI 联调均为 **未验证/pending**；Batch5 Browser 只有 shell/partial 控件静态检查证据；
- 若主代理后续提供 runner 与证据，应把命令、provider、model 来源、时间、状态码类别和退出码补入 final gate，不把 key 或完整响应提交。

## 2. 推荐分层顺序

真实验证应沿用代码中的阶段名，并由用户显式选择：

| stage | 目的 | 外部影响 |
|---|---|---|
| `local` | URL、mode、model 非空和 planner 解析 | 不发网络；当前已有离线证据 |
| `auth_model` | `/models` 或等价模型可见性 | 可能发网络；只证明账号可见性，不证明视觉/音频 |
| `text` | 极短文本最小生成 | 可能计费；低 token、单模型 |
| `vision` | 内置 1×1 测试图片验证 content part | 可能计费；禁止用户截图 |
| `audio` | 内置短静音 fixture 验证音频字段 | 可能计费；显式点击后才允许 |
| `stream` | SSE/事件、reasoning 和 usage | 可能计费；只允许诊断/开发验证 |

`auth_model` 返回模型可见并不等于模型支持视觉；代码当前会保留 `vision` 未验证提示。不能用一次 text 成功替代 vision/audio/stream 验收。

## 3. 安全运行约束

1. Key 只从当前用户进程环境或本地安全配置读取，不写入仓库、文档、fixture、截图、console、异常文本或测试报告。
2. 不在命令行参数、PowerShell 历史、URL query、日志和截图中传递或打印 Key。
3. 运行前只选择一个 provider 和一个已由官方页面或账号 `/models` 证实的 model ID；不能遍历 19 个 catalog，也不能把静态 catalog 当作账号可用性。
4. 使用内置公开测试图片/短音频；禁止上传用户截图、麦克风原音、聊天内容、支付页或企业内部页面。
5. 输出 token、请求数量、超时和费用预算必须预先设定；达到预算、收到 401/403/402/429、出现异常 endpoint 或返回敏感响应时立即停止。
6. 只保留脱敏摘要：provider、model 是否由账号发现、stage、HTTP 状态码类别、错误分类、request ID（若不含敏感内容）和退出码；不保留完整响应。
7. CI 默认不需要、也不应存放 live secret。live 结果不能成为默认 PR 门禁。

## 4. 环境变量策略

工单 05 中的变量名可作为后续 runner 的接口约定：

```text
DANMUAI_LIVE_API_TESTS
DANMUAI_LIVE_PROVIDER
DANMUAI_LIVE_MODEL
DANMUAI_LIVE_API_KEY
DANMUAI_LIVE_ENDPOINT
DANMUAI_LIVE_MAX_COST_USD
```

本文件不提供任何变量值。后续 runner 必须满足：

- `DANMUAI_LIVE_API_TESTS` 缺失、为空或不是明确的启用值时直接跳过，不创建 HTTP client；
- provider/model/endpoint 缺失时停止并报告配置错误；
- API Key 只在内存中传递给请求规划器/HTTP client，输出统一脱敏；
- max cost 未设置或无法解析时停止，不使用无限预算默认值；
- 单次运行只允许一个 provider，不自动 fallback 到另一个 provider；
- 401/403/402/429/timeout 应分别记录为认证、权限、配额、限流或不可判定，不伪装成实现失败或成功。

如果尚无满足这些条件的 runner，保持 live tests 未实现/未验证，不手工执行真实请求来补“通过”数字。

## 5. 待补证据

主代理需要提供以下证据后，才能关闭本指南的 pending 状态：

- runner 文件、显式开关实现和默认关闭测试；
- 脱敏后的实际命令、provider/model 来源、stage、退出码和分类结果；
- 费用/请求次数控制结果；
- 至少一条真实模型可见性与一条真实文本/多模态结果，且无敏感数据；
- 浏览器 UI 实际触发探活并正确显示 unknown/迁移/错误状态的证据；Batch5 的 shell/partial 静态检查不能替代该证据；
- 完整 API 联调的请求、响应分类和 UI 状态更新证据。

## 6. 官方资料入口

平台官方来源和索引核验日见 [`08_官方资料索引.md`](../danmuai_model_api_audit_2026-08-01/danmuai_model_api_audit_2026-08-01/08_官方资料索引.md)，该索引记录日期为 **2026-08-01**。来源页只能用于核对协议/字段；精确 model ID、价格和账号可用性仍须官方页面或账号 discovery 证据，不得由营销名称推断。
