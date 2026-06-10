# Codex 完成报告

> 工单 ID：W-DANMU-TTS-002  
> 完成时间：2026-05-30  
> 执行者：Cursor Agent（Composer）

---

## 1. 修改摘要

Web 侧栏新增「读弹幕」页：TTS API Key、间隔、开关、预置音色、风格指令；`GET/PUT /api/danmu-read/config` 与 `POST /api/danmu-read/probe`（试听）。配置不经 `PUT /api/config`；写操作经 `invoke_on_main` 调用 `DanmuApp.apply_danmu_read_config` / `run_danmu_read_probe`。

## 2. 修改的文件

- `web/static/index.html`
- `web/static/app.js`
- `app/web_api/danmu_read.py`
- `app/web_api/routes.py`
- `tests/test_danmu_read_api.py`
- `docs/WEB_CONSOLE.md`
- `docs/工单列表.md`
- `docs/当前仓库状态.md`
- `docs/已知问题与后续事项.md`
- `docs/templates/Codex完成报告/W-DANMU-TTS-001-完成报告.md`
- `docs/templates/Codex完成报告/W-DANMU-TTS-002-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `app/ai_client.py`：是
- 未修改助手设置 `WEB_CONFIG_KEYS`：是
- 未改 `main.py` 截图/AI 主链路顺序：是（仅既有 façade）

## 4. 运行的命令

```bash
python -m pytest tests/test_danmu_read_api.py tests/test_danmu_tts.py -q
python scripts/boundary_guard.py
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest（读弹幕相关） | 通过 | 13+23 |
| boundary_guard | 见命令输出 | 触达 main/web_api |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 侧栏「读弹幕」→ 填 Key → 保存 → 试听 | 有声音或明确错误 | 待负责人 | 待负责人 |
| 2 | 启用、间隔 5s → 开始生成 | 随机朗读屏上弹幕 | 待负责人 | 待负责人 |
| 3 | 停止生成 | 不再朗读 | 待负责人 | 待负责人 |
| 4 | 重启应用 | 配置保留 | 待负责人 | 待负责人 |

## 7. 风险与注意事项

- 试听与正式朗读均消耗 MiMo TTS 配额（文档称限时免费）。
- GET `api_key` 仅掩码 `********`。

## 8. 发现但未处理的问题

同 W-DANMU-TTS-001（ISSUE-024～026）。

## 9. 已更新的文档

- `docs/WEB_CONSOLE.md`
- `docs/工单列表.md`
- `docs/当前仓库状态.md`
- `docs/已知问题与后续事项.md`

## 10. 建议下一个工单

- 无必须项；可选：TTS 流式播放或助手设置页跳转说明。
- 验收热修见 [W-DANMU-TTS-003-完成报告.md](W-DANMU-TTS-003-完成报告.md)。
