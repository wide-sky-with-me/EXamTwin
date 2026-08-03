from examtwin.subjects.contracts import DefaultCurriculumTextNormalizer, SubjectPack, UnitRule
from examtwin.subjects.oxfordaqa import OXFORDAQA


class Mathematics9660TextNormalizer(DefaultCurriculumTextNormalizer):
    """Repair reviewed 9660 table continuations after generic structure extraction."""

    key = "mathematics-9660-v1"

    def objective_title(self, topic_title: str, raw_title: str) -> str:
        title = raw_title.strip().strip(";")
        lowered = title.lower()
        if lowered.startswith("and "):
            title = title[4:].strip()
            lowered = title.lower()
        if topic_title.lower() == "integration":
            prefix = "simple cases of integration:"
            if lowered.startswith(prefix):
                title = f"Integration {title[len(prefix) :].strip()}"
            elif lowered.startswith("by "):
                title = f"Integration {title}"
            elif lowered.startswith("these methods as the reverse processes"):
                title = title.replace("These methods", "Integration methods", 1)
        elif (
            topic_title.lower() == "continuous random variables"
            and lowered.rstrip(".") == "differences from discrete random variables"
        ):
            title = "Differences between continuous and discrete random variables"
        elif (
            "newton's law" in topic_title.lower()
            and lowered.rstrip(".") == "application to situations, with variable acceleration"
        ):
            title = "Applications of Newton's laws to motion with variable acceleration"
        title = title[:1].upper() + title[1:]
        return title.rstrip(".") + "."


OXFORDAQA_MATHEMATICS_9660 = SubjectPack(
    id="oxfordaqa-mathematics-9660",
    subject_code="9660",
    title="OxfordAQA International AS/A-level Mathematics (9660)",
    board=OXFORDAQA,
    specification_ref=(
        "data/牛津AQA/数学/1.AQA-alevel数学-考试大纲/"
        "oxfordaqa-a-level-mathematics-specification.pdf"
    ),
    unit_rules=(
        UnitRule("P1", "International AS Unit P1 (Pure Maths)", "Pure", 10, ("P1",)),
        UnitRule("PSM1", "International AS Unit PSM1", "Mixed", 14, ("PP1", "S1", "M1")),
        UnitRule("P2", "International A-level Unit P2 (Pure Maths)", "Pure", 20, ("P2",)),
        UnitRule("S2", "International A-level Unit S2 (Statistics)", "Statistics", 25, ("S2",)),
        UnitRule("M2", "International A-level Unit M2 (Mechanics)", "Mechanics", 27, ("M2",)),
    ),
    topic_code_pattern=r"(?:P1|PP1|S1|M1|P2|S2|M2)\.\d+",
    unit_patterns=(
        (r"\bupsm1\b|\bpsm1\b", "PSM1"),
        (r"\bup1\b|\bunit\s*p1\b|\bunit\s*1\b", "P1"),
        (r"\bup2\b|\bunit\s*p2\b|\bunit\s*3\b", "P2"),
        (r"\bus2\b|\bunit\s*s2\b|\bunit\s*4\b", "S2"),
        (r"\bum2\b|\bunit\s*m2\b|\bunit\s*5\b", "M2"),
    ),
    paper_unit_map={"1": "P1", "2": "PSM1", "3": "P2", "4": "S2", "5": "M2"},
    minimum_topics=35,
    minimum_objectives=100,
    curriculum_normalizer=Mathematics9660TextNormalizer(),
)
