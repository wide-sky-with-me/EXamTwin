from examtwin.subjects.contracts import BoardPack

OXFORDAQA = BoardPack(
    id="oxfordaqa-international",
    name="OxfordAQA International Qualifications",
    official_source_types=frozenset(
        {"syllabus", "question_paper", "mark_scheme", "examiner_report", "insert"}
    ),
    filename_subject_code_pattern=r"\baqa[-_ ]?(?P<subject_code>\d{4,5})(?!\d)",
)
