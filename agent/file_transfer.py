"""Chunked file upload/download helpers for the WebSocket channel.

Wire format per chunk (PRD §):
    {
        "type": "file_chunk",
        "filename": "report.pdf",
        "chunk_index": 0,
        "total_chunks": 4,
        "data_b64": "<base64>"
    }
"""
import base64
from pathlib import Path
from typing import Iterator, Optional, Tuple

DEFAULT_CHUNK_SIZE = 64 * 1024  # 64 KiB


def chunk_file(path: Path, chunk_size: int = DEFAULT_CHUNK_SIZE) -> Iterator[Tuple[int, int, str]]:
    """Yield ``(chunk_index, total_chunks, b64_data)`` tuples for ``path``."""
    data = Path(path).read_bytes()
    if not data:
        yield 0, 1, ""
        return
    total = (len(data) + chunk_size - 1) // chunk_size
    for i in range(total):
        chunk = data[i * chunk_size : (i + 1) * chunk_size]
        yield i, total, base64.b64encode(chunk).decode("ascii")


class FileAssembler:
    """Reassemble out-of-order base64 chunks into complete file bytes."""

    def __init__(self) -> None:
        self._buffers: dict[str, dict[int, bytes]] = {}
        self._totals: dict[str, int] = {}

    def add_chunk(
        self, filename: str, index: int, total: int, b64: str
    ) -> Optional[bytes]:
        self._totals[filename] = total
        self._buffers.setdefault(filename, {})[index] = base64.b64decode(b64) if b64 else b""

        if len(self._buffers[filename]) == total:
            ordered = b"".join(self._buffers[filename][i] for i in range(total))
            self._buffers.pop(filename, None)
            self._totals.pop(filename, None)
            return ordered
        return None

    def cancel(self, filename: str) -> None:
        self._buffers.pop(filename, None)
        self._totals.pop(filename, None)
