# W-005：补充小米 MiMo-V2.5 系列模型目录

## 背景

W-004 已对齐 MiMo 请求体并将默认视觉模型固定为 `mimo-v2.5`。官方 2026-05-27 起 MiMo-V2.5 系列永久降价后，目录显示名与定价未更新；`mimo-v2.5-pro` 未收录导致手填 ID 触发「平台与模型不匹配」（ISSUE-004）。

## 目标

1. Web「小米 MiMo」下拉可见 **MiMo-V2.5**（`mimo-v2.5`）且价格为官方国内未命中缓存价（¥1.00 / ¥2.00 元/M tokens）。
2. 同下拉新增 **MiMo-V2.5-Pro**（`mimo-v2.5-pro`，¥3.00 / ¥6.00）。
3. 切换小米预设时默认仍为 **`mimo-v2.5`**。

## 依赖项

- W-004（MiMo 请求与默认模型）已完成

## 允许修改的区域

- `app/model_catalog.py`
- `app/model_providers.py`（`model_id_hint` 文案）
- `tests/test_model_catalog.py`
- `tests/test_web_console.py`
- `docs/工单列表.md`、`docs/当前仓库状态.md`、`docs/已知问题与后续事项.md`
- `docs/templates/工单/`、`docs/templates/Codex完成报告/`

## 禁止修改的区域

- `main.py`
- `app/ai_client.py`、`app/providers/`、`app/api_probe.py`
- `web/static/`、`app/web_api/`
- `requirements.txt`

## 需求

1. 将 `mimo-v2.5` 显示名改为 `MiMo-V2.5`，定价 input=1.0、output=2.0（元/M，未命中缓存）。
2. 新增 `mimo-v2.5-pro` 目录项，显示名 `MiMo-V2.5-Pro`，定价 input=3.0、output=6.0。
3. 保留 `mimo-v2-omni`；`default_catalog_model_id("mimo")` 仍为 `mimo-v2.5`。
4. 更新服务商预设 `model_id_hint` 文案。
5. 更新相关单测与文档。

## 非目标

- 不新增 `mimo-v2-flash`、TTS 系列
- 不改 MiMo adapter / probe 识图
- 不自动迁移用户已保存的 `mimo-v2-omni` 配置
- 不把默认模型改为 `mimo-v2.5-pro`

## 验收标准

- [x] `python -m pytest tests/test_model_catalog.py tests/test_web_console.py::test_model_catalog_api_payload -q` 通过
- [x] `GET /api/model-catalog` 中 mimo 含 3 个模型，`default_model_id` 仍为 `mimo-v2.5`
- [ ] 手动：Web 下拉可见 MiMo-V2.5、MiMo-V2.5-Pro；选 Pro 保存不报错

## 手动验证步骤

1. `python -m pytest tests/test_model_catalog.py tests/test_web_console.py -q -k "mimo or model_catalog"`
2. `python main.py` → 服务商「小米 MiMo」→ 默认 `mimo-v2.5` / 显示 MiMo-V2.5
3. 改选 MiMo-V2.5-Pro → 保存 → 刷新仍为 Pro

## 风险点

- 目录定价仅供 Web 展示与选择校验；实际计费以小米账单为准。
- `mimo-v2-omni` 官方将于 2026-06 起转发/下线，后续可单独开移除工单。

## 完成后必须更新的文档

- [ ] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [ ] [docs/工单列表.md](../../工单列表.md)
- [ ] [docs/已知问题与后续事项.md](../../已知问题与后续事项.md)（ISSUE-004）

## Codex 完成报告要求

- 使用 [Codex完成报告模板.md](../Codex完成报告/Codex完成报告模板.md)
- 输出 `docs/templates/Codex完成报告/W-005-完成报告.md`
