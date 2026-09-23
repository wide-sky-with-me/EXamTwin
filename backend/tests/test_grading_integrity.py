import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from examtwin.assessment.grading import GradingService
from examtwin.contracts.evidence import AnswerDiagram, AnswerImage
from examtwin.contracts.grading import GradeRequest

CRITERIA = [
    {"criterion_id": "A", "description": "Method", "max_marks": 1},
    {"criterion_id": "B", "description": "Conclusion", "max_marks": 1},
]


def award(label="A", marks=1, evidence="x=2"):
    return dict(
        criterion_id=label,
        description="untrusted model description",
        max_marks=marks,
        awarded=marks,
        student_evidence=evidence,
        rationale="Model judgment",
        confidence=1,
    )


class Model:
    model_name = "offline-grading-integrity"

    def __init__(self, awards):
        self.awards = awards
        self.calls = []

    def complete(self, messages, response_model, **kwargs):
        self.calls.append(messages)
        return response_model(total_available=999, rubric_awards=self.awards)


class Store:
    def __init__(self):
        self.created = []

    def create(self, values):
        self.created.append(values)


def service(model):
    store = Store()
    settings = SimpleNamespace(
        grading_question_max_chars=10000,
        grading_mark_scheme_max_chars=10000,
        grading_answer_max_chars=10000,
        grading_timeout=10,
    )
    return GradingService(
        cast(Any, SimpleNamespace()),
        cast(Any, store),
        cast(Any, settings),
        cast(Any, SimpleNamespace(subject_code="9660")),
        structured_model=model,
    ), store


def request(answer="x=2"):
    return GradeRequest(
        answer_markdown=answer,
        question_markdown="(a) solve (b) explain",
        mark_scheme_markdown=json.dumps(CRITERIA),
        max_marks=2,
    )


@pytest.mark.parametrize("ids", [("A", "A"), ("A",), ("A", "UNKNOWN")])
def test_confirmed_criteria_reject_duplicate_missing_and_unknown_atoms(ids):
    grader, store = service(Model([award(i) for i in ids]))
    with pytest.raises(ValueError, match="评分原子逐项对应"):
        grader.grade(request(), confirmed_criteria=CRITERIA)
    assert not store.created


def test_confirmed_criteria_own_the_maximum_and_description():
    grader, _ = service(Model([award("A", 20), award("B", 0, None)]))
    result = grader.grade(request(), confirmed_criteria=CRITERIA)
    assert result.total_awarded == 1
    assert result.total_available == 2
    assert [a.max_marks for a in result.rubric_awards] == [1, 1]
    assert [a.description for a in result.rubric_awards] == ["Method", "Conclusion"]


@pytest.mark.parametrize("evidence", [None, "", "   "])
def test_positive_awards_without_evidence_are_retried_then_withheld(evidence):
    model = Model([award("A", 1, evidence), award("B", 0, None)])
    grader, _ = service(model)
    result = grader.grade(request(), confirmed_criteria=CRITERIA)
    assert len(model.calls) == 2
    assert result.total_awarded == 0
    assert any("暂缓授分" in warning for warning in result.warnings)


def diagram(x):
    return AnswerDiagram.model_validate(
        {
            "title": "Same caption",
            "elements": [{"kind": "line", "x1": 0, "y1": 0, "x2": x, "y2": 10}],
        }
    )


def test_actual_vectors_change_grading_evidence_and_are_persisted():
    prompts = []
    for x in (10, 30):
        model = Model([award("A", 1, f'"x2": {x}.0'), award("B", 0, None)])
        grader, store = service(model)
        result = grader.grade(
            request("See diagram."), confirmed_criteria=CRITERIA, answer_diagrams=[diagram(x)]
        )
        assert result.total_awarded == 1
        prompts.append(model.calls[0][1].content)
        assert f'"x2": {x}.0' in store.created[0]["answer_markdown"]
    assert prompts[0] != prompts[1]


def test_uninspectable_image_is_explicitly_deferred_without_model_guessing():
    model = Model([award("A"), award("B")])
    grader, store = service(model)
    image = AnswerImage(
        title="Looks correct", content_url="/api/v1/answer-assets/" + "a" * 32 + ".png"
    )
    result = grader.grade(request(), confirmed_criteria=CRITERIA, answer_images=[image])
    assert model.calls == []
    assert result.status == "pending_review"
    assert result.total_awarded == 0
    assert result.confidence == 0
    assert any("零分只是待复核占位" in w for w in result.warnings)
    assert image.content_url in store.created[0]["answer_markdown"]
