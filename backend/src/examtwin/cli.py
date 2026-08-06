from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from urllib.request import urlopen
from uuid import uuid4

import typer

from examtwin.composition import (
    build_corpus_ingestor,
    build_knowledge_pipeline,
    build_object_store,
    build_paper_worker,
    build_rag_service,
    corpus_repository,
    dashboard_repository,
    knowledge_repository,
    retrieval_trace_repository,
    vector_index_repository,
)
from examtwin.config import get_settings
from examtwin.config_contract import audit_environment_contract
from examtwin.contracts.system import API_CAPABILITIES, API_CONTRACT_VERSION
from examtwin.observability import configure_logging
from examtwin.persistence.migrations import upgrade_database
from examtwin.persistence.session import utcnow
from examtwin.services.ingestion import build_vector_index
from examtwin.services.inventory import corpus_stats, scan_corpus
from examtwin.services.providers import run_provider_smoke
from examtwin.services.retrieval_evaluation import (
    evaluate_retrieval,
    load_retrieval_dataset,
    render_evaluation,
)
from examtwin.services.storage_lifecycle import migrate_local_objects, run_storage_gc_forever
from examtwin.services.subject_context import subject_context
from examtwin.services.subject_pack_audit import audit_subject_pack_pdf
from examtwin.storage import ObjectMetadata
from examtwin.subjects import get_subject_pack

app = typer.Typer(no_args_is_help=True, help="ExamTwin evidence platform commands.")


@app.callback()
def configure_cli_logging() -> None:
    configure_logging()


@app.command("config-check")
def config_check() -> None:
    """Validate that Settings, Compose-only keys, .env, and .env.example agree."""
    audit = audit_environment_contract()
    if audit.errors:
        for error in audit.errors:
            typer.echo(error, err=True)
        raise typer.Exit(code=1)
    typer.echo(f"environment contract is complete ({len(audit.expected_keys)} keys)")


@app.command()
def init() -> None:
    """Apply all versioned PostgreSQL schema migrations."""
    upgrade_database(get_settings().database_url)
    typer.echo("PostgreSQL schema is ready. Run knowledge-build to publish a graph.")


@app.command("db-upgrade")
def db_upgrade(revision: str = typer.Option("head")) -> None:
    """Apply versioned PostgreSQL schema migrations."""
    settings = get_settings()
    upgrade_database(settings.database_url, revision)
    typer.echo(f"PostgreSQL schema upgraded to {revision}.")


@app.command("healthcheck")
def healthcheck(
    url: str = typer.Option("http://127.0.0.1:8000/api/v1/health"),
) -> None:
    """Fail unless the live API and this image expose the same healthy contract."""

    try:
        with urlopen(url, timeout=3) as response:  # noqa: S310 - fixed local default
            payload = json.load(response)
        capabilities = set(payload.get("capabilities", []))
        valid = (
            payload.get("status") == "ok"
            and payload.get("api_contract_version") == API_CONTRACT_VERSION
            and capabilities == set(API_CAPABILITIES)
        )
    except Exception as error:
        typer.echo(f"API healthcheck failed: {type(error).__name__}", err=True)
        raise typer.Exit(code=1) from None
    if not valid:
        typer.echo("API healthcheck failed: contract or infrastructure is degraded", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"API healthy ({API_CONTRACT_VERSION})")


@app.command("storage-migrate")
def storage_migrate(
    execute: bool = typer.Option(
        False,
        "--execute/--dry-run",
        help="Copy legacy local objects into the configured backend without deleting originals.",
    ),
) -> None:
    """Discover or idempotently copy legacy managed files into ObjectStore."""
    settings = get_settings()
    upgrade_database(settings.database_url)
    result = migrate_local_objects(settings, build_object_store(settings), execute=execute)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if int(result["failed"]):
        raise typer.Exit(code=1)


@app.command("storage-gc")
def storage_gc() -> None:
    """Delete one bounded batch of expired objects and persist every outcome."""
    settings = get_settings()
    upgrade_database(settings.database_url)
    result = build_object_store(settings).collect_expired(limit=settings.storage_gc_batch_size)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result["failed"]:
        raise typer.Exit(code=1)


@app.command("storage-stats")
def storage_stats() -> None:
    """Show reconciled object counts and bytes by lifecycle state."""
    settings = get_settings()
    upgrade_database(settings.database_url)
    result = build_object_store(settings).stats()
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("storage-smoke")
def storage_smoke() -> None:
    """Round-trip one uniquely named object through the configured backend."""
    settings = get_settings()
    upgrade_database(settings.database_url)
    store = build_object_store(settings)
    key = f"smoke/{uuid4().hex}.txt"
    content = b"examtwin-object-store-smoke"
    stored = None
    try:
        stored = store.put_bytes(
            key,
            content,
            metadata=ObjectMetadata(
                purpose="storage_smoke",
                owner_type="system",
                owner_id="storage-smoke",
                retain_until=utcnow() + timedelta(hours=1),
                content_type="text/plain",
            ),
        )
        if store.materialize(key).read_bytes() != content:
            raise RuntimeError("对象存储往返内容不一致")
    finally:
        if stored is not None:
            store.delete(key)
    typer.echo(
        json.dumps(
            {
                "backend": settings.object_store_backend,
                "bucket": stored.bucket if stored is not None else None,
                "roundtrip": "passed",
            },
            ensure_ascii=False,
        )
    )


@app.command("storage-gc-worker")
def storage_gc_worker() -> None:
    """Continuously reconcile expired ObjectStore records in bounded batches."""
    settings = get_settings()
    upgrade_database(settings.database_url)
    run_storage_gc_forever(
        build_object_store(settings),
        batch_size=settings.storage_gc_batch_size,
        interval_seconds=settings.storage_gc_interval_seconds,
        report=lambda result: typer.echo(json.dumps(result, ensure_ascii=False)),
    )


@app.command()
def inventory() -> None:
    """Scan the active subject corpus and build a strict source manifest."""
    settings = get_settings()
    upgrade_database(settings.database_url)
    subject = subject_context(settings)
    result = scan_corpus(
        corpus_repository(settings),
        subject.corpus_dir,
        subject.pack,
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("knowledge-build")
def knowledge_build() -> None:
    """Validate, evidence-rate, and publish the active SubjectPack knowledge graph."""
    settings = get_settings()
    upgrade_database(settings.database_url)
    result = build_knowledge_pipeline(settings).run()
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("curriculum-preview")
def curriculum_preview(output: Path | None = typer.Option(None, "--output")) -> None:
    """Extract and validate the active syllabus without writing or publishing graph data."""
    settings = get_settings()
    upgrade_database(settings.database_url)
    result = build_knowledge_pipeline(settings).preview()
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if output is not None:
        output.write_text(rendered + "\n", encoding="utf-8")
        typer.echo(str(output))
        return
    typer.echo(rendered)


@app.command()
def stats() -> None:
    """Show corpus, pairing, graph, and review statistics."""
    settings = get_settings()
    subject = subject_context(settings)
    typer.echo(
        json.dumps(
            corpus_stats(
                dashboard_repository(settings),
                subject_code=subject.subject_code,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("subject-pack-audit")
def subject_pack_audit(
    pack_id: str = typer.Option(..., "--pack"),
    specification: Path | None = typer.Option(None, "--specification"),
) -> None:
    """Validate one SubjectPack against a real official specification PDF."""
    settings = get_settings()
    subject_pack = get_subject_pack(pack_id)
    pdf_path = specification or settings.resolved(Path(subject_pack.specification_ref))
    result = audit_subject_pack_pdf(subject_pack, pdf_path)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise typer.Exit(code=1)


@app.command()
def convert(
    source_type: list[str] | None = typer.Option(None, "--type"),
    authority_tier: list[str] | None = typer.Option(None, "--tier"),
    document_id: list[str] | None = typer.Option(None, "--id"),
    limit: int | None = typer.Option(None),
    workers: int = typer.Option(2, min=1, max=8),
    force: bool = typer.Option(False),
) -> None:
    """Convert selected source files to auditable Markdown through MinerU."""
    service = build_corpus_ingestor(get_settings())
    result = service.convert_batch(
        document_ids=document_id,
        source_types=source_type,
        authority_tiers=authority_tier,
        limit=limit,
        workers=workers,
        force=force,
    )
    typer.echo(result.model_dump_json(indent=2))


@app.command("index")
def index_command(
    limit: int | None = typer.Option(None),
    resume: bool = typer.Option(
        False,
        help="Resume an interrupted staging collection from its current point count.",
    ),
) -> None:
    """Embed all converted Markdown and rebuild the Qdrant collection."""
    settings = get_settings()
    subject = subject_context(settings)
    result = build_vector_index(
        subject.runtime_settings(settings),
        subject,
        vector_index_repository(settings),
        knowledge_repository(settings),
        limit=limit,
        resume=resume,
    )
    typer.echo(result.model_dump_json(indent=2))


@app.command("retrieval-evaluate")
def retrieval_evaluate(
    dataset: Path | None = typer.Option(None, exists=True, dir_okay=False),
) -> None:
    """Run a subject-owned golden retrieval set and fail when its quality gate regresses."""

    settings = get_settings()
    subject = subject_context(settings)
    dataset_path = dataset or subject.package.source_dir / "retrieval-eval.json"
    if not dataset_path.is_file():
        raise typer.BadParameter(f"Retrieval evaluation dataset not found: {dataset_path}")
    definition = load_retrieval_dataset(dataset_path)
    if definition.subject_code != subject.subject_code:
        raise typer.BadParameter(
            "Retrieval evaluation subject does not match the active SubjectPack"
        )
    report = evaluate_retrieval(definition, build_rag_service(settings, subject).retrieve)
    typer.echo(render_evaluation(report))
    if not report["passed"]:
        raise typer.Exit(code=1)


@app.command("retrieval-traces")
def retrieval_traces(
    limit: int = typer.Option(20, min=1, max=200),
) -> None:
    """Show recent retrieval diagnostics for the active SubjectPack."""

    settings = get_settings()
    subject = subject_context(settings)
    rows = retrieval_trace_repository(settings).recent(
        subject_code=subject.subject_code,
        limit=limit,
    )
    typer.echo(json.dumps(rows, ensure_ascii=False, indent=2, default=str))


@app.command("provider-smoke")
def provider_smoke(
    provider: str = typer.Option(
        "all",
        help="Billable live check: all, llm, embedding, rerank, or a comma-separated subset.",
    ),
) -> None:
    """Call configured model providers and verify their real response contracts."""

    selected = {item.strip().lower() for item in provider.split(",") if item.strip()}
    if not selected or "all" in selected:
        selected = {"llm", "embedding", "rerank"}
    try:
        result = run_provider_smoke(get_settings(), selected)
    except (RuntimeError, ValueError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command()
def bootstrap(
    convert_limit: int = typer.Option(
        6, help="Number of authoritative sources to convert in the smoke-test bootstrap."
    ),
) -> None:
    """Initialize, inventory, convert a bounded core set, and build Qdrant."""
    settings = get_settings()
    upgrade_database(settings.database_url)
    subject = subject_context(settings)
    scan_corpus(
        corpus_repository(settings),
        subject.corpus_dir,
        subject.pack,
    )
    result = build_corpus_ingestor(settings).convert_batch(
        source_types=["syllabus", "question_paper", "mark_scheme"],
        limit=convert_limit,
        workers=2,
    )
    typer.echo(result.model_dump_json(indent=2))
    index_result = build_vector_index(
        subject.runtime_settings(settings),
        subject,
        vector_index_repository(settings),
        knowledge_repository(settings),
    )
    typer.echo(index_result.model_dump_json(indent=2))


@app.command("paper-worker")
def paper_worker(
    once: bool = typer.Option(False, help="Process at most one queued job and exit."),
) -> None:
    """Process persistent paper parsing and answering jobs."""
    settings = get_settings()
    upgrade_database(settings.database_url)
    worker = build_paper_worker(settings)
    if once:
        processed = worker.run_once()
        typer.echo("processed" if processed else "idle")
        return
    worker.run_forever()


if __name__ == "__main__":
    app()
