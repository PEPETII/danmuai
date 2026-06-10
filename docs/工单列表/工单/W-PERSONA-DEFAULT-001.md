# 工单 ID

W-PERSONA-DEFAULT-001

## 工单标题

测试1–3 内置系统提示词 + 默认活跃人格 6 项

## 背景

负责人已在人格工坊调试测试1–3 的系统提示补充，并希望将其固化为内置默认；默认活跃人格改为测试1–3 + 吐槽型 + 傲娇型 + 腹黑型。

## 目标

1. 将本机 `custom_personae` 中测试1–3 的 system 补充段写入 `personae_builtin.json` 的 `system_zh`
2. `DEFAULT_ACTIVE` 设为上述 6 人格；`active_personae_version` 升至 7 并迁移

## 允许修改的区域

- `data/personae_builtin.json`
- `app/persona_manager.py`
- `app/personae.py`
- `tests/test_reply_contract.py`
- `tests/test_web_persona_api.py`
- `docs/`

## 验收标准

- [x] 首装 / v7 迁移后活跃人格为 6 项
- [x] 测试1–3 恢复默认后 `system_zh` 为新文案
- [x] 相关 pytest 分批通过

## 完成后必须更新的文档

- [x] docs/workflow/当前仓库状态.md
- [x] docs/workflow/工单列表.md
- [x] 完成报告
