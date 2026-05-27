# Storage Boundary Plan

> Archived internal reference. See [CONTRIBUTING_ARCHITECTURE.md](../../CONTRIBUTING_ARCHITECTURE.md) for current storage rules.

## 范围

本文件只定义 Phase 2 的存储边界整理结果，不改 schema，不迁库，不改数据路径。

## 当前共享连接事实

当前仍由 `app/config_store.py::ConfigStore` 持有共享 SQLite 连接与 schema 初始化职责：

- `config` 表
- `history` 表
- `templates` 表

现存直接使用 `config.conn` 的模块：

- `app/config_store.py`
- `app/history.py`
- `app/history_writer.py`
- `app/templates.py`
- `app/danmu_engine.py`

说明：

- `app/history.py` 负责历史查询/导出。
- `app/history_writer.py` 负责后台批量写入历史。
- `app/templates.py` 负责人格模板版本化存取。
- `app/danmu_engine.py` 仍直接读取历史做去重预热。

## Phase 2 结论

- 不新增 schema。
- 不迁移现有 SQLite 数据。
- 不拆散 `ConfigStore`。
- 不改变 `HistoryWriter` 写入语义。
- 不改变 `TemplateManager` 行为。

## 最小边界建议

Phase 2 只做文档级边界声明：

1. 新增存储能力时，不再默认继续扩散 `config.conn`。
2. 配置写入口先收口到应用层服务，再考虑 Repository 化。
3. `history` / `templates` / `config` 的 Repository 拆分推迟到 Phase 3。

## Phase 3 才处理的事项

- `ConfigRepository`、`HistoryRepository`、`TemplateRepository` 的真实代码拆分
- `DanmuEngine` 的历史预热读取外移
- `TemplateManager` 对 `config._write_lock` 的依赖收口
- `ConfigStore` schema 初始化职责再分层
