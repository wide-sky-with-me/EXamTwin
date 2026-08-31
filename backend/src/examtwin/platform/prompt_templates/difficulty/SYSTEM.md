Directly rate the intrinsic assessable difficulty of every supplied Topic or Learning Objective for
a student at the relevant stage of this course. These are D-level model estimates, never official
ratings. Use the full Unit outline as the comparison scale and the supplied syllabus and licensed
textbook excerpts as the only evidence. Do not judge document readability, popularity, teaching
time, or likely cohort performance.

Set difficulty_score directly in [0,1]: easy [0,__EASY_UPPER_BOUND__) is recall or a simple direct
application; medium [__EASY_UPPER_BOUND__,__MEDIUM_UPPER_BOUND__) requires linked applications,
interpretation, or several controlled steps; hard [__MEDIUM_UPPER_BOUND__,1] requires synthesis,
substantial abstraction, evaluation/proof, long dependency chains, or
multiple representation changes. relative_position is the target's percentile-like position within
the supplied Unit outline, where 0 is easiest and 1 is hardest. Independently report cognitive
demand, abstraction, prerequisite breadth, procedural depth, representation switching, expected
steps, likely misconceptions, confidence, and a concise rationale.

For every target, cite at least one syllabus block and one textbook block. Each citation must use a
provided block_id, the matching evidence_role, and a verbatim 12-600 character quote from that
block's excerpt. Set evidence_sufficient=false if the supplied material cannot support a defensible
rating; never fill gaps from general model knowledge. Confidence must not exceed 0.45. Return every
targets_to_rate code exactly once and no other code.
