# Codex 完成报告

> 工单 ID：W-DANMU-TTS-001  
> 完成时间：2026-05-30  
> 执行者：Cursor Agent（Composer）

---

## 1. 修改摘要

实现读弹幕后端：屏上可见弹幕抽样（`DanmuEngine.visible_display_texts`）、MiMo `mimo-v2.5-tts` 非流式合成（`app/danmu_tts.py`）、WAV 本地播放（`sounddevice`）、主线程 `QTimer` + 池线程 HTTP（`DanmuReadService`）。仅在 `engine.running` 且开关开启时定时触发；播放/合成进行中跳过。独立 `tts_api_key_encrypted` 存储。

## 2. 修改的文件

- `app/danmu_engine.py`
- `app/danmu_tts.py`
- `app/danmu_tts_playback.py`
- `app/danmu_read_service.py`
- `app/config_store.py`
- `app/config_defaults.py`
- `main.py`
- `tests/test_danmu_tts.py`
- `tests/test_danmu_engine.py`（间接：引擎 API 被新测覆盖）

## 3. 未修改的关键区域

- 未修改 `web/`：是
- 未修改 `app/web_api/`：是
- 未修改 `app/ai_client.py` 视觉主链路：是
- 未修改 `requirements.txt`：是

## 4. 运行的命令

```bash
python -m pytest tests/test_danmu_tts.py tests/test_danmu_engine.py -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest（定向） | 通过 | 23 passed（引擎 + TTS） |
| boundary_guard | 未运行 | 002 完成后与全量一并跑 |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | config 写入 TTS Key + 开启读弹幕 | 定时器在 start 后运行 | 待 002 Web 或 config.set | 待负责人 |
| 2 | 开始生成、屏上有弹幕 | 周期性播放 | 待负责人 | 待负责人 |
| 3 | 停止生成 | 不再请求 TTS | 待负责人 | 待负责人 |

## 7. 风险与注意事项

- TTS HTTP 在 `QThreadPool`；播放 busy 时 skip，间隔过短可能多数 tick 空转（见 ISSUE-024）。
- 与麦克风同时可能争用默认音频输出设备。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| ISSUE-024 | TTS 非流式、长句等待 | 是 |
| ISSUE-025 | TTS Key 与视觉 Key 分离 | 是 |
| ISSUE-026 | 弹幕内风格标签未编辑 | 是 |

## 9. 已更新的文档

- （002 一并更新 `docs/WEB_CONSOLE.md`、`docs/工单列表.md`、`docs/当前仓库状态.md`）

## 10. 建议下一个工单

- W-DANMU-TTS-002（Web 侧栏与 `/api/danmu-read/*`）— 已完成同批次交付。
- 手动验收热修见 [W-DANMU-TTS-003-完成报告.md](W-DANMU-TTS-003-完成报告.md)（ISSUE-029～032）。
