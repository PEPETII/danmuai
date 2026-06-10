# Codex 完成报告

> 工单 ID：W-PROMPT-001  
> 完成时间：2026-05-29  
> 执行者：Cursor Agent

---

## 1. 修改摘要

优化正式 AI 弹幕生成提示词体系：重写 `build_normal_reply_contract_zh/en`，在契约中集中规定 JSON 输出、条数、字数与直播间口语风格；将 16 个正式内置人格 `system_*` / `user_*` 压缩为短观众口吻，全局规则不再在每个人格重复；保留 legacy 契约正则以便 `strip_reply_contract` 剥离旧版 Web 覆盖。**未修改** `BUILTIN_PERSONAE["测试"]` 与主链路/解析器。

## 2. 修改的文件

- `app/personae.py`
- `tests/test_reply_contract.py`
- `tests/test_reply_parser.py`
- `tests/test_web_persona_api.py`
- `docs/templates/Codex完成报告/W-PROMPT-001-完成报告.md`（本文件）
- `docs/当前仓库状态.md`
- `docs/工单列表.md`

## 3. 未修改的关键区域

- 未修改 `main.py`：是
- 未修改 `app/ai_client.py`、`app/reply_parser.py`：是
- 未修改 `app/web_api/`（业务代码）：是
- 未修改 `web/`、`app/overlay.py`：是
- 未修改 `BUILTIN_PERSONAE["测试"]`：是（SHA256 回归单测锁定）
- 未修改 Boundary Guard 登记表、`requirements.txt`：是

## 4. 运行的命令

```bash
python -m pytest tests/test_reply_contract.py tests/test_reply_parser.py tests/test_web_persona_api.py -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest（人格/契约） | 通过 | 36 passed |
| boundary_guard | 未运行 | 未触达主链路登记 |

## 6. Token 成本估算（默认 `normal_reply_count=5`、`danmu_max_chars=15`、中文、单人格）

| 组成 | 优化前（约） | 优化后（约） |
|------|-------------|-------------|
| normal 契约 | ~95 字 | ~115 字（+口语/禁则规则） |
| 单人格 `system_zh` | ~25–50 字 | ~10–18 字 |
| `user_zh` | ~12–18 字 | 6 字（`看图发弹幕：`） |
| **合计（契约+人格+user）** | ~130–160 字 | ~125–145 字 |

- **每次 API 请求（正式人格）**：净节省约 **5–20 汉字（约 3–12 tokens）**；契约略增、人格显著缩短，整体略降或持平。
- **「测试」人格**：未改动，仍数百字；不在 `DEFAULT_ACTIVE`，不影响默认路径成本。
- **用户 Web 覆盖内置人格**：仍按用户保存长度计费（范围外）。

## 7. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| `pytest` 人格/契约相关 | 36 passed | 36 passed | 是 |
| `ensure_reply_contract` 拼接 | 契约在前、人格在后 | 单测覆盖 | 是 |
| `python main.py` 开弹幕 2–3 人格 | JSON 数组可解析上屏 | 待负责人确认 | 待填 |
| Web 人格详情 | 契约与 `system_custom` 分离显示 | 待负责人确认 | 待填 |
| 「测试」人格文案 | 与改前一致 | SHA256 单测 | 是 |

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| — | 无 | — |

## 9. 已更新的文档

- [docs/当前仓库状态.md](../../当前仓库状态.md)
- [docs/工单列表.md](../../工单列表.md)

## 10. 建议下一个工单

- 负责人手动跑一轮真实识图弹幕，主观验收「活人感/口语感」是否提升。
- 若需进一步降 token，可考虑将 `template.default_user_prompt` 与内置 `user_zh` 对齐为同一短句（本次仅改内置人格字段）。
