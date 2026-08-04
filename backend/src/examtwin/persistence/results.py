from __future__ import annotations

from typing import Protocol, cast


class _RowCountResult(Protocol):
    rowcount: int


def affected_rows(result: object) -> int:
    """Expose DBAPI rowcount behind one checked SQLAlchemy typing boundary."""

    return cast(_RowCountResult, result).rowcount
