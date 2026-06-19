# 工单 ID

W-DANMU-POOL-20000

## 工单标题

将“自定义弹幕库 / 自定义公式化弹幕库”扩容至 20000 条，并完成 20000 条规模下的最小可靠性能优化

## 背景

已确认当前“公式化弹幕库”中的自定义弹幕实现并不是独立数据库表，而是以 JSON 列表形式存放在 `config` 表的 `custom_danmu_pool` 键内，由 `ConfigStore.get_custom_danmu_pool()` / `set_custom_danmu_pool()` 整体读写。

已确认当前实现存在以下瓶颈：

1. 存储层仍是整库 JSON 读写。
   证据：
   - `app/config_store.py:573-580`
   - `get_custom_danmu_pool()` 直接读取 `custom_danmu_pool` JSON。
   - `set_custom_danmu_pool()` 直接整列表 `set_json()` 回写。
2. API 层追加、删除都先整库读出，再整库写回。
   证据：
   - `app/web_api/danmu_pool.py:74-128`
3. API 当前上限仍是 2500，且单次追加上限 5000。
   证据：
   - `app/web_api/danmu_pool.py:24-26`
4. 前端打开页面时会一次性请求全部自定义弹幕，再整列表渲染 DOM。
   证据：
   - `web/static/modules/app-danmu-pool-page.js:33-55`
   - `web/static/modules/app-danmu-pool-page.js:152-163`
5. 导入 txt 后前端会直接重新渲染整个返回列表。
   证据：
   - `web/static/modules/app-danmu-pool-page.js:101-149`
6. 抽样链路当前虽有进程内缓存，但仍建立在“整库先读入 list”之上。
   证据：
   - `app/danmu_pool.py:46-84`

因此，本工单目标不是“只把数字改成 20000”，而是在尽量小改动前提下，将自定义弹幕从 JSON 整库方案迁移到适合 20000 条规模的可分页、可搜索、可增量写入的数据结构，并保持现有功能兼容。

## 目标

完成后必须满足：

1. 自定义弹幕库有效容量统一提升为 20000 条。
2. 启动、打开设置页、搜索、分页、导入、删除、保存、抽取时，不因 20000 条数据产生明显 UI 卡顿或主线程阻塞。
3. 列表页不能一次性渲染 20000 条。
4. `txt` 导入场景下，不在页面中展示全部导入内容；列表页只展示“手动添加”的内容。
5. 导入数据仍需计入总容量、支持去重、支持抽取。
6. 旧版本已有 `custom_danmu_pool` 数据必须可安全迁移，不得丢失。

## 依赖项

- Python 3.12+
- 现有 SQLite `config.db`
- 与本工单相关的测试可单独分批执行，不允许本地全量 pytest

## 允许修改的区域

- `app/config_store.py`
- `app/danmu_pool.py`
- `app/web_api/danmu_pool.py`
- `app/web_api/routes.py`
- `web/static/index.html`
- `web/static/app.js`
- `web/static/modules/app-danmu-pool-page.js`
- `tests/test_danmu_pool.py`
- `tests/test_danmu_pool_api.py`
- `tests/test_config_store.py`
- 与本功能直接相关的新增测试文件
- 必要的功能文档或交付文档

## 禁止修改的区域

- `main.py` 主链路结构
- 与本工单无关的 `app/main_*` mixin
- 与本工单无关的 UI 页面
- `requirements.txt`
- 与本工单无关的表结构、API、模型、人格、桌宠、麦克风功能

## 当前实现梳理

### 1. 存储位置与数据结构

- 当前自定义弹幕存储在 `config` 表的 `custom_danmu_pool` 键。
- 类型为 JSON 数组，每项是字符串。
- 没有独立行级主键，没有来源字段，没有分页查询能力，没有搜索索引。
- 当前测试假对象 `tests/fakes.py:108-115` 也沿用同样的整列表语义。

### 2. 读取、写入、导入、删除、去重逻辑

- 读取：
  - `ConfigStore.get_custom_danmu_pool()` 直接 JSON 反序列化。
- 写入：
  - `ConfigStore.set_custom_danmu_pool()` 直接整库 JSON 覆盖写回。
- 导入/追加：
  - `app/web_api/danmu_pool.py:74-113`
  - 先取全部 existing，再逐项去重，最后合并后整库回写。
- 删除：
  - `app/web_api/danmu_pool.py:116-128`
  - 先加载全部 existing，再过滤后整库回写。
- 去重：
  - 仅按字符串完全相等去重。
  - 无数据库唯一约束。

### 3. UI 列表展示、编辑、搜索、分页、筛选

- 当前页面加载时：
  - `GET /api/danmu-pool/meta`
  - `GET /api/danmu-pool/custom`
- 前端收到 `items` 后直接 `forEach` 渲染全部条目。
- 当前没有分页、虚拟列表、服务端搜索、服务端分页。
- 当前删除依赖页面中 checkbox 勾选项，因此列表规模大时会卡。

### 4. 弹幕抽取

- `app/danmu_pool.py:70-84`
- 当前抽取逻辑是先 `load_custom_danmu_pool(config)` 取到完整 list，再 `random.sample(...)`。
- `maybe_pool_topup()` 每次补位最多抽 8 条，单次成本不大，但底层仍依赖完整 list 常驻缓存。

### 5. 已确认的性能隐患

- 启动后首次读取自定义库，如果达到 20000 条，JSON 反序列化与去重会明显变重。
- 打开页面会一次性拉取全量条目并全量渲染。
- 导入大批量文本时会整批拼接、整库去重、整库写回。
- 删除/编辑任意条目也会整库写回。
- 当前 API 返回 `items` 全量列表，不适合 20000 条。

## 推荐实现方案

本工单优先采用“最小但可靠”的方案：把自定义弹幕迁移到 SQLite 独立表，不做无必要的大重构。

### 一、数据层改造

新增独立表，例如：

`custom_danmu_pool_entries`

建议字段：

- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `text TEXT NOT NULL`
- `source TEXT NOT NULL DEFAULT 'manual'`
- `enabled INTEGER NOT NULL DEFAULT 1`
- `created_at REAL NOT NULL`
- `updated_at REAL NOT NULL`
- `use_count INTEGER NOT NULL DEFAULT 0`

必要约束与索引：

- `UNIQUE(text)`：防止重复导入膨胀
- `INDEX(source, id)`
- 如需搜索，可先建：
  - `INDEX(text)`
  - 若 `LIKE '%keyword%'` 性能仍不足，再单独开后续工单，不在本工单内引入 FTS

### 二、兼容迁移

在 `ConfigStore` 初始化阶段增加一次性安全迁移：

1. 若新表为空且旧 `custom_danmu_pool` 有数据，则迁移旧 JSON 数据到新表。
2. 迁移过程要去重、过滤空行。
3. 迁移成功前不得删除旧 JSON 数据。
4. 迁移成功后可保留旧键作为回退冗余，或写入 `custom_danmu_pool_migrated=1` 标记。
5. 迁移失败时：
   - 新表不应污染为部分成功状态。
   - 旧 JSON 数据必须仍可读。

### 三、存储 API 重构

在 `ConfigStore` 中新增独立门面，替代整库 JSON 操作：

- `custom_danmu_count(...)`
- `custom_danmu_list(page, page_size, search, source)`
- `custom_danmu_insert_many(items, source)`
- `custom_danmu_delete_ids(ids)` 或 `custom_danmu_delete_texts(texts)`
- `custom_danmu_random_sample(count)`
- `custom_danmu_contains_text(text)`

要求：

1. 常规增删改不得再整库 JSON 重写。
2. 批量导入必须使用批量 SQL。
3. 返回列表必须支持分页。
4. 总数统计与列表读取分离。

### 四、导入来源区分

这是本次新增的明确需求，必须落实：

1. `txt` 导入的数据写入库时，`source='import'`。
2. 手动输入追加的数据写入库时，`source='manual'`。
3. 列表页默认只展示 `source='manual'` 的条目。
4. `txt` 导入后的内容：
   - 计入总容量；
   - 参与去重；
   - 参与随机抽取；
   - 不在“手动添加列表”中全量显示。
5. 页面上必须明确文案，例如：
   - “当前展示：手动添加条目”
   - “txt 导入内容已入库参与抽取，但不在此列表逐条展示”
6. 总数展示要区分：
   - 自定义库总数：`total / 20000`
   - 可选展示手动数：`manual_count`

### 五、前端列表与交互

前端必须改为分页或懒加载，不能再请求/渲染全量列表。

建议方案：

1. `GET /api/danmu-pool/custom` 改为支持：
   - `page`
   - `page_size`
   - `search`
   - `source`
2. 默认：
   - `source=manual`
   - `page_size=100`
3. 页面增加：
   - 搜索框
   - 分页控件
   - 总数展示：`自定义库：1234 / 20000`
   - 当前列表说明：`当前显示手动添加的 100 条`
4. 删除操作按当前页条目工作，不依赖全量 DOM。
5. 搜索结果也必须分页。

### 六、导入流程优化

当前前端一次读取文件全文后直接 POST，后端整批处理。保留整体交互，但要优化处理方式。

要求：

1. 单次导入仍可接受多文件，但总有效入库不得超过 20000。
2. 自动过滤：
   - 空行
   - 重复文本
   - 非法/不安全文本
   - 超限条目
3. 返回结构必须包含明确统计：
   - `added`
   - `skipped_duplicate`
   - `skipped_empty`
   - `skipped_unsafe`
   - `skipped_limit`
4. `txt` 导入完成后：
   - 不返回全量 `items`
   - 只返回统计与最新 meta
   - 前端不触发全量列表重渲染
5. 大批量导入应使用批量 SQL + 事务。
6. 如前端处理大文件仍卡，可在读取阶段加分批或 `await` 让步，但不要大改上传协议。

### 七、抽样逻辑优化

随机抽取要摆脱“先读完整 list 再 sample”的硬依赖。

建议：

1. 由 `ConfigStore.custom_danmu_random_sample(count)` 直接从 SQLite 获取样本。
2. 可接受的最小实现：
   - 先缓存 `id` 范围或可用总数；
   - 再按随机偏移/随机 id 做轻量抽样；
   - 或分页批量取样后再随机。
3. 禁止每轮补位都重新拉取 20000 条完整文本。
4. 若保留进程内缓存，缓存应是轻量索引或有限样本，不应是每次写入后频繁重建 20000 条完整字符串集合，除非有明确基准证明足够快。

### 八、现有缓存逻辑处理

当前 `app/danmu_pool.py` 中 `_custom_pool_lists`、`_formula_custom_sets` 是基于整库 list/set 的进程内缓存。

本工单要求：

1. 重新评估这些缓存是否还需要保留。
2. 若保留，必须与新表写入点统一失效。
3. 不允许因为缓存失效策略错误导致页面看不到新数据或抽样读取旧数据。

## 需求

1. 将自定义弹幕库全链路上限统一调整为 20000，包括后端常量、前端提示、校验、导入限制、错误提示、测试断言。
2. 自定义弹幕改为 SQLite 独立表存储，禁止继续依赖 `custom_danmu_pool` JSON 整库读写作为主存储。
3. 保留旧 JSON 数据兼容迁移，迁移失败不得导致旧数据丢失。
4. 页面列表必须分页或懒加载，禁止一次性展示 20000 条。
5. 搜索必须走分页结果，不能前端先拉全量再本地过滤。
6. `txt` 导入数据必须标记为 `source='import'`，且不在页面中逐条展示。
7. 页面列表默认只展示 `source='manual'` 的手动添加内容。
8. 导入后返回明确统计，不返回全量导入列表。
9. 删除、编辑、保存不得触发整库 JSON 重写。
10. 抽样逻辑不得每轮对 20000 条做全量高成本计算。
11. 所有与当前上限 `2500` 相关的测试和文案必须同步更新。
12. 新实现要尽量保持现有 API 语义稳定；若必须改响应结构，应同步改前端和测试。

## 非目标

- 不重构整个 Web 控制台架构
- 不引入新的外部依赖
- 不顺手修改 meme barrage 库逻辑
- 不调整主链路调度、截图、AI 请求架构
- 不做全文搜索高级能力（如 FTS）除非简单索引无法满足本工单基本要求
- 不把导入内容再做一套单独 UI 管理页，除非现有页无法承载基本说明与统计

## 建议修改文件

- `app/config_store.py`
  - 新增表初始化、迁移、分页查询、批量插入、随机抽样门面
- `app/danmu_pool.py`
  - 改造 pool 加载、抽样、缓存失效逻辑
- `app/web_api/danmu_pool.py`
  - 改造 meta/list/append/delete 返回结构与分页/搜索接口
- `app/web_api/routes.py`
  - 若请求模型需要新增 query 参数或响应结构
- `web/static/modules/app-danmu-pool-page.js`
  - 改造列表加载、分页、搜索、导入后刷新逻辑
- `web/static/index.html`
  - 增加分页/搜索/说明文案/计数展示
- `tests/test_config_store.py`
  - 增加迁移、分页、随机抽样、20000 条场景测试
- `tests/test_danmu_pool.py`
  - 更新抽样与缓存相关测试
- `tests/test_danmu_pool_api.py`
  - 更新上限、导入结果、分页、source 行为测试

## 验收标准

- [ ] 当前自定义弹幕库总上限已统一为 20000，代码、API、UI、提示文案、测试一致
- [ ] 打开自定义弹幕库页时，不会请求并渲染全部 20000 条
- [ ] 自定义列表支持分页，默认页大小在 50 至 200 之间
- [ ] 搜索结果也走分页，不是前端全量过滤
- [ ] `txt` 导入的数据成功入库并参与抽取，但页面列表只显示手动添加项
- [ ] 页面明确展示总数量，如“自定义库：1234 / 20000”
- [ ] 导入超过 20000 条时会正确截断，并返回清晰统计
- [ ] 重复文本不会重复入库
- [ ] 删除或新增单条时不再整库 JSON 重写
- [ ] 随机抽取在 20000 条规模下仍可稳定工作
- [ ] 旧版 `custom_danmu_pool` 数据迁移后仍可显示、删除、抽取
- [ ] 相关测试通过，且仅执行与本工单相关的分批测试

## 手动验证步骤

1. 用旧格式 `custom_danmu_pool` 数据启动应用，确认数据自动迁移后仍可在页面中看到手动条目，且抽取正常。
2. 批量导入接近 20000 条文本，确认页面不卡死，导入结果提示包含成功数、重复数、超限数、非法数。
3. 导入完成后确认列表页没有把导入内容全部渲染出来，只保留手动添加列表展示。
4. 手动新增若干条，确认当前页能看到新增项，总数同步增加。
5. 搜索手动条目，确认结果正确且分页可切换。
6. 在 20000 条规模下开始生成弹幕，确认公式化弹幕补位仍可正常抽取，不出现明显停顿。

## 测试要求

按项目约束，禁止本地全量 pytest。至少补充并执行：

1. `python -m pytest tests/test_config_store.py -q -x`
2. `python -m pytest tests/test_danmu_pool.py -q -x`
3. `python -m pytest tests/test_danmu_pool_api.py -q -x`
4. 如新增了专门的大数据场景测试，再单独 `-q -x` 执行

建议新增测试覆盖：

- 20000 条容量下的保存/加载
- 旧 JSON 到新表的迁移
- `txt` 导入写入 `source='import'`
- 手动输入写入 `source='manual'`
- 列表接口默认仅返回 `manual`
- 导入后不返回全量 `items`
- 搜索分页结果正确
- 随机抽样在大库规模下可用

## 风险点

1. 迁移逻辑如果处理不当，最容易造成旧数据丢失或重复写入。
2. 前端如果仍沿用“删除依赖当前 DOM checkbox 文本”的模式，分页后容易出现删除语义错误，建议尽快改成基于 `id` 删除。
3. 若随机抽样 SQL 方案设计不当，可能出现抽样不均或在稀疏 id 场景下性能波动。
4. 当前 `is_stored_custom_pool_text()` 等缓存逻辑依赖完整集合，迁移后必须重新核对调用点，否则会出现旧缓存命中问题。

## 完成后必须给出的报告

完成实现后，执行人必须在完成报告中明确回答：

1. 当前自定义弹幕库原本的存储方式和性能瓶颈是什么
2. 具体修改了哪些文件
3. 上限是否已经统一改为 20000
4. 是否避免了一次性渲染/一次性全量处理
5. 20000 条数据下的加载、搜索、保存、抽取表现是否正常
6. 是否保留旧数据兼容
7. 还剩哪些风险或后续优化建议

## 交接提示

执行人先读：

1. `E:/test/danmu/.local-ai/prompts/AGENTS.md`
2. `E:/test/danmu/.local-ai/prompts/Fable5.md`
3. `E:/test/danmu/.local-ai/prompts/ai-project-context.md`

再读以下现状文件：

1. `E:/test/danmu/app/config_store.py`
2. `E:/test/danmu/app/danmu_pool.py`
3. `E:/test/danmu/app/web_api/danmu_pool.py`
4. `E:/test/danmu/app/web_api/routes.py`
5. `E:/test/danmu/web/static/modules/app-danmu-pool-page.js`
6. `E:/test/danmu/tests/test_danmu_pool.py`
7. `E:/test/danmu/tests/test_danmu_pool_api.py`
