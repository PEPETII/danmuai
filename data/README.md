# Danmu data directory

| 路径 | 身份 | 用途 |
|------|------|------|
| `ai-platforms/` | 2026-06-29 生成快照 | Cherry Studio + LiteLLM 的 provider、模型和能力元数据；不是实时目录 |
| `personae_builtin.json` | 运行时资源 | 内置人格数据 |
| `pet/default/` | 运行时资源 | 内置 PetDex 桌宠包 |
| `prompt_eval/` | 评测 fixture | 人格候选与场景样本，不作为运行时配置 |

`ai-platforms/*.json` 的 `generatedAt` 与 `sourceFile` 是溯源依据；使用前需确认快照日期是否仍满足任务。仓库当前没有 `danmu_pool_zh.json` 或 `danmu_pool_zh_bootstrap.txt`，相关脚本见 [scripts/README.md](../scripts/README.md) 的历史数据管线说明。

## Desktop pet (PetDex format)

`pet/default/` — 内置桌宠素材（`pet.json` + `spritesheet.webp`，`yuexin-miao-animated`）。

用户可通过 Web「桌宠」页设置 `pet_asset_source=local` 与 `pet_asset_path` 指向本地 PetDex 包目录。

许可说明见 [ATTRIBUTION.md](ATTRIBUTION.md)。
