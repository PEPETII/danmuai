# 兼容矩阵

当前行为以源码和对应测试为准。新增模型使用 registry 与 TTS V2；下表仍有真实历史数据或调用方，不能因名称包含 legacy 就删除。

| 兼容面 | 当前入口与用途 | 验证 | 退出条件 |
|---|---|---|---|
| TTS 旧模型 ID 与异常类型 | `app/tts_providers.py:synthesize_tts` 先查 V2 catalog，未注册的旧 ID 进入 adapter；V2 结果保留 `DanmuTtsError` 公共异常 | `tests/test_tts_v2_compat_bridge.py`、`tests/test_tts_provider_credential_isolation.py` | 完成旧 ID 的持久化迁移，读弹幕及虚拟主播调用方只走 V2，并证明旧配置仍能恢复或给出明确迁移错误 |
| 两份模型目录视图 | 现有 provider/model catalog 与 V2 导出分别服务已有选择器及审计 | `scripts/audit_model_catalog.py`、`tests/model_api/test_golden_request_contract.py` | 所有读取方改用同一合同，保留排序、默认值、模型能力与公开 ID；再删除旧视图 |
| 人格模型绑定 | `persona_model_bindings` 历史数据保留；当前运行时读取全局 `active_model_profile_id` | `tests/test_web_custom_models.py`、配置/模型迁移测试 | 明确旧版本回读与导入策略，完成历史绑定数据的可恢复迁移，确认无旧读取方 |
| 已废弃启动参数 | `app/main_launch.py:check_deprecated_launch_args` 对旧 Qt 主窗参数和禁用 Web 控制台入口返回 2 | `tests/test_deprecated_launch_flags.py` | 只有正式兼容策略变更才调整拒绝规则；删除代码不能意外恢复旧入口 |

退出前须检查源码调用方、持久化样本、错误与回退路径，并运行对应测试。当前没有真实用户版本分布或使用遥测，不能断言兼容调用已经归零。SDK 移除不改变上述兼容面：Doubao 请求沿用现有 HTTP adapter，凭据仍按 provider 隔离。
