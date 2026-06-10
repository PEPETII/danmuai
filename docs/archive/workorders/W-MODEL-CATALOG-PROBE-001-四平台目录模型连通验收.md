# 工单：W-MODEL-CATALOG-PROBE-001

## 工单 ID

W-MODEL-CATALOG-PROBE-001

## 工单标题

四平台 model_catalog 模型文本 + 识图 live 验收

## 背景

负责人提供临时 API Key（`docs/templates/api.md`，验收后删除），需验证 Web 视觉模型选择器目录中各 `model.id` 是否可被当前 `api_probe`（文本）及主链路视觉请求格式（识图）调用。

## 目标

产出 25 模型 × 2 阶段（text / vision）连通矩阵、Codex 完成报告；失败项登记 ISSUE，不在当次修改 `app/`。

## 依赖项

- 本机已 `pip install -r requirements.txt`
- 可访问外网 API
- 临时 Key（环境变量，不入库）

## 允许修改的区域

- `docs/templates/工单/`
- `docs/templates/Codex完成报告/`
- `docs/templates/已知问题记录/`
- `docs/已知问题与后续事项.md`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`

## 禁止修改的区域

- `app/`
- `web/`
- `main.py`
- `tests/`
- `requirements.txt`、锁文件
- 勿提交 `docs/templates/api.md` 含明文密钥

## 需求

1. 对 `model_catalog.PLATFORM_CATALOGS` 中 doubao / dashscope / siliconflow / mimo 共 25 个模型执行 `probe_connection` 文本探测。
2. 对同一批模型执行最小识图请求（`placeholder_image_data_uri` + adapter 视觉 content）。
3. 结果写入 `.pytest_tmp/probe_results.json`（不 git add）。
4. 按模板输出完成报告与失败 ISSUE。
5. 更新工单列表与当前仓库状态。

## 非目标

- 不修复 probe/adapter 代码
- 不测智谱 / Moonshot（无 Key）
- 不做开麦 `input_audio` 全链路
- 不以全量 pytest 作为本工单门禁

## 验收标准

- [x] 25 个模型均完成 text 探测并记录
- [x] 25 个模型均完成 vision 探测并记录
- [x] 完成报告含 per-provider 汇总与失败明细
- [x] 失败项已写入 ISSUE-023+
- [x] `git diff` 无 `app/`、`web/`、`tests/` 变更

## 手动验证步骤

1. 设置 `DANMU_PROBE_*_KEY` 环境变量后运行 `.pytest_tmp/probe_catalog_live.py`。
2. 打开 `docs/templates/Codex完成报告/W-MODEL-CATALOG-PROBE-001-完成报告.md` 核对矩阵。
3. `git diff --name-only` 确认仅 docs 变更。

## 风险点

- 约 50 次 API 调用产生费用；可能遇 429 限流。
- 密钥不得写入完成报告正文。

## 完成后必须更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/已知问题与后续事项.md](../../已知问题与后续事项.md)

## Codex 完成报告要求

- [docs/templates/Codex完成报告/W-MODEL-CATALOG-PROBE-001-完成报告.md](../Codex完成报告/W-MODEL-CATALOG-PROBE-001-完成报告.md)
