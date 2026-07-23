"""知识包导入编排（A6.1）：extract → chunk → AI organize → validate → dedupe → save。

设计要点（spec §ADDED Requirements / AI Organizer + Validation）：

- **独立后台执行器**：``ThreadPoolExecutor(max_workers=1, thread_name_prefix="knowledge-import")``，
  不占用视觉 AI 的 ``MAX_IN_FLIGHT=1``，不阻塞 Qt 主线程或 FastAPI 事件循环。
- **协作式取消**：``cancel_job`` 设置 ``threading.Event``，执行器在下个 chunk 边界检查并停止。
- **错误隔离**：单 chunk 失败不终止整个 job；记录 ``failed_chunks``，继续后续 chunk。
- **完成状态**：``completed`` / ``completed_with_errors`` / ``failed`` / ``cancelled``。
- **token 累加**：每次 chunk 处理后立即更新 job 行，让前端轮询能看到进度。
- **不触 Qt 信号**：纯后台线程，不修改 Qt 对象。

不修改 ``ai_organizer`` / ``source_extractors`` / ``chunker`` / ``validator`` / ``deduplicator`` /
``database`` / ``migrations`` / ``repository`` / ``models``。
"""
from __future__ import annotations

import hashlib
import logging
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.knowledge.ai_organizer import organize_chunk
from app.knowledge.chunker import chunk_source
from app.knowledge.deduplicator import KnowledgeDeduplicator
from app.knowledge.source_extractors import MAX_SOURCE_CHARS, extract as extract_source
from app.knowledge.validator import validate_batch

if TYPE_CHECKING:
    from app.knowledge.database import KnowledgeDatabase
    from app.knowledge.repository import KnowledgeRepository

logger = logging.getLogger(__name__)

__all__ = ["ImportOrchestrator"]


def _now_iso() -> str:
    """当前 UTC ISO8601 时间戳（秒精度，与 repository 风格一致）。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _generate_job_public_id() -> str:
    """生成 job public_id：``"kj_" + uuid4().hex``。"""
    return "kj_" + uuid.uuid4().hex


def _content_hash(text: str) -> str:
    """SHA-256 十六进制（与 repository._content_hash 一致）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ImportOrchestrator:
    """知识包导入编排：extract → chunk → AI organize → validate → dedupe → save → update job progress。

    在独立 ``ThreadPoolExecutor(max_workers=1, thread_name_prefix="knowledge-import")`` 中运行。
    不占用 ``ai_in_flight`` / ``MAX_IN_FLIGHT=1``，不触 Qt 信号。

    线程模型：
        - 主线程持有 ``ImportOrchestrator`` 实例；
        - 导入任务在 ``knowledge-import`` 线程内串行执行（``max_workers=1``）；
        - ``cancel_job`` 从任意线程调用，设置 ``threading.Event``；
        - 执行器在下个 chunk 边界检查 ``Event`` 并停止。
    """

    def __init__(self, db: "KnowledgeDatabase", repository: "KnowledgeRepository") -> None:
        self._db = db
        self._repository = repository
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="knowledge-import",
        )
        # job_public_id -> threading.Event；协作式取消标志。
        self._cancel_flags: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def submit_import(
        self,
        *,
        config: Any,
        package_id: int,
        source_id: int,
        source_type: str,
        payload: dict,
        document_kind: str = "auto",
        content_kind: str = "auto",
    ) -> str:
        """创建 job 行 + 提交到执行器 + 立即返回 ``job_public_id``。

        流程：
            1. 在 ``_db`` 创建 ``knowledge_jobs`` 行（status='pending', stage='queued'）。
            2. 创建 ``cancel_flag = threading.Event()`` 并记入 ``_cancel_flags``。
            3. 提交 ``_run_import`` 到执行器。
            4. 注册 ``_on_job_done`` 回调记录异常日志。
            5. 立即返回 ``job_public_id``。
        """
        job_public_id = _generate_job_public_id()
        # 1. 创建 job 行
        self._create_job_row(package_id, source_id, job_public_id)
        # 2. 注册取消标志
        cancel_flag = threading.Event()
        with self._lock:
            self._cancel_flags[job_public_id] = cancel_flag
        # 3. 提交到执行器
        future = self._executor.submit(
            self._run_import,
            config,
            job_public_id,
            package_id,
            source_id,
            source_type,
            payload,
            document_kind,
            content_kind,
        )
        # 4. 异常日志回调
        future.add_done_callback(self._on_job_done)
        return job_public_id

    def cancel_job(self, job_public_id: str) -> bool:
        """协作式取消：设置 ``cancel_flag``，执行器在下个 chunk 边界检查并停止。

        Returns:
            True 若 job 存在并已设置取消标志；False 若 job 不存在或已完成。
        """
        with self._lock:
            flag = self._cancel_flags.get(job_public_id)
            if flag is None:
                return False
            flag.set()
            return True

    def close(self) -> None:
        """关闭执行器，等待未完成任务完成。"""
        self._executor.shutdown(wait=True, cancel_futures=False)

    # ------------------------------------------------------------------
    # 内部：job 行创建
    # ------------------------------------------------------------------

    def _create_job_row(
        self, package_id: int, source_id: int, job_public_id: str
    ) -> None:
        """直接插入 ``knowledge_jobs`` 行（使用自定义 public_id 格式 ``kj_<uuid>``）。"""
        now = _now_iso()
        with self._db.with_write_lock():
            self._db.conn.execute(
                "INSERT INTO knowledge_jobs "
                "(public_id, package_id, source_id, status, stage, total_chunks, "
                "processed_chunks, failed_chunks, generated_items, deduplicated_items, "
                "input_tokens, output_tokens, error_message, created_at, updated_at) "
                "VALUES (?, ?, ?, 'pending', 'queued', 0, 0, 0, 0, 0, 0, 0, '', ?, ?)",
                (job_public_id, package_id, source_id, now, now),
            )
            self._db.conn.commit()

    # ------------------------------------------------------------------
    # 内部：source 更新（按内部 id）
    # ------------------------------------------------------------------

    def _update_source(
        self,
        source_id: int,
        *,
        normalized_text: str | None = None,
        status: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """按内部 id 更新 source 行（repository 的 update_source_status 接收 public_id，
        这里 import_service 持有内部 id，直接写 SQL）。"""
        sets: list[str] = []
        params: list[Any] = []
        if normalized_text is not None:
            sets.append("normalized_text=?")
            params.append(normalized_text)
            sets.append("content_hash=?")
            params.append(_content_hash(normalized_text))
        if status is not None:
            sets.append("status=?")
            params.append(status)
        if error_message is not None:
            sets.append("error_message=?")
            params.append(error_message)
        if not sets:
            return
        sets.append("updated_at=?")
        params.append(_now_iso())
        params.append(source_id)
        with self._db.with_write_lock():
            self._db.conn.execute(
                f"UPDATE knowledge_sources SET {', '.join(sets)} WHERE id=?",
                params,
            )
            self._db.conn.commit()

    # ------------------------------------------------------------------
    # 内部：执行器主流程
    # ------------------------------------------------------------------

    def _run_import(
        self,
        config: Any,
        job_public_id: str,
        package_id: int,
        source_id: int,
        source_type: str,
        payload: dict,
        document_kind: str,
        content_kind: str,
    ) -> None:
        """执行器内运行的主流程（在 ``knowledge-import`` 线程内）。

        流程：extract → check size → update source → chunk → insert chunks →
        逐 chunk AI organize → validate → dedupe → save items → update job progress。
        """
        try:
            # 1. 更新 job.status='running', stage='extracting'
            self._repository.update_job_progress(
                job_public_id, status="running", stage="extracting"
            )

            # 2. 提取
            extraction_result = extract_source(source_type, payload or {})
            if extraction_result.error:
                self._fail_job(
                    job_public_id,
                    extraction_result.error,
                    source_id=source_id,
                    source_status="failed",
                    source_error=extraction_result.error,
                )
                return

            normalized_text = extraction_result.normalized_text
            if not normalized_text:
                # 防御性：提取成功但文本为空
                self._fail_job(
                    job_public_id,
                    "empty_content",
                    source_id=source_id,
                    source_status="failed",
                    source_error="empty_content",
                )
                return

            # 3. 检查大小上限（5 MiB）
            if len(normalized_text) > MAX_SOURCE_CHARS:
                self._fail_job(
                    job_public_id,
                    "source_too_large",
                    source_id=source_id,
                    source_status="failed",
                    source_error="source_too_large",
                )
                return

            # 4. 更新 source.normalized_text + status='extracted'
            self._update_source(
                source_id, normalized_text=normalized_text, status="extracted"
            )

            # 5. 分块（传 document_kind，使 livestream_log 在 content_kind=auto 时仍走直播分块）
            self._repository.update_job_progress(job_public_id, stage="chunking")
            chunks = chunk_source(
                source_type,
                normalized_text,
                content_kind=content_kind,
                document_kind=document_kind,
            )

            # 5.1 无 chunk：立即失败（不进入 AI 整理）
            if not chunks:
                self._fail_job(
                    job_public_id,
                    "no_chunks_generated",
                    source_id=source_id,
                    source_status="failed",
                    source_error="no_chunks_generated",
                )
                return

            # 6. 插入 chunks 行
            chunk_dicts: list[dict[str, Any]] = [
                {
                    "sequence_no": c.sequence_no,
                    "heading": c.heading,
                    "content": c.content,
                }
                for c in chunks
            ]
            inserted_chunks = self._repository.insert_chunks(
                source_id=source_id, chunks=chunk_dicts
            )

            # 7. 更新 job.total_chunks + stage='organizing'；source=processing
            self._update_source(source_id, status="processing")
            self._repository.update_job_progress(
                job_public_id,
                stage="organizing",
                total_chunks=len(inserted_chunks),
                processed_chunks=0,
            )

            # 9-11. 逐 chunk 处理（预载包内已有条目，跨导入去重）
            deduplicator = KnowledgeDeduplicator(package_id=package_id, threshold=0.85)
            try:
                existing_rows = self._repository.list_item_dedupe_keys(package_id)
                deduplicator.seed_existing(existing_rows)
            except Exception as exc:
                logger.warning(
                    "knowledge import seed_existing failed (non-fatal): %r",
                    exc,
                )
            total_input_tokens = 0
            total_output_tokens = 0
            total_kept = 0
            total_dedup = 0
            total_failed = 0
            all_errors: list[dict[str, Any]] = []
            processed = 0
            cancelled = False

            for chunk in inserted_chunks:
                # 11.1 协作式取消检查
                with self._lock:
                    flag = self._cancel_flags.get(job_public_id)
                if flag is not None and flag.is_set():
                    cancelled = True
                    break

                # 11.2 更新 chunk.status='processing'
                self._repository.update_chunk_status(
                    chunk["id"], status="processing"
                )

                # 11.3 AI 整理
                try:
                    result = organize_chunk(
                        config,
                        chunk["content"],
                        document_kind,
                        package_id,
                        source_id,
                        chunk["id"],
                    )
                except Exception as exc:
                    # organize_chunk 内部已有 try/except，这里是双保险
                    result = {
                        "ok": False,
                        "items": [],
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "error": f"organize_exception: {exc!r}",
                    }

                if not result.get("ok", False):
                    # 11.4 chunk 失败
                    total_failed += 1
                    error_msg = result.get("error", "unknown")
                    all_errors.append(
                        {"chunk_id": chunk["id"], "error": error_msg}
                    )
                    self._repository.update_chunk_status(
                        chunk["id"], status="failed", error_message=error_msg
                    )
                    total_input_tokens += int(result.get("input_tokens", 0))
                    total_output_tokens += int(result.get("output_tokens", 0))
                    processed += 1
                    self._repository.update_job_progress(
                        job_public_id,
                        processed_chunks=processed,
                        failed_chunks=total_failed,
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                    )
                    continue

                # 11.5 校验
                items_raw = result.get("items") or []
                parsed = {
                    "document_kind": document_kind,
                    "items": items_raw,
                }
                valid_items, validation_errors = validate_batch(parsed, chunk["content"])

                # 11.5.1 校验错误写入 chunk 和 all_errors
                if validation_errors:
                    val_msg = "; ".join(validation_errors[:5])
                    if len(validation_errors) > 5:
                        val_msg += f"; ... and {len(validation_errors) - 5} more"
                    self._repository.update_chunk_status(
                        chunk["id"], status="completed", error_message=val_msg
                    )
                    all_errors.append(
                        {"chunk_id": chunk["id"], "error": f"validation: {val_msg}"}
                    )

                # 11.6 去重
                kept_items, dedup_count = deduplicator.dedupe(valid_items)

                # 11.7 保存 items
                for item in kept_items:
                    self._repository.insert_item(
                        package_id=package_id,
                        source_id=source_id,
                        chunk_id=chunk["id"],
                        kind=item.get("kind", "fact"),
                        title=item.get("title", ""),
                        content=item.get("content", ""),
                        examples=item.get("examples", []),
                        triggers=item.get("triggers", []),
                        tones=item.get("tones", []),
                        scopes=item.get("scopes", []),
                        entities=item.get("entities", []),
                        confidence=item.get("confidence", 1.0),
                        evidence=item.get("evidence", ""),
                    )

                # 11.8 更新 chunk.status='completed'（若校验有错误已在 11.5.1 更新）
                if not validation_errors:
                    self._repository.update_chunk_status(
                        chunk["id"], status="completed"
                    )

                # 11.9 累加统计
                total_input_tokens += int(result.get("input_tokens", 0))
                total_output_tokens += int(result.get("output_tokens", 0))
                total_kept += len(kept_items)
                total_dedup += dedup_count
                processed += 1

                # 11.10 更新 job 进度（每次 chunk 后更新，让前端看到进度）
                self._repository.update_job_progress(
                    job_public_id,
                    processed_chunks=processed,
                    failed_chunks=total_failed,
                    generated_items=total_kept,
                    deduplicated_items=total_dedup,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                )

            # 12. 确定最终 job/source status
            # source 映射：
            #   cancelled → cancelled
            #   completed → processed
            #   completed_with_errors → processed_with_errors
            #   failed / zero items → failed (+ no_items_generated)
            if cancelled:
                final_status = "cancelled"
                final_stage = "cancelled"
                source_final_status = "cancelled"
            elif total_failed == 0 and total_kept > 0:
                final_status = "completed"
                final_stage = "finished"
                source_final_status = "processed"
            elif total_failed > 0 and total_kept > 0:
                final_status = "completed_with_errors"
                final_stage = "finished"
                source_final_status = "processed_with_errors"
            elif total_failed > 0 and total_kept == 0:
                final_status = "failed"
                final_stage = "finished"
                source_final_status = "failed"
            else:
                # total_failed == 0 and total_kept == 0：AI 未生成任何条目
                final_status = "failed"
                final_stage = "finished"
                source_final_status = "failed"

            # 13. 更新 job 最终状态
            error_message = self._format_errors(all_errors)
            if not error_message and total_kept == 0 and not cancelled:
                error_message = "no_items_generated"
            self._repository.update_job_progress(
                job_public_id,
                status=final_status,
                stage=final_stage,
                generated_items=total_kept,
                deduplicated_items=total_dedup,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                error_message=error_message,
                finished_at=_now_iso(),
            )

            # 14. 按终态同步 source（禁止无条件 processed）
            if source_final_status == "failed":
                source_error = error_message or "no_items_generated"
            elif source_final_status == "processed_with_errors":
                source_error = error_message or ""
            elif source_final_status == "cancelled":
                source_error = error_message or "cancelled"
            else:
                # processed：清空错误
                source_error = ""
            self._update_source(
                source_id,
                status=source_final_status,
                error_message=source_error,
            )

        except Exception as exc:
            # 15. 异常处理：更新 job + source 均为 failed
            logger.exception(
                "knowledge import job %s failed unexpectedly", job_public_id
            )
            err_text = str(exc)[:500]
            try:
                self._repository.update_job_progress(
                    job_public_id,
                    status="failed",
                    stage="failed",
                    error_message=err_text,
                    finished_at=_now_iso(),
                )
            except Exception:
                logger.exception(
                    "knowledge import job %s: failed to update job status after exception",
                    job_public_id,
                )
            try:
                self._update_source(
                    source_id,
                    status="failed",
                    error_message=err_text,
                )
            except Exception:
                logger.exception(
                    "knowledge import job %s: failed to update source status after exception",
                    job_public_id,
                )
        finally:
            # 16. 从 _cancel_flags 移除 job_public_id（在锁内）
            with self._lock:
                self._cancel_flags.pop(job_public_id, None)

    # ------------------------------------------------------------------
    # 内部：辅助
    # ------------------------------------------------------------------

    def _fail_job(
        self,
        job_public_id: str,
        error_message: str,
        *,
        source_id: int | None = None,
        source_status: str | None = None,
        source_error: str | None = None,
    ) -> None:
        """统一处理 job 失败：更新 job + 可选更新 source。"""
        self._repository.update_job_progress(
            job_public_id,
            status="failed",
            stage="failed",
            error_message=error_message,
            finished_at=_now_iso(),
        )
        if source_id is not None:
            self._update_source(
                source_id,
                status=source_status or "failed",
                error_message=source_error,
            )

    @staticmethod
    def _format_errors(errors: list[dict[str, Any]]) -> str:
        """格式化错误列表为字符串（前 5 条，超出省略）。"""
        if not errors:
            return ""
        parts = [
            f"chunk {e.get('chunk_id', '?')}: {e.get('error', 'unknown')}"
            for e in errors[:5]
        ]
        msg = "; ".join(parts)
        if len(errors) > 5:
            msg += f"; ... and {len(errors) - 5} more"
        return msg

    def _on_job_done(self, future: Future) -> None:
        """future 完成回调，记录异常日志。

        ``_run_import`` 内部已有 ``try/except``，正常情况下不会传播异常。
        此回调是双保险：若 ``_run_import`` 之外有异常逃逸，记录日志。
        """
        try:
            future.result()
        except Exception:
            logger.exception(
                "knowledge import job raised unexpected exception in future"
            )
