from __future__ import annotations

from typing import Protocol

from examtwin.assessment.answering_agent.tools.paired_exam import PairedExamReader
from examtwin.knowledge.public import SourceDocumentReader


class AnswerEvidenceReader(SourceDocumentReader, PairedExamReader, Protocol):
    """Documents exposed to answer tools through reviewed read-only methods."""
