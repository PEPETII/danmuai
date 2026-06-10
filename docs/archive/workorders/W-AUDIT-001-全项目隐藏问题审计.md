# W-AUDIT-001 全项目隐藏问题审计

---

## 工单 ID

`W-AUDIT-001`

## 工单标题

DanmuAI 全项目隐藏问题审计

## 背景

当前仓库已完成多轮 Web 控制台、pywebview、单实例、Provider 适配层、麦克风与 TTS 相关交付，但缺少一次面向真实用户场景的全项目健康检查。  
本工单用于对启动链路、Web/API、截图、AI 调用、Overlay、配置持久化、测试/CI、打包发布和可诊断性做只读审计，并形成正式报告。

## 目标

- 产出一份完整的全项目隐藏问题审计报告，覆盖启动、主链路、Web、配置、并发、打包和测试基线。
- 所有高优先级问题都要给出代码位置、风险原因、影响范围、最小修复建议和验证方式。
- 同步更新工单列表、当前仓库状态和 Codex 完成报告。

## 依赖项

- 无

## 允许修改的区域

- `docs/audits/full-project-hidden-issues-audit.md`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/W-AUDIT-001-完成报告.md`
- `docs/templates/工单/W-AUDIT-001-全项目隐藏问题审计.md`

## 禁止修改的区域

- `main.py`
- `app/**`
- `web/static/**`
- `tests/**`
- `requirements.txt`
- `requirements-dev.txt`
- `pyproject.toml`
- `DanmuAI.spec`
- `scripts/**`

## 需求

1. 先阅读项目边界文档、主入口和关键模块，只做静态审计，不修改业务代码。
2. 对启动链路、Web 控制台链路、截图链路、API 调用链路、弹幕上屏链路、配置保存链路分别做审查。
3. 对以下主题做全文检索并人工归类：
   `danmu_app._`、`_trigger_api_call`、`_consume_reply_queue`、`QTimer`、`QThreadPool`、`sqlite`、`conn`、`config`、`status`、`snapshot`、`request_started_at`、`last_api_trigger_at`、`model`、`endpoint`、`provider`、`websocket`、`pywebview`、`tray`、`overlay`
4. 审计报告必须包含：
   P0/P1/P2 问题分级、架构边界风险、性能风险、用户真实场景风险、建议修复顺序、建议新增测试、建议验证命令、本次不建议修改的内容。
5. 本工单完成后必须同步更新 `docs/工单列表.md`、`docs/当前仓库状态.md` 和 Codex 完成报告。

## 非目标

- 不修复本轮发现的问题
- 不重构 `DanmuApp`、`DanmuEngine`、`Overlay`、pywebview 架构
- 不改动 `main.py`、`app/`、`web/static/`、`tests/`、打包脚本和依赖清单

## 验收标准

- [ ] 只产生文档 diff
- [ ] 已生成 `docs/audits/full-project-hidden-issues-audit.md`
- [ ] 报告覆盖 12 个约定章节
- [ ] 每个高优先级问题都有文件路径、函数名、代码证据、触发条件、影响、修复建议、验证方式
- [ ] `docs/工单列表.md` 已登记并标记 `W-AUDIT-001` 已完成
- [ ] `docs/当前仓库状态.md` 已同步本工单摘要与验证结果
- [ ] 已生成 `docs/templates/Codex完成报告/W-AUDIT-001-完成报告.md`

## 手动验证步骤

1. 打开 `docs/audits/full-project-hidden-issues-audit.md`，确认 12 个章节完整可读。
2. 打开 `docs/工单列表.md`，确认存在 `W-AUDIT-001` 且状态为已完成。
3. 打开 `docs/当前仓库状态.md`，确认已追加 `W-AUDIT-001` 审计摘要、执行命令和关键发现。
4. 运行 `git diff --name-only`，确认仅包含文档文件。

## 风险点

- 本地仓库当前已存在未提交文档变更，更新时必须避免覆盖无关内容。
- 审计报告若把测试中的故意违规样例误当作生产问题，会造成误报。
- 真实桌面场景（OBS、全屏游戏、WebView2 缺失）若未真机验证，只能标注为高风险待验，不能伪装成已证实问题。

## 完成后必须更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/audits/full-project-hidden-issues-audit.md](../../audits/full-project-hidden-issues-audit.md)
- [x] [docs/templates/Codex完成报告/W-AUDIT-001-完成报告.md](../Codex完成报告/W-AUDIT-001-完成报告.md)

## Codex 完成报告要求

- 使用 [Codex完成报告模板.md](../Codex完成报告/Codex完成报告模板.md)
- 必须列出全部修改文件路径
- 必须明确说明未修改 `main.py`、`app/`、`web/static/`、`tests/`
- 必须记录实际执行的验证命令与结果
