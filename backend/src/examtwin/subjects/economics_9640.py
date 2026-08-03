from examtwin.subjects.contracts import SubjectPack, UnitRule
from examtwin.subjects.oxfordaqa import OXFORDAQA

OXFORDAQA_ECONOMICS_9640 = SubjectPack(
    id="oxfordaqa-economics-9640",
    subject_code="9640",
    title="OxfordAQA International AS/A-level Economics (9640)",
    board=OXFORDAQA,
    specification_ref=(
        "data/牛津AQA/经济/00_旧库补充/官方资料/考试大纲/"
        "oxfordaqa-a-level-economics-specification.pdf"
    ),
    unit_rules=(
        UnitRule(
            "U1",
            "Unit 1: Markets, market failure and government",
            "Microeconomics",
            10,
            ("3.1",),
        ),
        UnitRule(
            "U2",
            "Unit 2: The national economy in a global environment",
            "Macroeconomics",
            19,
            ("3.2",),
        ),
        UnitRule(
            "U3",
            "Unit 3: Business behaviour and income distribution",
            "Microeconomics",
            25,
            ("3.3",),
        ),
        UnitRule(
            "U4",
            "Unit 4: Economic development and the global economy",
            "Global economics",
            34,
            ("3.4",),
        ),
    ),
    topic_code_pattern=r"3\.[1-4]\.\d+\.\d+",
    unit_patterns=(
        (r"\beconomics\s*u1a?\b|\bunit\s*1\b", "U1"),
        (r"\beconomics\s*u2a?\b|\bunit\s*2\b", "U2"),
        (r"\beconomics\s*u3a?\b|\bunit\s*3\b", "U3"),
        (r"\beconomics\s*u4a?\b|\bunit\s*4\b", "U4"),
    ),
    paper_unit_map={"1": "U1", "2": "U2", "3": "U3", "4": "U4"},
    minimum_topics=75,
    minimum_objectives=120,
)
