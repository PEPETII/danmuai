# Codex 完成报告

> 工单 ID：W-MODEL-CATALOG-PROBE-001  
> 完成时间：2026-05-30  
> 执行者：Cursor Agent

---

## 1. 修改摘要

对 `model_catalog.PLATFORM_CATALOGS` 中 **24** 个目录模型（doubao 6、dashscope 8、siliconflow 9、mimo 1；当前仓库 catalog 无第 25 条）在负责人提供的临时 Key 下执行 **文本 ping**（`app.api_probe.probe_connection`）与 **最小识图**（64×64 占位图 + adapter 视觉 content）live 验收。结果：**text 21/24、vision 23/24**。未修改 `app/` / `web/` / `tests/`；失败根因登记 ISSUE-027、ISSUE-028。

## 2. 修改的文件

- `docs/templates/工单/W-MODEL-CATALOG-PROBE-001-四平台目录模型连通验收.md`
- `docs/templates/Codex完成报告/W-MODEL-CATALOG-PROBE-001-完成报告.md`
- `docs/templates/已知问题记录/ISSUE-027-doubao-pro目录模型404.md`
- `docs/templates/已知问题记录/ISSUE-028-api_probe对百炼Omni模型max_tokens下限.md`
- `docs/已知问题与后续事项.md`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`

**未提交**：`.pytest_tmp/probe_catalog_live.py`、`.pytest_tmp/probe_results.json`（本地探测产物）

## 3. 未修改的关键区域

- 未修改 `app/`：是
- 未修改 `web/`：是
- 未修改 `main.py`：是
- 未修改 `tests/`：是

## 4. 运行的命令

```bash
# 环境变量（Key 来自 docs/templates/api.md，未写入仓库）
$env:DANMU_PROBE_DOUBAO_KEY='ark-***'
$env:DANMU_PROBE_DASHSCOPE_KEY='sk-***'
$env:DANMU_PROBE_SILICONFLOW_KEY='sk-***'
$env:DANMU_PROBE_MIMO_KEY='sk-***'

python .pytest_tmp/probe_catalog_live.py
python -m pytest tests/test_api_probe.py -q
git diff --name-only
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| live 探测 | 完成 | 24 模型 × 2 阶段；约 2.5 分钟 |
| pytest `test_api_probe` | 通过 | `4 passed` |
| boundary_guard | 未运行 | 未触达编排 |

## 6. 手动验证步骤

### 6.1 按服务商汇总

| provider | 模型数 | text 通过 | vision 通过 | 备注 |
|----------|--------|-----------|-------------|------|
| doubao | 6 | 5/6 | 5/6 | pro 404 |
| dashscope | 8 | 6/8 | 8/8 | 2× Omni text 400 |
| siliconflow | 9 | 9/9 | 9/9 | 全通过 |
| mimo | 1 | 1/1 | 1/1 | 全通过 |
| **合计** | **24** | **21/24** | **23/24** | |

### 6.2 明细矩阵

| provider | model_id | text | vision | 备注 |
|----------|----------|------|--------|------|
| doubao | doubao-seed-2-0-pro-260215 | 否 | 否 | 404 模型不存在 |
| doubao | doubao-seed-2-0-lite-260428 | 是 | 是 | |
| doubao | doubao-seed-2-0-mini-260428 | 是 | 是 | |
| doubao | doubao-seed-1-8-251228 | 是 | 是 | |
| doubao | doubao-seed-1-6-251015 | 是 | 是 | |
| doubao | doubao-seed-1-6-flash-250828 | 是 | 是 | |
| dashscope | qwen3-vl-flash | 是 | 是 | |
| dashscope | qwen3.5-flash | 是 | 是 | |
| dashscope | qwen-omni-turbo | 否 | 是 | text: max_tokens 须 ≥10 |
| dashscope | qwen2.5-omni-7b | 否 | 是 | text: max_tokens 须 ≥10 |
| dashscope | qwen-vl-plus | 是 | 是 | |
| dashscope | qwen3.5-plus | 是 | 是 | |
| dashscope | qwen3.6-flash | 是 | 是 | |
| dashscope | qwen-vl-max | 是 | 是 | |
| siliconflow | Qwen/Qwen3-VL-8B-Instruct | 是 | 是 | |
| siliconflow | Qwen/Qwen3-VL-8B-Thinking | 是 | 是 | |
| siliconflow | Qwen/Qwen3-VL-30B-A3B-Instruct | 是 | 是 | |
| siliconflow | Qwen/Qwen3-VL-30B-A3B-Thinking | 是 | 是 | |
| siliconflow | Qwen/Qwen3-Omni-30B-A3B-Instruct | 是 | 是 | |
| siliconflow | Qwen/Qwen3-Omni-30B-A3B-Thinking | 是 | 是 | |
| siliconflow | Qwen/Qwen3-Omni-30B-A3B-Captioner | 是 | 是 | |
| siliconflow | Qwen/Qwen3-VL-32B-Instruct | 是 | 是 | |
| siliconflow | zai-org/GLM-4.5V | 是 | 是 | |
| mimo | mimo-v2.5 | 是 | 是 | |

### 6.3 步骤核对

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 运行探测脚本 | 生成 `probe_results.json` | 24 行 JSON | 是 |
| 硅基 / MiMo 全绿 | 9+1 模型双通过 | 是 | 是 |
| 失败登记 ISSUE | ISSUE-027/028 | 已写模板 + 总表 | 是 |

## 7. 风险与注意事项

- 探测使用临时 Key，**不代表**所有用户账号对 `doubao-seed-2-0-pro-260215` 有开通；404 可能为账号/接入点权限而非目录错误。
- Web「测试连接」仍仅文本 ping（ISSUE-005）；本工单识图结果来自一次性脚本，**未**并入 `api_probe`。
- `api_probe` 对百炼 Omni 模型 `max_tokens=1` 会 400，但识图（16 tokens）与正式弹幕链路可用；见 ISSUE-028。
- 负责人应删除 `docs/templates/api.md` 明文 Key。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| ISSUE-027 | 目录 `doubao-seed-2-0-pro-260215` 对测试 ark Key 返回 404 | 是 |
| ISSUE-028 | `api_probe` 文本 ping `max_tokens=1` 不兼容百炼 Omni（须 ≥10） | 是 |
| ISSUE-005 | 产品内建 probe 仍不含识图 | 是（既有；本工单为补充 live 证据） |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/已知问题与后续事项.md](../../已知问题与后续事项.md)

## 10. 建议下一个工单

- 可选：`api_probe` 对 DashScope Omni 将 probe `max_tokens` 提至 10（修 ISSUE-028）
- 可选：将最小识图并入 `api_probe` 或 Web「测试连接」（延续 ISSUE-005）
- 负责人复核：是否从 catalog 移除/标注未开通的 `doubao-seed-2-0-pro-260215`（ISSUE-027）
