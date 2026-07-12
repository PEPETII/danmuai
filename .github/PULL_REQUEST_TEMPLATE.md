## 变更说明

简要描述本 PR 的目的和改动内容。

## 关联 Issue

Closes #

## 变更类型

- [ ] Bug 修复
- [ ] 新功能
- [ ] 文档更新
- [ ] 重构

## 自检清单

- [ ] 已记录基线 commit、开工前工作树状态和定向测试基线
- [ ] 已按改动范围分批运行相关 `tests/test_*.py -q -x`，并记录每批通过/失败数；未由 Agent 本地执行全量 pytest
- [ ] 未引入 API Key、日志、截图等敏感文件
- [ ] **Web/API/UI**：已运行相关 Web 测试批次并带 `-q -x`；触达编排、Web API 或 `DanmuApp` 主链路时已运行 `python scripts/boundary_guard.py`
- [ ] 如涉及 Web UI 变更，已对照 `prototype/Qwen_html_*.html`
- [ ] 已按需要更新 `README.md`、`docs/operations/CHANGELOG.md`、架构登记表或工单状态
- [ ] 已列出手动验证结果、未验证路径、兼容旧契约的消费者和回滚方式

## 验证结果与风险

- 实际运行的命令与结果：
- 未覆盖的路径（需谁手动验证）：
- 兼容旧客户端/缓存/服务端的说明：
- 回滚方式：

## 截图/录屏

如涉及 UI 变更，请附截图。请勿包含敏感内容。
