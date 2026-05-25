# 弹幕显示模式切换实施规划

## 目标

在 Web 控制台「设置 / 弹幕显示」tab 新增模式切换：

- `实时模式`：保持当前行为不变。当前模式是 1 秒截图、200ms 节奏检查、按库存和新鲜度预触发下一批 AI 请求。
- `普通模式`：新增定时识别模式。用户可配置「每 x 秒识别一次画面」和「每次生成 y 个弹幕」。每次 AI 返回后，经过去重和屏幕容量判断，尽量把本批未被拒绝的弹幕全部输出到弹幕显示链路。

本规划仅面向默认 Web 控制台（遗留 Qt 主窗已移除）。

## 非目标

- 不改 Overlay 窗口标志、渲染方式、轨道算法。
- 不重写 `DanmuEngine` 去重算法。
- 不新增 Qt 主窗设置项。
- 不引入新的后台线程或独立调度框架。
- 不改变麦克风插入弹幕逻辑。

## 推荐配置模型

新增 3 个配置键：

| key | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `danmu_display_mode` | string | `realtime` | `realtime` 为当前实时模式，`normal` 为普通模式 |
| `normal_recognition_interval_sec` | int | `5` | 普通模式每隔多少秒识别一次画面，建议范围 1-60 |
| `normal_reply_count` | int | `5` | 普通模式每次要求 AI 生成多少条弹幕，建议范围 1-20 |

保留现有 `reply_scene_count` / `reply_filler_count`，但它们只作为实时模式的输出契约配置。普通模式使用 `normal_reply_count` 生成单一总数，避免把普通模式强行拆成「画面强相关 + 泛用氛围」两个概念。

兼容策略：

- 未写入 `danmu_display_mode` 时按 `realtime` 处理。
- `normal_reply_count` 非法时回退到 5。
- `normal_recognition_interval_sec` 非法时回退到 5。
- 切换模式时不清空配置库，只切换运行时调度策略。

## 涉及文件

| 文件 | 修改点 |
| --- | --- |
| `web/static/index.html` | 在「弹幕显示」tab 增加模式切换和普通模式参数输入 |
| `web/static/app.js` | 增加配置字段、默认值填充、普通模式字段显隐 |
| `app/web_console.py` | `WEB_CONFIG_KEYS` 加新键，`apply_config_patch()` 做范围钳制 |
| `app/personae.py` | 增加普通模式输出契约构建函数，或让现有 contract builder 支持总数模式 |
| `main.py` | 根据模式切换截图定时器和节奏触发逻辑；普通模式消费整批 |
| `tests/test_web_console.py` | 覆盖 Web 配置键和钳制 |
| `tests/test_reply_contract.py` | 覆盖普通模式输出契约 |
| `tests/test_p0_main_flow.py` | 覆盖普通模式定时触发和批量消费行为 |
| `docs/WEB_CONSOLE.md` | 同步说明新配置 |

## UI 方案

位置：`web/static/index.html` 的 `settingsTab-danmu` 内，放在「每次生成弹幕数」配置块之前。

控件建议：

- 使用 `<select id="danmu_display_mode" name="danmu_display_mode">`
  - `realtime`：实时模式
  - `normal`：普通模式
- 新增一个 `id="normalModeOptions"` 的容器，普通模式时显示，实时模式时隐藏。
- 容器内放两个 number input：
  - `normal_recognition_interval_sec`
  - `normal_reply_count`

交互规则：

- 实时模式：显示现有 `reply_scene_count` / `reply_filler_count` 配置块。
- 普通模式：显示普通模式参数；可以隐藏实时模式的「画面强相关 / 泛用弹幕」拆分配置，避免用户误解。
- `app.js` 增加 `updateDisplayModeControls()`，在加载配置和模式切换时同步显隐。

## 后端配置入口

`app/web_console.py`：

1. `WEB_CONFIG_KEYS` 增加：
   - `danmu_display_mode`
   - `normal_recognition_interval_sec`
   - `normal_reply_count`

2. `apply_config_patch()` 增加钳制：
   - `danmu_display_mode` 只允许 `realtime` / `normal`，否则回退 `realtime`。
   - `normal_recognition_interval_sec` 钳制到 1-60。
   - `normal_reply_count` 钳制到 1-20。

3. 建议新增小函数，避免把 `apply_config_patch()` 继续堆大：
   - `_clamp_choice(items, key, allowed, default)`
   - `_clamp_int_key(items, key, default, min_value, max_value)`

## 输出契约

当前实时模式通过 `reply_scene_count` + `reply_filler_count` 构造「固定返回 x+y 条」契约。普通模式需要更直接：

```text
固定返回 {normal_reply_count} 条弹幕，必须与当前画面或直播氛围相关，避免重复。
```

推荐在 `app/personae.py` 新增：

- `DEFAULT_NORMAL_REPLY_COUNT = 5`
- `NORMAL_REPLY_COUNT_MIN = 1`
- `NORMAL_REPLY_COUNT_MAX = 20`
- `normal_reply_count_from_config(config)`
- `build_normal_reply_contract_zh(count, max_chars=None)`
- `build_normal_reply_contract_en(count, max_chars=None)`
- `get_reply_contract(config)` 内根据 `danmu_display_mode` 选择普通/实时契约。

这样 AI 解析仍可复用 `parse_ai_reply_payload()` 与 `normalize_reply_batch()`，避免新增响应格式。

## 运行时调度方案

### 实时模式

保持现有逻辑：

- `start()` 中 `screenshot_timer.setInterval(1000)`。
- `start()` 中启动 `_rhythm_check_timer.start(200)`。
- `_check_rhythm_trigger()` 按 `BatchTracker.next_generation_time` 预触发。
- `_enqueue_reply_batch()` 使用 `prepend_batch()`，新批次可覆盖旧库存，仅保留少量 fallback。

### 普通模式

核心规则：

- 截图和 API 请求按 `normal_recognition_interval_sec` 定时触发。
- 不使用 `_rhythm_check_timer` 的库存预触发。
- 每次 AI 返回后，本批弹幕进入队列，不因为新批次到来主动替换上一批。
- 消费时继续走 `DanmuEngine.add_text()`，让去重和同屏容量控制保持单一事实来源。
- 「输出所有生成的弹幕」解释为：本批经过去重和容量判断后，所有可进入显示链路的弹幕都被消费；不是绕过 `min_on_screen` 本地补足或轨道容量硬塞到屏幕上。

建议新增辅助方法：

```python
def _display_mode(self) -> str:
    return "normal" if self.config.get("danmu_display_mode", "realtime") == "normal" else "realtime"

def _is_normal_mode(self) -> bool:
    return self._display_mode() == "normal"

def _normal_recognition_interval_ms(self) -> int:
    return clamp(self.config.get_int("normal_recognition_interval_sec", 5), 1, 60) * 1000
```

`start()` 分支：

- realtime：维持现有启动逻辑。
- normal：
  - `screenshot_timer.setInterval(self._normal_recognition_interval_ms())`
  - 启动 `screenshot_timer`
  - 不启动 `_rhythm_check_timer`
  - 立即 `_capture_screenshot()` 后触发一次 API，或等待第一个 timer tick。建议立即触发，用户点击开始后有反馈。

普通模式下的 `_capture_screenshot()`：

- 抓图后递增 `screenshot_id`。
- 如果无 in-flight，则立即 `_trigger_api_call(source="normal_interval")`。
- 如果已有 in-flight，跳过本次请求，不排队堆积。

为避免污染实时逻辑，推荐新增：

```python
def _on_normal_capture_tick(self):
    self._capture_screenshot()
    if self._latest_screenshot is not None:
        self._trigger_api_call(source="normal_interval")
```

然后普通模式下把 `screenshot_timer.timeout` 仍连到 `_capture_screenshot()` 会不够清晰。更稳妥的做法是在 timeout 固定连接一个统一入口：

```python
def _on_screenshot_timer(self):
    if self._is_normal_mode():
        self._on_normal_capture_tick()
    else:
        self._capture_screenshot()
```

但这会改动初始化连接点，需要补测试。

## 普通模式队列行为

当前 `_enqueue_reply_batch()` 对 AI 批次使用：

```python
self.reply_buffer.prepend_batch(batch_items, preserve_existing=...)
```

普通模式建议不要 prepend 覆盖旧项，改为按返回顺序追加或替换为当前批：

推荐方案 A：追加本批并消费完

- 给 `AIReplyFIFOBuffer` 增加 `extend(items)`，按顺序 append。
- 普通模式下 `_enqueue_reply_batch()` 调用 `extend(batch_items)`。
- `reply_buffer.max_items` 在普通模式下至少为 `normal_reply_count`，避免刚入队就被容量截断。

推荐方案 B：每轮只保留当前批

- 普通模式下先 `reply_buffer.clear()`，再 append 本批。
- 语义更简单：一次识别对应一次输出。
- 如果上一批还没显示完，新识别会替换旧批；这与「输出所有生成的弹幕」略有冲突。

建议采用方案 A。它更符合用户目标，也更少丢弹幕。

消费节奏：

- 可以复用 `_consume_reply_queue()` 当前逐条消费逻辑。
- 普通模式下 `delay = 100 if item is None else self._estimated_reply_gap_ms()` 可以保留。
- 如果用户期望更快输出整批，可后续新增普通模式专用间隔；本次不做，避免过度设计。

## 去重语义

普通模式不绕过去重。流程应保持：

1. AI 返回 `normal_reply_count` 条。
2. `normalize_reply_batch()` 标准化。
3. 消费时调用 `DanmuEngine.add_text()`。
4. 重复项返回 `None` 并记录拒绝原因。
5. 非重复项全部进入显示链路。

注意点：

- 不要在 `_enqueue_reply_batch()` 阶段做额外去重，否则会形成第二套规则。
- 不要因为普通模式要求「输出所有」而设置 `skip_dedup=True`。
- `drop_stale` 在普通模式下建议默认仍生效，但 TTL 应按 `normal_recognition_interval_sec` 调整，否则 x 较大时容易把合法批次判旧。

建议：

- `_is_reply_stale()` 对普通模式使用 `max(existing_ttl, normal_recognition_interval_sec * 2)`。
- 或普通模式下仅保留 `scene_generation` 过期判断，关闭 captured_at TTL。第一版推荐前者，风险更小。

## 与现有实时新鲜度的关系

实时模式依赖：

- `stale_scene`
- `stale_scene_in_flight`
- `freshness` TTL
- `BatchTracker`
- 本地 fallback
- 库存低水位预触发

普通模式应尽量减少这些实时策略的介入：

- 不触发 `_maybe_emit_local_fallback()`。
- 不使用 `_check_rhythm_trigger()`。
- 不根据库存低水位提前请求。
- 场景变化可以继续更新 `scene_generation`，但不应清空普通模式当前批的去重窗口，除非现有 strict/medium 行为明确需要。

## 测试计划

### Web 配置

新增或扩展 `tests/test_web_console.py`：

- `test_web_config_keys_include_display_mode_settings`
  - 断言 3 个新 key 在 `WEB_CONFIG_KEYS`。
- `test_apply_config_patch_clamps_display_mode_settings`
  - 非法模式回退 `realtime`。
  - interval 小于 1 变 1，大于 60 变 60。
  - count 小于 1 变 1，大于 20 变 20。

### 输出契约

新增或扩展 `tests/test_reply_contract.py`：

- `test_normal_mode_contract_uses_single_reply_count`
  - 配置 `danmu_display_mode=normal`、`normal_reply_count=8`。
  - 断言契约要求固定返回 8 条。
  - 断言不再出现「前 x 条 / 后 y 条」的实时拆分语义。

### 主流程

新增或扩展 `tests/test_p0_main_flow.py`：

- `test_normal_mode_start_uses_configured_capture_interval`
  - normal 模式 interval=7。
  - start 后 `screenshot_timer` interval 为 7000ms。
  - `_rhythm_check_timer` 不启动。

- `test_normal_mode_enqueues_full_batch_without_prepend_replacement`
  - 构造两批普通模式 AI 返回。
  - 第二批入队不覆盖第一批未消费项。
  - 队列容量足够时，所有 item 都保留。

- `test_normal_mode_consumes_all_non_duplicate_items`
  - FakeEngine 让其中一条重复返回 `None`，其他返回 item。
  - 断言非重复项都会调用 `add_text()`。
  - 断言重复项不会写 history。

- `test_realtime_mode_behavior_unchanged`
  - realtime 模式仍启动 1s screenshot timer 和 200ms rhythm timer。

## 实施顺序

1. 先加配置键和钳制测试。
2. 加 Web UI 字段和 `app.js` 显隐逻辑。
3. 加普通模式输出契约，补契约测试。
4. 在 `main.py` 增加模式读取和 `start()` 分支，但先保持实时路径完全不动。
5. 增加普通模式队列 append 行为，补主流程测试。
6. 手动运行 Web 控制台验证：

```bash
python -m pytest tests/test_web_console.py tests/test_reply_contract.py tests/test_p0_main_flow.py -v --tb=short
python main.py --web-browser
```

## 风险点

- `screenshot_timer.timeout` 当前直接连接 `_capture_screenshot()`，普通模式如果要截图后立即触发 API，需要新增统一入口或额外触发点。
- `AIReplyFIFOBuffer.prepend_batch()` 当前适配实时模式，新批会替换库存；普通模式必须避免沿用该行为。
- `normal_reply_count` 如果允许 20，`max_tokens` 下限和人格契约需要保证模型能完整返回；必要时普通模式保存时提示用户调高 `max_tokens`。
- `drop_stale` TTL 需要适配普通模式间隔，否则间隔较大时可能误丢。
- 现有文件存在部分中文 mojibake，实施时应避免无关格式化，防止扩大 diff。

## 验收标准

- 默认配置下行为与当前实时模式一致。
- Web「弹幕显示」tab 能切换普通/实时模式，并正确保存、刷新后保留。
- 普通模式下按 x 秒触发一次画面识别。
- 普通模式下每次请求契约要求生成 y 条弹幕。
- 普通模式下 AI 返回的 y 条弹幕经过去重后，不被实时模式的 prepend/库存策略丢弃。
- 实时模式原有测试通过，且普通模式新增测试通过。
