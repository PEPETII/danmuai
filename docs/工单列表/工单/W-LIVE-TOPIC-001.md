# W-LIVE-TOPIC-001 — 人格工坊新增「提示内容」输入框并接入 AI 弹幕生成提示词

> **来源**：用户需求（2026-06-06 讨论确立）
> **执行者**：Codex / Cursor Agent
> **优先级**：中（提升直播氛围感，行为零侵入）
> **预计工时**：5–10 分钟
> **风格参考**：[W-NICKNAME-001 完成报告](../templates/Codex完成报告/W-NICKNAME-001-完成报告.md)（同样为人格工坊全局设定 + 注入 system 提示）

---

## 工单 ID

`W-LIVE-TOPIC-001`

## 工单标题

人格工坊新增「提示内容」输入框（全局直播主题）并注入 AI 弹幕生成 system 提示词

## 背景

- 用户希望增加直播氛围感：在「人格工坊」顶部新增一个输入框「提示内容」，用于告知 AI "本次直播主题/即将要玩什么游戏"，让 AI 在生成弹幕时自然贴合。
- 与现有「昵称」（W-NICKNAME-001）同属"全局用户级设定"层级：跨所有人格共用，不跟随具体人格。
- 已有先例可参考：
  - W-NICKNAME-001 的 `append_nickname_to_system_pt` 函数 + `app/config_defaults.py` 白名单 + `app/application/config_service.py:WEB_CONFIG_KEYS` + `main.py` 两处 system_pt 拼接点。
  - 「昵称」输入框在 `web/static/index.html:872-884` 的位置与交互（textarea + 保存按钮 + `loadUserNickname` / `saveUserNickname`）。

## 目标

完成后：

1. 人格工坊卡片顶部（昵称上方）出现「提示内容」textarea 与「保存主题」按钮。
2. 输入并保存的内容持久化到 `%APPDATA%/DanmuAI/config.db`（`config` 表 `key='live_topic'`）。
3. 每次 AI 请求前，`main.py` 在 `append_nickname_to_system_pt` 之后追加 `append_live_topic_to_system_pt`，将直播主题写入 system 提示词。
4. 留空时，system 提示词与未启用本功能前**逐字节一致**（空值零侵入）。
5. 切换不同人格，主题行保持一致（证明是全局而非跟人格）。

## 依赖项

- W-NICKNAME-001 已完成（`append_nickname_to_system_pt` 在 `app/persona_contract.py` 已落地）。
- 现有 `PUT /api/config` 与 `GET /api/config` 已支持任意 string key。
- 现有 `app/application/config_service.py:WEB_CONFIG_KEYS` 是白名单，需要追加新 key 才能让 `GET /api/config` 暴露。

## 允许修改的区域

- `app/persona_contract.py`（追加 `LIVE_TOPIC_MAX_LEN` 常量、`_LIVE_TOPIC_LINE_ZH`/`_LIVE_TOPIC_LINE_EN` 模板、`_read_live_topic` 内部函数、`append_live_topic_to_system_pt` 公开函数）
- `app/personae.py`（仅 `__all__` 列表追加 `"append_live_topic_to_system_pt"`、`"LIVE_TOPIC_MAX_LEN"` 导出）
- `app/application/config_service.py`（`WEB_CONFIG_KEYS` 元组末尾追加 `"live_topic"`）
- `app/config_defaults.py`（`CONFIG_DEFAULTS` dict 追加 `"live_topic": ""` 默认值）
- `main.py`（import 区追加 `append_live_topic_to_system_pt`；第 523 行附近与第 899 行附近的 system_pt 拼接各加一行调用）
- `web/static/index.html`（人格工坊 section 第 871 行前/第 885 行前插入新 div 块）
- `web/static/app.js`（追加 `loadLiveTopic` / `saveLiveTopic` 函数；`loadPersonaEditor` 末尾挂载；`#btnSaveLiveTopic` click 监听）
- `tests/test_web_persona_api.py`（新增用例）
- `tests/test_reply_contract.py`（可选，验证 `append_live_topic_to_system_pt` 行为）
- `docs/workflow/当前仓库状态.md`（追加 W-LIVE-TOPIC-001 最近变更段）
- `docs/WEB_CONSOLE.md`（「人格工坊」节加新输入框 + config key 说明）
- `docs/CHANGELOG.md`（行为变更条目）
- `docs/workflow/工单列表.md`（本工单登记为「已完成」）
- `docs/templates/Codex完成报告/W-LIVE-TOPIC-001-完成报告.md`（新建完成报告）

## 禁止修改的区域

- `app/persona_manager.py`（无关）
- `app/persona_builtin.py`、`app/persona_version_history.py`（无关）
- `app/ai_client.py`、`app/overlay.py`、`app/danmu_engine.py`（与提示词无关）
- `app/mic_*.py`、`app/memory/`（麦克风 / 记忆与本功能无关）
- `app/web_api/` 全部（不需要新端点，PUT/GET /api/config 已自动支持）
- `app/danmu_pool.py`、`app/danmu_read_service.py`、`app/danmu_tts*.py`（读弹幕/TTS 无关）
- `web/static/modules/`（settings.js 等子模块不涉及本 UI）
- `web/static/index.html` 中除人格工坊 section 之外的其它区块
- `tests/conftest.py`、`tests/fakes.py`（共享假对象不动）
- `requirements.txt`、锁文件、CI 配置文件
- `docs/runtime-state-map.md`、`docs/main-pipeline-sequence.md`、`docs/final-architecture-baseline.md`（Boundary Guard 维护者登记文档，不重命名/不重写）
- `docs/archive/`（历史文档，禁动）

## 需求

1. **后端函数**：在 `app/persona_contract.py` 末尾追加：

   ```python
   # W-LIVE-TOPIC-001
   LIVE_TOPIC_MAX_LEN = 200
   _LIVE_TOPIC_LINE_ZH = "[本次直播主题：{topic}；请围绕此主题营造氛围并自然带入弹幕风格]"
   _LIVE_TOPIC_LINE_EN = "[Live stream topic: {topic}; please set the tone around this topic and weave it naturally into your danmu]"


   def _read_live_topic(config: ConfigStore | None) -> str:
       if config is None:
           return ""
       try:
           value = config.get("live_topic", "")
       except Exception:
           return ""
       return str(value or "")


   def append_live_topic_to_system_pt(system_pt: str, config: ConfigStore | None) -> str:
       """Append a live-topic line to system_pt; returns unchanged prompt when empty."""
       topic = _read_live_topic(config).strip()
       if not topic:
           return system_pt
       topic = topic[:LIVE_TOPIC_MAX_LEN]
       template = _LIVE_TOPIC_LINE_EN if Translator.get_language() == "en" else _LIVE_TOPIC_LINE_ZH
       suffix = template.format(topic=topic)
       base = (system_pt or "").rstrip()
       if not base:
           return suffix
       return f"{base}\n{suffix}"
   ```

2. **白名单与默认值**：
   - `app/application/config_service.py` 第 44 行后追加 `"live_topic",  # W-LIVE-TOPIC-001`。
   - `app/config_defaults.py` 第 56 行后追加 `"live_topic": "",  # W-LIVE-TOPIC-001`。

3. **main.py 注入点**：第 523 行与第 899 行各在 `append_nickname_to_system_pt(...)` 之后紧跟一行 `append_live_topic_to_system_pt(...)`；import 区追加 `append_live_topic_to_system_pt`。

4. **前端 HTML**：在 `web/static/index.html` 第 884 行（昵称块的 `</div>` 之后）插入：

   ```html
   <div class="flex flex-wrap gap-3 items-end">
     <div class="flex-1 min-w-[220px]">
       <label for="liveTopicInput" class="block text-sm font-semibold mb-2 text-warmText">提示内容</label>
       <textarea
         id="liveTopicInput"
         rows="2"
         maxlength="200"
         autocomplete="off"
         class="w-full px-4 py-3 bg-cream rounded-xl text-warmText"
         placeholder="本次直播主题/内容，例如：今晚播《黑神话：悟空》第三章，主玩大圣模式，欢迎弹幕互动"
       ></textarea>
     </div>
     <button type="button" id="btnSaveLiveTopic" class="px-4 py-3 bg-white border border-gray-200 rounded-xl font-semibold text-warmText">保存主题</button>
   </div>
   ```

5. **前端 JS**：在 `web/static/app.js` 中仿 `loadUserNickname` / `saveUserNickname` 追加 `loadLiveTopic` / `saveLiveTopic`；在 `loadPersonaEditor` 末尾追加 `await loadLiveTopic();`；在 `#btnSaveUserNickname` click 监听附近为 `#btnSaveLiveTopic` 注册 click 监听。

6. **测试**：在 `tests/test_web_persona_api.py` 新增以下用例（可拆为多个）：
   - `test_append_live_topic_empty_returns_unchanged`：空值时不追加。
   - `test_append_live_topic_basic_injection_zh` / `_en`：中/英模板。
   - `test_append_live_topic_truncates_long_input`：超 200 字符截断。
   - `test_export_config_includes_live_topic`：`GET /api/config` 返回 `live_topic` 字段。
   - `test_put_config_persists_live_topic`：`PUT /api/config {live_topic: "..."}` 后 config_store 有该值。

7. **回归测试**：`tests/test_reply_contract.py`（如已存在）追加：
   - `append_live_topic_to_system_pt` 与 `append_nickname_to_system_pt` 链式调用顺序与可空性。
   - 注入后 system prompt 包含 `[本次直播主题：...]` 或英文模板。

## 非目标

- 不实现 `{topic}` 占位符替换（用户明确第一版不做）。
- 不做主题模板/预设/历史记录。
- 不做"主题切换"（多主题并存），第一版单值。
- 不做主题的自动翻译（用户原文，AI 自行理解）。
- 不重构 `app/personae.py` / `app/persona_manager.py` 既有逻辑。
- 不修改 `app/web_api/` 任何文件（无需新端点）。
- 不把 `live_topic` 与人格绑定（明确是全局设定）。
- 不动麦克风、TTS、Overlay、截图主链路。
- 不修复任何范围外 bug（若发现，登记到 `docs/已知问题与后续事项.md`）。

## 验收标准

- [ ] `python -m pytest tests/ -q` 全量通过（基线不退步；本工单应净增 ≥5 个测试）。
- [ ] `python scripts/boundary_guard.py` 仍 PASS。
- [ ] `python -m ruff check app main.py tests` 0 错误（不引入新 I001/F401）。
- [ ] `git diff --stat` 仅显示"允许修改的区域"列出的文件。
- [ ] **数据流**：在人格工坊填入主题文字并保存后，DB 中 `config.db` 表 `config` 有 `key='live_topic'` 行（可用 `sqlite3 %APPDATA%/DanmuAI/config.db "SELECT * FROM config WHERE key='live_topic'"` 验证）。
- [ ] **空值零侵入**：`live_topic=""` 时，AI 请求的 system 提示词与改前**逐字节一致**（可通过 `DANMU_API_SCHEDULE_DEBUG=1` 抓取请求体核对）。
- [ ] **运行时注入**：`live_topic="今晚播《艾尔登法环》"` 时，AI 请求 system 提示词包含 `[本次直播主题：今晚播《艾尔登法环》；请围绕此主题营造氛围并自然带入弹幕风格]`。
- [ ] **跨人格**：切换 3 个不同人格，system 提示词都包含同一行主题（证明全局而非跟人格）。
- [ ] **多语言**：`language=en` 时模板变为 `[Live stream topic: ...; please set the tone around this topic and weave it naturally into your danmu]`。
- [ ] **长度截断**：绕过前端 `maxlength`，通过 `PUT /api/config` 写入 500 字符，AI 请求中只包含前 200 字符。
- [ ] **按钮 UI**：textarea 与「保存主题」按钮在「昵称」上方、在「选择人格」上方。
- [ ] **持久化往返**：保存后离开人格工坊页再回来，输入框内容仍存在（GET /api/config 返回值正确填入）。
- [ ] **空值时按钮也可保存**：清空后点保存，DB 中 `live_topic` 变为 `""`，toast 提示"主题已清空"。
- [ ] 完成报告已写至 `docs/templates/Codex完成报告/W-LIVE-TOPIC-001-完成报告.md`。
- [ ] [docs/workflow/当前仓库状态.md](../../workflow/当前仓库状态.md) 追加 W-LIVE-TOPIC-001 最近变更段。
- [ ] [docs/workflow/工单列表.md](../../workflow/工单列表.md) 将 W-LIVE-TOPIC-001 登记为「已完成」。

## 手动验证步骤

1. **冷启动 + 编辑**：
   ```bash
   python main.py --web-browser
   ```
   打开浏览器，进「人格工坊」→ 确认顶部出现「提示内容」textarea + 「保存主题」按钮，且位于「昵称」上方。

2. **保存正向路径**：
   - 在 textarea 填入 `今晚播《艾尔登法环》DLC 黄金树之影，挑战拉达冈，欢迎弹幕互动`。
   - 点「保存主题」→ 看到 toast「主题已保存~」。
   - 离开人格工坊页（切到「API 与模型」），再切回「人格工坊」→ textarea 内容仍在。
   - 终端验证 DB：
     ```bash
     sqlite3 "$APPDATA/DanmuAI/config.db" "SELECT value FROM config WHERE key='live_topic';"
     ```
     预期：返回刚填的字符串。

3. **运行时注入**：
   - 启动一个浏览器可识别的画面（如随便开一个浏览器窗口或游戏窗口）。
   - 启用 `DANMU_API_SCHEDULE_DEBUG=1` 重启 `python main.py`。
   - 等 1-2 个截图周期。
   - 在应用日志中应看到 system 提示词末尾含 `[本次直播主题：...]` 行。

4. **空值零侵入**：
   - 回到人格工坊 → 清空 textarea → 保存。
   - 重启 `python main.py`（带 `DANMU_API_SCHEDULE_DEBUG=1`）。
   - 等 1-2 个截图周期。
   - 在日志中 system 提示词末尾**不应**有 `[本次直播主题：...]` 行。
   - 与 W-NICKNAME-001 提交时的 system 提示词抓取结果做 diff：应**逐字节一致**（仅 nickname 行存在；topic 行不存在）。

5. **跨人格**：
   - 重新填入主题并保存。
   - 在「激活人格」勾选 3 个不同人格（包含至少 1 个内置、1 个自定义）。
   - 等 3 个截图周期。
   - 在日志中确认 3 次的 system 提示词末尾都包含同一行主题。

6. **多语言**：
   - 临时在 `config.db` 中改 `key='language'` 值为 `en`（或在 UI 切语言）。
   - 重启应用，等一个截图周期。
   - 日志中应出现 `[Live stream topic: ...; please set the tone around this topic and weave it naturally into your danmu]`。
   - 完成后改回 `zh`。

7. **长度截断**（开发验证，可选）：
   - 在浏览器 DevTools Console 中执行：
     ```js
     fetch('/api/config', {
       method: 'PUT',
       headers: {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + localStorage.getItem('danmu_token')},
       body: JSON.stringify({live_topic: '啊'.repeat(500)})
     })
     ```
   - 触发一次 AI 请求，日志中 topic 应为前 200 个「啊」。

8. **回归**：
   ```bash
   python -m pytest tests/ -q
   python scripts/boundary_guard.py
   ```
   预期：pytest 全绿；boundary_guard PASS。

## 风险点

- **空值兼容性**：本工单核心承诺是"未启用时与现状逐字节一致"。`append_live_topic_to_system_pt` 必须严格在 `live_topic.strip() == ""` 时返回原 `system_pt`（不引入额外空白/换行）。Codex 需对边界 case 写测试，避免引入隐藏字符。
- **system prompt 体积**：`LIVE_TOPIC_MAX_LEN=200` 是给中文字符预留的；如未来允许 emoji / 拉丁字母混排，200 字约 ≤ 600 bytes，对 512+ token 的输出下限不构成压力。Codex 无需动态估算 token。
- **配置键命名冲突**：`live_topic` 与 `app/window_info.py:130` 的 `topic_hint`（自动从窗口标题推断）语义不同，但**有意为之**：用户主动写 vs. 系统自动推断，是两个独立来源。Codex 不得合并 / 复用 `topic_hint` 字段。
- **`WEB_CONFIG_KEYS` 副作用**：把 `live_topic` 加入白名单后，「助手设置→恢复默认」按钮会**清空** `live_topic`。这与 `user_nickname` 行为一致（`user_nickname` 也是加入白名单后被"恢复默认"清空），属于可接受行为，本工单**不**做特殊豁免（避免引入"哪些键可恢复"的额外复杂度）。
- **main.py 两处注入点**：第 523 行（普通模式）和第 899 行（另一条路径，可能是 fallback / 冷启动路径）。Codex **必须**两处都加，不可遗漏。遗漏一处将导致部分请求不带主题、行为不一致。完成报告应明确"两处均已加"。
- **前端 input id 冲突**：`liveTopicInput` / `btnSaveLiveTopic` 为新 id，不与既有 `userNicknameInput` / `btnSaveUserNickname` 冲突。Codex 仍应 grep 一次 `id="liveTopic` 与 `id="btnSaveLive` 确认零冲突。
- **回滚方式**：本工单改动分散在 6 个文件，1 commit 内可整体 `git revert`。

## 完成后必须更新的文档

- [ ] [docs/workflow/当前仓库状态.md](../../workflow/当前仓库状态.md)（追加 W-LIVE-TOPIC-001 最近变更段）
- [ ] [docs/workflow/工单列表.md](../../workflow/工单列表.md)（将 W-LIVE-TOPIC-001 从「待办」移入「已完成工单」表行）
- [ ] [docs/WEB_CONSOLE.md](../../WEB_CONSOLE.md)（在「人格工坊」节追加新输入框说明 + `live_topic` config key）
- [ ] [docs/CHANGELOG.md](../../CHANGELOG.md)（行为变更条目）
- [ ] [docs/templates/Codex完成报告/W-LIVE-TOPIC-001-完成报告.md](../../templates/Codex完成报告/Codex完成报告模板.md)（新建完成报告）

## Codex 完成报告要求

- 使用 [Codex完成报告模板.md](../../templates/Codex完成报告/Codex完成报告模板.md)
- 必须列出**全部**修改文件路径（约 11 个）
- 报告 §3「未修改的关键区域」应确认 `app/persona_manager.py`、`app/persona_builtin.py`、`app/mic_*.py`、`app/memory/`、`app/danmu_tts*.py`、`web/static/modules/` 等均未改动
- 报告 §6「手动验证步骤」应包含 7 步的实测结果（可用截图或日志引用）
- 报告 §7「风险与注意事项」应特别指出「恢复默认按钮会清空 live_topic」是与昵称一致的有意行为
- 报告 §10「建议下一个工单」可建议：W-LIVE-TOPIC-002（多主题切换 / 主题历史）或 W-LIVE-TOPIC-003（`{topic}` 占位符支持），但**本工单不实现**

---

## 附录 A：核心代码草稿（给 Codex 一次性 diff 用）

### A.1 `app/persona_contract.py`（追加，文件末）

```python
# W-LIVE-TOPIC-001
LIVE_TOPIC_MAX_LEN = 200
_LIVE_TOPIC_LINE_ZH = "[本次直播主题：{topic}；请围绕此主题营造氛围并自然带入弹幕风格]"
_LIVE_TOPIC_LINE_EN = "[Live stream topic: {topic}; please set the tone around this topic and weave it naturally into your danmu]"


def _read_live_topic(config: ConfigStore | None) -> str:
    if config is None:
        return ""
    try:
        value = config.get("live_topic", "")
    except Exception:
        return ""
    return str(value or "")


def append_live_topic_to_system_pt(system_pt: str, config: ConfigStore | None) -> str:
    """Append a live-topic line to system_pt; returns unchanged prompt when empty."""
    topic = _read_live_topic(config).strip()
    if not topic:
        return system_pt
    topic = topic[:LIVE_TOPIC_MAX_LEN]
    template = _LIVE_TOPIC_LINE_EN if Translator.get_language() == "en" else _LIVE_TOPIC_LINE_ZH
    suffix = template.format(topic=topic)
    base = (system_pt or "").rstrip()
    if not base:
        return suffix
    return f"{base}\n{suffix}"
```

### A.2 `app/personae.py` `__all__` 追加

```python
"append_live_topic_to_system_pt",
"LIVE_TOPIC_MAX_LEN",
```

### A.3 `app/application/config_service.py` `WEB_CONFIG_KEYS` 追加

```python
"user_nickname",  # W-NICKNAME-001
"live_topic",  # W-LIVE-TOPIC-001
)
```

### A.4 `app/config_defaults.py` 追加

```python
"user_nickname": "",  # W-NICKNAME-001
"live_topic": "",  # W-LIVE-TOPIC-001
```

### A.5 `main.py` 改 2 处

- import 区追加 `append_live_topic_to_system_pt`
- 紧跟 `append_nickname_to_system_pt` 之后加一行：

```python
system_pt = append_nickname_to_system_pt(system_pt, self.config)  # W-NICKNAME-001
system_pt = append_live_topic_to_system_pt(system_pt, self.config)  # W-LIVE-TOPIC-001
```

### A.6 `web/static/index.html`（在 884 行后插入）

见 §需求.4。

### A.7 `web/static/app.js`

```javascript
async function loadLiveTopic() {
  const input = document.getElementById('liveTopicInput');
  if (!input) return;
  try {
    const cfg = await apiFetch('/api/config');
    input.value = cfg?.live_topic ?? '';
  } catch (err) {
    console.warn('loadLiveTopic failed:', err);
  }
}

async function saveLiveTopic() {
  const input = document.getElementById('liveTopicInput');
  if (!input) return;
  const value = (input.value || '').trim().slice(0, 200);
  try {
    await apiFetch('/api/config', {
      method: 'PUT',
      body: JSON.stringify({ live_topic: value }),
    });
    input.value = value;
    showToast(value ? '主题已保存~' : '主题已清空~');
  } catch (err) {
    showToast(err.message || '主题保存失败', true);
  }
}
```

并在 `loadPersonaEditor()` 末尾追加 `await loadLiveTopic();`，以及在 `#btnSaveUserNickname` 监听注册处附近为 `#btnSaveLiveTopic` 注册 click。

## 附录 B：参考 commit 风格

参考 W-NICKNAME-001 的提交风格（人格工坊全局设定 + 注入 system 提示）：

```
feat: add live topic input to persona workshop (W-LIVE-TOPIC-001)

Adds a "提示内容" textarea at the top of the persona workshop that
sets a global "live_topic" config key. The value is injected into
the AI system prompt as a single line, after the nickname line.

- Empty value is a no-op (no system-prompt change vs. baseline).
- Truncates input to 200 chars defensively.
- Bilingual template (zh/en) keyed off Translator.get_language().
- Persists via PUT /api/config; read via GET /api/config.
- Closes: W-LIVE-TOPIC-001
```

## 附录 C：与未来工单的边界

| 维度 | W-LIVE-TOPIC-001（本工单） | W-LIVE-TOPIC-002（后续可选） | W-LIVE-TOPIC-003（后续可选） |
|------|---------------------------|---------------------------|---------------------------|
| 范围 | 单值主题，textarea + 按钮 | 多主题并存，可切换 | `{topic}` 占位符替换 |
| 文件 | 6 后端 + 2 前端 + tests + docs | 需新增"场景"维度 + UI 切换器 | 需在 user_pt 模板层加替换 |
| 风险 | 低（零侵入） | 中（涉及 schema 与 UI 新增） | 中（影响所有内置人格 user_pt） |
| 建议顺序 | 先做本工单 | 用户反馈"想多主题"后再立项 | 用户反馈"想模板化"后再立项 |
