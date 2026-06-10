# Codex 完成报告

> 工单 ID：W-DANMU-TTS-003  
> 完成时间：2026-05-30  
> 执行者：Cursor Agent（Composer）

---

## 1. 修改摘要

读弹幕功能交付后的**手动验收热修**：修复「不朗读 / 仅读几个字 / 退出崩溃 / 句末硬切」四类问题。核心改动：`DanmuReadService` 挂到 `DanmuApp` 生命周期（`shutdown` + `shiboken6.isValid` 安全 emit）；合成 in-flight 保持至 `playback_finished`，避免定时 tick 触发新的 `sd.play` 打断上一句；试听支持请求体传入未保存的 `api_key`；播放前追加约 80ms 淡出 + 1s 静音尾韵。Web 页补充间隔说明（建议 ≥15s）。

## 2. 修改的文件

- `app/danmu_read_service.py`
- `app/danmu_tts_playback.py`
- `app/web_api/danmu_read.py`（probe `api_key` 覆盖，001/002 已含，本批确认行为）
- `main.py`（`DanmuReadService(self)` 父对象、`quit()` → `shutdown()`）
- `web/static/index.html`
- `tests/test_danmu_tts.py`
- `docs/templates/Codex完成报告/W-DANMU-TTS-003-完成报告.md`
- `docs/templates/已知问题记录/ISSUE-029-*.md` … `ISSUE-033-*.md`
- `docs/已知问题与后续事项.md`
- `docs/工单列表.md`
- `docs/当前仓库状态.md`

## 3. 未修改的关键区域

- 未修改 `app/ai_client.py` 视觉主链路：是
- 未修改 `app/danmu_engine.py` 轨道/去重逻辑（001 已加 `visible_display_texts`）：是
- 未修改 `PUT /api/config` 与 `WEB_CONFIG_KEYS`：是
- 未修改 `requirements.txt`：是

## 4. 运行的命令

```bash
python -m pytest tests/test_danmu_tts.py tests/test_danmu_read_api.py -q
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| pytest（读弹幕） | 通过 | `test_danmu_tts.py` 10 项 + `test_danmu_read_api.py` |
| boundary_guard | 未重跑 | 未改 boundary 登记字段语义 |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 读弹幕页填 Key → **未保存**点试听 | 有声音或明确错误 | 待负责人 | 待负责人 |
| 2 | 保存、启用、间隔 ≥15s → 开始生成 | 日志含 `danmu read: synthesizing` / `playback started` | 待负责人 | 待负责人 |
| 3 | 长句朗读 | 整句播完，句末有约 1s 留白，非硬切 | 待负责人 | 待负责人 |
| 4 | 播放中退出应用 | 无 `DanmuReadService has been deleted` | 待负责人 | 待负责人 |

## 7. 风险与注意事项

- 每句实际播放时长 = API WAV 时长 + **约 1s** 尾韵；间隔须大于「合成 + 播放」总和（UI 已提示 ≥15s）。
- `quit()` 仍 `waitForDone(2000)`，极长句播放中强退可能仍有竞态（见 ISSUE-033）。
- 播放线程为 daemon，退出时不调用 `sd.stop()`，依赖自然播完或进程结束。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| ISSUE-029 | 未保存 Key / 信号线程导致不朗读 | 是（**已修复**） |
| ISSUE-030 | `_tts_in_flight` 过早释放致播放被打断 | 是（**已修复**） |
| ISSUE-031 | 退出后池线程 emit 已销毁 QObject | 是（**已修复**） |
| ISSUE-032 | 句末听感生硬截断 | 是（**已修复**） |
| ISSUE-033 | `waitForDone(2000)` 短于长 TTS 播放 | 是 |
| ISSUE-024～026 | 原 TTS 产品/架构项 | 是（仍开放） |

## 9. 已更新的文档

- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] [docs/已知问题与后续事项.md](../../已知问题与后续事项.md)
- [x] 本完成报告与 ISSUE-029～033 模板

## 10. 建议下一个工单

- 可选：退出时按 TTS busy 延长 `waitForDone` 或文档化「播放中请稍候再退出」（ISSUE-033）。
- 可选：TTS 流式/边下边播（ISSUE-024）。
