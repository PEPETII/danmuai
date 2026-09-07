# Danmu data directory

| 路径 | 身份 | 用途 |
|------|------|------|
| `ai-platforms/` | 2026-06-29 生成快照 | Cherry Studio + LiteLLM 的 provider、模型和能力元数据；不是实时目录 |
| `personae_builtin.json` | 运行时资源 | 内置人格数据 |
| `prompt_eval/` | 评测 fixture | 人格候选与场景样本，不作为运行时配置 |

`ai-platforms/*.json` 的 `generatedAt` 与 `sourceFile` 是溯源依据；使用前需确认快照日期是否仍满足任务。仓库当前没有 `danmu_pool_zh.json` 或 `danmu_pool_zh_bootstrap.txt`，相关脚本见 [scripts/README.md](../scripts/README.md) 的历史数据管线说明。
