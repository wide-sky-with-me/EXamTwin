import re

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


VISUAL_TOOL_POLICIES = {
    "mathematics-answer-visual-v1": select_mathematics_answer_visual_tool,
}
