from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Response

from examtwin.app.api.dependencies import get_subject_context
from examtwin.contracts.graphs import (
    BuildGraphRequest,
    GraphEdgeResponse,
    GraphNodeResponse,
    GraphVersionResponse,
    GraphVersionSummary,
    ReviewAllRequest,
    ReviewGraphEdgeRequest,
    ReviewGraphNodeRequest,
)
from examtwin.knowledge.document_block_repository import DocumentBlockRepository
from examtwin.knowledge.graph_extraction import KnowledgeGraphBuildService
from examtwin.knowledge.graph_repository import GraphRepository
from examtwin.platform.config import Settings, get_settings
from examtwin.platform.database.session import create_session_factory
from examtwin.subjects.public import SubjectContext
from examtwin.subjects.workspace_repository import WorkspaceRepository

router = APIRouter()


def _repositories(
    settings: Settings,
) -> tuple[WorkspaceRepository, DocumentBlockRepository, GraphRepository]:
    sessions = create_session_factory(settings.database_url)
    return (
        WorkspaceRepository(sessions),
        DocumentBlockRepository(sessions),
        GraphRepository(sessions),
    )


def _require_graph(graphs: GraphRepository, version_id: str, subject_id: str) -> dict:
    graph = graphs.get(version_id)
    if graph["subject_id"] != subject_id:
        raise LookupError("知识图谱版本不属于当前科目")
    return graph


@router.get("/knowledge-graphs", response_model=list[GraphVersionSummary])
def graph_versions(
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
) -> list[GraphVersionSummary]:
    _, _, graphs = _repositories(settings)
    return [GraphVersionSummary.model_validate(item) for item in graphs.list_versions(subject.id)]


@router.post("/knowledge-graphs/build", response_model=GraphVersionResponse)
def build_graph(
    request: BuildGraphRequest,
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
) -> GraphVersionResponse:
    workspaces, blocks, graphs = _repositories(settings)
    try:
        result = KnowledgeGraphBuildService(
            settings,
            subject,
            workspaces,
            blocks,
            graphs,
        ).build(request.knowledge_base_version_id)
        return GraphVersionResponse.model_validate(result)
    except (LookupError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=502, detail=f"知识图谱抽取失败：{str(error)[:500]}"
        ) from error


@router.get("/knowledge-graphs/{version_id}", response_model=GraphVersionResponse)
def graph_version(
    version_id: str,
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
) -> GraphVersionResponse:
    _, _, graphs = _repositories(settings)
    try:
        return GraphVersionResponse.model_validate(_require_graph(graphs, version_id, subject.id))
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/knowledge-graphs/{version_id}", status_code=204)
def delete_graph_version(
    version_id: str,
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
) -> Response:
    _, _, graphs = _repositories(settings)
    try:
        graphs.delete(version_id, subject_id=subject.id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return Response(status_code=204)


@router.patch(
    "/knowledge-graphs/{version_id}/nodes/{node_id}",
    response_model=GraphNodeResponse,
)
def review_graph_node(
    version_id: str,
    node_id: str,
    request: ReviewGraphNodeRequest,
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
) -> GraphNodeResponse:
    _, _, graphs = _repositories(settings)
    try:
        _require_graph(graphs, version_id, subject.id)
        values = request.model_dump(exclude_none=True)
        aliases = values.pop("aliases", None)
        if aliases is not None:
            values["aliases_json"] = json.dumps(aliases, ensure_ascii=False)
        return GraphNodeResponse.model_validate(graphs.review_node(version_id, node_id, values))
    except (LookupError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.patch(
    "/knowledge-graphs/{version_id}/edges/{edge_id}",
    response_model=GraphEdgeResponse,
)
def review_graph_edge(
    version_id: str,
    edge_id: str,
    request: ReviewGraphEdgeRequest,
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
) -> GraphEdgeResponse:
    _, _, graphs = _repositories(settings)
    try:
        _require_graph(graphs, version_id, subject.id)
        return GraphEdgeResponse.model_validate(
            graphs.review_edge(
                version_id,
                edge_id,
                relation_type=request.relation_type,
                review_status=request.review_status,
            )
        )
    except (LookupError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post(
    "/knowledge-graphs/{version_id}/review-all",
    response_model=GraphVersionResponse,
)
def review_all(
    version_id: str,
    request: ReviewAllRequest,
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
) -> GraphVersionResponse:
    _, _, graphs = _repositories(settings)
    try:
        _require_graph(graphs, version_id, subject.id)
        return GraphVersionResponse.model_validate(
            graphs.review_all(version_id, request.review_status)
        )
    except (LookupError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post(
    "/knowledge-graphs/{version_id}/publish",
    response_model=GraphVersionResponse,
)
def publish_graph(
    version_id: str,
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
) -> GraphVersionResponse:
    _, _, graphs = _repositories(settings)
    try:
        _require_graph(graphs, version_id, subject.id)
        return GraphVersionResponse.model_validate(graphs.publish(version_id))
    except (LookupError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
