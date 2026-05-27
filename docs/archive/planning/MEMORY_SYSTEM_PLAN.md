# 场景状态记忆系统升级实施规划

> **Archived.** Current behavior: [ARCHITECTURE.md](../../ARCHITECTURE.md#memory-modes), [WEB_CONSOLE.md](../../WEB_CONSOLE.md). Source: `app/memory/`.

## 目标

将进程内 `scene_memory` 升级为双轨「场景状态记忆 + 弹幕去重记忆」，保持不持久化、低成本，并兼容 `memory_mode=off` / `scene_card`。

## memory_mode 四档

| UI | 值 | 注入 |
|----|-----|------|
| 关闭 | `off` | 无 |
| 轻量 | `dedup_only` | 去重 + 约束 |
| 标准 | `scene_card` | 场景状态 + 去重 + 约束 |
| 强记忆 | `strong` | 同标准，更大 prompt 预算与场景切换 carry |

## 场景切换策略

| policy | SceneContextMemory | BulletDedupMemory |
|--------|-------------------|-------------------|
| strict | 全新空卡（仅 tone_hint） | 清空 |
| medium | 保留 confidence≥0.6 的 stable_facts + tone_hint；清 volatile/open_threads/last_focus/summary | 清空 |
| loose | 保留 stable；summary/last_focus 压缩 carryover；open_threads≤2 | 保留 min(3, window) bullets |

`strong` + medium：若 stable_facts 为空，将上一场景 scene_summary 写入低置信 stable 锚点。

## 模块布局

| 路径 | 职责 |
|------|------|
| `app/memory/types.py` | VisualMemoryUpdate、DisplayedBullet、常量 |
| `app/memory/scene_context.py` | SceneContextMemory |
| `app/memory/bullet_dedup.py` | BulletDedupMemory |
| `app/memory/store.py` | SceneMemoryStore 门面 |
| `app/memory/visual_update.py` | 信封解析与 batch 推断 |
| `app/memory_prompt_builder.py` | 三段 prompt + 字符预算 |
| `app/scene_memory.py` | 兼容 re-export |

## 分阶段 checklist

- [x] 阶段 0：本文档 + AGENTS.md
- [x] 阶段 1：`app/memory/*` + `memory_prompt_builder` + store 单元测试
- [x] 阶段 2：`web_console` 四档校验
- [x] 阶段 3：`reply_parser` 信封 + `main.py` 钩子
- [x] 阶段 4：Web UI 三控件
- [x] 阶段 5：清理旧 API + WEB_CONSOLE.md

## 验收命令

```bash
python -m pytest tests/test_scene_memory.py tests/test_memory_prompt_builder.py tests/test_web_console.py -q
python -m pytest tests/ -q
```

## 非目标

- 数据库 / 向量库 / 跨会话持久化
- 修改 DanmuEngine 去重、live_freshness stale
- 麦克风路径记忆注入
