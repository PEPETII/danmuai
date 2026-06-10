# W-MIC-UTTERANCE-HYSTERESIS-001 — 修复 mic 端点检测阈值反转死循环

> **来源**：用户反馈（issue）；在 [app/mic_utterance.py](../../ai-project-context.md) 状态机审计中发现  
> **执行者**：Codex / Cursor Agent  
> **优先级**：高（用户可见；语音被静默丢弃，影响麦克风模式可用性）  
> **预计工时**：10–15 分钟（1 处方法实现 + 1 段 docstring + 2 个回归用例 + 4 处文档）

---

## 工单 ID

`W-MIC-UTTERANCE-HYSTERESIS-001`

## 工单标题

修复 `MicUtteranceDetector._speech_exit_threshold()` 在 loud utterance 时反超 enter 阈值，导致 SPEAKING ↔ SILENCE_PENDING 死循环、`on_utterance_end` 永不触发的 bug

## 背景

`MicUtteranceDetector`（[app/mic_utterance.py](../../app/mic_utterance.py)）使用四状态机（IDLE → SPEAKING → SILENCE_PENDING → COOLDOWN）来判断用户何时开始说话、何时说完。状态机依赖 enter / exit 双阈值形成滞回（hysteresis），避免音量在阈值附近抖动时状态来回切换。

### 根因

状态机 line 154 注释明确假设 `enter > exit` 形成滞回区，但两个公式不保证这一关系：

| 阈值 | 公式 | 行号 |
|------|------|------|
| enter | `max(speech_rms, floor+120, floor*1.6+60)` | line 105-109 |
| exit | `max(80, floor+40, int(self._peak_rms * 0.45))` | line 113-114 |

`enter` 只取决于 `speech_rms` 和 `noise_floor`；`exit` 中的 `peak_rms` 在 `SPEAKING` 期间被持续推高（line 140 `self._peak_rms = max(self._peak_rms, rms)`）。

**复现算例**：`floor=0` / `speech_rms=200` / 用户大声说话 `peak_rms=500`：
- enter = `max(200, 120, 60)` = **200**
- exit = `max(80, 40, 500*0.45)` = `max(80, 40, 225)` = **225**
- 此时 `exit (225) > enter (200)` — 滞回消失

**死循环路径**（用户音量回落到 220，介于 enter 200 与 exit 225 之间）：

| 当前状态 | 判定（line 150/155） | 结果 |
|---------|---------------------|------|
| SILENCE_PENDING | `220 >= enter(200)` ✅ | → SPEAKING（line 151）|
| SPEAKING | `220 < exit(225)` ❌ | → SILENCE_PENDING（line 144）|

状态在两者间无限振荡；`on_utterance_end` 永不触发；语音被静默丢弃。

## 目标

1. `_speech_exit_threshold()` 返回值**始终**满足 `exit < enter`（滞回不变量）。
2. 极端音量下（`peak_rms` 远超 `enter`）状态机仍能稳定完成 IDLE → SPEAKING → SILENCE_PENDING → COOLDOWN 的完整流转。
3. 用回归用例锁定滞回不变量，防止后续重构破坏。
4. 现有 8 个 mic_utterance 测试不破。

## 依赖项

- 无前置工单
- 无外部依赖
- 仅修改 `app/mic_utterance.py`（生产代码） + `tests/test_mic_utterance.py`（测试） + 文档 3 个

## 允许修改的区域

- [app/mic_utterance.py](../../app/mic_utterance.py) — `_speech_exit_threshold()` 方法体 + 文件顶部 docstring
- [tests/test_mic_utterance.py](../../tests/test_mic_utterance.py) — 新增 2 个回归用例
- [docs/已知问题与后续事项.md](../../workflow/已知问题与后续事项.md) — 登记 ISSUE-053
- [docs/workflow/工单列表.md](../../workflow/工单列表.md) — 登记本工单 + 完工后状态切换
- [docs/workflow/当前仓库状态.md](../../workflow/当前仓库状态.md) — 顶部新增最近变更段
- [docs/工单列表/工单/W-MIC-UTTERANCE-HYSTERESIS-001.md](../../工单列表/工单/W-MIC-UTTERANCE-HYSTERESIS-001.md) — 本工单正文
- [docs/archive/completion-reports/W-MIC-UTTERANCE-HYSTERESIS-001-completion-report.md](../../archive/completion-reports/W-MIC-UTTERANCE-HYSTERESIS-001-completion-report.md) — 完工报告（新建）

## 禁止修改的区域

- `main.py`（本工单不涉及主链路）
- `app/main_*_mixin.py`（含 `main_mic_mixin.py`，**不**改 `_poll_mic_utterance` / `_on_mic_utterance_end`）
- `app/mic_orchestrator.py`（orchestrator 只读 `enter_threshold()`，不改）
- `app/mic_service.py` / `app/mic_capture.py` / `app/mic_buffer.py` / `app/mic_prompt.py` / `app/mic_test.py` / `app/mic_encode.py`
- `app/web_api/*` / `app/overlay.py` / `app/danmu_engine.py`
- `web/static/**`（麦克风 UI 不动）
- `requirements.txt` / 锁文件 / CI / `DanmuAI.spec` / `pyproject.toml`
- `tests/conftest.py` / `tests/fakes.py` / 其他 `tests/test_mic_*.py`
- `docs/archive/` / `supabase/` / `community-site/`

## 需求

1. **滞回钳位**：`_speech_exit_threshold()` 在原 `max(80, floor+40, peak*0.45)` 计算后，附加 `min(raw_exit, enter - 1)` 钳位；当 `enter <= 0` 时按原值返回（防御性兜底，实际不会触发）。
2. **不变量文档化**：文件顶部 docstring line 9-10 增加 **「**滞回保证**：`exit < enter` 始终成立；用户音量再大也不会让退出阈值反超进入阈值」** 的说明。
3. **回归用例 1**：`test_exit_threshold_always_below_enter_with_high_peak` — 构造 `floor=0` / `speech_rms=200` / `peak_rms=5000`，断言 `_speech_exit_threshold() < _speech_enter_threshold()`，且两者差距 ≥ 1。
4. **回归用例 2**：`test_loud_utterance_still_fires_on_utterance_end` — 端到端：模拟"大声说话（`loud_rms=1500`）→ 静音"，状态机应正常走 SPEAKING → SILENCE_PENDING → COOLDOWN，`on_utterance_end` 回调被调用 1 次。
5. **ISSUE-053 登记**：`docs/已知问题与后续事项.md` 顶部新增「W-MIC-UTTERANCE-HYSTERESIS-001 修复 ISSUE-053」段。

## 非目标

- 不实现新功能。
- 不重构 `MicUtteranceDetector` 类（不改状态机其他分支判定）。
- 不重写 `_speech_enter_threshold()`（保留 `floor+120` / `floor*1.6+60` 抬高环境噪声的现有语义）。
- 不修改 `MicUtteranceConfig`（不改 `speech_rms` / `silence_ms` / `min_speech_ms` / `cooldown_sec` 字段）。
- 不改 `enter_threshold()` 公共方法（被 `mic_orchestrator` 日志调用，保持原签名）。
- 不修改 `app/mic_orchestrator.py` 内的 calibrate / sync 逻辑。
- 不接入任何 UI 改动；不调整 Web 麦克风设置页。
- 不顺手修复范围外任何 `app/mic_*.py` 问题。

## 验收标准

- [ ] `app/mic_utterance.py` `_speech_exit_threshold()` 返回 `min(raw_exit, enter - 1)`；当 `enter > 0` 时保证 `exit < enter`。
- [ ] `app/mic_utterance.py` 文件顶部 docstring 包含"滞回保证"声明。
- [ ] `tests/test_mic_utterance.py` 新增 2 个回归用例，且全部通过。
- [ ] 既有 8 个 `tests/test_mic_utterance.py` 用例（含 `test_utterance_with_high_noise_floor`）不破。
- [ ] `python -m pytest tests/test_mic_utterance.py -q -x` 全 PASS。
- [ ] `python -m pytest tests/test_mic_orchestrator.py tests/test_mic_service.py -q -x` 全 PASS（orchestrator 未越界）。
- [ ] `python -m pytest tests/test_mic_*.py -q -x` 全 PASS（mic 模块兜底）。
- [ ] **未执行** `python -m pytest tests/` 全量。
- [ ] **未执行** `python scripts/boundary_guard.py`（不触达编排 / Web API / 主链路）。
- [ ] `git diff --stat` 仅显示允许修改区内的文件。
- [ ] `docs/已知问题与后续事项.md` 顶部出现「W-MIC-UTTERANCE-HYSTERESIS-001 修复 ISSUE-053」段。
- [ ] `docs/workflow/工单列表.md` 工单登记表新增 W-MIC-UTTERANCE-HYSTERESIS-001（待办 → 已完成）。
- [ ] `docs/workflow/当前仓库状态.md` 顶部新增「最近变更（W-MIC-UTTERANCE-HYSTERESIS-001）」段。
- [ ] 完成报告 `docs/archive/completion-reports/W-MIC-UTTERANCE-HYSTERESIS-001-completion-report.md` 已写完。

## 手动验证步骤

1. **拉取本工单分支**，执行：
   ```bash
   python -m pytest tests/test_mic_utterance.py -q -x
   ```
   预期：10 passed（8 既有 + 2 新），且 2 个新用例在原代码上**应失败**（用 stash 验证）。
2. **状态机单元验证**：
   ```python
   from app.mic_utterance import MicUtteranceDetector, MicUtteranceConfig
   d = MicUtteranceDetector(on_utterance_end=lambda: None, config=MicUtteranceConfig(speech_rms=200))
   # 模拟在 SPEAKING 期间 peak_rms 被推高到 5000
   d._peak_rms = 5000
   d._noise_floor = 0
   enter = d._speech_enter_threshold()
   exit_ = d._speech_exit_threshold()
   assert enter > 0
   assert exit_ < enter, f"hysteresis broken: enter={enter} exit={exit_}"
   ```
3. **极端算例自检**：`peak_rms=5000` 时，原代码 `exit=2250`，`enter=200`；新代码 `exit=199`（被 `enter-1=199` 钳位）。
4. **端到端不变量**：复现"loud_rms=1500 + 静音"完整流程，断言 `fired == [True]` 且 `state == COOLDOWN`。
5. **兜底批次**：
   ```bash
   python -m pytest tests/test_mic_orchestrator.py tests/test_mic_service.py -q -x
   python -m pytest tests/test_mic_*.py -q -x
   ```
6. **范围检查**：
   ```bash
   git diff --stat
   ```
   预期：仅 `app/mic_utterance.py` / `tests/test_mic_utterance.py` / 4 个 docs 文件 / 1 个 reports 文件 / 1 个工单正文文件。

## 风险点

- **`enter_threshold()` 公共方法签名**：[app/mic_orchestrator.py:135](../../app/mic_orchestrator.py) 日志输出格式依赖返回值不变；本工单不修改 `_speech_enter_threshold()`，仅在 `_speech_exit_threshold()` 末尾加钳位，`enter_threshold()` 输出不受影响。
- **state machine 分支判定**：line 129-135 / 139-146 / 148-166 三处判定逻辑**完全不改**，仅阈值计算变化；line 154 注释「enter > exit 形成滞回」由本工单正式兑现。
- **回归风险**：本工单仅改 1 个方法体（5 行内）+ 1 段 docstring，1 commit 内可整体 `git revert`。
- **`enter <= 0` 防御分支**：`floor=0` / `speech_rms=0` 也不会让 `_speech_enter_threshold()` 返回 0（worst case `max(0, 120, 60) = 120`），所以 `enter <= 0` 实际不会进入；保留仅为防御性兜底，避免极小概率下被钳位到负数。
- **pytest `FakeLogger` 等共享**：本工单不新增 fixture，复用既有 `_pcm_with_rms` / `_silent_pcm` / `_finish_utterance` 辅助函数。
- **mic_orchestrator / mic_service 兜底**：跑 `test_mic_orchestrator.py` + `test_mic_service.py` 验证未越界。

## 完成后必须更新的文档

- [x] [docs/已知问题与后续事项.md](../../workflow/已知问题与后续事项.md)（顶部新增 ISSUE-053 段）
- [x] [docs/workflow/工单列表.md](../../workflow/工单列表.md)（工单登记表第 N 行新增；完工后改状态）
- [x] [docs/workflow/当前仓库状态.md](../../workflow/当前仓库状态.md)（顶部新增最近变更段）
- [x] [docs/工单列表/工单/W-MIC-UTTERANCE-HYSTERESIS-001.md](../../工单列表/工单/W-MIC-UTTERANCE-HYSTERESIS-001.md)（本工单正文）
- [x] [docs/archive/completion-reports/W-MIC-UTTERANCE-HYSTERESIS-001-completion-report.md](../../archive/completion-reports/W-MIC-UTTERANCE-HYSTERESIS-001-completion-report.md)（新建完工报告）

## Codex 完成报告要求

- 使用 [Codex完成报告模板.md](../../templates/Codex完成报告/Codex完成报告模板.md)
- 必须列出**全部**修改文件路径（4 业务 + 3 文档 + 1 报告 = 8 文件；详见附录 A）
- §3「未修改的关键区域」必须列出 `main.py` / `app/main_mic_mixin.py` / `app/mic_orchestrator.py` / `app/mic_service.py` / `app/web_api/*` / `web/static/**`
- §4「运行的命令」列 2 个 pytest 批次 + git diff --stat
- §5.1「分批测试报告」按 [docs/IDE_AGENT_RULES.md §10.6](../../IDE_AGENT_RULES.md)
- §8「发现但未处理的问题」引用 ISSUE-053 编号
- §10「建议下一个工单」仅建议，不擅自实现

---

## 附录 A：核心代码 diff 摘要（给 Codex 一次性参考）

### `app/mic_utterance.py`（line 9-10 docstring）

**Before**：

```python
动态阈值：enter 取 max(配置, floor+120, floor*1.6+60) 抬高门槛抑制环境噪声误触；
exit 取 max(80, floor+40, peak*0.45) 相对峰值回落判定「说完了」，避免单帧抖动。
```

**After**：

```python
动态阈值：enter 取 max(配置, floor+120, floor*1.6+60) 抬高门槛抑制环境噪声误触；
exit 取 max(80, floor+40, peak*0.45) 相对峰值回落判定「说完了」，避免单帧抖动。
**滞回保证**：`_speech_exit_threshold()` 返回值始终严格小于 `_speech_enter_threshold()`，
用 `min(raw_exit, enter - 1)` 钳位（user 大声说话时 peak_rms 推高 raw_exit）；否则
SILENCE_PENDING ↔ SPEAKING 死循环，on_utterance_end 永不触发（W-MIC-UTTERANCE-HYSTERESIS-001）。
```

### `app/mic_utterance.py`（line 111-114 `_speech_exit_threshold()`）

**Before**：

```python
def _speech_exit_threshold(self) -> int:
    # 相对本次 utterance 的 peak 回落到 45% 以下视为「音量下降」；并与噪声底+40 取 max
    floor = self._noise_floor
    return max(80, floor + 40, int(self._peak_rms * 0.45))
```

**After**：

```python
def _speech_exit_threshold(self) -> int:
    # 相对本次 utterance 的 peak 回落到 45% 以下视为「音量下降」；并与噪声底+40 取 max
    floor = self._noise_floor
    raw_exit = max(80, floor + 40, int(self._peak_rms * 0.45))
    # 关键不变量：exit < enter 形成滞回；用户大声说话时 peak_rms 推高 raw_exit，
    # 一旦 raw_exit 追平/反超 enter，状态机会在 SILENCE_PENDING/SPEAKING 死循环。
    # 用 enter - 1 钳位，确保滞回区至少 1 RMS 宽度（W-MIC-UTTERANCE-HYSTERESIS-001）。
    enter = self._speech_enter_threshold()
    if enter <= 0:
        return raw_exit
    return min(raw_exit, enter - 1)
```

### `tests/test_mic_utterance.py`（末尾追加 2 用例）

```python
def test_exit_threshold_always_below_enter_with_high_peak():
    """W-MIC-UTTERANCE-HYSTERESIS-001: peak_rms 推高时 exit 仍 < enter（滞回不变量）。"""
    detector = MicUtteranceDetector(
        on_utterance_end=lambda: None,
        config=MicUtteranceConfig(speech_rms=200),
    )
    detector._peak_rms = 5000  # 极端 loud utterance
    detector._noise_floor = 0
    enter = detector._speech_enter_threshold()
    exit_ = detector._speech_exit_threshold()
    assert enter > 0
    assert exit_ < enter, f"hysteresis broken: enter={enter} exit={exit_}"


def test_loud_utterance_still_fires_on_utterance_end():
    """W-MIC-UTTERANCE-HYSTERESIS-001: loud utterance 不再卡死在 SILENCE_PENDING。"""
    fired = []
    detector = MicUtteranceDetector(
        on_utterance_end=lambda: fired.append(True),
        config=MicUtteranceConfig(
            speech_rms=200,
            silence_ms=300,
            min_speech_ms=200,
            cooldown_sec=10.0,
        ),
    )
    t0 = 1000.0
    _finish_utterance(detector, t0=t0, speech_sec=0.3, silence_sec=0.35, loud_rms=1500)
    assert detector.state == UtteranceState.COOLDOWN
    assert fired == [True]
```

---

## 附录 B：与既有状态机分支契约

本工单**不**修改 `poll()` 中其他分支判定；仅阈值计算变化后既有 line 154 注释「enter > exit 形成滞回」正式生效。

| 状态 | 判定（line） | 阈值 | 修后行为 |
|------|-------------|------|---------|
| IDLE → SPEAKING | `rms >= enter` (line 131) | `_speech_enter_threshold()` | 不变 |
| SPEAKING → SILENCE_PENDING | `rms < exit` (line 141) | `_speech_exit_threshold()`（**新**带钳位）| 行为等价：loud 时 exit 降低，更快进入 SILENCE_PENDING |
| SILENCE_PENDING → SPEAKING | `rms >= enter` (line 150) | `_speech_enter_threshold()` | 不变 |
| SILENCE_PENDING 继续 | `rms >= exit` (line 155) | `_speech_exit_threshold()`（**新**带钳位）| 行为等价：loud 时 exit 降低，更快触发 line 157 silence_ms 计时 |
| SILENCE_PENDING → _fire | `silence_ms >= silence_ms` 且 `speech_ms >= min_speech_ms` (line 157-161) | 时间常量 | 不变 |

---

## 附录 C：参考历史 bug 修复风格

- W-RACE-001（陈旧 `AiRunnable` 丢弃）：单行 + 注释 + 2 个回归用例 + `reason=` 表新增
- W-LINT-001（历史 ruff I001/F401）：9 处自动修复 + 1 个 untracked 脚本决策
- W-AUDIT-FIX-001/002（/api/config 假成功 + 退出竞态）：核心方法 patch + 测试 + 文档

本工单属于「核心方法 patch + 回归测试 + 文档登记」，与上述工单同质。
