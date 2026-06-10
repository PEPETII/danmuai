# Codex 完成报告

> 工单 ID：W-AI-BUTLER-001  
> 完成时间：2026-05-31（含同日 UX 补充：思考中提示）  
> 执行者：Cursor Agent（Composer）

---

## 1. 修改摘要

在 Web 控制台新增 **「AI 管家」** 侧栏页：用户以自然语言咨询或调整「助手设置」相关项。后端 `POST /api/ai-butler/chat` 读取已保存的视觉 API（Endpoint/Key/Model/Mode），经同步 `httpx` 纯文本请求（不经 `AiWorker`、不占用 `ai_in_flight`），解析 JSON 后对白名单 17 字段做白名单校验；前端展示 patch 预览，用户点击「应用修改」后才 `POST /api/config` 持久化。

**UX 补充（同工单交付内）**：发送消息后聊天区显示助手气泡「正在思考中…」（轻量动画），输入框与发送按钮在等待期间禁用、按钮文案为「思考中…」，避免用户误以为无响应。

**FAQ 问答（W-AI-BUTLER-001 延续）**：扩展 `build_product_knowledge` + 系统提示词，支持使用说明/排障（如 DeepSeek 无预设、需视觉模型、401 排查）；纯问答时 `patch` 仍为空，不改 API 契约与白名单。

## 2. 修改的文件

- `app/web_api/ai_butler.py`
- `app/web_api/routes.py`
- `web/static/index.html`
- `web/static/app.js`（含 `showAiButlerThinking` / `setAiButlerInputBusy`）
- `web/static/warm-tokens.css`（含 `.ai-butler-thinking-bubble` 动画）
- `tests/test_ai_butler.py`
- `docs/WEB_CONSOLE.md`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/W-AI-BUTLER-001-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `main.py`：是
- 未修改 `app/ai_client.py` / `app/runnable.py` 主链路：是
- 未修改 `app/overlay.py` / `app/danmu_engine.py`：是
- 未修改 `requirements.txt`：是
- 思考中提示仅改 `web/static/`，未改后端管家逻辑：是
- 管家路由未直接 `invoke_on_main` 写配置：是（仅 `_read_api` + 外呼 AI）

## 4. 运行的命令

```bash
python -m pytest tests/test_ai_butler.py tests/test_web_console.py tests/test_web_custom_models.py tests/test_ai_client.py -q
python -m pytest tests/ -q
python scripts/boundary_guard.py
```

（思考中提示为纯前端变更，未新增单测；全量 pytest 在 W-AI-BUTLER-001 初版已通过。）

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest（定向） | 通过 | 11 passed（`test_ai_butler.py`，含 FAQ prompt 用例） |
| pytest（全量） | 通过 | 735 passed, 1 skipped（初版） |
| boundary_guard | 通过 | PASS（初版） |
| 思考中 UX | 未单独跑测 | 仅 `app.js` / `warm-tokens.css`；刷新页面即可验收 |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 侧栏可见「AI 管家」 | | 待负责人 |
| 2 | 未配置 API 时进入页面有提示 | | 待负责人 |
| 3 | 问「为什么不能用 DeepSeek？」 | 有排障说明；无配置预览表 | 待负责人 |
| 4 | 配置 API 后发送「帮我把弹幕调慢一点」 | 有回复 + `danmu_speed` 建议预览 | 待负责人 |
| 5 | 发送后、回复前 | 聊天区显示「正在思考中…」；输入禁用；按钮为「思考中…」 | 待负责人 |
| 6 | 收到回复后 | 思考气泡消失，显示正常助手回复 | 待负责人 |
| 7 | 未点「应用修改」时助手设置未变 | | 待负责人 |
| 8 | 点「应用修改」后设置页 `danmu_speed` 更新 | | 待负责人 |
| 9 | 启停弹幕主链路仍正常 | | 待负责人 |

## 7. 风险与注意事项

- 每次对话消耗视觉 API token；无计费展示。
- 部分模型 JSON 输出不稳定时走非 JSON 兜底（仅 `reply`，无 patch）。
- 豆包多轮 `assistant` 消息格式依赖 Responses API；若服务商不支持，可仅用单轮或 OpenAI 兼容端点。
- 请求较慢时「正在思考中…」会持续显示直至 HTTP 返回或报错；无单独超时 UI（与接口 60s 超时一致）。

## 8. 发现但未处理的问题

无（未记入 [docs/已知问题与后续事项.md](../../已知问题与后续事项.md)）。

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| — | — | — |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/WEB_CONSOLE.md](../../WEB_CONSOLE.md)
- [x] 本完成报告

## 10. 建议下一个工单

- 为 AI 管家增加「仅解释常用设置」快捷问题按钮（纯前端，可选）。
- 若豆包多轮 assistant 格式不稳定，可拆 W-xxx 做服务商专项兼容。
- 可选：请求超时后在聊天区显示可重试提示（与思考中状态区分）。
