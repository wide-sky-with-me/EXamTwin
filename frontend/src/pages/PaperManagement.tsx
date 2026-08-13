import {
  Button,
  Card,
  Checkbox,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Flex,
  Form,
  Input,
  Modal,
  Row,
  Select,
  Skeleton,
  Space,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from "antd";
import {
  ArrowLeft,
  BookOpenCheck,
  ClipboardList,
  Download,
  Eye,
  FileText,
  ChevronRight,
  Layers3,
  Pencil,
  Play,
  Plus,
  ShieldCheck,
  Trash2,
  UploadCloud,
} from "lucide-react";
import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { ErrorBanner } from "../components/Feedback";
import { PaperJobHistory } from "../components/PaperJobHistory";
import { useToast } from "../components/toast-context";
import { AppConfirmDialog } from "../components/ui/AppConfirmDialog";
import { ListPagination } from "../components/ui/ListControls";
import {
  answerPaperUnit,
  apiClient,
  archivePaperUnit,
  backendResourceUrl,
  createPaperUnit,
  importPaperUnitAnswer,
  listPaperUnits,
  subjectHeaders,
  unwrapApi,
  updatePaperUnit,
  uploadWorkspaceDocument,
} from "../lib/api";
import type {
  PaperJobResult,
  PaperUnitDocument,
  PaperUnitList,
  PaperUnitSummary,
  SourceDocument,
  SubjectStatus,
} from "../types";

const { Text, Title } = Typography;
const PAGE_SIZE = 12;
const EMPTY_LIST: PaperUnitList = {
  items: [],
  total: 0,
  limit: PAGE_SIZE,
  offset: 0,
  available_units: [],
  available_years: [],
  available_sessions: [],
};

type Detail =
  | { kind: "paper"; id: string }
  | { kind: "document"; id: string; parentPaperId?: string }
  | { kind: "job"; id: string }
  | null;

type PaperManagementProps = {
  subjects: SubjectStatus[];
  subjectId?: string;
  detail?: Detail;
  onSubjectChange?: (subjectId: string) => void;
  onOpenPaper?: (subjectId: string, paperUnitId: string) => void;
  onOpenDocument?: (subjectId: string, documentId: string, paperUnitId?: string) => void;
  onBackDocument?: (subjectId: string, paperUnitId?: string) => void;
  onOpenJob?: (subjectId: string, paperUnitId: string, jobId: string) => void;
  onCloseDetail?: (subjectId: string) => void;
  onStartAnswering?: (subjectId: string, paperUnitId: string, jobId: string) => void;
  onStartGrading?: (subjectId: string, paperUnitId: string) => void;
  onOpenAnswerCatalog?: (subjectId: string) => void;
};

type BindingDraft = {
  displayName: string;
  questionPaperId: string;
  markSchemeId: string;
  sourceBookletId: string;
};

const EMPTY_DRAFT: BindingDraft = {
  displayName: "",
  questionPaperId: "",
  markSchemeId: "",
  sourceBookletId: "",
};

function documentLabel(document: Pick<SourceDocument | PaperUnitDocument, "display_name" | "filename">) {
  return document.display_name || document.filename;
}

function paperDisplayName(paper: PaperUnitSummary) {
  const questionPaper = paper.documents.find((item) => item.role === "question_paper");
  return paper.display_name
    || questionPaper?.display_name
    || questionPaper?.filename.replace(/\.pdf$/i, "")
    || paper.pair_key;
}

function sessionLabel(session: string) {
  return { JAN: "一月", MAR: "三月", JUN: "六月", NOV: "十一月" }[session] ?? session;
}

function documentTypeLabel(sourceType: string) {
  return {
    question_paper: "Question Paper",
    mark_scheme: "Mark Scheme",
    insert: "Source Booklet",
    source_booklet: "Source Booklet",
  }[sourceType] ?? sourceType;
}

function documentStatusLabel(status: string) {
  return {
    converted: "已解析",
    discovered: "待解析",
    converting: "解析中",
    failed: "解析失败",
  }[status] ?? status;
}

function PaperDocumentRow({
  document,
  onOpen,
}: {
  document: PaperUnitDocument;
  onOpen: () => void;
}) {
  const labels = {
    question_paper: "Question Paper",
    mark_scheme: "Mark Scheme",
    source_booklet: "Source Booklet",
  } as const;
  const icons = {
    question_paper: FileText,
    mark_scheme: ShieldCheck,
    source_booklet: Layers3,
  } as const;
  const Icon = icons[document.role];
  return (
    <button className="paper-binding-row" onClick={onOpen} type="button">
      <Icon size={18} />
      <span>
        <strong>{labels[document.role]}</strong>
        <Tooltip placement="bottomLeft" title={documentLabel(document)}><small>{documentLabel(document)}</small></Tooltip>
      </span>
      <em>{document.page_count ? `${document.page_count} 页` : document.status}</em>
      <ChevronRight size={16} />
    </button>
  );
}

export function PaperManagement({
  subjects,
  subjectId: controlledSubjectId,
  detail = null,
  onSubjectChange,
  onOpenPaper,
  onOpenDocument,
  onBackDocument,
  onOpenJob,
  onCloseDetail,
  onStartAnswering,
  onStartGrading,
  onOpenAnswerCatalog,
}: PaperManagementProps) {
  const [localSubjectId, setLocalSubjectId] = useState(controlledSubjectId ?? subjects[0]?.id ?? "");
  const subjectId = controlledSubjectId ?? localSubjectId;
  const subject = subjects.find((item) => item.id === subjectId) ?? null;
  const [papers, setPapers] = useState<PaperUnitList>(EMPTY_LIST);
  const [documents, setDocuments] = useState<SourceDocument[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [unitCode, setUnitCode] = useState("");
  const [examYear, setExamYear] = useState("");
  const [examSession, setExamSession] = useState("");
  const [page, setPage] = useState(0);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<PaperUnitSummary | null>(null);
  const [draft, setDraft] = useState<BindingDraft>(EMPTY_DRAFT);
  const [files, setFiles] = useState<Record<string, File | null>>({
    question_paper: null,
    mark_scheme: null,
    insert: null,
  });
  const [uploadingRoles, setUploadingRoles] = useState<Record<string, boolean>>({
    question_paper: true,
    mark_scheme: true,
    insert: true,
  });
  const [licenseConfirmed, setLicenseConfirmed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deletingCandidate, setDeletingCandidate] = useState<PaperUnitSummary | null>(null);
  const [starting, setStarting] = useState(false);
  const [answerHistoryVersion, setAnswerHistoryVersion] = useState(0);
  const [externalImportOpen, setExternalImportOpen] = useState(false);
  const [externalAnswerFile, setExternalAnswerFile] = useState<File | null>(null);
  const [importingAnswer, setImportingAnswer] = useState(false);
  const [convertingDocumentId, setConvertingDocumentId] = useState<string | null>(null);
  const [job, setJob] = useState<PaperJobResult | null>(null);
  const [detailPaper, setDetailPaper] = useState<PaperUnitSummary | null>(null);
  const { notify } = useToast();

  useEffect(() => {
    if (!subjectId && subjects[0]) setLocalSubjectId(subjects[0].id);
  }, [subjectId, subjects]);

  const loadDocuments = useCallback(async () => {
    if (!subjectId) return;
    const rows = await unwrapApi(
      apiClient.GET("/api/v1/subject-workspaces/{workspace_id}/documents", {
        headers: subjectHeaders(subjectId),
        params: { path: { workspace_id: subjectId } },
      }),
    );
    setDocuments(rows);
  }, [subjectId]);

  const loadPapers = useCallback(async () => {
    if (!subjectId) {
      setPapers(EMPTY_LIST);
      return;
    }
    setLoading(true);
    try {
      const next = await listPaperUnits(subjectId, {
        query: query.trim() || undefined,
        unitCode: unitCode || undefined,
        examYear: examYear ? Number(examYear) : undefined,
        examSession: examSession || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      });
      setPapers(next);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "试卷列表加载失败");
    } finally {
      setLoading(false);
    }
  }, [examSession, examYear, page, query, subjectId, unitCode]);

  useEffect(() => {
    setPage(0);
    setQuery("");
    setUnitCode("");
    setExamYear("");
    setExamSession("");
    void loadDocuments().catch((cause: unknown) => {
      setError(cause instanceof Error ? cause.message : "试卷资料加载失败");
    });
  }, [loadDocuments, subjectId]);

  useEffect(() => {
    if (!convertingDocumentId) return;
    const timer = window.setInterval(() => {
      void loadDocuments().catch(() => undefined);
    }, 900);
    return () => window.clearInterval(timer);
  }, [convertingDocumentId, loadDocuments]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadPapers(), 180);
    return () => window.clearTimeout(timer);
  }, [loadPapers]);

  useEffect(() => {
    if (detail?.kind !== "paper" || !subjectId) {
      setDetailPaper(null);
      return;
    }
    const listed = papers.items.find((item) => item.id === detail.id);
    if (listed) {
      setDetailPaper(listed);
      return;
    }
    let current = true;
    void unwrapApi(apiClient.GET(
      "/api/v1/subject-workspaces/{workspace_id}/paper-units/{paper_unit_id}",
      {
        headers: subjectHeaders(subjectId),
        params: { path: { workspace_id: subjectId, paper_unit_id: detail.id } },
      },
    )).then((result) => {
      if (current) setDetailPaper(result);
    }).catch((cause: unknown) => {
      if (current) setError(cause instanceof Error ? cause.message : "试卷详情加载失败");
    });
    return () => { current = false; };
  }, [detail, papers.items, subjectId]);

  useEffect(() => {
    if (detail?.kind !== "job" || !subjectId) {
      setJob(null);
      return;
    }
    let current = true;
    void unwrapApi(apiClient.GET("/api/v1/papers/jobs/{job_id}", {
      headers: subjectHeaders(subjectId),
      params: { path: { job_id: detail.id } },
    })).then((result) => {
      if (current) setJob(result as unknown as PaperJobResult);
    }).catch((cause: unknown) => {
      if (current) setError(cause instanceof Error ? cause.message : "作答记录加载失败");
    });
    return () => { current = false; };
  }, [detail, subjectId]);

  const selectedPaper = detail?.kind === "paper" ? detailPaper : null;
  const selectedDocument = detail?.kind === "document"
    ? documents.find((item) => item.id === detail.id) ?? null
    : null;

  const candidates = useMemo(() => {
    const usable = documents.filter((item) => item.status !== "deleted" && item.identity_status === "complete");
    return {
      question_paper: usable.filter((item) => item.source_type === "question_paper"),
      mark_scheme: usable.filter((item) => item.source_type === "mark_scheme"),
      insert: usable.filter((item) => item.source_type === "insert"),
    };
  }, [documents]);

  function chooseSubject(nextSubjectId: string) {
    if (nextSubjectId === subjectId) return;
    setLocalSubjectId(nextSubjectId);
    onSubjectChange?.(nextSubjectId);
  }

  function openCreate() {
    setEditing(null);
    setDraft(EMPTY_DRAFT);
    setFiles({ question_paper: null, mark_scheme: null, insert: null });
    setUploadingRoles({ question_paper: true, mark_scheme: true, insert: true });
    setLicenseConfirmed(false);
    setEditorOpen(true);
  }

  function openEdit(paper: PaperUnitSummary) {
    setEditing(paper);
    setDraft({
      displayName: paper.display_name ?? paperDisplayName(paper),
      questionPaperId: paper.documents.find((item) => item.role === "question_paper")?.id ?? "",
      markSchemeId: paper.documents.find((item) => item.role === "mark_scheme")?.id ?? "",
      sourceBookletId: paper.documents.find((item) => item.role === "source_booklet")?.id ?? "",
    });
    setFiles({ question_paper: null, mark_scheme: null, insert: null });
    setUploadingRoles({
      question_paper: !paper.documents.some((item) => item.role === "question_paper"),
      mark_scheme: !paper.documents.some((item) => item.role === "mark_scheme"),
      insert: !paper.documents.some((item) => item.role === "source_booklet"),
    });
    setLicenseConfirmed(false);
    setEditorOpen(true);
  }

  async function uploadCandidate(role: "question_paper" | "mark_scheme" | "insert") {
    const file = files[role];
    if (!file || !subjectId) return "";
    const uploaded = await uploadWorkspaceDocument(subjectId, file, role, { licenseConfirmed });
    return uploaded.id;
  }

  async function savePaper(event: FormEvent) {
    event.preventDefault();
    if (!subjectId) return;
    if (Object.values(files).some(Boolean) && !licenseConfirmed) {
      setError("上传文件前请确认你有权使用这些考试资料。");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const uploadedIds = await Promise.all([
        uploadCandidate("question_paper"),
        uploadCandidate("mark_scheme"),
        uploadCandidate("insert"),
      ]);
      const uploadedByRole = {
        question_paper: uploadedIds[0],
        mark_scheme: uploadedIds[1],
        source_booklet: uploadedIds[2],
      };
      const existingIds = editing?.documents
        .filter((document) => !uploadedByRole[document.role])
        .map((document) => document.id) ?? [];
      const documentIds = editing
        ? [...existingIds, ...uploadedIds.filter(Boolean)]
        : [
            uploadedIds[0] || draft.questionPaperId,
            uploadedIds[1] || draft.markSchemeId,
            uploadedIds[2] || draft.sourceBookletId,
          ].filter(Boolean);
      if (!documentIds[0]) throw new Error("必须选择或上传 Question Paper。");
      if (editing) {
        const bindingsChanged = uploadedIds.some(Boolean);
        await updatePaperUnit(
          subjectId,
          editing.id,
          bindingsChanged ? documentIds : null,
          draft.displayName.trim() || null,
        );
        notify(bindingsChanged ? "试卷名称与资料已更新。" : "试卷名称已更新。");
      } else {
        await createPaperUnit(subjectId, documentIds, draft.displayName.trim() || null);
        notify("试卷已加入管理库。");
      }
      setEditorOpen(false);
      await Promise.all([loadDocuments(), loadPapers()]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "试卷保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function confirmDelete() {
    if (!deletingCandidate || !subjectId) return;
    try {
      await archivePaperUnit(subjectId, deletingCandidate.id);
      notify("试卷已从管理列表删除；原始资料与历史记录仍保留。");
      setDeletingCandidate(null);
      onCloseDetail?.(subjectId);
      await loadPapers();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "试卷删除失败");
    }
  }

  async function startAnswering(paper: PaperUnitSummary) {
    const questionPaper = paper.documents.find((item) => item.role === "question_paper");
    const sourceBooklet = paper.documents.find((item) => item.role === "source_booklet");
    if (!questionPaper || !subjectId) return;
    setStarting(true);
    try {
      const created = await answerPaperUnit(subjectId, paper.id, questionPaper.id, sourceBooklet?.id);
      notify("已使用当前试卷及绑定资料创建作答任务。");
      onStartAnswering?.(subjectId, paper.id, created.job_id);
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "作答任务创建失败";
      setError(null);
      notify(
        message,
        message.includes("尚未按当前文件版本完成转换") ? "warning" : "error",
      );
    } finally {
      setStarting(false);
    }
  }

  function openExternalImport() {
    setExternalAnswerFile(null);
    setError(null);
    setExternalImportOpen(true);
  }

  async function importExternalAnswer() {
    if (!selectedPaper || !subjectId || !externalAnswerFile) return;
    const questionPaper = selectedPaper.documents.find((item) => item.role === "question_paper");
    if (!questionPaper) {
      setError("当前试卷缺少 Question Paper，不能导入外部答卷。");
      return;
    }
    setImportingAnswer(true);
    setError(null);
    try {
      const created = await importPaperUnitAnswer(
        subjectId,
        selectedPaper.id,
        questionPaper.id,
        externalAnswerFile,
      );
      setExternalImportOpen(false);
      setAnswerHistoryVersion((value) => value + 1);
      notify("外部答卷已归入当前试卷，后台开始解析。", "success");
      onStartAnswering?.(subjectId, selectedPaper.id, created.job_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "外部答卷导入失败");
    } finally {
      setImportingAnswer(false);
    }
  }

  function openDocument(documentId: string) {
    if (subjectId) onOpenDocument?.(subjectId, documentId, selectedPaper?.id);
  }

  async function convertDocument(document: SourceDocument) {
    if (!subjectId || convertingDocumentId) return;
    setConvertingDocumentId(document.id);
    setError(null);
    try {
      const conversion = await unwrapApi(
        apiClient.POST("/api/v1/corpus/convert", {
          headers: subjectHeaders(subjectId),
          body: {
            authority_tiers: [],
            document_ids: [document.id],
            force: false,
            limit: 1,
            source_types: [document.source_type],
            workers: 1,
          },
        }),
      );
      if (conversion.failed || conversion.succeeded + conversion.skipped !== 1) {
        throw new Error(conversion.errors.filter(Boolean).join("；") || "资料解析未完成，请重试。");
      }
      await loadDocuments();
      notify(conversion.skipped ? "资料已有可用解析结果。" : "资料解析完成。", "success");
    } catch (cause) {
      await loadDocuments().catch(() => undefined);
      notify(cause instanceof Error ? cause.message : "资料解析失败。", "error");
    } finally {
      setConvertingDocumentId(null);
    }
  }

  const detailVisible = Boolean(detail);
  const selectedDocumentUrl = selectedDocument && subjectId
    ? backendResourceUrl(
        `/subject-workspaces/${encodeURIComponent(subjectId)}/documents/${encodeURIComponent(selectedDocument.id)}/content`,
        subjectId,
      )
    : null;
  const selectedDocumentStatus = selectedDocument
    ? convertingDocumentId === selectedDocument.id ? "converting" : selectedDocument.status
    : null;

  return (
    <div className="paper-management-page">
      <Card className="paper-management-toolbar-card" size="small">
        <Flex align="center" className="paper-management-toolbar" gap="small" wrap>
          <Select
            aria-label="选择科目"
            className="paper-subject-filter"
            onChange={chooseSubject}
            options={subjects.map((item) => ({ label: `${item.title} · ${item.subject_code}`, value: item.id }))}
            placeholder="选择科目"
            value={subjectId || undefined}
          />
          <Input.Search
            allowClear
            aria-label="搜索试卷"
            className="paper-search-filter"
            disabled={!subject}
            onChange={(event) => { setQuery(event.target.value); setPage(0); }}
            placeholder="搜索名称、年份或配对键"
            value={query}
          />
          <Select
            aria-label="按单元筛选"
            className="paper-unit-filter"
            disabled={!subject}
            onChange={(value) => { setUnitCode(value); setPage(0); }}
            options={[{ label: "全部单元", value: "" }, ...papers.available_units.map((value) => ({ label: value, value }))]}
            value={unitCode}
          />
          <Select
            aria-label="按年份筛选"
            className="paper-year-filter"
            disabled={!subject}
            onChange={(value) => { setExamYear(value); setPage(0); }}
            options={[{ label: "全部年份", value: "" }, ...papers.available_years.map((value) => ({ label: String(value), value: String(value) }))]}
            value={examYear}
          />
          <Select
            aria-label="按考季筛选"
            className="paper-session-filter"
            disabled={!subject}
            onChange={(value) => { setExamSession(value); setPage(0); }}
            options={[{ label: "全部考季", value: "" }, ...papers.available_sessions.map((value) => ({ label: sessionLabel(value), value }))]}
            value={examSession}
          />
          <Button aria-label="查看全部作答记录" disabled={!subject} icon={<ClipboardList size={17} />} onClick={() => subjectId && onOpenAnswerCatalog?.(subjectId)} />
          <Button aria-label="添加试卷" disabled={!subject} icon={<Plus size={17} />} onClick={openCreate} type="primary" />
        </Flex>
      </Card>

      {subject ? (
        <>
          <ErrorBanner message={error} />

          {loading ? (
            <Row gutter={[16, 16]}>{Array.from({ length: 6 }, (_, index) => <Col key={index} lg={8} md={12} xs={24}><Card><Skeleton active /></Card></Col>)}</Row>
          ) : papers.items.length > 0 ? (
            <Row gutter={[16, 16]}>
              {papers.items.map((paper) => {
                const markScheme = paper.documents.some((item) => item.role === "mark_scheme");
                const booklet = paper.documents.some((item) => item.role === "source_booklet");
                const name = paperDisplayName(paper);
                return (
                  <Col key={paper.id} lg={8} md={12} xs={24}>
                    <Card className="paper-unit-card" hoverable>
                      <button
                        aria-label={`查看试卷 ${name}`}
                        className="paper-unit-card-main"
                        onClick={() => onOpenPaper?.(subject.id, paper.id)}
                        type="button"
                      >
                        <span className="paper-unit-card-header">
                          <span className="paper-unit-card-icon"><FileText size={20} /></span>
                          <span className="paper-unit-card-title">
                            <Tooltip placement="topLeft" title={name}><strong>{name}</strong></Tooltip>
                            <small>{paper.exam_year} · {sessionLabel(paper.exam_session)} · {paper.unit_code}</small>
                          </span>
                          <Tag color={paper.status === "active" ? "success" : "default"}>{paper.status === "active" ? "使用中" : "已删除"}</Tag>
                        </span>
                        <span className="paper-unit-card-overview">
                          <span><small>资料</small><strong>{paper.documents.length}</strong></span>
                          <span><small>作答记录</small><strong>{paper.paper_job_count}</strong></span>
                          <span><small>评分标准</small><strong className={markScheme ? "complete" : "pending"}>{markScheme ? "已绑定" : "待绑定"}</strong></span>
                        </span>
                        <span className="paper-unit-card-bindings">
                          <span className={markScheme ? "complete" : "pending"}><ShieldCheck size={13} />{markScheme ? "Mark Scheme" : "缺少 Mark Scheme"}</span>
                          <span className={booklet ? "complete" : "muted"}><Layers3 size={13} />{booklet ? "含支撑材料" : "无支撑材料"}</span>
                        </span>
                      </button>
                      <footer>
                        <Tooltip title={paper.pair_key}><code>{paper.pair_key}</code></Tooltip>
                        <Button aria-label={`编辑 ${name}`} icon={<Pencil size={15} />} onClick={() => openEdit(paper)} type="text">编辑</Button>
                        <Button aria-label={`删除 ${name}`} danger icon={<Trash2 size={15} />} onClick={() => setDeletingCandidate(paper)} type="text">删除</Button>
                      </footer>
                    </Card>
                  </Col>
                );
              })}
            </Row>
          ) : (
            <Card>
              <Empty description="当前条件下没有试卷">
                <Button icon={<Plus size={16} />} onClick={openCreate} type="primary">添加第一份试卷</Button>
              </Empty>
            </Card>
          )}

          <ListPagination
            ariaLabel="试卷分页"
            itemName="试卷"
            itemUnit="份"
            onPageChange={setPage}
            onPageSizeChange={() => undefined}
            page={page}
            pageSize={PAGE_SIZE}
            pageSizes={[PAGE_SIZE]}
            total={papers.total}
            visibleCount={papers.items.length}
          />
        </>
      ) : (
        <Card><Empty description="先选择科目" /></Card>
      )}

      <Drawer
        destroyOnHidden
        onClose={() => subjectId && onCloseDetail?.(subjectId)}
        open={detailVisible}
        rootClassName="paper-detail-drawer"
        size="large"
        title="试卷详情"
      >
        {selectedPaper && (
          <Space className="paper-detail-content" orientation="vertical" size="large" style={{ width: "100%" }}>
            <div className="paper-detail-hero">
              <span className="paper-detail-hero-icon"><FileText size={24} /></span>
              <div>
                <Text type="secondary">{selectedPaper.exam_year} · {sessionLabel(selectedPaper.exam_session)} · {selectedPaper.unit_code}</Text>
                <Tooltip placement="topLeft" title={paperDisplayName(selectedPaper)}><Title level={2}>{paperDisplayName(selectedPaper)}</Title></Tooltip>
                <Text code copyable>{selectedPaper.pair_key}</Text>
              </div>
              <Tag color={selectedPaper.status === "active" ? "success" : "default"}>{selectedPaper.status === "active" ? "使用中" : "已删除"}</Tag>
            </div>
            <Flex className="paper-detail-primary-actions" gap="small" wrap>
              <Button icon={<Play size={16} />} loading={starting} onClick={() => void startAnswering(selectedPaper)} type="primary">AI 自动作答</Button>
              <Button icon={<UploadCloud size={16} />} onClick={openExternalImport}>导入外部答卷</Button>
              <Button disabled={!selectedPaper.documents.some((item) => item.role === "mark_scheme")} icon={<BookOpenCheck size={16} />} onClick={() => onStartGrading?.(subjectId, selectedPaper.id)}>进入评分</Button>
              <Button icon={<Pencil size={16} />} onClick={() => openEdit(selectedPaper)}>编辑试卷</Button>
            </Flex>
            <section className="paper-detail-section">
              <Flex align="center" justify="space-between"><Title level={4}>资料绑定</Title><Tag>{selectedPaper.documents.length} 份资料</Tag></Flex>
              <Space orientation="vertical" size="small" style={{ width: "100%" }}>
                {selectedPaper.documents.map((document) => <PaperDocumentRow document={document} key={document.id} onOpen={() => openDocument(document.id)} />)}
              </Space>
            </section>
            <dl className="paper-detail-summary">
              <div>
                <dt>作答记录</dt>
                <dd>{selectedPaper.paper_job_count}<small>条</small></dd>
              </div>
              <div>
                <dt>试卷状态</dt>
                <dd><Tag color={selectedPaper.status === "active" ? "success" : "default"}>{selectedPaper.status === "active" ? "使用中" : "已删除"}</Tag></dd>
              </div>
              <div>
                <dt>最近更新</dt>
                <dd className="paper-detail-summary-date">{new Date(selectedPaper.updated_at).toLocaleDateString("zh-CN")}</dd>
              </div>
            </dl>
            <PaperJobHistory
              currentJobId={null}
              embedded
              onDeleted={() => setAnswerHistoryVersion((value) => value + 1)}
              onOpen={(jobId) => onOpenJob?.(subjectId, selectedPaper.id, jobId)}
              paperUnitId={selectedPaper.id}
              refreshKey={answerHistoryVersion}
              subject={subject}
            />
          </Space>
        )}
        {selectedDocument && (
          <div className="paper-document-detail">
            <Button
              className="paper-document-back"
              icon={<ArrowLeft size={16} />}
              onClick={() => subjectId && onBackDocument?.(subjectId, detail?.kind === "document" ? detail.parentPaperId : undefined)}
              type="text"
            >返回{detail?.kind === "document" && detail.parentPaperId ? "试卷详情" : "试卷列表"}</Button>
            <div className="paper-document-detail-hero">
              <span className="paper-document-detail-icon"><FileText size={24} /></span>
              <div>
                <Text type="secondary">{documentTypeLabel(selectedDocument.source_type)}</Text>
                <Tooltip placement="topLeft" title={documentLabel(selectedDocument)}>
                  <Title level={2}>{documentLabel(selectedDocument)}</Title>
                </Tooltip>
                <Text className="paper-document-detail-filename" type="secondary">{selectedDocument.filename}</Text>
              </div>
              <Tag color={selectedDocument.identity_status === "complete" ? "success" : "warning"}>
                {selectedDocument.identity_status === "complete" ? "已识别" : "待识别"}
              </Tag>
            </div>

            <Flex className="paper-document-detail-actions" gap="small" wrap>
              <Button href={selectedDocumentUrl ?? undefined} icon={<Eye size={16} />} target="_blank" type="primary">预览原文件</Button>
              <Button href={selectedDocumentUrl ? `${selectedDocumentUrl}&download=true` : undefined} icon={<Download size={16} />}>下载原文件</Button>
              {selectedDocumentStatus !== "converted" && (
                <Button
                  icon={<UploadCloud size={16} />}
                  loading={convertingDocumentId === selectedDocument.id}
                  onClick={() => void convertDocument(selectedDocument)}
                >{convertingDocumentId === selectedDocument.id ? "正在解析并实时刷新" : "解析内容"}</Button>
              )}
            </Flex>

            <section className="paper-detail-section paper-document-detail-section">
              <Title level={4}>文件信息</Title>
              <dl className="paper-document-detail-meta">
                <div><dt>资料类型</dt><dd>{documentTypeLabel(selectedDocument.source_type)}</dd></div>
                <div><dt>页数</dt><dd>{selectedDocument.page_count ?? "—"}<small>{selectedDocument.page_count ? "页" : ""}</small></dd></div>
                <div><dt>配对键</dt><dd><Text code copyable>{selectedDocument.pair_key || "未识别"}</Text></dd></div>
                <div><dt>解析状态</dt><dd><Tag color={selectedDocumentStatus === "converted" ? "success" : selectedDocumentStatus === "failed" ? "error" : "warning"}>{documentStatusLabel(selectedDocumentStatus ?? selectedDocument.status)}</Tag></dd></div>
                <div className="paper-document-detail-meta-wide">
                  <dt>原始文件名</dt>
                  <dd><Tooltip placement="topLeft" title={selectedDocument.filename}><span>{selectedDocument.filename}</span></Tooltip></dd>
                </div>
              </dl>
            </section>
          </div>
        )}
        {detail?.kind === "job" && (
          job ? (
            <Space orientation="vertical" size="large" style={{ width: "100%" }}>
              <Title level={2}>{job.display_name || job.filename}</Title>
              <Descriptions bordered column={1} size="small">
                <Descriptions.Item label="状态">{job.status}</Descriptions.Item>
                <Descriptions.Item label="题目">{job.completed_questions}/{job.total_questions}</Descriptions.Item>
                <Descriptions.Item label="单元">{job.unit_code || "—"}</Descriptions.Item>
              </Descriptions>
              {onOpenJob && subjectId && job.paper_unit_id && <Button onClick={() => { if (job.paper_unit_id) onOpenJob(subjectId, job.paper_unit_id, job.job_id); }} type="primary">打开作答结果</Button>}
            </Space>
          ) : <Skeleton active />
        )}
      </Drawer>

      <Modal
        destroyOnHidden
        footer={null}
        onCancel={() => setEditorOpen(false)}
        open={editorOpen}
        rootClassName="paper-editor-modal"
        styles={{ body: { maxHeight: "calc(100vh - 190px)", overflowY: "auto", paddingRight: 4 } }}
        title={editing ? "编辑试卷" : "添加试卷"}
        width={760}
        zIndex={1300}
      >
        <form onSubmit={savePaper}>
          <Form component={false} layout="vertical">
            <Form.Item extra={editing ? "修改后会同步显示在试卷卡片和详情中。" : "留空时使用 Question Paper 文件名。"} label="试卷名称">
              <Input aria-label="试卷名称" maxLength={200} onChange={(event) => setDraft((value) => ({ ...value, displayName: event.target.value }))} placeholder="例如 2024 June Paper 1" value={draft.displayName} />
            </Form.Item>
            {(["question_paper", "mark_scheme", "insert"] as const).map((role) => {
              const titles = { question_paper: "Question Paper", mark_scheme: "Mark Scheme", insert: "Source Booklet" };
              const valueKey = { question_paper: "questionPaperId", mark_scheme: "markSchemeId", insert: "sourceBookletId" } as const;
              const label = role === "question_paper" ? titles[role] : `${titles[role]}（可选）`;
              const paperRole = role === "insert" ? "source_booklet" : role;
              const currentDocuments = editing?.documents.filter((document) => document.role === paperRole) ?? [];
              return (
                <Card className="paper-editor-material" key={role} size="small" title={label}>
                  <Space orientation="vertical" size="small" style={{ width: "100%" }}>
                    {editing ? (
                      <>
                        {currentDocuments.length ? currentDocuments.map((boundDocument) => {
                          const sourceDocument = documents.find((document) => document.id === boundDocument.id);
                          const status = convertingDocumentId === boundDocument.id ? "converting" : sourceDocument?.status ?? boundDocument.status;
                          return (
                            <div className="paper-editor-current-file" key={boundDocument.id}>
                              <span className="paper-editor-current-file-icon"><FileText size={17} /></span>
                              <span className="paper-editor-current-file-copy">
                                <Tooltip placement="topLeft" title={documentLabel(boundDocument)}><strong>{documentLabel(boundDocument)}</strong></Tooltip>
                                <small>{boundDocument.page_count ? `${boundDocument.page_count} 页` : "页数待解析"}</small>
                              </span>
                              <Tag color={status === "converted" ? "success" : status === "failed" ? "error" : "warning"}>{documentStatusLabel(status)}</Tag>
                              {sourceDocument && status !== "converted" && (
                                <Button
                                  loading={convertingDocumentId === boundDocument.id}
                                  onClick={() => void convertDocument(sourceDocument)}
                                  size="small"
                                >{status === "converting" ? "解析中" : "解析"}</Button>
                              )}
                            </div>
                          );
                        }) : <div className="paper-editor-missing">尚未上传 {titles[role]}</div>}
                        {!uploadingRoles[role] ? (
                          <Button icon={<UploadCloud size={15} />} onClick={() => setUploadingRoles((current) => ({ ...current, [role]: true }))} type="link">{currentDocuments.length ? "更新文件" : "上传文件"}</Button>
                        ) : currentDocuments.length ? (
                          <Button onClick={() => {
                            setUploadingRoles((current) => ({ ...current, [role]: false }));
                            setFiles((current) => ({ ...current, [role]: null }));
                          }} type="link">取消更新</Button>
                        ) : null}
                      </>
                    ) : (
                      <select
                        aria-label={label}
                        onChange={(event) => setDraft((current) => ({ ...current, [valueKey[role]]: event.target.value }))}
                        value={draft[valueKey[role]]}
                      >
                        <option value="">从资料库选择…</option>
                        {candidates[role].map((document) => <option key={document.id} value={document.id}>{documentLabel(document)} · {document.pair_key}</option>)}
                      </select>
                    )}
                    {uploadingRoles[role] && (
                      <Upload.Dragger
                        accept=".pdf,.md,.markdown,application/pdf,text/markdown"
                        aria-label={`上传 ${label}`}
                        beforeUpload={(file) => {
                          setFiles((current) => ({ ...current, [role]: file }));
                          return false;
                        }}
                        fileList={files[role] ? [files[role] as File & { uid: string }] : []}
                        maxCount={1}
                        onRemove={() => {
                          setFiles((current) => ({ ...current, [role]: null }));
                        }}
                      >
                        <p className="paper-upload-drag-icon"><UploadCloud size={22} /></p>
                        <strong>{currentDocuments.length ? "拖拽新文件以更新" : "点击或拖拽文件到这里"}</strong>
                        <small>支持 PDF、Markdown；保存后更新资料状态</small>
                      </Upload.Dragger>
                    )}
                  </Space>
                </Card>
              );
            })}
            {Object.values(files).some(Boolean) && (
              <Form.Item>
                <Checkbox checked={licenseConfirmed} onChange={(event) => setLicenseConfirmed(event.target.checked)}>我确认有权在本系统中使用以上考试资料。</Checkbox>
              </Form.Item>
            )}
            <ErrorBanner message={error} />
            <Flex gap="small" justify="flex-end">
              <Button onClick={() => setEditorOpen(false)}>取消</Button>
              <Button disabled={!draft.questionPaperId && !files.question_paper} htmlType="submit" loading={saving} type="primary">保存试卷</Button>
            </Flex>
          </Form>
        </form>
      </Modal>

      <Modal
        cancelText="取消"
        confirmLoading={importingAnswer}
        okButtonProps={{ disabled: !externalAnswerFile }}
        okText="导入并解析"
        onCancel={() => setExternalImportOpen(false)}
        onOk={() => void importExternalAnswer()}
        open={externalImportOpen}
        title="导入外部答卷"
        width={560}
        zIndex={1300}
      >
        <div className="paper-external-import">
          <p>答卷会与当前试卷绑定，并与 AI 作答记录统一管理；列表中将标记为“外部答卷”。</p>
          <Upload.Dragger
            accept=".pdf,.md,.markdown,application/pdf,text/markdown"
            aria-label="上传外部答卷"
            beforeUpload={(file) => {
              setExternalAnswerFile(file);
              return false;
            }}
            maxCount={1}
            onRemove={() => setExternalAnswerFile(null)}
          >
            <p className="paper-upload-drag-icon"><UploadCloud size={24} /></p>
            <strong>点击或拖拽答卷文件到这里</strong>
            <small>支持 PDF、Markdown；无需重新上传试卷</small>
          </Upload.Dragger>
          <ErrorBanner message={error} />
        </div>
      </Modal>

      <AppConfirmDialog
        confirmLabel="删除试卷"
        danger
        description="试卷将从管理列表移除；已绑定的原始资料、历史作答与评分记录仍会保留。"
        onConfirm={() => void confirmDelete()}
        onOpenChange={(open) => { if (!open) setDeletingCandidate(null); }}
        open={Boolean(deletingCandidate)}
        title={`删除「${deletingCandidate ? paperDisplayName(deletingCandidate) : "试卷"}」？`}
      />
    </div>
  );
}
