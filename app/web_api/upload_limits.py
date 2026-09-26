"""Shared bounded readers for multipart upload routes."""

from __future__ import annotations

from typing import Protocol

UPLOAD_READ_CHUNK_SIZE = 64 * 1024


class _AsyncUploadReader(Protocol):
    async def read(self, size: int = -1) -> bytes: ...


class UploadSizeLimitExceeded(Exception):
    """Raised before an oversized upload reaches a storage or parser service."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def reject_upload_if_too_large(
    upload: object,
    *,
    content_length: int | None,
    limit: int,
    detail: str,
) -> None:
    """Reject a known file size, falling back to Content-Length as a hint.

    ``Content-Length`` describes the whole multipart request, not just the file
    part.  Prefer Starlette's parsed ``UploadFile.size`` when available so a
    valid file at the exact limit is not rejected because of multipart framing.
    The bounded reader remains authoritative when neither value is reliable.
    """

    file_size = getattr(upload, "size", None)
    if isinstance(file_size, int):
        if file_size > limit:
            raise UploadSizeLimitExceeded(detail)
        return
    if content_length is not None and content_length > limit:
        raise UploadSizeLimitExceeded(detail)


async def read_upload_with_limit(
    upload: _AsyncUploadReader,
    *,
    limit: int,
    detail: str,
    chunk_size: int = UPLOAD_READ_CHUNK_SIZE,
) -> bytes:
    """Read and reassemble an upload, stopping at the first byte over limit."""

    if limit < 0 or chunk_size <= 0:
        raise ValueError("上传读取限制必须为非负数，分块大小必须为正数")

    chunks: list[bytes] = []
    total = 0
    while total <= limit:
        # Read at most one byte over the limit.  This bounds both the final
        # read and the amount retained before rejecting the upload.
        read_size = min(chunk_size, limit - total + 1)
        chunk = await upload.read(read_size)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > limit:
            raise UploadSizeLimitExceeded(detail)
    return b"".join(chunks)
