import {
  BookOpen,
  CheckCircle2,
  FileText,
  FolderOpen,
  GitBranch,
  LoaderCircle,
  Maximize2,
  Minimize2,
  Network,
  RefreshCw,
  Save,
  Sparkles,
  Trash2,
  UploadCloud,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ErrorBanner } from "../components/Feedback";
import { GraphNodeFormula, KnowledgeGraphCanvas } from "../components/KnowledgeGraphCanvas";
import { InlineMarkdown } from "../components/Markdown";
import { AppConfirmDialog } from "../components/ui/AppConfirmDialog";
import { apiClient, unwrapApi, uploadWorkspaceDocument } from "../lib/api";
import { difficultyOf, relationLabels, sourceLabels } from "../lib/evidence";
import { useModalFocus } from "../lib/use-modal-focus";
import type {
  GraphVersion,
  GraphVersionSummary,
  KnowledgePoint,
  KnowledgeRelation,
  SourceDocument,
  SubjectPack,
} from "../types";

export function Knowledge({
  points,
  relations,
  subject,
  refresh,
}: {
  points: KnowledgePoint[];
  relations: KnowledgeRelation[];
  subject: SubjectPack;
  refresh: () => Promise<void>;
}) {
  const [view, setView] = useState<"workspace" | "catalog" | "graph">("workspace");
  const [unit, setUnit] = useState("ALL");
  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const [expandedTopics, setExpandedTopics] = useState<Set<string>>(() => new Set());
  const units = [
    "ALL",
    ...points
      .filter((point) => point.features.node_type === "unit")
      .map((point) => point.code),
  ];
  const visible = unit === "ALL" ? points : points.filter((point) => point.unit_code === unit);
  const topics = visible.filter((point) => point.features.node_type === "topic");
  const objectives = visible.filter(
    (point) => point.features.node_type === "learning_objective",
  );
  const selected =
    visible.find((point) => point.code === selectedCode) ??
    topics[0] ??
    objectives[0] ??
    null;
  const selectedRelations = selected
    ? relations.filter(
        (relation) =>
          relation.source_code === selected.code || relation.target_code === selected.code,
      )
    : [];
  const visibleCodes = new Set(visible.map((point) => point.code));
  const visiblePrerequisites = relations.filter(
    (relation) =>
      relation.relation_type === "prerequisite_of"
      && visibleCodes.has(relation.source_code)
      && visibleCodes.has(relation.target_code),
  );
  const selectedDifficulty = selected ? difficultyOf(selected) : null;
  const selectedTopicCode = selected
    ? selected.features.node_type === "topic"
      ? selected.code
      : topics.find((topic) => topic.id === selected.parent_id)?.code ?? null
    : null;
  const selectedBreadcrumb = selected
    ? selected.path.filter((item) => item.code !== selected.code).map((item) => item.title).join(" › ")
    : "";
  const selectedDefinition = selected
    ? String(selected.definition ?? selected.features.description ?? "").trim()
    : "";
  const showSelectedDefinition = Boolean(
    selectedDefinition && selectedDefinition !== selected?.title.trim(),
  );

  useEffect(() => {
    if (!selectedTopicCode) return;
    setExpandedTopics((current) => {
      if (current.has(selectedTopicCode)) return current;
      return new Set([...current, selectedTopicCode]);
    });
  }, [selectedTopicCode]);

  const heading = view === "workspace"
    ? {
        title: "科目资料与版本工作区",
        description: "资料先进入隔离工作区，按核心或补充知识库组织；只有审核后发布的版本参与 RAG。",
      }
    : view === "graph"
      ? {
          title: "知识图谱生产与发布",
          description: "从已发布知识库 AI 抽取实体与关系，在图上校订，审核后发布为检索上下文。",
        }
      : {
          title: "从 Unit 下钻到可考查目标",
          description: "Unit → 章节 → syllabus 学习目标；同时展示先修、顺序、难度方法与证据等级。",
        };

  return (
    <section className="knowledge-page">
      <div className="page-heading compact knowledge-heading">
        <div>
          <h1>{heading.title}</h1>
          <p>{heading.description}</p>
        </div>
        <div className="knowledge-heading-actions">
          <div className="view-switch">
            <button className={view === "workspace" ? "active" : ""} onClick={() => setView("workspace")} type="button"><FolderOpen size={15} />资料工作区</button>
            <button className={view === "graph" ? "active" : ""} onClick={() => setView("graph")} type="button"><GitBranch size={15} />图谱生产</button>
            <button className={view === "catalog" ? "active" : ""} onClick={() => setView("catalog")} type="button"><Network size={15} />层级浏览</button>
          </div>
        </div>
      </div>
      {view === "workspace" ? <WorkspaceView subject={subject} refresh={refresh} /> : view === "graph" ? <GraphWorkbench subject={subject} refresh={refresh} /> : (
      <>
      <div className="unit-tabs">
        {units.map((item) => (
          <button
            className={unit === item ? "active" : ""}
            onClick={() => {
              setUnit(item);
              setSelectedCode(null);
              setExpandedTopics(new Set());
            }}
            key={item}
          >
            {item}
          </button>
        ))}
      </div>
      <div className="knowledge-metrics">
        <span><b>{topics.length}</b> 章节</span>
        <span><b>{objectives.length}</b> 学习目标</span>
        <span><b>{visiblePrerequisites.length}</b> 先修关系</span>
      </div>
      <div className="knowledge-layout">
        <article className="panel knowledge-tree">
          {topics.map((topic) => {
            const children = objectives.filter((item) => item.parent_id === topic.id);
            return (
              <details
                className={selected?.code === topic.code ? "active" : ""}
                key={topic.id}
                onToggle={(event) => {
                  const open = event.currentTarget.open;
                  setExpandedTopics((current) => {
                    if (current.has(topic.code) === open) return current;
                    const next = new Set(current);
                    if (open) next.add(topic.code);
                    else next.delete(topic.code);
                    return next;
                  });
                }}
                open={expandedTopics.has(topic.code)}
              >
                <summary onClick={() => setSelectedCode(topic.code)}>
                  <span><code>{topic.code}</code><strong><InlineMarkdown>{topic.title}</InlineMarkdown></strong></span>
                  <em>{children.length} 项</em>
                </summary>
                <div>
                  {children.map((child) => (
                    <button
                      className={selected?.code === child.code ? "active" : ""}
                      key={child.id}
                      onClick={() => setSelectedCode(child.code)}
                    >
                      <code>{child.code}</code>
                      <span><InlineMarkdown>{child.title}</InlineMarkdown></span>
                      <b>{child.difficulty_score.toFixed(2)}</b>
                    </button>
                  ))}
                </div>
              </details>
            );
          })}
        </article>
        <article className="panel knowledge-detail">
          {!selected ? <div className="empty"><Network size={34} /><p>请选择知识节点</p></div> : (
            <>
              <div className="knowledge-detail-head">
                <div><code>{selected.code}</code><h2><InlineMarkdown>{selected.title}</InlineMarkdown></h2></div>
                <span className={`level level-${selected.evidence_level.toLowerCase()}`}>
                  {selected.evidence_level} 级证据
                </span>
              </div>
              {selectedBreadcrumb && (
                <p className="knowledge-breadcrumb">
                  <InlineMarkdown>{selectedBreadcrumb}</InlineMarkdown>
                </p>
              )}
              {showSelectedDefinition && (
                <p className="knowledge-definition">
                  <InlineMarkdown>{selectedDefinition}</InlineMarkdown>
                </p>
              )}
              <div className="difficulty-card">
                <div><span>正则化难度</span><strong>{selectedDifficulty?.score.toFixed(2)}</strong></div>
                <div className="difficulty"><span><i style={{ width: `${(selectedDifficulty?.score ?? 0) * 100}%` }} /></span></div>
                <small>
                  {selectedDifficulty?.label} · {selectedDifficulty?.evidence_level} 级证据 ·
                  置信度 {Math.round((selectedDifficulty?.confidence ?? 0) * 100)}%
                </small>
                <p>{selectedDifficulty?.rationale}</p>
              </div>
              <dl className="knowledge-meta">
                <div><dt>层级</dt><dd>{String(selected.features.node_type ?? "topic")}</dd></div>
                <div><dt>分支</dt><dd>{selected.strand}</dd></div>
                <div><dt>大纲页</dt><dd>{String(selected.features.syllabus_page ?? "—")}</dd></div>
                <div><dt>难度方法</dt><dd>{selectedDifficulty?.method}</dd></div>
              </dl>
              <h3>直接关系</h3>
              <div className="relation-list">
                {selectedRelations.length === 0 && <p>当前没有直接关系。</p>}
                {selectedRelations.map((relation) => {
                  const outgoing = relation.source_code === selected.code;
                  return (
                    <button
                      key={relation.id}
                      onClick={() => setSelectedCode(
                        outgoing ? relation.target_code : relation.source_code,
                      )}
                    >
                      <span>{relationLabels[relation.relation_type] ?? relation.relation_type}</span>
                      <b>{outgoing ? "→" : "←"}</b>
                      <strong>
                        <InlineMarkdown>
                          {outgoing ? relation.target_title : relation.source_title}
                        </InlineMarkdown>
                      </strong>
                      <small>{Math.round(relation.confidence * 100)}%</small>
                    </button>
                  );
                })}
              </div>
              <div className="source-ref">来源：{selected.source_ref}</div>
            </>
          )}
        </article>
      </div>
      </>
      )}
    </section>
  );
}

const CORE_SOURCE_TYPES = ["syllabus", "textbook"];
const SUPPLEMENTARY_SOURCE_TYPES = ["textbook", "slide", "revision_note", "topic_practice"];

function WorkspaceView({
  subject,
  refresh,
}: {
  subject: SubjectPack;
  refresh: () => Promise<void>;
}) {
  const [documents, setDocuments] = useState<SourceDocument[]>([]);
  const [selectedBaseId, setSelectedBaseId] = useState(
    subject.knowledge_bases[0]?.id ?? "",
  );
  const [sourceType, setSourceType] = useState("syllabus");
  const [licenseConfirmed, setLicenseConfirmed] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [busy, setBusy] = useState<"load" | "upload" | "build" | null>("load");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState<string | null>(null);
  const selectedBase =
    subject.knowledge_bases.find((base) => base.id === selectedBaseId)
    ?? subject.knowledge_bases[0]
    ?? null;
  const availableTypes = selectedBase?.kind === "core"
    ? CORE_SOURCE_TYPES
    : SUPPLEMENTARY_SOURCE_TYPES;
  const selectedDocuments = useMemo(
    () => documents.filter((document) => document.knowledge_base_id === selectedBase?.id),
    [documents, selectedBase?.id],
  );

  const loadDocuments = useCallback(async () => {
    setBusy("load");
    try {
      const rows = await unwrapApi(
        apiClient.GET("/api/v1/subject-workspaces/{workspace_id}/documents", {
          params: { path: { workspace_id: subject.id } },
        }),
      );
      setDocuments(rows);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "工作区资料加载失败");
    } finally {
      setBusy(null);
    }
  }, [subject.id]);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  function selectBase(baseId: string) {
    const base = subject.knowledge_bases.find((item) => item.id === baseId);
    setSelectedBaseId(baseId);
    setSourceType(base?.kind === "core" ? "syllabus" : "textbook");
    setLicenseConfirmed(false);
    setFile(null);
    setFileInputKey((value) => value + 1);
    setNotice("");
    setError(null);
  }

  async function uploadDocument() {
    if (!file || !selectedBase) return;
    if (sourceType === "textbook" && !licenseConfirmed) {
      setError("教材进入知识库前必须确认已获得使用授权。");
      return;
    }
    setBusy("upload");
    setNotice("");
    setError(null);
    try {
      const uploaded = await uploadWorkspaceDocument(
        subject.id,
        file,
        sourceType,
        {
          knowledgeBaseId: selectedBase.id,
          licenseConfirmed,
        },
      );
      await unwrapApi(
        apiClient.POST("/api/v1/corpus/convert", {
          body: {
            document_ids: [uploaded.id],
            source_types: [],
            authority_tiers: [],
            limit: null,
            workers: 2,
            force: false,
          },
        }),
      );
      setNotice(`${file.name} 已进入${selectedBase.name}并完成转换。`);
      setFile(null);
      setFileInputKey((value) => value + 1);
      await Promise.all([loadDocuments(), refresh()]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "资料上传或转换失败");
    } finally {
      setBusy(null);
    }
  }

  async function buildVersion() {
    if (!selectedBase) return;
    setBusy("build");
    setNotice("");
    setError(null);
    try {
      const result = await unwrapApi(
        apiClient.POST("/api/v1/knowledge-bases/{knowledge_base_id}/build", {
          params: { path: { knowledge_base_id: selectedBase.id } },
        }),
      );
      setNotice(`${selectedBase.name} v${result.version.version_number} 已构建并发布。`);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "知识库版本构建失败");
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <div className="workspace-grid" aria-label="知识库工作区">
        {subject.knowledge_bases.map((base) => {
          const count = documents.filter((document) => document.knowledge_base_id === base.id).length;
          const active = base.id === selectedBase?.id;
          return (
            <button
              aria-pressed={active}
              className={`workspace-card ${active ? "active" : ""}`}
              key={base.id}
              onClick={() => selectBase(base.id)}
              type="button"
            >
              <span className="workspace-icon">
                {base.kind === "core" ? <BookOpen size={20} /> : <FolderOpen size={20} />}
              </span>
              <div>
                <small>{base.kind === "core" ? "受控核心知识" : "可选补充材料"}</small>
                <strong>{base.name}</strong>
                <p>{base.kind === "core" ? "课程大纲 + 已授权教材" : "教材、课件、复习笔记与专题练习"}</p>
              </div>
              <dl>
                <div><dt>资料</dt><dd>{count}</dd></div>
                <div><dt>当前版本</dt><dd>{base.active_version_number ? `v${base.active_version_number}` : "未发布"}</dd></div>
                <div><dt>向量点</dt><dd>{base.vector_points}</dd></div>
              </dl>
            </button>
          );
        })}
      </div>

      <ErrorBanner message={error} />
      {notice && <div className="notice">{notice}</div>}
      {selectedBase ? (
        <div className="workspace-detail-grid">
          <article className="panel workspace-upload-panel">
            <div className="panel-title">
              <div>
                <span className="kicker">当前工作区</span>
                <h2>{selectedBase.name}</h2>
              </div>
              <button
                className="secondary"
                disabled={busy !== null}
                onClick={() => void loadDocuments()}
                type="button"
              >
                <RefreshCw className={busy === "load" ? "spin" : ""} size={16} />
                刷新
              </button>
            </div>
            <div className="workspace-policy">
              <CheckCircle2 size={18} />
              <p>
                {selectedBase.kind === "core"
                  ? "只接受课程大纲和已确认授权的教材。试卷、Mark Scheme、Insert 与考官报告不能进入 RAG 知识库。"
                  : "补充材料默认不参与检索；发布补充版本后，仍需在作答时显式选择。"}
              </p>
            </div>
            <div className="workspace-upload-form">
              <label>
                资料类型
                <select value={sourceType} onChange={(event) => {
                  setSourceType(event.target.value);
                  setLicenseConfirmed(false);
                }}>
                  {availableTypes.map((type) => (
                    <option key={type} value={type}>{sourceLabels[type] ?? type}</option>
                  ))}
                </select>
              </label>
              <label>
                文件
                <input
                  accept=".pdf,.ppt,.pptx,.doc,.docx,.md,.txt"
                  key={fileInputKey}
                  onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                  type="file"
                />
              </label>
              {sourceType === "textbook" && (
                <label className="license-confirmation">
                  <input
                    checked={licenseConfirmed}
                    onChange={(event) => setLicenseConfirmed(event.target.checked)}
                    type="checkbox"
                  />
                  我确认该教材已获得当前项目使用授权
                </label>
              )}
              <button
                className="primary"
                disabled={!file || busy !== null || (sourceType === "textbook" && !licenseConfirmed)}
                onClick={() => void uploadDocument()}
                type="button"
              >
                {busy === "upload" ? <LoaderCircle className="spin" size={16} /> : <UploadCloud size={16} />}
                上传并转换
              </button>
            </div>
          </article>

          <article className="panel workspace-documents">
            <div className="panel-title">
              <div>
                <span className="kicker">版本输入</span>
                <h2>{selectedDocuments.length} 份资料</h2>
              </div>
              <button
                className="primary"
                disabled={!selectedDocuments.length || busy !== null}
                onClick={() => void buildVersion()}
                type="button"
              >
                {busy === "build" ? <LoaderCircle className="spin" size={16} /> : <Sparkles size={16} />}
                构建并发布新版本
              </button>
            </div>
            <div className="workspace-document-list">
              {selectedDocuments.map((document) => (
                <div key={document.id}>
                  <FileText size={17} />
                  <span>
                    <strong>{document.filename}</strong>
                    <small>{sourceLabels[document.source_type] ?? document.source_type} · {document.page_count ?? "—"} 页</small>
                  </span>
                  <em className={document.status}>{document.status}</em>
                </div>
              ))}
              {!selectedDocuments.length && (
                <div className="empty compact-empty">
                  <FolderOpen size={30} />
                  <p>这个工作区还没有资料。上传后先转换，再构建不可变版本。</p>
                </div>
              )}
            </div>
          </article>
        </div>
      ) : (
        <article className="panel empty"><FolderOpen size={34} /><p>当前科目还没有知识库工作区。</p></article>
      )}
    </>
  );
}

function GraphWorkbench({
  subject,
  refresh,
}: {
  subject: SubjectPack;
  refresh: () => Promise<void>;
}) {
  const [versions, setVersions] = useState<GraphVersionSummary[]>([]);
  const [graph, setGraph] = useState<GraphVersion | null>(null);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [versionId, setVersionId] = useState(subject.active_graph_version_id ?? "");
  const [baseVersionId, setBaseVersionId] = useState(
    subject.knowledge_bases.find((base) => base.active_version_id)?.active_version_id ?? "",
  );
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [aliases, setAliases] = useState("");
  const [relationType, setRelationType] = useState("related_to");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const fullscreenRef = useModalFocus(fullscreen, setFullscreen);
  const graphRequestRef = useRef(0);
  const versionIdRef = useRef(versionId);
  const selectedNode = graph?.nodes.find((node) => node.id === selectedNodeId) ?? null;
  const selectedEdge = graph?.edges.find((edge) => edge.id === selectedEdgeId) ?? null;

  const fetchGraph = useCallback(async (
    nextVersionId: string,
    selection?: { nodeId: string | null; edgeId: string | null },
  ) => {
    const requestId = ++graphRequestRef.current;
    if (!nextVersionId) {
      setGraph(null);
      setSelectedNodeId(null);
      setSelectedEdgeId(null);
      return;
    }
    if (!selection) {
      setGraph(null);
      setSelectedNodeId(null);
      setSelectedEdgeId(null);
    }
    let detail: GraphVersion;
    try {
      detail = await unwrapApi(
        apiClient.GET("/api/v1/knowledge-graphs/{version_id}", {
          params: { path: { version_id: nextVersionId } },
        }),
      );
    } catch (cause) {
      if (requestId !== graphRequestRef.current) return;
      throw cause;
    }
    if (
      requestId !== graphRequestRef.current
      || nextVersionId !== versionIdRef.current
    ) return;
    const edgeId =
      selection?.edgeId && detail.edges.some((edge) => edge.id === selection.edgeId)
        ? selection.edgeId
        : null;
    const nodeId =
      selection?.nodeId && detail.nodes.some((node) => node.id === selection.nodeId)
        ? selection.nodeId
        : edgeId
          ? null
          : detail.nodes[0]?.id ?? null;
    setGraph(detail);
    setSelectedNodeId(nodeId);
    setSelectedEdgeId(edgeId);
  }, []);

  const loadVersions = useCallback(async (preferred?: string) => {
    const rows = await unwrapApi(apiClient.GET("/api/v1/knowledge-graphs"));
    setVersions(rows);
    setVersionId((current) => {
      const candidate = preferred || current || rows[0]?.id || "";
      const next = rows.some((row) => row.id === candidate) ? candidate : rows[0]?.id ?? "";
      versionIdRef.current = next;
      return next;
    });
  }, []);

  useEffect(() => {
    void loadVersions().catch((cause: unknown) => {
      setError(cause instanceof Error ? cause.message : "知识图谱版本加载失败");
    });
  }, [loadVersions]);

  useEffect(() => {
    void fetchGraph(versionId).catch((cause: unknown) => {
      setError(cause instanceof Error ? cause.message : "知识图谱版本加载失败");
    });
  }, [fetchGraph, versionId]);

  useEffect(() => {
    if (!selectedNode) return;
    setTitle(selectedNode.title);
    setDescription(selectedNode.description);
    setAliases(selectedNode.aliases.join("，"));
  }, [selectedNode]);

  useEffect(() => {
    if (selectedEdge) setRelationType(selectedEdge.relation_type);
  }, [selectedEdge]);

  async function buildGraph() {
    if (!baseVersionId) return;
    setBusy("build");
    setError(null);
    try {
      const created = await unwrapApi(
        apiClient.POST("/api/v1/knowledge-graphs/build", {
          body: { knowledge_base_version_id: baseVersionId },
        }),
      );
      await loadVersions(created.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "AI 图谱生成失败");
    } finally {
      setBusy(null);
    }
  }

  async function saveNode(reviewStatus: "accepted" | "rejected" = "accepted") {
    if (!graph || !selectedNode) return;
    setBusy("node");
    setError(null);
    try {
      await unwrapApi(
        apiClient.PATCH("/api/v1/knowledge-graphs/{version_id}/nodes/{node_id}", {
          params: { path: { version_id: graph.id, node_id: selectedNode.id } },
          body: {
            aliases: aliases.split(/[，,]/).map((item) => item.trim()).filter(Boolean),
            description,
            node_type: selectedNode.node_type as "concept" | "subconcept" | "formula" | "term",
            parent_key: selectedNode.parent_key,
            review_status: reviewStatus,
            title,
          },
        }),
      );
      if (versionIdRef.current === graph.id) {
        await fetchGraph(graph.id, { nodeId: selectedNode.id, edgeId: null });
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "节点保存失败");
    } finally {
      setBusy(null);
    }
  }

  async function saveEdge(reviewStatus: "accepted" | "rejected" = "accepted") {
    if (!graph || !selectedEdge) return;
    setBusy("edge");
    setError(null);
    try {
      await unwrapApi(
        apiClient.PATCH("/api/v1/knowledge-graphs/{version_id}/edges/{edge_id}", {
          params: { path: { version_id: graph.id, edge_id: selectedEdge.id } },
          body: {
            relation_type: relationType as "contains" | "prerequisite_of" | "applies_to" | "equivalent_to" | "related_to",
            review_status: reviewStatus,
          },
        }),
      );
      if (versionIdRef.current === graph.id) {
        await fetchGraph(graph.id, { nodeId: null, edgeId: selectedEdge.id });
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "关系保存失败");
    } finally {
      setBusy(null);
    }
  }

  async function reviewAll() {
    if (!graph) return;
    setBusy("review");
    setError(null);
    try {
      const updated = await unwrapApi(
        apiClient.POST("/api/v1/knowledge-graphs/{version_id}/review-all", {
          params: { path: { version_id: graph.id } },
          body: { review_status: "accepted" },
        }),
      );
      setGraph(updated);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "批量审核失败");
    } finally {
      setBusy(null);
    }
  }

  async function publishGraph() {
    if (!graph) return;
    setBusy("publish");
    setError(null);
    try {
      const published = await unwrapApi(
        apiClient.POST("/api/v1/knowledge-graphs/{version_id}/publish", {
          params: { path: { version_id: graph.id } },
        }),
      );
      setGraph(published);
      await loadVersions(published.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "知识图谱发布失败");
    } finally {
      setBusy(null);
    }
  }

  async function deleteGraph() {
    if (!graph) return;
    setBusy("delete");
    setError(null);
    try {
      const deleted = await apiClient.DELETE("/api/v1/knowledge-graphs/{version_id}", {
        params: { path: { version_id: graph.id } },
      });
      if (!deleted.response.ok) {
        const detail = deleted.error && typeof deleted.error === "object" && "detail" in deleted.error
          ? String(deleted.error.detail)
          : deleted.response.statusText;
        throw new Error(detail || "知识图谱版本删除失败");
      }
      graphRequestRef.current += 1;
      setFullscreen(false);
      setGraph(null);
      setDeleteConfirmOpen(false);
      setSelectedNodeId(null);
      setSelectedEdgeId(null);
      await loadVersions();
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "知识图谱版本删除失败");
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <article className="panel graph-toolbar">
        <label>
          来源知识库版本
          <select value={baseVersionId} onChange={(event) => setBaseVersionId(event.target.value)}>
            <option value="">暂无已发布知识库版本</option>
            {subject.knowledge_bases.filter((base) => base.active_version_id).map((base) => (
              <option key={base.id} value={base.active_version_id ?? ""}>{base.name} · v{base.active_version_number ?? "—"}</option>
            ))}
          </select>
        </label>
        <button className="primary" disabled={!baseVersionId || busy !== null} onClick={() => void buildGraph()} type="button">
          {busy === "build" ? <LoaderCircle className="spin" size={16} /> : <Sparkles size={16} />}
          AI 生成新版本
        </button>
        <div className="graph-version-picker">
          <span>图谱版本</span>
          <div aria-label="图谱版本列表" className="graph-version-list" role="list">
            {versions.length === 0 ? <small>尚无图谱版本</small> : versions.map((item) => {
              const active = item.id === subject.active_graph_version_id;
              return (
                <button
                  aria-label={`选择图谱 v${item.version_number} · ${item.status}${active ? " · 当前使用" : ""}`}
                  className={item.id === versionId ? "selected" : ""}
                  disabled={busy !== null}
                  key={item.id}
                  onClick={() => {
                    versionIdRef.current = item.id;
                    setVersionId(item.id);
                  }}
                  type="button"
                >
                  <b>v{item.version_number}</b>
                  <span>{item.status}</span>
                  {active && <small>当前使用</small>}
                </button>
              );
            })}
          </div>
        </div>
        {graph?.status === "draft" && <button className="secondary" disabled={busy !== null} onClick={() => void reviewAll()} type="button"><CheckCircle2 size={16} />接受全部</button>}
        {graph?.status === "draft" && <button className="primary" disabled={busy !== null} onClick={() => void publishGraph()} type="button"><UploadCloud size={16} />发布图谱</button>}
        {graph && <button className="secondary danger" disabled={busy !== null} onClick={() => setDeleteConfirmOpen(true)} type="button"><Trash2 size={16} />删除当前图谱</button>}
        {graph?.status === "published" && <span className="graph-published"><CheckCircle2 size={15} />已发布并参与检索</span>}
      </article>
      <ErrorBanner message={error} />
      {!graph ? (
        <article className="panel empty"><Network size={36} /><p>选择已发布知识库版本，由 AI 生成第一版图谱。</p></article>
      ) : (
        <div className="graph-editor-layout">
          <article
            aria-label={fullscreen ? "图谱全屏预览" : undefined}
            aria-modal={fullscreen || undefined}
            className={`panel graph-canvas${fullscreen ? " is-fullscreen" : ""}`}
            ref={fullscreenRef}
            role={fullscreen ? "dialog" : undefined}
            tabIndex={-1}
          >
            <div className="graph-canvas-header">
              <div className="graph-canvas-meta">
                <span><b>{graph.nodes.length}</b> 节点</span>
                <span><b>{graph.edges.length}</b> 关系</span>
                <span><b>{graph.nodes.filter((node) => node.review_status === "pending").length}</b> 待审核</span>
              </div>
              <div className="graph-legend" aria-label="节点类型图例">
                <span className="type-concept">概念</span>
                <span className="type-formula">公式</span>
                <span className="type-skill">技能 / 方法</span>
              </div>
              <button
                aria-label={fullscreen ? "退出图谱全屏" : "全屏预览图谱"}
                className="graph-fullscreen-button"
                data-modal-close={fullscreen ? "" : undefined}
                onClick={() => setFullscreen((current) => !current)}
                title={fullscreen ? "退出全屏" : "全屏预览"}
                type="button"
              >
                {fullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
                {fullscreen ? "退出全屏" : "全屏"}
              </button>
            </div>
            <KnowledgeGraphCanvas
              key={graph.id}
              edges={graph.edges}
              nodes={graph.nodes}
              onSelectEdge={(id) => {
                setSelectedEdgeId(id);
                setSelectedNodeId(null);
              }}
              onSelectNode={(id) => {
                setSelectedNodeId(id);
                setSelectedEdgeId(null);
              }}
              selectedEdgeId={selectedEdgeId}
              selectedNodeId={selectedNodeId}
            />
            <small>滚轮平移画布，双指或控制按钮缩放；悬浮节点查看详情，点击后在右侧校订。</small>
          </article>
          <aside className="panel graph-inspector">
            {selectedNode ? (
              <>
                <span>节点编辑 · {selectedNode.review_status}</span>
                <div className="graph-inspector-preview">
                  <code>{selectedNode.code}</code>
                  <h3><InlineMarkdown>{selectedNode.title}</InlineMarkdown></h3>
                  <GraphNodeFormula node={selectedNode} />
                  {selectedNode.description && <div><InlineMarkdown>{selectedNode.description}</InlineMarkdown></div>}
                </div>
                <label>标题<input value={title} onChange={(event) => setTitle(event.target.value)} /></label>
                <label>定义<textarea rows={5} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
                <label>别名<input value={aliases} onChange={(event) => setAliases(event.target.value)} /></label>
                <div className="graph-evidence"><strong>来源证据</strong>{selectedNode.evidence.map((item, index) => <div className="graph-evidence-item" key={`${item.block_id}-${index}`}><InlineMarkdown>{item.quote}</InlineMarkdown><small>{item.document_id} · p.{item.page ?? "—"}</small></div>)}</div>
                {graph.status === "draft" && <div className="graph-edit-actions"><button className="primary" disabled={busy !== null} onClick={() => void saveNode()} type="button"><Save size={15} />保存并接受</button><button className="danger" disabled={busy !== null} onClick={() => void saveNode("rejected")} type="button">拒绝</button></div>}
              </>
            ) : selectedEdge ? (
              <>
                <span>关系编辑 · {selectedEdge.review_status}</span>
                <strong>{selectedEdge.source_key} → {selectedEdge.target_key}</strong>
                <label>关系类型<select value={relationType} onChange={(event) => setRelationType(event.target.value)}><option value="contains">contains</option><option value="prerequisite_of">prerequisite_of</option><option value="applies_to">applies_to</option><option value="equivalent_to">equivalent_to</option><option value="related_to">related_to</option></select></label>
                <div className="graph-evidence"><strong>来源证据</strong>{selectedEdge.evidence.map((item, index) => <div className="graph-evidence-item" key={`${item.block_id}-${index}`}><InlineMarkdown>{item.quote}</InlineMarkdown><small>{item.document_id} · p.{item.page ?? "—"}</small></div>)}</div>
                {graph.status === "draft" && <div className="graph-edit-actions"><button className="primary" disabled={busy !== null} onClick={() => void saveEdge()} type="button"><Save size={15} />保存并接受</button><button className="danger" disabled={busy !== null} onClick={() => void saveEdge("rejected")} type="button">拒绝</button></div>}
              </>
            ) : <div className="empty compact-empty"><Network size={30} /><p>选择节点或连线进行校订</p></div>}
          </aside>
        </div>
      )}
      <AppConfirmDialog
        busy={busy === "delete"}
        confirmLabel="永久删除图谱"
        danger
        description={graph
          ? `将永久删除图谱 v${graph.version_number} 的全部节点与关系。此操作不可恢复。`
          : ""}
        onConfirm={deleteGraph}
        onOpenChange={setDeleteConfirmOpen}
        open={deleteConfirmOpen}
        title="确认删除图谱"
      />
    </>
  );
}
