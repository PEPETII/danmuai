# Codex 完成报告

> 工单 ID：W-REFACTOR-BUG-P0P1-012  
> 完成时间：2026-06-02  
> 执行者：Cursor Agent（Composer）

---

## 1. 修改摘要

修复 **BUG-016**：将 `language` 纳入 `CONFIG_DEFAULTS`（默认 `"zh"`），首装/缺键时由 `seed_config_defaults` 持久化；`DanmuApp.__init__` 经 `config_value_with_default` 读取，使 DB 值与运行时初始化路径一致，不再依赖空键 + `detect_system_language()` 隐式兜底。

## 2. 修改的文件

- `app/config_defaults.py` — `DEFAULT_LANGUAGE`、`CONFIG_DEFAULTS["language"]`
- `main.py` — `config_value_with_default(self.config, "language")` 初始化 `Translator`
- `tests/test_config_store.py` — 首装 seed 断言 + `test_config_value_with_default_language`
- `tests/test_p0_main_flow.py` — `test_init_language_uses_seeded_config_not_system_locale`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/W-REFACTOR-BUG-P0P1-012-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `web/static/`：是
- 未修改 `community-site/`：是
- 未修改 `app/web_console.py` / `app/web_api/`：是
- 未修改 `app/translations.py`：是
- 未修改 `docs/refactor/**`：是
- 未添加 Web 语言切换 UI：是

## 4. 运行的命令

```bash
python scripts/boundary_guard.py
python -m pytest tests/test_p0_main_flow.py tests/test_config_store.py -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| boundary_guard | 通过 | Boundary Guard: PASS |
| pytest（工单指定子集） | 通过 | 58 passed |

## 6. 手动验证步骤

W-MANUAL-SIGNOFF-001（2026-06-02）首次 GUI 补签时本机为 `zh-CN`；后续已由 W-GUI-RETEST-012-001（2026-06-02）补充英文 locale 首装复测。

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 清空 `%APPDATA%/DanmuAI/config.db` 后启动 | `language` 键存在且值为 `zh` | `test_first_run_seeds_config_defaults`（`language==zh`）；§5 **58 passed** | 是（自动化） |
| 2 | 英文系统 locale 下首装 | 托盘/启动 notice 为中文 | W-GUI-RETEST-012-001 以 `LANG=en_US.UTF-8` + 全新 `APPDATA` 子进程启动 `python main.py --web-browser`；`/api/meta.language == "zh"`，临时 `config.db` 中 `language=zh`，`/api/logs/recent` 含中文首装日志「未找到配置文件，已创建默认配置…」，`POST /api/start` 后 `status.error_message == "API Key 未配置，请在设置中填写"` | 是 |

## 7. 风险与注意事项

- 已有 `config.db` 但无 `language` 键的用户，下次启动会补种 `"zh"`（可能从隐式英文变为显式中文）。
- 用户已存 `language=en` 不受影响；Web 控制台仍无语言切换 UI。

## 8. 发现但未处理的问题

无（本票范围内）。

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] 本完成报告

## 10. 建议下一个工单

- 按 [docs/bug-audit/FIX-ORDER.md](../../bug-audit/FIX-ORDER.md) 继续 P1（如 BUG-017、BUG-018）。
