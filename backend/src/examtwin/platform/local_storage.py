from __future__ import annotations

from pathlib import Path
from typing import BinaryIO
from uuid import uuid4


class SafeLocalStorage:
    """Atomic, traversal-safe local storage shared by worker-visible artifacts."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def resolve(self, relative_path: str, *, require_file: bool = False) -> Path:
        root = self.root.resolve()
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root):
            raise ValueError("存储路径越界")
        if require_file and not path.is_file():
            raise LookupError("存储对象不存在")
        return path

    def write_atomic(self, relative_path: str, content: bytes | str) -> Path:
        path = self.resolve(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        if isinstance(content, str):
            temporary.write_text(content, encoding="utf-8")
        else:
            temporary.write_bytes(content)
        temporary.replace(path)
        return path

    def write_stream_atomic(
        self,
        relative_path: str,
        stream: BinaryIO,
        *,
        max_bytes: int,
        chunk_bytes: int = 1024 * 1024,
    ) -> tuple[Path, int]:
        """Copy a binary stream with a hard size ceiling without buffering it in memory."""

        if max_bytes < 1 or chunk_bytes < 1:
            raise ValueError("存储流容量参数必须为正数")
        path = self.resolve(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        total = 0
        try:
            with temporary.open("wb") as output:
                while block := stream.read(chunk_bytes):
                    total += len(block)
                    if total > max_bytes:
                        raise ValueError("上传文件超过容量限制")
                    output.write(block)
            if total == 0:
                raise ValueError("上传文件为空")
            temporary.replace(path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return path, total

    def delete(self, relative_path: str) -> None:
        self.resolve(relative_path).unlink(missing_ok=True)
