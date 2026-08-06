from pathlib import Path

from examtwin.subjects.contracts import BoardPack, SubjectPack, UnitRule


def get_subject_pack(pack_id: str, root: Path | None = None) -> SubjectPack:
    from examtwin.subjects.packages import DEFAULT_SUBJECT_PACKS_ROOT, get_subject_package

    return get_subject_package(pack_id, root or DEFAULT_SUBJECT_PACKS_ROOT).pack


__all__ = [
    "BoardPack",
    "SubjectPack",
    "UnitRule",
    "get_subject_pack",
]
