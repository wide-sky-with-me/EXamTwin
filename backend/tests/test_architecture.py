from pathlib import Path

import scripts.check_architecture as architecture


def _check(
    tmp_path: Path,
    monkeypatch,
    relative_path: str,
    source: str,
    *,
    complete_managed_routes: bool = True,
    enforce_managed_dependencies: bool = False,
) -> list[str]:
    package_root = tmp_path / "examtwin"
    path = package_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    module_key = Path(relative_path).with_suffix("").parts
    if complete_managed_routes and (
        managed_routes := architecture.THIN_ROUTE_FUNCTIONS.get(module_key)
    ):
        source += "".join(
            f"\ndef {route}():\n    return None\n"
            for route in sorted(managed_routes)
            if f"def {route}(" not in source
        )
    path.write_text(source, encoding="utf-8")
    monkeypatch.setattr(architecture, "PACKAGE_ROOT", package_root)
    if not enforce_managed_dependencies:
        monkeypatch.setattr(architecture, "MANAGED_ROUTE_DEPENDENCIES", {})
    return architecture.check_file(path)


def test_platform_cannot_import_feature(tmp_path: Path, monkeypatch) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "platform/provider.py",
        "from examtwin.assessment import grading\n",
    )

    assert any("platform must not depend on feature" in error for error in errors)


def test_feature_cannot_import_app(tmp_path: Path, monkeypatch) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "knowledge/service.py",
        "from examtwin.app.api import dependencies\n",
    )

    assert any("feature must not depend on app" in error for error in errors)


def test_feature_dependencies_follow_subjects_knowledge_assessment_order(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "knowledge/service.py",
        "from examtwin.assessment import grading\n",
    )

    assert any(
        "knowledge must not depend on downstream feature assessment" in error for error in errors
    )


def test_cross_feature_imports_use_public_entrypoint(tmp_path: Path, monkeypatch) -> None:
    internal_errors = _check(
        tmp_path,
        monkeypatch,
        "assessment/service.py",
        "from examtwin.knowledge.rag import RagService\n",
    )
    public_errors = _check(
        tmp_path,
        monkeypatch,
        "assessment/service.py",
        "from examtwin.knowledge.public import KnowledgeRepository\n",
    )

    assert any(
        "cross-feature imports must use knowledge.public" in error for error in internal_errors
    )
    assert public_errors == []


def test_fastapi_is_restricted_to_app(tmp_path: Path, monkeypatch) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "assessment/grading.py",
        "from fastapi import HTTPException\n",
    )

    assert any("FastAPI is restricted to the app boundary" in error for error in errors)


def test_relative_import_cannot_bypass_dependency_direction(tmp_path: Path, monkeypatch) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "platform/bypass.py",
        "from ..assessment import grading\n",
    )

    assert any("platform must not depend on feature" in error for error in errors)


def test_legacy_horizontal_module_is_rejected(tmp_path: Path, monkeypatch) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "services/rag.py",
        "VALUE = 1\n",
    )

    assert any("legacy horizontal module is forbidden" in error for error in errors)


def test_app_may_compose_features(tmp_path: Path, monkeypatch) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/composition.py",
        "from examtwin.knowledge import rag\nfrom fastapi import Depends\n",
    )

    assert errors == []


def test_managed_workspace_routes_cannot_assemble_persistence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "def upload_workspace_document():\n"
            "    sessions = create_session_factory('postgresql://test')\n"
            "    return WorkspaceRepository(sessions)\n"
        ),
    )

    assert any(
        "route must delegate persistence orchestration to an application service" in error
        for error in errors
    )


def test_managed_workspace_routes_follow_same_module_persistence_helpers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "def _workspaces(settings):\n"
            "    sessions = create_session_factory(settings.database_url)\n"
            "    return WorkspaceRepository(sessions)\n\n"
            "def upload_workspace_document(settings):\n"
            "    return _workspaces(settings)\n"
        ),
    )

    assert any(
        "route must delegate persistence orchestration to an application service" in error
        for error in errors
    )


def test_managed_workspace_routes_resolve_aliased_persistence_imports(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "from examtwin.app.composition import corpus_repository as load_corpus\n\n"
            "def build_knowledge_base():\n"
            "    return load_corpus()\n"
        ),
    )

    assert any("build_knowledge_base calls corpus_repository" in error for error in errors)


def test_managed_workspace_routes_follow_reachable_nested_function_and_async_helpers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "def upload_workspace_document(settings):\n"
            "    def assemble():\n"
            "        return WorkspaceRepository(settings)\n"
            "    async def persist():\n"
            "        return create_session_factory(settings.database_url)\n"
            "    assemble()\n"
            "    return persist()\n"
        ),
    )

    assert any(
        "upload_workspace_document calls create_session_factory" in error for error in errors
    )
    assert any("upload_workspace_document calls WorkspaceRepository" in error for error in errors)


def test_unreachable_nested_persistence_helpers_are_allowed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "def upload_workspace_document(service):\n"
            "    def assemble():\n"
            "        return WorkspaceRepository(create_session_factory('test'))\n"
            "    return service.upload()\n"
        ),
    )

    assert errors == []


def test_managed_workspace_routes_resolve_assignment_aliases(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "from examtwin.app.composition import create_session_factory\n\n"
            "def _workspaces(settings):\n"
            "    return WorkspaceRepository(settings)\n\n"
            "def upload_workspace_document(settings):\n"
            "    factory = create_session_factory\n"
            "    helper: object = _workspaces\n"
            "    factory(settings.database_url)\n"
            "    return helper(settings)\n"
        ),
    )

    assert any(
        "upload_workspace_document calls create_session_factory" in error for error in errors
    )
    assert any("upload_workspace_document calls WorkspaceRepository" in error for error in errors)


def test_rebound_callable_aliases_are_not_treated_as_persistence_factories(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "def _workspaces(settings):\n"
            "    return WorkspaceRepository(settings)\n\n"
            "def upload_workspace_document(service):\n"
            "    factory = create_session_factory\n"
            "    helper = _workspaces\n"
            "    factory = service.make_factory\n"
            "    helper = service.make_helper\n"
            "    return factory(), helper()\n"
        ),
    )

    assert errors == []


def test_managed_workspace_routes_keep_forbidden_targets_across_control_flow_joins(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "def upload_workspace_document(service, flag, mode, items):\n"
            "    factory = service.make_factory\n"
            "    if flag:\n"
            "        factory = create_session_factory\n"
            "    else:\n"
            "        factory = service.make_factory\n"
            "    factory('test')\n"
            "    matcher = service.make_factory\n"
            "    match mode:\n"
            "        case 'forbidden':\n"
            "            matcher = corpus_repository\n"
            "        case _:\n"
            "            matcher = service.make_factory\n"
            "    matcher()\n"
            "    loop_factory = service.make_factory\n"
            "    for item in items:\n"
            "        if item:\n"
            "            loop_factory = build_object_store\n"
            "    loop_factory()\n"
            "    try:\n"
            "        try_factory = service.make_factory\n"
            "        service.maybe_raise()\n"
            "    except RuntimeError:\n"
            "        try_factory = knowledge_repository\n"
            "    return try_factory()\n"
        ),
    )

    assert any(
        "upload_workspace_document calls create_session_factory" in error for error in errors
    )
    assert any("upload_workspace_document calls corpus_repository" in error for error in errors)
    assert any("upload_workspace_document calls build_object_store" in error for error in errors)
    assert any("upload_workspace_document calls knowledge_repository" in error for error in errors)


def test_definite_safe_rebinding_clears_merged_forbidden_targets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "def upload_workspace_document(service, flag):\n"
            "    if flag:\n"
            "        factory = corpus_repository\n"
            "    else:\n"
            "        factory = create_session_factory\n"
            "    factory = service.make_factory\n"
            "    return factory()\n"
        ),
    )

    assert errors == []


def test_non_fallthrough_branches_do_not_pollute_joined_callable_bindings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "def upload_workspace_document(service, should_return, should_raise):\n"
            "    upload = corpus_repository\n"
            "    if should_return:\n"
            "        return service.upload()\n"
            "    else:\n"
            "        upload = service.upload\n"
            "    upload()\n"
            "    build = knowledge_repository\n"
            "    if should_raise:\n"
            "        raise RuntimeError('stopped')\n"
            "    else:\n"
            "        build = service.build\n"
            "    return build()\n"
        ),
    )

    assert errors == []


def test_statements_after_terminal_control_flow_are_not_inspected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "def upload_workspace_document(service, items):\n"
            "    for item in items:\n"
            "        if item:\n"
            "            break\n"
            "            WorkspaceRepository('dead')\n"
            "        continue\n"
            "        create_session_factory('dead')\n"
            "    return service.upload()\n"
            "    corpus_repository()\n"
        ),
    )

    assert errors == []


def test_live_forbidden_branch_binding_still_reaches_the_join(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "def upload_workspace_document(service, use_repository):\n"
            "    if use_repository:\n"
            "        upload = corpus_repository\n"
            "    else:\n"
            "        return service.upload()\n"
            "    return upload()\n"
        ),
    )

    assert any("upload_workspace_document calls corpus_repository" in error for error in errors)


def test_try_else_return_does_not_discard_live_handler_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "def upload_workspace_document(service):\n"
            "    upload = service.upload\n"
            "    try:\n"
            "        service.maybe_raise()\n"
            "    except RuntimeError:\n"
            "        upload = corpus_repository\n"
            "    else:\n"
            "        return service.upload()\n"
            "    return upload()\n"
        ),
    )

    assert any("upload_workspace_document calls corpus_repository" in error for error in errors)


def test_try_else_rebinding_keeps_normal_continuation_safe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "def upload_workspace_document(service):\n"
            "    upload = corpus_repository\n"
            "    try:\n"
            "        service.maybe_raise()\n"
            "    except RuntimeError:\n"
            "        return service.upload()\n"
            "    else:\n"
            "        upload = service.upload\n"
            "    return upload()\n"
        ),
    )

    assert errors == []


def test_managed_workspace_route_decorators_and_defaults_are_inspected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "def wrap(value):\n"
            "    return value\n\n"
            "@wrap(WorkspaceRepository('test'))\n"
            "def upload_workspace_document(\n"
            "    sessions=create_session_factory('test'),\n"
            "    *,\n"
            "    corpus=corpus_repository(),\n"
            "):\n"
            "    return sessions, corpus\n"
        ),
    )

    assert any("upload_workspace_document calls WorkspaceRepository" in error for error in errors)
    assert any(
        "upload_workspace_document calls create_session_factory" in error for error in errors
    )
    assert any("upload_workspace_document calls corpus_repository" in error for error in errors)


def test_managed_workspace_routes_accept_only_the_approved_dependency_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "from fastapi import Depends as Inject\n"
            "from .dependencies import (\n"
            "    get_corpus_workspace_service as provide_workspace_service,\n"
            ")\n\n"
            "def upload_workspace_document(\n"
            "    service=Inject(provide_workspace_service),\n"
            "):\n"
            "    return service.upload()\n\n"
            "def build_knowledge_base(\n"
            "    service=Inject(provide_workspace_service),\n"
            "):\n"
            "    return service.build()\n"
        ),
        enforce_managed_dependencies=True,
    )

    assert errors == []


def test_managed_workspace_routes_reject_another_imported_dependency_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "from fastapi import Depends\n"
            "from examtwin.app.api.dependencies import (\n"
            "    get_corpus_workspace_service,\n"
            "    get_subject_context as imported_provider,\n"
            ")\n\n"
            "def upload_workspace_document(service=Depends(imported_provider)):\n"
            "    return service.upload()\n\n"
            "def build_knowledge_base(\n"
            "    service=Depends(get_corpus_workspace_service),\n"
            "):\n"
            "    return service.build()\n"
        ),
        enforce_managed_dependencies=True,
    )

    assert any(
        "upload_workspace_document.service must use "
        "examtwin.app.api.dependencies.get_corpus_workspace_service" in error
        for error in errors
    )
    assert not any(
        "build_knowledge_base.service" in error and "dependency contract violated" in error
        for error in errors
    )


def test_managed_workspace_routes_accept_assignment_aliases_at_definition_time(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "from fastapi import Depends\n"
            "from examtwin.app.api.dependencies import (\n"
            "    get_corpus_workspace_service,\n"
            "    get_subject_context,\n"
            ")\n\n"
            "upload_provider = get_corpus_workspace_service\n"
            "def upload_workspace_document(service=Depends(upload_provider)):\n"
            "    return service.upload()\n\n"
            "build_provider: object = get_corpus_workspace_service\n"
            "def build_knowledge_base(service=Depends(build_provider)):\n"
            "    return service.build()\n\n"
            "upload_provider = get_subject_context\n"
            "build_provider = get_subject_context\n"
        ),
        enforce_managed_dependencies=True,
    )

    assert errors == []


def test_managed_workspace_routes_reject_rebound_provider_names(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "from fastapi import Depends\n"
            "from examtwin.app.api.dependencies import (\n"
            "    get_corpus_workspace_service,\n"
            "    get_subject_context,\n"
            ")\n\n"
            "upload_provider = get_corpus_workspace_service\n"
            "upload_provider: object = get_subject_context\n"
            "def upload_workspace_document(service=Depends(upload_provider)):\n"
            "    return service.upload()\n\n"
            "build_provider = get_corpus_workspace_service\n"
            "def build_provider():\n"
            "    return get_subject_context()\n\n"
            "def build_knowledge_base(service=Depends(build_provider)):\n"
            "    return service.build()\n"
        ),
        enforce_managed_dependencies=True,
    )

    assert any(
        "upload_workspace_document.service must use "
        "examtwin.app.api.dependencies.get_corpus_workspace_service" in error
        for error in errors
    )
    assert any(
        "build_knowledge_base.service must use "
        "examtwin.app.api.dependencies.get_corpus_workspace_service" in error
        for error in errors
    )


def test_managed_workspace_routes_follow_lambda_callbacks_consumed_during_request(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "from examtwin.app.api.errors import guarded_api_call\n\n"
            "def upload_workspace_document(settings):\n"
            "    return guarded_api_call(\n"
            "        lambda: WorkspaceRepository(settings),\n"
            "        code='UPLOAD_FAILED',\n"
            "        message='failed',\n"
            "    )\n"
        ),
    )

    assert any("upload_workspace_document calls WorkspaceRepository" in error for error in errors)


def test_managed_workspace_routes_follow_named_callbacks_passed_by_keyword(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "from examtwin.app.api.errors import guarded_api_call\n\n"
            "def upload_workspace_document(settings):\n"
            "    def operation():\n"
            "        return create_session_factory(settings.database_url)\n"
            "    return guarded_api_call(\n"
            "        operation=operation,\n"
            "        code='UPLOAD_FAILED',\n"
            "        message='failed',\n"
            "    )\n"
        ),
    )

    assert any(
        "upload_workspace_document calls create_session_factory" in error for error in errors
    )


def test_managed_workspace_routes_follow_depends_providers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "from fastapi import Depends\n\n"
            "def local_provider():\n"
            "    return WorkspaceRepository('test')\n\n"
            "def upload_workspace_document(service=Depends(local_provider)):\n"
            "    return service.upload()\n"
        ),
    )

    assert any("upload_workspace_document calls WorkspaceRepository" in error for error in errors)


def test_inert_callback_arguments_and_unreferenced_lambda_bodies_are_allowed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "def remember(callback):\n"
            "    return callback\n\n"
            "def upload_workspace_document(settings):\n"
            "    def named_callback():\n"
            "        return create_session_factory(settings.database_url)\n"
            "    inline_callback = lambda: WorkspaceRepository(settings)\n"
            "    remember(named_callback)\n"
            "    remember(inline_callback)\n"
            "    return object()\n"
        ),
    )

    assert errors == []


def test_managed_workspace_route_helper_cycle_terminates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "def _first_helper():\n"
            "    return _second_helper()\n\n"
            "def _second_helper():\n"
            "    return _first_helper()\n\n"
            "def upload_workspace_document():\n"
            "    return _first_helper()\n"
        ),
    )

    assert errors == []


def test_persistence_helpers_reachable_only_from_unmanaged_routes_are_allowed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        (
            "def _workspaces(settings):\n"
            "    return WorkspaceRepository(\n"
            "        create_session_factory(settings.database_url)\n"
            "    )\n\n"
            "def list_workspace_documents(settings):\n"
            "    return _workspaces(settings)\n\n"
            "def upload_workspace_document(service):\n"
            "    return service.upload()\n"
        ),
    )

    assert errors == []


def test_configured_managed_route_must_exist(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/api/workspaces.py",
        "def upload_workspace_document(service):\n    return service.upload()\n",
        complete_managed_routes=False,
    )

    assert any(
        "configured managed route is missing: build_knowledge_base" in error for error in errors
    )


def test_relative_import_above_package_root_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "platform/bypass.py",
        "from ...assessment import grading\n",
    )

    assert any("relative import traverses above examtwin package" in error for error in errors)
