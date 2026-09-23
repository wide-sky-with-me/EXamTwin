"""Opt-in real-paper experiment through production answering runtime and tools.

Uses local syllabus page retrieval and a read-only document adapter instead of deployed
Postgres/Qdrant. No MS or previous answers enter execution. First drafts, failures and tool
events are preserved; no question retries or grading-feedback tuning. The runtime's bounded
protocol/tool recovery remains enabled. Partial probes are separate
from the primary 48/80 experiment and never contribute to its score.
"""

from __future__ import annotations

import argparse
import asyncio
import faulthandler
import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path

import pymupdf
from examtwin.assessment.answering_agent.contracts import AnswerTask, QuestionImage, QuestionSpec
from examtwin.assessment.answering_agent.factory import build_answering_runtime
from examtwin.assessment.strategy_execution import apply_question_strategy
from examtwin.contracts.evidence import Citation
from examtwin.contracts.strategy import StrategyOption, StrategyPlan
from examtwin.platform.config import get_settings
from examtwin.platform.providers import build_chat_model
from examtwin.subjects.public import get_subject_package
from llama_index.core.schema import NodeWithScore, TextNode


def save(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def pdf_text(path: Path) -> str:
    with pymupdf.open(path) as pdf:
        return "\n\n".join(f"<!-- page:{i + 1} -->\n{p.get_text()}" for i, p in enumerate(pdf))


class LocalEvidence:
    """Only the current syllabus and exact insert; no assessment-answer evidence."""

    def __init__(self, root: Path, settings, fixture, package, destination: Path):
        self.rows = {}
        self.nodes = []
        paths = {"syllabus": root / package.manifest.specification_ref}
        if "source_booklet" in fixture:
            paths["insert"] = root / fixture["source_booklet"]["relative_path"]
        settings.markdown_dir.mkdir(parents=True, exist_ok=True)
        provenance = {}
        for kind, path in paths.items():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            document_id = f"{fixture['subject_code']}-{kind}"
            cache = settings.markdown_dir / f"{document_id}.md"
            cache.write_text(pdf_text(path), encoding="utf-8")
            self.rows[document_id] = {
                "id": document_id,
                "path": str(path),
                "markdown_path": str(cache),
                "source_type": kind,
                "authority_tier": "official",
                "status": "converted",
                "pair_key": fixture["pair_key"] if kind == "insert" else None,
                "checksum": digest,
                "converted_source_checksum": digest,
            }
            provenance[kind] = {"path": str(path), "sha256": digest}
            if kind == "syllabus":
                with pymupdf.open(path) as pdf:
                    self.nodes = [
                        NodeWithScore(
                            node=TextNode(
                                text=p.get_text(),
                                metadata={
                                    "source": str(path),
                                    "document_id": document_id,
                                    "page": i + 1,
                                },
                            )
                        )
                        for i, p in enumerate(pdf)
                        if p.get_text().strip()
                    ]
        save(destination / "retrieval-provenance.json", provenance)

    def get(self, document_id):
        return self.rows.get(document_id)

    def get_converted(self, document_id):
        return self.get(document_id)

    def exact_pair_documents(self, pair_key, limit=4):
        return [r for r in self.rows.values() if r["pair_key"] == pair_key][:limit]

    def retrieve(self, query, *, top_k=6, **kwargs):
        terms = set(re.findall(r"[a-z]{3,}", query.lower())) - {"the", "and", "for", "with"}
        scored = [(sum(n.node.text.lower().count(t) for t in terms), n) for n in self.nodes]
        return [n for score, n in sorted(scored, key=lambda x: -x[0])[:top_k] if score]

    @staticmethod
    def citation(node):
        return Citation(
            **node.node.metadata,
            source_type="syllabus",
            authority_tier="official",
            excerpt=node.node.text[:4200],
        )


class RecordingRunner:
    def __init__(self, delegate, destination):
        self.delegate = delegate
        self.destination = destination

    async def run(self, **kwargs):
        result = await self.delegate.run(**kwargs)
        context = kwargs["context"]
        save(
            self.destination / "first-draft.json",
            {
                "payload": result.model_dump(mode="json"),
                "diagrams": [d.model_dump(mode="json") for d in context.diagrams],
            },
        )
        return result


def partial_probe(plan: StrategyPlan, code: str) -> StrategyPlan:
    """Predeclared boundary tests, not optimized score experiments."""
    if code == "9640":
        candidates = [
            o for o in plan.analysis.options if o.mode == "partial" and not o.requires_options
        ]
        chosen = max(candidates, key=lambda o: (o.upper_marks, o.id))
    else:
        # QP supplies the quadratic in 3(c)(i); only solve it, omit distance work in 3(c)(ii).
        chosen = StrategyOption(
            id="probe-q3-cii-partial",
            question_number="3",
            subpart="(c)(ii)",
            mode="partial",
            expected_marks=1,
            lower_marks=0,
            upper_marks=2,
            exam_minutes=3,
            practice_minutes=0,
            skills=["skill:quadratic-solving"],
            approach="Solve the quadratic equation printed in (c)(i) for the two x-coordinates.",
            stop_before="Do not calculate y-coordinates or the length of PQ.",
            rationale="Preset QP-only partial boundary probe; not a calibrated scoring estimate.",
        )
    probe = plan.model_copy(deep=True)
    probe.analysis.options = (
        [*probe.analysis.options, chosen] if code == "9660" else probe.analysis.options
    )
    probe.selected.option_ids = [chosen.id]
    return probe


async def run_subject(args, root: Path, code: str) -> None:
    destination = args.output / code
    destination.mkdir()
    plan_dir = args.plans / code
    plan = StrategyPlan.model_validate_json((plan_dir / "plan-48-720.json").read_text())
    split = json.loads((plan_dir / "split.json").read_text())
    fixture_name = (
        "oxfordaqa-mathematics-9660-2019-jan-p1"
        if code == "9660"
        else "oxfordaqa-economics-9640-2024-jan-u1"
    )
    fixture = json.loads((root / "data/test-fixtures" / fixture_name / "fixture.json").read_text())
    for key in ("question_paper", "source_booklet", "mark_scheme"):
        if key in fixture:
            assert (
                hashlib.sha256((root / fixture[key]["relative_path"]).read_bytes()).hexdigest()
                == fixture[key]["sha256"]
            )
    save(destination / "frozen-plan.json", plan.model_dump())
    save(
        destination / "experiment.json",
        {
            "plan_source": str(plan_dir),
            "plan_sha256": hashlib.sha256((plan_dir / "plan-48-720.json").read_bytes()).hexdigest(),
            "primary": "48/80, study 720 minutes, first attempt only",
            "partial_probe": (
                "Separate scope test; math preset from QP, "
                "economics largest standalone partial candidate"
            ),
            "production_runtime": True,
            "production_database_retrieval_worker": False,
        },
    )
    settings = get_settings().model_copy(
        update={
            "object_store_backend": "local",
            "object_store_local_root": destination / "objects",
            "answer_agent_timeout": 360,
            "answer_agent_max_iterations": 12,
            "answer_agent_max_tool_calls": 8,
            "paper_vision_timeout": 60,
        }
    )
    package = get_subject_package(fixture["subject_pack_id"])
    evidence = LocalEvidence(root, settings, fixture, package, destination)
    semaphore = asyncio.Semaphore(args.concurrency)

    async def answer_one(row, execution_plan, prefix):
        scoped = apply_question_strategy(execution_plan, row, row["answer_requirements"])
        if scoped is None:
            return {
                "question_number": row["number"],
                "answer_markdown": "",
                "diagrams": [],
                "status": "skipped",
            }
        if args.reuse_submissions and prefix == "primary":
            previous = args.reuse_submissions / code
            old_plan = StrategyPlan.model_validate_json((previous / "frozen-plan.json").read_text())
            if old_plan != plan:
                raise ValueError("Cannot reuse a submission from a different frozen plan")
            saved = previous / f"primary-q{row['number']}" / "result.json"
            combined = previous / "first-answers.json"
            if not saved.exists() and combined.exists():
                output = next(
                    r
                    for r in json.loads(combined.read_text())["answers"]
                    if r["question_number"] == row["number"]
                )
                if output["status"] == "completed":
                    save(
                        destination / f"reused-q{row['number']}.json",
                        {
                            "source": str(combined),
                            "question_number": row["number"],
                            "sha256": hashlib.sha256(combined.read_bytes()).hexdigest(),
                        },
                    )
                    return output
            if saved.exists():
                output = json.loads(saved.read_text())
                if output["status"] == "completed":
                    save(
                        destination / f"reused-q{row['number']}.json",
                        {
                            "source": str(saved),
                            "sha256": hashlib.sha256(saved.read_bytes()).hexdigest(),
                        },
                    )
                    return output
        async with semaphore:
            task_dir = destination / f"{prefix}-q{row['number']}"
            task_dir.mkdir()
            events = []

            def record_event(event):
                events.append(asdict(event))
                save(task_dir / "events.json", events)
                print(
                    f"{code} {prefix} Q{row['number']}: {event.phase} {event.status} "
                    f"{event.tool_name or ''}",
                    flush=True,
                )

            runtime = build_answering_runtime(
                settings,
                retriever=evidence.retrieve,
                citation_factory=evidence.citation,
                documents=evidence,
                subject_package=package,
            )
            runtime.model = build_chat_model(settings, timeout=240, max_retries=0)
            runtime.runner = RecordingRunner(runtime.runner, task_dir)
            with pymupdf.open(root / fixture["question_paper"]["relative_path"]) as pdf:
                images = tuple(
                    QuestionImage(
                        page_number=p,
                        content=pdf[p - 1]
                        .get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5))
                        .tobytes("jpeg"),
                    )
                    for p in row["source_pages"]
                )
            task = AnswerTask(
                question="Execute only the frozen approaches.\n\n" + row["question_markdown"],
                visual_request_text=row["question_markdown"],
                subject_code=code,
                question_number=row["number"],
                unit_code=fixture["unit_code"],
                pair_key=fixture["pair_key"],
                question_images=images,
                question_spec=QuestionSpec.model_validate_json(scoped["requirements_json"]),
                strategy_instruction=scoped["strategy_instruction"],
                source_booklet_document_id=f"{code}-insert"
                if "source_booklet" in fixture
                else None,
                source_booklet_checksum=fixture.get("source_booklet", {}).get("sha256"),
            )
            save(task_dir / "execution.json", json.loads(scoped["strategy_instruction"]))
            print(f"{code} {prefix} Q{row['number']}: running", flush=True)
            try:
                result = await runtime.asolve(task, event_sink=record_event)
                output = {
                    "question_number": row["number"],
                    "answer_markdown": result.answer_markdown,
                    "diagrams": [d.model_dump(mode="json") for d in result.diagrams],
                    "status": "completed",
                }
                save(task_dir / "result.json", output)
            except Exception as error:
                # Failure is a blank submission, never silently replace it with an unchecked draft.
                detail = str(error)
                if settings.llm_api_key:
                    detail = detail.replace(settings.llm_api_key.get_secret_value(), "[REDACTED]")
                output = {
                    "question_number": row["number"],
                    "answer_markdown": "",
                    "diagrams": [],
                    "status": "failed",
                    "error_type": type(error).__name__,
                }
                save(task_dir / "failure.json", {**output, "detail": detail[:2000]})
            save(task_dir / "events.json", events)
            print(f"{code} {prefix} Q{row['number']}: {output['status']}", flush=True)
            return output

    outputs = await asyncio.gather(*(answer_one(row, plan, "primary") for row in split))
    save(destination / "first-answers.json", {"answers": outputs})
    probe_output = None
    if not args.skip_partial:
        probe = partial_probe(plan, code)
        probe_number = next(
            o.question_number
            for o in probe.analysis.options
            if o.id == probe.selected.option_ids[0]
        )
        probe_row = next(r for r in split if r["number"] == probe_number)
        probe_output = await answer_one(probe_row, probe, "partial")
    # Mark scheme read only after all primary and probe submissions have been frozen.
    bundle = {
        "subject_code": code,
        "question_paper": pdf_text(root / fixture["question_paper"]["relative_path"]),
        "source_booklet": pdf_text(root / fixture["source_booklet"]["relative_path"])
        if "source_booklet" in fixture
        else None,
        "mark_scheme": pdf_text(root / fixture["mark_scheme"]["relative_path"]),
        "answers": outputs,
        "notes": (
            "Blind grade only submitted answers and actual diagrams; "
            "blank/failed earns zero. No target supplied."
        ),
    }
    save(destination / "blind-judge-bundle.json", bundle)
    if probe_output is not None:
        save(
            destination / "partial-blind-judge-bundle.json",
            {
                **bundle,
                "answers": [probe_output],
                "notes": "Separate submission: grade this question only. No target supplied.",
            },
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--plans", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--subjects", nargs="+", choices=("9660", "9640"), default=["9660", "9640"])
    parser.add_argument("--reuse-submissions", type=Path)
    parser.add_argument("--diagnostics", action="store_true")
    parser.add_argument("--skip-partial", action="store_true")
    args = parser.parse_args()
    if not args.live:
        parser.error("Configured model calls require --live")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    if args.diagnostics:
        faulthandler.dump_traceback_later(90, repeat=True)
    root = Path(__file__).resolve().parents[1]
    for code in args.subjects:
        asyncio.run(run_subject(args, root, code))


if __name__ == "__main__":
    main()
