import re

from examtwin.answering_agent.contracts import SubjectSkill

_ANSWER_VISUAL_REQUEST = re.compile(
    r"""
    (?:^|[.!?;:]\s+|\n[ \t]*)
    (?:\|[ \t]*)?
    (?:\#{1,6}[ \t]*)?
    (?:[*_]{1,2})?
    (?:\d+(?:[.)])?[ \t]*)?
    (?:\([a-zivx]+\)[ \t]*){0,2}
    (?:[*_]{1,2})?
    (?:\|[ \t]*)?
    (?:
        (?:on|in)\s+(?:the\s+)?(?:axes|figure|diagram|grid)\b
            [^.!?\n]{0,160}\b(?:sketch|draw|shade|mark|label)\b
            [^.!?\n]{0,160}
      | (?:sketch|draw|shade|plot)\b[^.!?\n]{0,220}\b
            (?:graph|curve|diagram|figure|axis|axes|grid|plots?|points?|
               trapez(?:ium|ia|oid)s?|region|area|forces?|vectors?|
               construction|locus|lines?)\b
      | complete\b[ \t]+
            (?:(?:the|this|that|your|their|following|given)[ \t]+)?
            (?:(?!table\b)[a-z][\w-]*[ \t]+){0,4}
            (?:diagram|graph|figure)\b
      | copy\b[^.!?\n]{0,160}\bsketch\b
      | construct\b[^.!?\n]{0,160}\b
            (?:triangle|bisector|circle|locus|diagram|figure|perpendicular)\b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
_COORDINATE_VISUAL = re.compile(
    r"\b(?:axis|axes|graph|curve|plots?|points?|coordinates?|ordinates?|cobweb|staircase|"
    r"trapez(?:ium|ia|oid)s?|histogram|scatter|box\s+plot|"
    r"cumulative\s+(?:frequency|distribution)|"
    r"(?:velocity|acceleration|displacement)[-\s]time)\b",
    re.IGNORECASE,
)
_REQUEST_CONTEXT_END = re.compile(r"(?:[.!?](?=\s|$)|\n[ \t]*\n)")
_SOURCE_FIGURE_DRAWING = re.compile(
    r"\b(?:sketch|draw|shade|plot|mark|label)\b[^.!?\n]{0,240}"
    r"\b(?:on|in)\s+(?:the\s+)?(?:axes|figure|diagram|grid)\b"
    r"|\b(?:on|in)\s+(?:the\s+)?(?:axes|figure|diagram|grid)\b"
    r"[^.!?\n]{0,240}\b(?:sketch|draw|shade|plot|mark|label)\b",
    re.IGNORECASE,
)
_TRAPEZIA_DRAWING = re.compile(
    r"\b(?:draw|show|mark)\b[^.!?\n]{0,220}\btrapez(?:ium|ia|oid)s?\b",
    re.IGNORECASE,
)


def _request_context(question: str, request: re.Match[str]) -> str:
    """Include the rest of the instruction sentence when classifying its canvas."""

    tail = question[request.end() : request.end() + 320]
    boundary = _REQUEST_CONTEXT_END.search(tail)
    if boundary is not None:
        tail = tail[: boundary.start()]
    return question[request.start() : request.end()] + tail


def select_mathematics_answer_visual_tool(question: str) -> str | None:
    """Choose the exact vector tool only for an explicit answer-drawing instruction."""

    requests = tuple(_ANSWER_VISUAL_REQUEST.finditer(question))
    if not requests:
        return None
    if any(_COORDINATE_VISUAL.search(_request_context(question, request)) for request in requests):
        return "math_plot"
    return "math_diagram"


def mathematics_source_plot_overlay_mode(question: str) -> str | None:
    """Return the deterministic paper-overlay mode required by the wording."""

    if not _SOURCE_FIGURE_DRAWING.search(question):
        return None
    if _TRAPEZIA_DRAWING.search(question):
        return "existing_curve_grid"
    if _COORDINATE_VISUAL.search(question):
        return "blank_axes"
    return None


MATHEMATICS_9660 = SubjectSkill(
    name="oxfordaqa-mathematics-9660",
    subject_codes=("9660",),
    instructions=(
        "You are an OxfordAQA International AS/A-level Mathematics (9660) tutor. "
        "Show enough mathematical working for the requested result and preserve "
        "standard mathematical notation in Markdown. Respect exact values, units, "
        "domains, endpoint conventions and the requested degree of accuracy. "
        "Treat drawing as a separate answer artifact: use math_plot for function "
        "graphs, coordinate plots, cobweb or staircase diagrams, and statistical "
        "line plots; use math_diagram for geometry, vectors, constructions, loci, "
        "number lines, and other figures without mathematical coordinate axes. "
        "Use image_generate only for a genuinely pictorial educational illustration "
        "that neither exact vector tool can represent; never use it for coordinate "
        "graphs, statistical plots, exact geometry, constructions, tables, or text "
        "that must be mathematically precise. "
        "Before drawing, derive and check the decisive coordinates, intercepts, "
        "turning points, asymptotes, labels, boundaries, and shaded-region vertices. "
        "When the question says to draw on supplied axes, a figure, diagram, or grid, "
        "math_plot calibrates a vector overlay to the trusted original-paper pixels; "
        "do not recreate that background or use image generation. "
        "Create the complete figure in one tool call and do not imitate a drawing "
        "with Markdown, ASCII art, raw SVG, HTML, JavaScript, or base64."
    ),
    tool_names=(
        "question_vision",
        "knowledge_search",
        "source_read",
        "paired_exam_lookup",
        "math_calculate",
        "probability_calculate",
        "math_plot",
        "math_diagram",
        "image_generate",
    ),
    required_tool_names=("knowledge_search",),
    mandatory_tool_names=("knowledge_search",),
    visual_tool_selector=select_mathematics_answer_visual_tool,
)

SUBJECT_SKILLS = (MATHEMATICS_9660,)
