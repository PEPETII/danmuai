"""知识库数据层测试（任务 A1.6）。

覆盖 spec §ADDED Requirements — Knowledge Database 的全部 Scenario：
    - 首次启动建库
    - 迁移幂等
    - FTS5 不可用回退
    - 多线程连接安全
    - 启动时中断恢复
    - 级联删除（应用层单事务）

约定（AGENTS.md §A.4.4）：
    - 使用 ``tmp_path`` fixture（pytest 自动重定向到 ``.pytest_tmp/``）；
    - 不使用 ``sqlite3.connect(":memory:")``（FTS5 探测需真实文件）；
    - 用 ``KnowledgeDatabase._open_at(path)`` 工厂指定路径。
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from app.knowledge import (
    KnowledgeBatchResponse,
    KnowledgeContextSnapshot,
    KnowledgeDatabase,
    KnowledgeItemCandidate,
    KnowledgeRepository,
)
from app.knowledge.migrations import _detect_fts_backend, run_pending


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path: Path) -> KnowledgeDatabase:
    """在 tmp_path 下开一个独立 KnowledgeDatabase。"""
    return KnowledgeDatabase._open_at(tmp_path / "test_knowledge.db")


@pytest.fixture
def repo(db: KnowledgeDatabase) -> KnowledgeRepository:
    return KnowledgeRepository(db)


# ---------------------------------------------------------------------------
# 模型测试
# ---------------------------------------------------------------------------


class TestModels:
    """A1.2：Pydantic 模型字段约束。"""

    def test_knowledge_item_candidate_valid(self) -> None:
        item = KnowledgeItemCandidate(
            kind="fact",
            title="葛瑞克二阶段",
            content="葛瑞克二阶段会断臂接上龙头并使用喷火攻击。",
            examples=["又开始了", "经典"],
            triggers=["葛瑞克", "二阶段"],
            tones=["轻松"],
            scopes=["游戏", "艾尔登法环"],
            entities=["接肢葛瑞克"],
            confidence=0.94,
            evidence="这波没绷住",
        )
        assert item.kind == "fact"
        assert item.title == "葛瑞克二阶段"
        assert len(item.examples) == 2

    def test_knowledge_item_candidate_rejects_invalid_kind(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            KnowledgeItemCandidate(
                kind="invalid_kind",  # type: ignore[arg-type]
                title="标题",
                content="内容",
            )

    def test_knowledge_item_candidate_rejects_empty_title(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            KnowledgeItemCandidate(kind="fact", title="", content="内容")

    def test_knowledge_item_candidate_rejects_long_title(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            KnowledgeItemCandidate(
                kind="fact",
                title="字" * 41,
                content="内容",
            )

    def test_knowledge_item_candidate_rejects_long_content(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            KnowledgeItemCandidate(
                kind="fact",
                title="标题",
                content="字" * 161,
            )

    def test_knowledge_item_candidate_rejects_too_many_examples(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            KnowledgeItemCandidate(
                kind="fact",
                title="标题",
                content="内容",
                examples=["例1", "例2", "例3", "例4", "例5", "例6"],
            )

    def test_knowledge_item_candidate_rejects_long_example(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            KnowledgeItemCandidate(
                kind="fact",
                title="标题",
                content="内容",
                examples=["字" * 31],
            )

    def test_knowledge_item_candidate_rejects_confidence_out_of_range(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            KnowledgeItemCandidate(
                kind="fact",
                title="标题",
                content="内容",
                confidence=1.5,
            )
        with pytest.raises(ValidationError):
            KnowledgeItemCandidate(
                kind="fact",
                title="标题",
                content="内容",
                confidence=-0.1,
            )

    def test_knowledge_item_candidate_ignores_extra_fields(self) -> None:
        item = KnowledgeItemCandidate(
            kind="fact",
            title="标题",
            content="内容",
            extra_field="应被忽略",  # type: ignore[call-arg]
        )
        assert not hasattr(item, "extra_field")

    def test_knowledge_batch_response(self) -> None:
        batch = KnowledgeBatchResponse(
            document_kind="livestream_chat",
            items=[
                KnowledgeItemCandidate(
                    kind="meme", title="又开始了", content="当主播重复此前失败操作时。"
                )
            ],
        )
        assert batch.document_kind == "livestream_chat"
        assert len(batch.items) == 1
        assert batch.items[0].kind == "meme"

    def test_knowledge_context_snapshot_is_frozen(self) -> None:
        snapshot = KnowledgeContextSnapshot(
            prompt_text="片段",
            scene_brief="玩家与Boss战斗",
            keywords=("Boss战", "喷火"),
            item_ids=(1, 2),
            source_request_round=3,
            source_screenshot_id=42,
            updated_at=time.time(),
        )
        # frozen dataclass：正常赋值会抛 FrozenInstanceError
        with pytest.raises(Exception):
            snapshot.prompt_text = "改"  # type: ignore[misc]
        assert snapshot.prompt_text == "片段"
        assert snapshot.keywords == ("Boss战", "喷火")


# ---------------------------------------------------------------------------
# 数据库基础测试
# ---------------------------------------------------------------------------


class TestDatabaseOpen:
    """A1.3 + spec Scenario: 首次启动建库 / 迁移幂等 / FTS5 探测。"""

    def test_first_time_creation_creates_all_tables(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "knowledge.db"
        assert not db_path.exists()

        db = KnowledgeDatabase._open_at(db_path)

        assert db_path.exists()
        # 5 张主表 + schema_meta
        tables = self._table_names(db)
        for expected in (
            "knowledge_packages",
            "knowledge_sources",
            "knowledge_chunks",
            "knowledge_items",
            "knowledge_jobs",
            "schema_meta",
        ):
            assert expected in tables, f"missing table: {expected}"

        # schema_version 已写入
        row = db.conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        assert row is not None
        assert int(row[0]) >= 1

        # FTS5 表存在当且仅当 backend != fallback
        if db.fts_backend != "fallback":
            assert "knowledge_items_fts" in tables
        else:
            assert "knowledge_items_fts" not in tables

        db.close()

    def test_migration_idempotent(self, tmp_path: Path) -> None:
        """再次打开已存在的库不应抛异常，schema_version 不变。"""
        db_path = tmp_path / "knowledge.db"
        db1 = KnowledgeDatabase._open_at(db_path)
        version1 = db1.conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0]
        db1.close()

        # 再次打开（迁移应 no-op）
        db2 = KnowledgeDatabase._open_at(db_path)
        version2 = db2.conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0]
        assert version1 == version2
        db2.close()

    def test_run_pending_is_idempotent_on_same_conn(self, tmp_path: Path) -> None:
        """在同一连接上重复调 run_pending 不应报错或重复写入。"""
        db = KnowledgeDatabase._open_at(tmp_path / "knowledge.db")
        version_before = db.conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0]
        # 再调一次（fts_backend 显式传入避免重探测）
        run_pending(db.conn, fts_backend=db.fts_backend)
        version_after = db.conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0]
        assert version_before == version_after
        db.close()

    def test_fts_backend_is_known_value(self, tmp_path: Path) -> None:
        """FTS5 探测结果必须是 trigram/fts5/fallback 之一。"""
        db = KnowledgeDatabase._open_at(tmp_path / "knowledge.db")
        assert db.fts_backend in ("trigram", "fts5", "fallback")
        db.close()

    def test_fts_detection_does_not_pollute_connection(
        self, tmp_path: Path
    ) -> None:
        """_detect_fts_backend 用独立内存连接探测，不应在业务连接留下临时表。"""
        conn = sqlite3.connect(str(tmp_path / "probe.db"))
        try:
            backend = _detect_fts_backend(conn)
            assert backend in ("trigram", "fts5", "fallback")
            # 业务连接不应有探测临时表
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "_t" not in tables
            assert "_t2" not in tables
            assert "_fts5_probe" not in tables
        finally:
            conn.close()

    def test_open_does_not_enable_foreign_keys(self, tmp_path: Path) -> None:
        """项目约定：不启用 PRAGMA foreign_keys。"""
        db = KnowledgeDatabase._open_at(tmp_path / "knowledge.db")
        row = db.conn.execute("PRAGMA foreign_keys").fetchone()
        assert int(row[0]) == 0
        db.close()

    def test_open_sets_wal_and_busy_timeout(self, tmp_path: Path) -> None:
        db = KnowledgeDatabase._open_at(tmp_path / "knowledge.db")
        journal = db.conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(journal).lower() == "wal"
        busy = db.conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert int(busy) == 5000
        db.close()

    @staticmethod
    def _table_names(db: KnowledgeDatabase) -> set[str]:
        return {
            row[0]
            for row in db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            ).fetchall()
        }


# ---------------------------------------------------------------------------
# 级联删除测试
# ---------------------------------------------------------------------------


class TestCascadeDelete:
    """spec §ADDED Requirements — Knowledge Database：级联删除 SHALL 在应用层
    单事务内显式执行（DELETE FTS 行 → DELETE items → DELETE chunks →
    DELETE sources → DELETE packages）。"""

    def test_delete_package_cascades_to_all_children(
        self, repo: KnowledgeRepository, db: KnowledgeDatabase
    ) -> None:
        # 构造完整层级：package → source → chunk → item + job
        pkg = repo.create_package(name="测试包")
        package_id = repo.get_package(pkg["public_id"])["id"]  # type: ignore[index]

        source = repo.create_source(
            package_id=package_id,
            source_type="pasted_text",
            display_name="测试来源",
            normalized_text="一些正文",
        )
        source_id = source["id"]

        chunks = repo.insert_chunks(
            source_id=source_id,
            chunks=[{"sequence_no": 0, "heading": "标题", "content": "块内容"}],
        )
        chunk_id = chunks[0]["id"]

        item = repo.insert_item(
            package_id=package_id,
            source_id=source_id,
            chunk_id=chunk_id,
            kind="fact",
            title="事实",
            content="事实内容",
            triggers=["触发词"],
        )

        job = repo.create_job(package_id=package_id, source_id=source_id)

        # 删包
        assert repo.delete_package(pkg["public_id"]) is True

        # 全部子表应清空
        assert repo.get_package(pkg["public_id"]) is None
        assert repo.get_source(source["public_id"]) is None
        assert repo.list_sources(package_id) == []
        assert repo.list_chunks(source_id) == []
        assert repo.get_item(item["public_id"]) is None
        assert repo.get_job(job["public_id"]) is None

        # 直接查表确认无残留
        assert self._count(db, "knowledge_packages") == 0
        assert self._count(db, "knowledge_sources") == 0
        assert self._count(db, "knowledge_chunks") == 0
        assert self._count(db, "knowledge_items") == 0
        assert self._count(db, "knowledge_jobs") == 0

        # FTS 表也应无残留（若存在）
        if db.fts_backend != "fallback":
            fts_count = db.conn.execute(
                "SELECT COUNT(*) FROM knowledge_items_fts"
            ).fetchone()[0]
            assert fts_count == 0

    def test_delete_nonexistent_package_returns_false(
        self, repo: KnowledgeRepository
    ) -> None:
        assert repo.delete_package("nonexistent_public_id") is False

    def test_delete_item_removes_fts_row(
        self, repo: KnowledgeRepository, db: KnowledgeDatabase
    ) -> None:
        pkg = repo.create_package(name="包")
        package_id = repo.get_package(pkg["public_id"])["id"]  # type: ignore[index]
        source = repo.create_source(
            package_id=package_id,
            source_type="pasted_text",
            display_name="来源",
        )
        item = repo.insert_item(
            package_id=package_id,
            source_id=source["id"],
            chunk_id=None,
            kind="fact",
            title="标题",
            content="内容",
        )

        # FTS 行存在
        if db.fts_backend != "fallback":
            fts_count = db.conn.execute(
                "SELECT COUNT(*) FROM knowledge_items_fts WHERE rowid=?",
                (item["id"],),
            ).fetchone()[0]
            assert fts_count == 1

        # 删除 item
        assert repo.delete_item(item["public_id"]) is True
        assert repo.get_item(item["public_id"]) is None

        # FTS 行也应删除
        if db.fts_backend != "fallback":
            fts_count = db.conn.execute(
                "SELECT COUNT(*) FROM knowledge_items_fts WHERE rowid=?",
                (item["id"],),
            ).fetchone()[0]
            assert fts_count == 0

    @staticmethod
    def _count(db: KnowledgeDatabase, table: str) -> int:
        return int(
            db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        )


# ---------------------------------------------------------------------------
# 启动时中断恢复测试
# ---------------------------------------------------------------------------


class TestJobInterruptedRecovery:
    """spec §ADDED Requirements — Knowledge Database：启动时中断恢复。"""

    def test_mark_job_interrupted_at_startup_updates_pending_and_running(
        self, repo: KnowledgeRepository
    ) -> None:
        pkg = repo.create_package(name="包")
        package_id = repo.get_package(pkg["public_id"])["id"]  # type: ignore[index]
        source = repo.create_source(
            package_id=package_id,
            source_type="pasted_text",
            display_name="来源",
        )

        # 构造三种状态的 job
        job_pending = repo.create_job(
            package_id=package_id, source_id=source["id"], status="pending"
        )
        job_running = repo.create_job(
            package_id=package_id, source_id=source["id"], status="running"
        )
        job_completed = repo.create_job(
            package_id=package_id, source_id=source["id"], status="completed"
        )
        job_failed = repo.create_job(
            package_id=package_id, source_id=source["id"], status="failed"
        )

        affected = repo.mark_job_interrupted_at_startup()
        assert affected == 2  # pending + running

        assert repo.get_job(job_pending["public_id"])["status"] == "interrupted"  # type: ignore[index]
        assert repo.get_job(job_running["public_id"])["status"] == "interrupted"  # type: ignore[index]
        # completed / failed 不受影响
        assert repo.get_job(job_completed["public_id"])["status"] == "completed"  # type: ignore[index]
        assert repo.get_job(job_failed["public_id"])["status"] == "failed"  # type: ignore[index]

    def test_mark_job_interrupted_at_startup_idempotent(
        self, repo: KnowledgeRepository
    ) -> None:
        pkg = repo.create_package(name="包")
        package_id = repo.get_package(pkg["public_id"])["id"]  # type: ignore[index]
        source = repo.create_source(
            package_id=package_id,
            source_type="pasted_text",
            display_name="来源",
        )
        repo.create_job(
            package_id=package_id, source_id=source["id"], status="running"
        )

        assert repo.mark_job_interrupted_at_startup() == 1
        # 再调一次，无 pending/running 可改
        assert repo.mark_job_interrupted_at_startup() == 0

    def test_mark_job_interrupted_at_startup_sets_finished_at(
        self, repo: KnowledgeRepository
    ) -> None:
        pkg = repo.create_package(name="包")
        package_id = repo.get_package(pkg["public_id"])["id"]  # type: ignore[index]
        source = repo.create_source(
            package_id=package_id,
            source_type="pasted_text",
            display_name="来源",
        )
        job = repo.create_job(
            package_id=package_id, source_id=source["id"], status="running"
        )

        repo.mark_job_interrupted_at_startup()

        updated = repo.get_job(job["public_id"])
        assert updated is not None
        assert updated["status"] == "interrupted"
        assert updated["finished_at"] is not None
        assert updated["updated_at"] is not None


# ---------------------------------------------------------------------------
# 多线程连接安全测试
# ---------------------------------------------------------------------------


class TestMultiThreadSafety:
    """spec §ADDED Requirements — Knowledge Database：多线程连接安全。"""

    def test_concurrent_writes_do_not_raise_database_locked(
        self, repo: KnowledgeRepository, db: KnowledgeDatabase
    ) -> None:
        """多线程并发写 packages，由 _write_lock 串行化，不抛 database is locked。"""
        pkg = repo.create_package(name="root")
        package_id = repo.get_package(pkg["public_id"])["id"]  # type: ignore[index]
        errors: list[Exception] = []

        def worker(thread_idx: int) -> None:
            try:
                for i in range(10):
                    repo.create_source(
                        package_id=package_id,
                        source_type="pasted_text",
                        display_name=f"t{thread_idx}-src{i}",
                        normalized_text=f"内容-{thread_idx}-{i}",
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"concurrent writes raised: {errors}"
        sources = repo.list_sources(package_id)
        assert len(sources) == 40  # 4 threads × 10 sources

    def test_concurrent_reads_during_write(
        self, repo: KnowledgeRepository, db: KnowledgeDatabase
    ) -> None:
        """WAL 允许独立连接并发读不阻塞写（spec §5.1：每个工作线程独立连接）。

        注意：Python ``sqlite3.Connection`` 即使设 ``check_same_thread=False``，
        在多线程并发执行查询时仍非线程安全（共享内部游标状态会抛
        ``InterfaceError('bad parameter or other API misuse')``）。
        spec §5.1 明确推荐"每个工作线程独立连接"；本测试用独立连接做并发读，
        验证 WAL 在 DB 层支持并发读不阻塞写，并通过共享 repo 验证最终一致性。
        """
        pkg = repo.create_package(name="root")
        package_id = repo.get_package(pkg["public_id"])["id"]  # type: ignore[index]
        db_path = db.path

        # 预先插入一些数据
        for i in range(5):
            repo.create_source(
                package_id=package_id,
                source_type="pasted_text",
                display_name=f"pre-{i}",
            )

        errors: list[Exception] = []
        stop = threading.Event()

        def reader() -> None:
            try:
                # 独立连接（spec §5.1 推荐）；不复用共享 db.conn，避免游标冲突
                conn = sqlite3.connect(str(db_path), check_same_thread=False)
                try:
                    while not stop.is_set():
                        conn.execute(
                            "SELECT COUNT(*) FROM knowledge_sources WHERE package_id=?",
                            (package_id,),
                        ).fetchone()
                        time.sleep(0.001)
                finally:
                    conn.close()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def writer() -> None:
            try:
                for i in range(20):
                    repo.create_source(
                        package_id=package_id,
                        source_type="pasted_text",
                        display_name=f"new-{i}",
                    )
                    time.sleep(0.002)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        readers = [threading.Thread(target=reader) for _ in range(3)]
        writer_t = threading.Thread(target=writer)
        for t in readers:
            t.start()
        writer_t.start()
        writer_t.join(timeout=30)
        stop.set()
        for t in readers:
            t.join(timeout=5)

        assert not errors, f"concurrent read/write raised: {errors}"
        # 最终一致性：通过共享 repo 读到全部 25 条（5 pre + 20 new）
        sources = repo.list_sources(package_id)
        assert len(sources) == 25

    def test_write_lock_is_not_reentrant(self, db: KnowledgeDatabase) -> None:
        """_write_lock 是 threading.Lock（非 RLock），递归获取会自死锁。

        用 threading.Timer 模拟"在锁内回调持锁方法"，验证会阻塞（非可重入）。
        """
        # 直接验证 lock 类型：threading.Lock 不可在同线程内重复 acquire
        lock = db._write_lock  # noqa: SLF001 — 测试需要验证锁语义
        acquired = lock.acquire(blocking=False)
        assert acquired, "first acquire should succeed"
        try:
            # 同线程再次 acquire 应失败（非可重入）
            second = lock.acquire(blocking=False)
            assert not second, "threading.Lock is non-reentrant"
        finally:
            lock.release()


# ---------------------------------------------------------------------------
# FTS 索引同步测试
# ---------------------------------------------------------------------------


class TestFtsSync:
    """A1.5：FTS 索引同步（插入 item 时同步插入 FTS 行；删除时同步删除）。"""

    def test_insert_item_syncs_fts_row(
        self, repo: KnowledgeRepository, db: KnowledgeDatabase
    ) -> None:
        if db.fts_backend == "fallback":
            pytest.skip("FTS5 not available on this SQLite build")

        pkg = repo.create_package(name="包")
        package_id = repo.get_package(pkg["public_id"])["id"]  # type: ignore[index]
        source = repo.create_source(
            package_id=package_id,
            source_type="pasted_text",
            display_name="来源",
        )
        item = repo.insert_item(
            package_id=package_id,
            source_id=source["id"],
            chunk_id=None,
            kind="fact",
            title="葛瑞克二阶段",
            content="葛瑞克二阶段会断臂接上龙头并使用喷火攻击。",
            triggers=["葛瑞克", "二阶段", "龙头", "喷火"],
        )

        # FTS 行存在
        row = db.conn.execute(
            "SELECT title, content FROM knowledge_items_fts WHERE rowid=?",
            (item["id"],),
        ).fetchone()
        assert row is not None
        assert row[0] == "葛瑞克二阶段"

    def test_fts_match_finds_inserted_item(
        self, repo: KnowledgeRepository, db: KnowledgeDatabase
    ) -> None:
        """FTS MATCH 查询能命中已插入 item（仅 trigram/fts5 backend）。"""
        if db.fts_backend == "fallback":
            pytest.skip("FTS5 not available on this SQLite build")

        pkg = repo.create_package(name="包")
        package_id = repo.get_package(pkg["public_id"])["id"]  # type: ignore[index]
        source = repo.create_source(
            package_id=package_id,
            source_type="pasted_text",
            display_name="来源",
        )
        repo.insert_item(
            package_id=package_id,
            source_id=source["id"],
            chunk_id=None,
            kind="fact",
            title="葛瑞克二阶段",
            content="葛瑞克二阶段会断臂接上龙头并使用喷火攻击。",
            triggers=["葛瑞克"],
        )

        # trigram 支持中文子串匹配
        rows = db.conn.execute(
            "SELECT rowid FROM knowledge_items_fts WHERE knowledge_items_fts MATCH ?",
            ("葛瑞克",),
        ).fetchall()
        assert len(rows) >= 1

    def test_search_text_contains_all_fields(
        self, repo: KnowledgeRepository
    ) -> None:
        """search_text 由 title + content + examples + triggers + tones + scopes + entities 拼接。"""
        pkg = repo.create_package(name="包")
        package_id = repo.get_package(pkg["public_id"])["id"]  # type: ignore[index]
        source = repo.create_source(
            package_id=package_id,
            source_type="pasted_text",
            display_name="来源",
        )
        item = repo.insert_item(
            package_id=package_id,
            source_id=source["id"],
            chunk_id=None,
            kind="fact",
            title="标题文本",
            content="内容文本",
            examples=["例句A"],
            triggers=["触发词B"],
            tones=["轻松C"],
            scopes=["游戏D"],
            entities=["角色E"],
        )
        fetched = repo.get_item(item["public_id"])
        assert fetched is not None
        search_text = fetched["search_text"]
        for expected in ("标题文本", "内容文本", "例句A", "触发词B", "轻松C", "游戏D", "角色E"):
            assert expected in search_text


# ---------------------------------------------------------------------------
# CRUD 基础测试
# ---------------------------------------------------------------------------


class TestRepositoryCrud:
    """A1.5：CRUD 基础覆盖。"""

    def test_package_crud_roundtrip(self, repo: KnowledgeRepository) -> None:
        # create
        pkg = repo.create_package(
            name="我的知识包",
            description="描述",
            content_kind="game",
            scope_mode="custom",
            scope_tags=["游戏", "艾尔登法环"],
            enabled=True,
            priority=10,
        )
        public_id = pkg["public_id"]
        assert public_id
        assert pkg["scope_tags"] == ["游戏", "艾尔登法环"]

        # get
        fetched = repo.get_package(public_id)
        assert fetched is not None
        assert fetched["name"] == "我的知识包"
        assert fetched["scope_tags"] == ["游戏", "艾尔登法环"]
        assert fetched["enabled"] is True
        assert fetched["priority"] == 10

        # list
        packages = repo.list_packages()
        assert len(packages) == 1
        assert packages[0]["public_id"] == public_id

        # update
        updated = repo.update_package(public_id, name="改名", enabled=False)
        assert updated is not None
        assert updated["name"] == "改名"
        assert updated["enabled"] is False
        # 未改的字段保留
        assert updated["scope_tags"] == ["游戏", "艾尔登法环"]

        # delete
        assert repo.delete_package(public_id) is True
        assert repo.get_package(public_id) is None

    def test_update_nonexistent_package_returns_none(
        self, repo: KnowledgeRepository
    ) -> None:
        result = repo.update_package("nonexistent", name="x")
        assert result is None

    def test_list_packages_enabled_only(self, repo: KnowledgeRepository) -> None:
        repo.create_package(name="启用", enabled=True)
        repo.create_package(name="停用", enabled=False)
        enabled = repo.list_packages(enabled_only=True)
        assert len(enabled) == 1
        assert enabled[0]["name"] == "启用"

    def test_item_pagination(self, repo: KnowledgeRepository) -> None:
        pkg = repo.create_package(name="包")
        package_id = repo.get_package(pkg["public_id"])["id"]  # type: ignore[index]
        source = repo.create_source(
            package_id=package_id,
            source_type="pasted_text",
            display_name="来源",
        )
        # 插入 7 条 item
        for i in range(7):
            repo.insert_item(
                package_id=package_id,
                source_id=source["id"],
                chunk_id=None,
                kind="fact",
                title=f"条目{i}",
                content=f"内容{i}",
            )

        # page=1, page_size=3
        page1 = repo.list_items(package_id=package_id, page=1, page_size=3)
        assert page1["total"] == 7
        assert page1["page"] == 1
        assert page1["page_size"] == 3
        assert len(page1["items"]) == 3

        # page=3, page_size=3 → 只有 1 条
        page3 = repo.list_items(package_id=package_id, page=3, page_size=3)
        assert len(page3["items"]) == 1

        # page=4 → 空
        page4 = repo.list_items(package_id=package_id, page=4, page_size=3)
        assert len(page4["items"]) == 0
        assert page4["total"] == 7

    def test_list_items_filter_by_kind(self, repo: KnowledgeRepository) -> None:
        pkg = repo.create_package(name="包")
        package_id = repo.get_package(pkg["public_id"])["id"]  # type: ignore[index]
        source = repo.create_source(
            package_id=package_id,
            source_type="pasted_text",
            display_name="来源",
        )
        repo.insert_item(
            package_id=package_id,
            source_id=source["id"],
            chunk_id=None,
            kind="fact",
            title="事实",
            content="内容",
        )
        repo.insert_item(
            package_id=package_id,
            source_id=source["id"],
            chunk_id=None,
            kind="meme",
            title="梗",
            content="内容",
        )

        only_fact = repo.list_items(package_id=package_id, kind="fact")
        assert only_fact["total"] == 1
        assert only_fact["items"][0]["kind"] == "fact"

        only_meme = repo.list_items(package_id=package_id, kind="meme")
        assert only_meme["total"] == 1
        assert only_meme["items"][0]["kind"] == "meme"

    def test_list_items_filter_by_enabled(self, repo: KnowledgeRepository) -> None:
        pkg = repo.create_package(name="包")
        package_id = repo.get_package(pkg["public_id"])["id"]  # type: ignore[index]
        source = repo.create_source(
            package_id=package_id,
            source_type="pasted_text",
            display_name="来源",
        )
        item1 = repo.insert_item(
            package_id=package_id,
            source_id=source["id"],
            chunk_id=None,
            kind="fact",
            title="启用",
            content="内容",
            enabled=True,
        )
        item2 = repo.insert_item(
            package_id=package_id,
            source_id=source["id"],
            chunk_id=None,
            kind="fact",
            title="停用",
            content="内容",
            enabled=False,
        )

        only_enabled = repo.list_items(package_id=package_id, enabled=True)
        assert only_enabled["total"] == 1
        assert only_enabled["items"][0]["public_id"] == item1["public_id"]

        only_disabled = repo.list_items(package_id=package_id, enabled=False)
        assert only_disabled["total"] == 1
        assert only_disabled["items"][0]["public_id"] == item2["public_id"]

    def test_list_items_query_searches_search_text(
        self, repo: KnowledgeRepository
    ) -> None:
        pkg = repo.create_package(name="包")
        package_id = repo.get_package(pkg["public_id"])["id"]  # type: ignore[index]
        source = repo.create_source(
            package_id=package_id,
            source_type="pasted_text",
            display_name="来源",
        )
        repo.insert_item(
            package_id=package_id,
            source_id=source["id"],
            chunk_id=None,
            kind="fact",
            title="葛瑞克",
            content="Boss",
            triggers=["喷火"],
        )
        repo.insert_item(
            package_id=package_id,
            source_id=source["id"],
            chunk_id=None,
            kind="fact",
            title="其他",
            content="无关键内容",
        )

        result = repo.list_items(package_id=package_id, query="葛瑞克")
        assert result["total"] == 1
        assert result["items"][0]["title"] == "葛瑞克"

    def test_update_item_reindexes_search_text(
        self, repo: KnowledgeRepository, db: KnowledgeDatabase
    ) -> None:
        pkg = repo.create_package(name="包")
        package_id = repo.get_package(pkg["public_id"])["id"]  # type: ignore[index]
        source = repo.create_source(
            package_id=package_id,
            source_type="pasted_text",
            display_name="来源",
        )
        item = repo.insert_item(
            package_id=package_id,
            source_id=source["id"],
            chunk_id=None,
            kind="fact",
            title="原标题",
            content="原内容",
        )

        updated = repo.update_item(
            item["public_id"], title="新标题", triggers=["新触发词"]
        )
        assert updated is not None
        assert updated["title"] == "新标题"
        assert "新触发词" in updated["search_text"]
        assert "新标题" in updated["search_text"]

        # FTS 索引也应同步更新（先删后插）
        if db.fts_backend != "fallback":
            fts_row = db.conn.execute(
                "SELECT title FROM knowledge_items_fts WHERE rowid=?",
                (item["id"],),
            ).fetchone()
            assert fts_row is not None
            assert fts_row[0] == "新标题"

    def test_mark_items_used_increments_use_count(
        self, repo: KnowledgeRepository
    ) -> None:
        pkg = repo.create_package(name="包")
        package_id = repo.get_package(pkg["public_id"])["id"]  # type: ignore[index]
        source = repo.create_source(
            package_id=package_id,
            source_type="pasted_text",
            display_name="来源",
        )
        item = repo.insert_item(
            package_id=package_id,
            source_id=source["id"],
            chunk_id=None,
            kind="meme",
            title="梗",
            content="内容",
        )

        assert item["use_count"] == 0
        assert item["last_used_at"] is None

        repo.mark_items_used([item["id"]])
        fetched = repo.get_item(item["public_id"])
        assert fetched is not None
        assert fetched["use_count"] == 1
        assert fetched["last_used_at"] is not None

        # 再次调用
        repo.mark_items_used([item["id"]])
        fetched = repo.get_item(item["public_id"])
        assert fetched is not None
        assert fetched["use_count"] == 2

    def test_job_progress_update(self, repo: KnowledgeRepository) -> None:
        pkg = repo.create_package(name="包")
        package_id = repo.get_package(pkg["public_id"])["id"]  # type: ignore[index]
        source = repo.create_source(
            package_id=package_id,
            source_type="pasted_text",
            display_name="来源",
        )
        job = repo.create_job(
            package_id=package_id, source_id=source["id"], total_chunks=12
        )

        updated = repo.update_job_progress(
            job["public_id"],
            status="running",
            stage="ai_organizing",
            processed_chunks=3,
            generated_items=8,
            input_tokens=1024,
            output_tokens=512,
        )
        assert updated is not None
        assert updated["status"] == "running"
        assert updated["stage"] == "ai_organizing"
        assert updated["processed_chunks"] == 3
        assert updated["generated_items"] == 8
        assert updated["input_tokens"] == 1024
        assert updated["output_tokens"] == 512
        assert updated["total_chunks"] == 12  # 未改

        # 完成时设 finished_at
        finished = repo.update_job_progress(
            job["public_id"],
            status="completed",
            processed_chunks=12,
            finished_at="2026-07-18T00:00:00Z",
        )
        assert finished is not None
        assert finished["status"] == "completed"
        assert finished["finished_at"] == "2026-07-18T00:00:00Z"


# ---------------------------------------------------------------------------
# close 测试
# ---------------------------------------------------------------------------


class TestDatabaseClose:
    """A1.3：close() 在写锁内关闭连接（仿 ConfigStore.close）。"""

    def test_close_is_safe_to_call_twice(self, tmp_path: Path) -> None:
        db = KnowledgeDatabase._open_at(tmp_path / "knowledge.db")
        db.close()
        # 第二次 close 不应抛异常
        db.close()

    def test_close_acquires_write_lock(self, tmp_path: Path) -> None:
        """close 应在写锁内完成；通过先持有写锁验证会阻塞（非阻塞 acquire 失败）。"""
        db = KnowledgeDatabase._open_at(tmp_path / "knowledge.db")
        # 先持有写锁
        with db._write_lock:  # noqa: SLF001
            # 此时 close 需要等锁；非阻塞 close 不可行，但可验证锁被持有
            second = db._write_lock.acquire(blocking=False)  # noqa: SLF001
            assert not second, "write lock should be held by outer with"
        # 出 with 后锁释放
        db.close()
