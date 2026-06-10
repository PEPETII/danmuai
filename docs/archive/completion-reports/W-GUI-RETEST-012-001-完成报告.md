# Codex 完成报告

> 工单 ID：W-GUI-RETEST-012-001  
> 完成时间：2026-06-02  
> 执行者：Codex

---

## 1. 修改摘要

为 `W-REFACTOR-BUG-P0P1-012` 构造英文 locale 首装复测环境：通过 `LANG=en_US.UTF-8` + 临时 `APPDATA` 启动独立 `python main.py --web-browser` 进程，不污染真实配置目录；验证首装时 `language` 真实落库为 `zh`，`/api/meta` 也返回 `zh`，且无 API key 的启动提示仍为中文，关闭 012 的英文 locale GUI 前置缺口。

## 2. 修改的文件

- `docs/templates/Codex完成报告/W-REFACTOR-BUG-P0P1-012-完成报告.md`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/W-GUI-RETEST-012-001-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `main.py`：是
- 未修改 `app/**`：是
- 未修改 `web/static/**`：是
- 未修改 `community-site/**`：是
- 未修改 `supabase/**`：是

## 4. 运行的命令

```bash
python -c "from PyQt6.QtCore import QLocale; print(QLocale.system().name())"
$env:LANG='en_US.UTF-8'; python -c "from PyQt6.QtCore import QLocale; print(QLocale.system().name())"
python main.py --web-browser
GET  /api/session
GET  /api/meta
GET  /api/logs/recent
POST /api/start
GET  /api/status
```

复测环境额外约束：

- `APPDATA=E:/test/danmu/.pytest_tmp/appdata_en_locale`
- `LANG=en_US.UTF-8`
- `PYTHONPATH` 显式补入当前用户 site-packages（避免切换 `APPDATA` 后丢失 `idna/httpx`）

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 英文 locale 检测 | 通过 | `QLocale.system().name()` 从 `zh_CN` 变为 `en_US` |
| 首装配置落库 | 通过 | 临时 `config.db` 中 `language=zh` |
| 运行态 meta | 通过 | `/api/meta.language == "zh"` |
| 启动提示语言 | 通过 | `/api/logs/recent` 与 `status.error_message` 均为中文 |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 英文 locale 子进程启动 | `QLocale.system().name()` 为 `en_US` | `LANG=en_US.UTF-8` 下独立进程 `en_US` | 是 |
| 2 | 首装后语言默认值持久化 | `config.db` 中存在 `language=zh` | 临时 `config.db` 查询结果 `("language", "zh")` | 是 |
| 3 | Web meta 反映默认语言 | `/api/meta.language == "zh"` | 实测返回 `zh` | 是 |
| 4 | 无 API key 启动提示仍为中文 | 日志/状态错误文案为中文 | `未找到配置文件，已创建默认配置...`；`API Key 未配置，请在设置中填写` | 是 |

## 7. 风险与注意事项

- 本票使用 `LANG=en_US.UTF-8` 模拟英文 locale；证据链覆盖 Qt locale、首装落库和启动提示，但未要求真实切换整机 Windows 显示语言。
- 切换 `APPDATA` 会导致 Python 用户 site-packages 丢失，因此复测时额外补了 `PYTHONPATH`。

## 8. 发现但未处理的问题

- 当前正式未闭合项已从 GUI 补签转移到测试债务 / ROADMAP backlog。

## 9. 已更新的文档

- [x] [docs/templates/Codex完成报告/W-REFACTOR-BUG-P0P1-012-完成报告.md](W-REFACTOR-BUG-P0P1-012-完成报告.md)
- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] 本完成报告

## 10. 建议下一个工单

- 从 `docs/bug-audit/TEST-GAPS.md` §10 拆第一张测试债务票。
