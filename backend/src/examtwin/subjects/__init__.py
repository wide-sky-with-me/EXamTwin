from examtwin.subjects.contracts import BoardPack, SubjectPack, UnitRule
from examtwin.subjects.economics_9640 import OXFORDAQA_ECONOMICS_9640
from examtwin.subjects.mathematics_9660 import OXFORDAQA_MATHEMATICS_9660

SUBJECT_PACKS = {
    pack.id: pack
    for pack in (
        OXFORDAQA_MATHEMATICS_9660,
        OXFORDAQA_ECONOMICS_9640,
    )
}


def get_subject_pack(pack_id: str) -> SubjectPack:
    try:
        return SUBJECT_PACKS[pack_id]
    except KeyError as error:
        available = ", ".join(sorted(SUBJECT_PACKS))
        raise ValueError(f"Unknown subject pack {pack_id!r}; available: {available}") from error


__all__ = [
    "BoardPack",
    "OXFORDAQA_ECONOMICS_9640",
    "OXFORDAQA_MATHEMATICS_9660",
    "SUBJECT_PACKS",
    "SubjectPack",
    "UnitRule",
    "get_subject_pack",
]
