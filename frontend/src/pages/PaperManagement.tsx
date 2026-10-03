import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Dropdown,
  Flex,
  Form,
  Input,
  Modal,
  Row,
  Segmented,
  Select,
  Skeleton,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from "antd";
import {
  ArchiveRestore,
  ArrowLeft,
  Check,
  ClipboardList,
  Database,
  Download,
  Eye,
  FileText,
  ChevronRight,
  MoreHorizontal,
  Layers3,
  Pencil,
  Play,
  Plus,
  RotateCcw,
  Save,
  ScanText,
  Search,
  ShieldCheck,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import { type FormEvent, lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ErrorBanner } from "../components/Feedback";
import { PaperJobHistory } from "../components/PaperJobHistory";
import { TargetScoreFields, type StrategyRequest } from "../components/TargetScoreStrategy";
import { useToast } from "../components/toast-context";
import { AppConfirmDialog } from "../components/ui/AppConfirmDialog";
import { TaskWorkspaceDialog } from "../components/ui/AppDialog";
import { ListPagination } from "../components/ui/ListControls";
import {
  answerPaperUnit,
  apiClient,
  archivePaperUnit,
  backendResourceUrl,
  createPaperUnit,
  importPaperUnitAnswer,
  listPaperUnits,
  listTrashedPaperUnits,
  permanentlyDeletePaperUnit,
  restorePaperUnit,
  subjectHeaders,
  unwrapApi,
  updatePaperUnit,
  uploadWorkspaceDocument,
} from "../lib/api";
import { useConversionQueue } from "../lib/conversion-queue";
import type { PaperDetail } from "../lib/paper-routes";
import type {
  PaperUnitDocument,
  PaperUnitList,
  PaperUnitSummary,
  SourceDocument,
  SubjectStatus,
} from "../types";

const { Text, Title } = Typography;
const PaperAnswering = lazy(() => import("./PaperAnswering").then(({ PaperAnswering: Page }) => ({ default: Page })));
const Grading = lazy(() => import("./Grading").then(({ Grading: Page }) => ({ default: Page })));
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


type PaperManagementProps = {
  subjects: SubjectStatus[];
  subjectId?: string;
  detail?: PaperDetail;
  onSubjectChange?: (subjectId: string) => void;
  onOpenPaper?: (subjectId: string, paperUnitId: string) => void;
  onOpenAnswers?: (subjectId: string, paperUnitId: string) => void;
  onOpenDocument?: (subjectId: string, documentId: string, paperUnitId?: string) => void;
  onBackDocument?: (subjectId: string, paperUnitId?: string) => void;
  onOpenJob?: (subjectId: string, paperUnitId: string, jobId: string) => void;
  onCloseDetail?: (subjectId: string) => void;
  onStartAnswering?: (subjectId: string, paperUnitId: string, jobId: string) => void;
  onStartGrading?: (subjectId: string, paperUnitId: string, jobId: string) => void;
  onGradingChanged?: () => Promise<void>;
};

type BindingDraft = {
  displayName: string;
  questionPaperId: string;
  markSchemeId: string;
  sourceBookletId: string;
};

type StagedFilePreview = {
  file: File;
  url?: string;
  text?: string;
};


const EMPTY_DRAFT: BindingDraft = {
  displayName: "",
  questionPaperId: "",
  markSchemeId: "",
  sourceBookletId: "",
};

const PAPER_DOCUMENT_ROLE_META = {
  question_paper: { icon: FileText, label: "Question Paper" },
  mark_scheme: { icon: ShieldCheck, label: "Mark Scheme" },
  source_booklet: { icon: Layers3, label: "Source Booklet" },
} as const;

function documentLabel(document: Pick<SourceDocument | PaperUnitDocument, "display_name" | "filename">) {
  return document.display_name || document.filename;
}

function fileSizeLabel(size: number) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function inferredPaperName(value: string) {
  return value.replace(/\.(pdf|md|markdown)$/i, "").trim();
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
    queued: "排队中",
    converting: "解析中",
    failed: "解析失败",
    missing: "资料缺失",
  }[status] ?? status;
}

function isConverted(status: string) {
  return status === "converted" || status === "indexed";
}

function conversionStatusColor(status: string) {
  if (status === "converted" || status === "indexed") return "success";
  if (status === "failed" || status === "missing") return "error";
  if (status === "queued") return "processing";
  return "warning";
}

function PaperDocumentRow({
  document,
  onOpen,
}: {
  document: PaperUnitDocument;
  onOpen: () => void;
}) {
  const { icon: Icon, label } = PAPER_DOCUMENT_ROLE_META[document.role];
  return (
    <button className="paper-binding-row" onClick={onOpen} type="button">
      <span aria-hidden="true" className={`paper-binding-icon is-${document.role.replaceAll("_", "-")}`}>
        <Icon size={19} strokeWidth={1.8} />
      </span>
      <span className="paper-binding-copy">
        <span className="paper-binding-title-line">
          <strong>{label}</strong>
          <Tag color={conversionStatusColor(document.status)}>{documentStatusLabel(document.status)}</Tag>
        </span>
        <Tooltip placement="bottomLeft" title={documentLabel(document)}>
          <small className="paper-binding-filename">{documentLabel(document)}</small>
        </Tooltip>
      </span>
      <span aria-hidden="true" className="paper-binding-meta">
        <span>{document.page_count ? `${document.page_count} 页` : "页数未识别"}</span>
        <ChevronRight className="paper-binding-chevron" size={17} strokeWidth={2} />
      </span>
    </button>
  );
}

export function PaperManagement({
  subjects,
  subjectId: controlledSubjectId,
  detail = null,
  onSubjectChange,
  onOpenPaper,
  onOpenAnswers,
  onOpenDocument,
  onBackDocument,
  onOpenJob,
  onCloseDetail,
  onStartAnswering,
  onStartGrading,
  onGradingChanged = async () => undefined,
}: PaperManagementProps) {
  const [localSubjectId, setLocalSubjectId] = useState(controlledSubjectId ?? subjects[0]?.id ?? "");
  const subjectId = controlledSubjectId ?? localSubjectId;
  const subject = subjects.find((item) => item.id === subjectId) ?? null;
  const [papers, setPapers] = useState<PaperUnitList>(EMPTY_LIST);
  const [documents, setDocuments] = useState<SourceDocument[]>([]);
  const [documentsSubjectId, setDocumentsSubjectId] = useState<string | null>(null);
  const [loading, setLoading] = useState(() => Boolean(subjectId));
  const [error, setError] = useState<string | null>(null);
  /** Errors raised inside the paper editor or external-answer dialog, shown in that dialog only. */
  const [dialogError, setDialogError] = useState<string | null>(null);
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
    question_paper: false,
    mark_scheme: false,
    insert: false,
  });
  const [stagedPreview, setStagedPreview] = useState<StagedFilePreview | null>(null);
  const [nameEditing, setNameEditing] = useState(false);
  const [nameCustomized, setNameCustomized] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deletingCandidate, setDeletingCandidate] = useState<PaperUnitSummary | null>(null);
  const [archiving, setArchiving] = useState(false);
  const [archiveError, setArchiveError] = useState<string | null>(null);
  const [trashError, setTrashError] = useState<string | null>(null);
  const [permanentDeleteError, setPermanentDeleteError] = useState<string | null>(null);
  const [trashOpen, setTrashOpen] = useState(false);
  const [trash, setTrash] = useState<PaperUnitList>(EMPTY_LIST);
  const [trashLoading, setTrashLoading] = useState(false);
  const [trashBusyId, setTrashBusyId] = useState<string | null>(null);
  const [permanentDeleteCandidate, setPermanentDeleteCandidate] = useState<PaperUnitSummary | null>(null);
  const [starting, setStarting] = useState(false);
  const [answerStrategy, setAnswerStrategy] = useState<StrategyRequest | null>(null);
  const [answerHistoryVersion, setAnswerHistoryVersion] = useState(0);
  const [externalImportOpen, setExternalImportOpen] = useState(false);
  const [externalAnswerFile, setExternalAnswerFile] = useState<File | null>(null);
  const [importingAnswer, setImportingAnswer] = useState(false);
  const [detailPaper, setDetailPaper] = useState<PaperUnitSummary | null>(null);
  const [detailLoading, setDetailLoading] = useState(Boolean(detail));
  const [detailError, setDetailError] = useState<string | null>(null);
  const resolvedDetailKeyRef = useRef<string | null>(null);
  const paperRequestRef = useRef(0);
  const documentRequestRef = useRef(0);
  const previousSubjectIdRef = useRef(subjectId);
  const { notify } = useToast();
  const {
    queue: conversionQueue,
    snapshot: {
      states: conversionStates,
      activeDocumentId: convertingDocumentId,
      finished: finishedConversions,
    },
  } = useConversionQueue(notify);

  useEffect(() => {
    if (!subjectId && subjects[0]) setLocalSubjectId(subjects[0].id);
  }, [subjectId, subjects]);

  const loadDocuments = useCallback(async () => {
    if (!subjectId) return;
    const requestId = ++documentRequestRef.current;
    try {
      const rows = await unwrapApi(
        apiClient.GET("/api/v1/subject-workspaces/{workspace_id}/documents", {
          headers: subjectHeaders(subjectId),
          params: { path: { workspace_id: subjectId } },
        }),
      );
      if (requestId === documentRequestRef.current) {
        setDocuments(rows);
        setDocumentsSubjectId(subjectId);
      }
    } catch (cause) {
      if (requestId === documentRequestRef.current) throw cause;
    }
  }, [subjectId]);

  const loadPapers = useCallback(async () => {
    const requestId = ++paperRequestRef.current;
    if (!subjectId) {
      if (requestId === paperRequestRef.current) {
        setPapers(EMPTY_LIST);
        setLoading(false);
      }
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
      if (requestId === paperRequestRef.current) {
        const lastPage = Math.max(0, Math.ceil(next.total / PAGE_SIZE) - 1);
        if (page > lastPage) {
          setPage(lastPage);
          return;
        }
        setPapers(next);
        setError(null);
      }
    } catch (cause) {
      if (requestId === paperRequestRef.current) {
        setError(cause instanceof Error ? cause.message : "试卷列表加载失败");
      }
    } finally {
      if (requestId === paperRequestRef.current) setLoading(false);
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

  const handledConversionsRef = useRef(finishedConversions);
  useEffect(() => {
    if (handledConversionsRef.current === finishedConversions) return;
    handledConversionsRef.current = finishedConversions;
    void loadDocuments().catch(() => undefined);
  }, [finishedConversions, loadDocuments]);

  useEffect(() => () => {
    if (stagedPreview?.url) URL.revokeObjectURL(stagedPreview.url);
  }, [stagedPreview]);

  useEffect(() => {
    const subjectChanged = previousSubjectIdRef.current !== subjectId;
    previousSubjectIdRef.current = subjectId;
    if (subjectChanged) {
      void loadPapers();
      return;
    }
    const timer = window.setTimeout(() => void loadPapers(), 180);
    return () => window.clearTimeout(timer);
  }, [loadPapers, subjectId]);

  useEffect(() => {
    const paperId = detail?.kind === "paper"
      ? detail.id
      : detail?.kind === "document"
        ? detail.parentPaperId
        : detail?.kind === "answers" || detail?.kind === "job" || detail?.kind === "grading"
          ? detail.paperId
          : undefined;
    if (!paperId || !subjectId) {
      resolvedDetailKeyRef.current = null;
      setDetailPaper(null);
      setDetailLoading(false);
      setDetailError(null);
      return;
    }
    const detailKey = `${subjectId}:${paperId}`;
    const listed = papers.items.find((item) => item.id === paperId);
    if (listed) {
      resolvedDetailKeyRef.current = detailKey;
      setDetailPaper(listed);
      setDetailLoading(false);
      setDetailError(null);
      return;
    }
    // A list refresh re-fetches an unlisted paper in place; replacing a resolved
    // detail or not-found state with a skeleton would detach its controls.
    if (resolvedDetailKeyRef.current !== detailKey) {
      setDetailPaper(null);
      setDetailError(null);
      setDetailLoading(true);
    }
    let current = true;
    void unwrapApi(apiClient.GET(
      "/api/v1/subject-workspaces/{workspace_id}/paper-units/{paper_unit_id}",
      {
        headers: subjectHeaders(subjectId),
        params: { path: { workspace_id: subjectId, paper_unit_id: paperId } },
      },
    )).then((result) => {
      if (current) {
        resolvedDetailKeyRef.current = detailKey;
        setDetailError(null);
        setDetailPaper(result);
        setDetailLoading(false);
      }
    }).catch((cause: unknown) => {
      if (current) {
        resolvedDetailKeyRef.current = detailKey;
        setDetailPaper(null);
        setDetailError(cause instanceof Error ? cause.message : "试卷详情加载失败");
        setDetailLoading(false);
      }
    });
    return () => { current = false; };
  }, [detail, papers.items, subjectId]);
  const selectedPaper = detailPaper;
  useEffect(() => {
    setAnswerStrategy(null);
  }, [subjectId, selectedPaper?.id]);
  const documentsLoaded = documentsSubjectId === subjectId;

  function paperMaterialStates(paper: PaperUnitSummary) {
    return paper.documents.map((binding) => {
      const sourceDocument = documents.find((document) => document.id === binding.id);
      const missing = documentsLoaded && !sourceDocument;
      return {
        binding,
        sourceDocument,
        status: missing ? "missing" : conversionStates[binding.id] ?? sourceDocument?.status ?? binding.status,
      };
    });
  }

  const answerReadiness = (() => {
    if (!selectedPaper) return null;
    const states = paperMaterialStates(selectedPaper);
    const questionPaper = states.find(({ binding }) => binding.role === "question_paper");
    const booklets = states.filter(({ binding }) => binding.role === "source_booklet");
    const booklet = booklets[0];
    if (!subject?.answering_enabled) {
      return { blocker: subject?.answering_disabled_reason || "该科目尚未开放 AI 作答。", booklet: null };
    }
    if (!questionPaper || questionPaper.status === "missing") {
      return { blocker: "试卷缺少可用的 Question Paper，请先编辑试卷重新绑定。", booklet: null };
    }
    if (subject.source_booklet_required && booklets.length !== 1) {
      return { blocker: "该科目作答需要且只能绑定一份 Source Booklet，请先编辑试卷。", booklet: null };
    }
    if (booklet?.status === "missing") {
      return { blocker: "绑定的 Source Booklet 已缺失，请先编辑试卷重新绑定。", booklet: null };
    }
    if (booklet && !isConverted(booklet.status)) return { blocker: null, booklet };
    return { blocker: null, booklet: null };
  })();
  const bookletConversionRunning = answerReadiness?.booklet
    ? answerReadiness.booklet.status === "queued" || answerReadiness.booklet.status === "converting"
    : false;

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
    paperRequestRef.current += 1;
    documentRequestRef.current += 1;
    setLoading(true);
    setError(null);
    setPage(0);
    setQuery("");
    setUnitCode("");
    setExamYear("");
    setExamSession("");
    setLocalSubjectId(nextSubjectId);
    onSubjectChange?.(nextSubjectId);
  }

  function resetPaperFilters() {
    setQuery("");
    setUnitCode("");
    setExamYear("");
    setExamSession("");
    setPage(0);
  }

  function openCreate() {
    setDialogError(null);
    setEditing(null);
    setDraft(EMPTY_DRAFT);
    setFiles({ question_paper: null, mark_scheme: null, insert: null });
    setUploadingRoles({ question_paper: false, mark_scheme: false, insert: false });
    setStagedPreview(null);
    setNameEditing(false);
    setNameCustomized(false);
    setEditorOpen(true);
  }

  function openEdit(paper: PaperUnitSummary) {
    setDialogError(null);
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
    setStagedPreview(null);
    setNameEditing(false);
    setNameCustomized(true);
    setEditorOpen(true);
  }

  function stageFile(role: "question_paper" | "mark_scheme" | "insert", file: File | null) {
    setStagedPreview(null);
    setFiles((current) => ({ ...current, [role]: file }));
    if (role === "question_paper" && !nameCustomized) {
      setDraft((current) => ({ ...current, displayName: file ? inferredPaperName(file.name) : "" }));
      setNameEditing(false);
    }
  }

  async function previewStagedFile(file: File) {
    try {
      if (/\.(md|markdown)$/i.test(file.name) || file.type === "text/markdown") {
        setStagedPreview({ file, text: await file.text() });
        return;
      }
      setStagedPreview({ file, url: URL.createObjectURL(file) });
    } catch (cause) {
      setDialogError(cause instanceof Error ? cause.message : "文件预览失败");
    }
  }

  async function uploadCandidate(role: "question_paper" | "mark_scheme" | "insert") {
    const file = files[role];
    if (!file || !subjectId) return null;
    return uploadWorkspaceDocument(subjectId, file, role);
  }

  async function savePaper(event: FormEvent) {
    event.preventDefault();
    if (!subjectId) return;
    setSaving(true);
    setDialogError(null);
    // Uploads dedupe by checksum, so only documents the server reports as newly created are
    // removed again if the paper cannot be saved; matched existing documents stay untouched.
    const createdDocumentIds: string[] = [];
    try {
      const uploads = await Promise.allSettled([
        uploadCandidate("question_paper"),
        uploadCandidate("mark_scheme"),
        uploadCandidate("insert"),
      ]);
      for (const upload of uploads) {
        if (upload.status === "fulfilled" && upload.value?.created) {
          createdDocumentIds.push(upload.value.id);
        }
      }
      const failedUpload = uploads.find((upload) => upload.status === "rejected");
      if (failedUpload) throw failedUpload.reason;
      const uploadedIds = uploads.map((upload) => upload.status === "fulfilled" ? upload.value?.id ?? "" : "");
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
      createdDocumentIds.length = 0;
      setEditorOpen(false);
      await Promise.all([loadDocuments(), loadPapers()]);
    } catch (cause) {
      await Promise.allSettled(createdDocumentIds.map((documentId) => unwrapApi(
        apiClient.DELETE("/api/v1/subject-workspaces/{workspace_id}/documents/{document_id}", {
          headers: subjectHeaders(subjectId),
          params: { path: { workspace_id: subjectId, document_id: documentId } },
        }),
      )));
      setDialogError(cause instanceof Error ? cause.message : "试卷保存失败");
    } finally {
      setSaving(false);
    }
  }

  function requestArchive(paper: PaperUnitSummary) {
    setArchiveError(null);
    setDeletingCandidate(paper);
  }

  async function confirmDelete() {
    if (!deletingCandidate || !subjectId || archiving) return;
    setArchiving(true);
    setArchiveError(null);
    try {
      await archivePaperUnit(subjectId, deletingCandidate.id);
      notify("试卷已移入回收站，可随时恢复。");
      setDeletingCandidate(null);
      onCloseDetail?.(subjectId);
      await loadPapers();
    } catch (cause) {
      setArchiveError(cause instanceof Error ? cause.message : "试卷删除失败");
    } finally {
      setArchiving(false);
    }
  }

  async function openTrash() {
    if (!subjectId) return;
    setTrashOpen(true);
    setTrashLoading(true);
    setTrashError(null);
    try {
      setTrash(await listTrashedPaperUnits(subjectId));
    } catch (cause) {
      setTrashError(cause instanceof Error ? cause.message : "回收站加载失败");
    } finally {
      setTrashLoading(false);
    }
  }

  async function restoreFromTrash(paper: PaperUnitSummary) {
    if (!subjectId) return;
    setTrashBusyId(paper.id);
    setTrashError(null);
    try {
      await restorePaperUnit(subjectId, paper.id);
      notify("试卷已恢复到管理列表。");
      const nextTrash = await listTrashedPaperUnits(subjectId);
      setTrash(nextTrash);
      await Promise.all([loadDocuments(), loadPapers()]);
    } catch (cause) {
      setTrashError(cause instanceof Error ? cause.message : "试卷恢复失败");
    } finally {
      setTrashBusyId(null);
    }
  }

  async function permanentlyDeleteFromTrash() {
    if (!subjectId || !permanentDeleteCandidate) return;
    const candidate = permanentDeleteCandidate;
    setTrashBusyId(candidate.id);
    setPermanentDeleteError(null);
    try {
      await permanentlyDeletePaperUnit(subjectId, candidate.id);
      notify("试卷及关联资料、作答、评分和复核记录已永久删除。");
      setPermanentDeleteCandidate(null);
      const nextTrash = await listTrashedPaperUnits(subjectId);
      setTrash(nextTrash);
      await loadDocuments();
    } catch (cause) {
      setPermanentDeleteError(cause instanceof Error ? cause.message : "试卷永久删除失败");
    } finally {
      setTrashBusyId(null);
    }
  }

  async function startAnswering(paper: PaperUnitSummary) {
    const questionPaper = paper.documents.find((item) => item.role === "question_paper");
    const sourceBooklet = paper.documents.find((item) => item.role === "source_booklet");
    if (!questionPaper || !subjectId || starting) return;
    setStarting(true);
    try {
      const created = await answerPaperUnit(subjectId, paper.id, questionPaper.id, sourceBooklet?.id, answerStrategy);
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
    setDialogError(null);
    setExternalImportOpen(true);
  }

  async function importExternalAnswer() {
    if (!selectedPaper || !subjectId || !externalAnswerFile) return;
    const questionPaper = selectedPaper.documents.find((item) => item.role === "question_paper");
    if (!questionPaper) {
      setDialogError("当前试卷缺少 Question Paper，不能导入外部答卷。");
      return;
    }
    setImportingAnswer(true);
    setDialogError(null);
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
      setDialogError(cause instanceof Error ? cause.message : "外部答卷导入失败");
    } finally {
      setImportingAnswer(false);
    }
  }

  function openDocument(documentId: string) {
    if (subjectId) onOpenDocument?.(subjectId, documentId, selectedPaper?.id);
  }

  function queueDocumentsForConversion(
    candidates: SourceDocument[],
    message: (count: number) => string,
  ) {
    if (!subjectId) return;
    const added = conversionQueue.enqueue(candidates, subjectId);
    if (!added) return;
    setError(null);
    notify(message(added));
  }

  function convertDocument(document: SourceDocument) {
    queueDocumentsForConversion([document], () => `${documentLabel(document)} 已加入解析队列。`);
  }

  function convertPaperDocuments(paper: PaperUnitSummary) {
    const boundIds = new Set(paper.documents.map((document) => document.id));
    queueDocumentsForConversion(
      documents.filter((document) => boundIds.has(document.id)),
      (count) => `已将 ${count} 份绑定资料加入解析队列。`,
    );
  }

  const selectedDocumentUrl = selectedDocument && subjectId
    ? backendResourceUrl(
        `/subject-workspaces/${encodeURIComponent(subjectId)}/documents/${encodeURIComponent(selectedDocument.id)}/content`,
        subjectId,
      )
    : null;
  const selectedDocumentStatus = selectedDocument
    ? conversionStates[selectedDocument.id] ?? selectedDocument.status
    : null;

  const paperFiltersActive = Boolean(query || unitCode || examYear || examSession);
  return (
    <div className="paper-management-page">
      <header className="catalog-page-header">
        <div className="catalog-page-heading">
          <Title className="catalog-page-title" level={1}>试卷</Title>
        </div>
        <Button
          className="catalog-primary-action"
          disabled={!subject || loading}
          icon={<Plus aria-hidden="true" size={17} />}
          onClick={openCreate}
          type="primary"
        >
          添加试卷
        </Button>
      </header>
      <Card className="catalog-toolbar-card paper-management-toolbar-card" size="small">
        <Flex align="center" className="paper-management-toolbar" gap="small" wrap>
          <Select
            aria-label="选择科目"
            className="paper-subject-filter"
            onChange={chooseSubject}
            options={subjects.map((item) => ({ label: `${item.title} · ${item.subject_code}`, value: item.id }))}
            placeholder="选择科目"
            value={subjectId || undefined}
          />
          <Input
            allowClear
            aria-label="搜索试卷"
            autoComplete="off"
            className="paper-search-filter"
            disabled={!subject}
            onChange={(event) => { setQuery(event.target.value); setPage(0); }}
            placeholder="搜索名称、年份或配对键"
            prefix={<Search aria-hidden="true" size={16} />}
            value={query}
          />
          <Select
            aria-label="按单元筛选"
            className="paper-unit-filter"
            disabled={!subject || loading}
            onChange={(value) => { setUnitCode(value); setPage(0); }}
            options={[{ label: "全部单元", value: "" }, ...papers.available_units.map((value) => ({ label: value, value }))]}
            value={unitCode}
          />
          <Select
            aria-label="按年份筛选"
            className="paper-year-filter"
            disabled={!subject || loading}
            onChange={(value) => { setExamYear(value); setPage(0); }}
            options={[{ label: "全部年份", value: "" }, ...papers.available_years.map((value) => ({ label: String(value), value: String(value) }))]}
            value={examYear}
          />
          <Select
            aria-label="按考季筛选"
            className="paper-session-filter"
            disabled={!subject || loading}
            onChange={(value) => { setExamSession(value); setPage(0); }}
            options={[{ label: "全部考季", value: "" }, ...papers.available_sessions.map((value) => ({ label: sessionLabel(value), value }))]}
            value={examSession}
          />
          <Tooltip title="重置筛选">
            <Button aria-label="重置筛选" disabled={!paperFiltersActive} icon={<RotateCcw aria-hidden="true" size={16} />} onClick={resetPaperFilters} />
          </Tooltip>
          <Tooltip title="回收站">
            <Button aria-label="打开试卷回收站" disabled={!subject} icon={<ArchiveRestore size={17} />} onClick={() => void openTrash()} />
          </Tooltip>
        </Flex>
      </Card>

      {subject ? (
        <section aria-busy={loading} className={`paper-management-results${loading ? " is-loading" : ""}`}>
          <div aria-hidden={loading || undefined} className="paper-management-results-content">
            {error && (
              <div className="catalog-error-row">
                <ErrorBanner message={error} />
                <Button disabled={loading} onClick={() => void loadPapers()}>重新加载</Button>
              </div>
            )}

            {papers.items.length > 0 ? (
            <Row gutter={[16, 16]}>
              {papers.items.map((paper) => {
                const name = paperDisplayName(paper);
                const materialStates = paperMaterialStates(paper);
                const convertedCount = materialStates.filter(({ status }) => isConverted(status)).length;
                const allConverted = materialStates.length > 0 && convertedCount === materialStates.length;
                const conversionActive = materialStates.some(({ status }) => status === "queued" || status === "converting");
                const canQuickConvert = materialStates.some(({ sourceDocument, status }) =>
                  sourceDocument && !isConverted(status) && status !== "queued" && status !== "converting",
                );
                const needsBinding = documentsLoaded
                  && (materialStates.length === 0 || materialStates.some(({ status }) => status === "missing"));
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
                        </span>
                        <span className="paper-unit-card-overview">
                          <span><small>资料</small><strong>{paper.documents.length}</strong></span>
                          <span><small>作答记录</small><strong>{paper.paper_job_count}</strong></span>
                          <span><small>解析状态</small><strong className={allConverted ? "complete" : "pending"}>{convertedCount}/{materialStates.length}</strong></span>
                        </span>
                        <span className="paper-unit-card-conversions">
                          {materialStates.map(({ binding, status }) => {
                            const { icon: MaterialIcon, label } = PAPER_DOCUMENT_ROLE_META[binding.role];
                            return (
                              <span className={`paper-unit-card-conversion is-${status}`} key={binding.id}>
                                <MaterialIcon aria-hidden="true" size={14} strokeWidth={1.8} />
                                <span><small>{label}</small><strong>{documentStatusLabel(status)}</strong></span>
                              </span>
                            );
                          })}
                        </span>
                      </button>
                      <div className={`paper-unit-card-quick-action${allConverted ? " is-complete" : ""}`}>
                        {allConverted ? (
                          <span><Check aria-hidden="true" size={15} />资料已全部解析</span>
                        ) : needsBinding && !conversionActive ? (
                          <Button
                            danger
                            icon={<Pencil aria-hidden="true" size={15} />}
                            onClick={() => openEdit(paper)}
                            size="small"
                          >
                            {materialStates.length ? "资料缺失，重新绑定" : "未绑定资料，去绑定"}
                          </Button>
                        ) : (
                          <Button
                            aria-label={`一键解析 ${name}`}
                            disabled={!canQuickConvert && !conversionActive}
                            icon={<ScanText aria-hidden="true" size={15} />}
                            loading={conversionActive}
                            onClick={() => convertPaperDocuments(paper)}
                            size="small"
                          >
                            {conversionActive ? "解析处理中" : canQuickConvert ? "一键解析绑定资料" : "正在加载资料状态"}
                          </Button>
                        )}
                      </div>
                      <footer>
                        <Tooltip title={paper.pair_key}><code>{paper.pair_key}</code></Tooltip>
                        <Button aria-label={`编辑 ${name}`} icon={<Pencil size={15} />} onClick={() => openEdit(paper)} type="text">编辑</Button>
                        <Button aria-label={`删除 ${name}`} danger icon={<Trash2 size={15} />} onClick={() => requestArchive(paper)} type="text">删除</Button>
                      </footer>
                    </Card>
                  </Col>
                );
              })}
            </Row>
            ) : (
              <Card className="paper-management-empty">
                <Empty
                  description={(
                    <span className="catalog-empty-copy">
                      <strong>{paperFiltersActive ? "没有符合当前条件的试卷" : "还没有试卷"}</strong>
                    </span>
                  )}
                >
                  <Button onClick={paperFiltersActive ? resetPaperFilters : openCreate}>
                    {paperFiltersActive ? "清除筛选" : "添加试卷"}
                  </Button>
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
          </div>
          {loading && (
            <div className="paper-management-loading-overlay" role="status">
              <Spin size="large" />
              <span>正在加载试卷…</span>
            </div>
          )}
        </section>
      ) : (
        <Card className="paper-management-empty">
          <Empty
            description={(
              <span className="catalog-empty-copy">
                <strong>尚未选择科目</strong>
              </span>
            )}
          >
            {subjects[0] && (
              <Button onClick={() => chooseSubject(subjects[0].id)} type="primary">
                选择 {subjects[0].title}
              </Button>
            )}
          </Empty>
        </Card>
      )}

      {(detail?.kind === "paper" || detail?.kind === "document") && <TaskWorkspaceDialog
        className="paper-domain-modal paper-detail-modal"
        onClose={() => {
          if (subjectId) onCloseDetail?.(subjectId);
        }}
        title={detail?.kind === "document" ? "资料详情" : "试卷详情"}
        width={980}
      >
        {detail?.kind === "paper" && selectedPaper && (
          <Space className="paper-detail-content" orientation="vertical" size="large" style={{ width: "100%" }}>
            <div className="paper-detail-hero">
              <span className="paper-detail-hero-icon"><FileText size={24} /></span>
              <div>
                <Tooltip placement="topLeft" title={paperDisplayName(selectedPaper)}><Title level={2}>{paperDisplayName(selectedPaper)}</Title></Tooltip>
                <Text type="secondary">
                  {selectedPaper.exam_year} · {sessionLabel(selectedPaper.exam_session)} · {selectedPaper.unit_code}
                </Text>
                <Text className="paper-detail-identity" code copyable>{selectedPaper.pair_key}</Text>
              </div>
            </div>
            <form id="paper-answer-options" onSubmit={(event) => { event.preventDefault(); void startAnswering(selectedPaper); }}>
              <fieldset disabled={starting} style={{ border: 0, margin: 0, padding: 0 }}>
                <TargetScoreFields value={answerStrategy} onChange={setAnswerStrategy} economics={subject?.subject_code === "9640"} />
              </fieldset>
            </form>
            {answerReadiness?.blocker && (
              <Alert className="paper-answer-blocker" message={answerReadiness.blocker} showIcon type="warning" />
            )}
            {answerReadiness?.booklet && (
              <Alert
                action={answerReadiness.booklet.sourceDocument && (
                  <Button
                    loading={bookletConversionRunning}
                    onClick={() => answerReadiness.booklet?.sourceDocument && convertDocument(answerReadiness.booklet.sourceDocument)}
                    size="small"
                  >
                    {bookletConversionRunning ? "解析中" : "解析 Source Booklet"}
                  </Button>
                )}
                className="paper-answer-blocker"
                message="Source Booklet 解析完成后才能开始作答。"
                showIcon
                type="info"
              />
            )}
            <Flex className="paper-detail-primary-actions" gap="small" wrap>
              <Button
                disabled={Boolean(answerReadiness?.blocker || answerReadiness?.booklet)}
                form="paper-answer-options"
                htmlType="submit"
                icon={<Play size={16} />}
                loading={starting}
                type="primary"
              >
                AI 自动作答
              </Button>
              <Dropdown
                menu={{
                  items: [
                    { key: "import", icon: <UploadCloud size={15} />, label: "导入外部答卷" },
                    { key: "history", icon: <ClipboardList size={15} />, label: "查看作答记录" },
                    { key: "edit", icon: <Pencil size={15} />, label: "编辑试卷" },
                    { type: "divider" },
                    { key: "delete", danger: true, icon: <Trash2 size={15} />, label: "移入回收站" },
                  ],
                  onClick: ({ key }) => {
                    if (key === "import") openExternalImport();
                    if (key === "history") onOpenAnswers?.(subjectId, selectedPaper.id);
                    if (key === "edit") openEdit(selectedPaper);
                    if (key === "delete") requestArchive(selectedPaper);
                  },
                }}
                placement="bottomRight"
                trigger={["click"]}
              >
                <Button aria-label="更多试卷操作" icon={<MoreHorizontal size={16} />}>更多操作</Button>
              </Dropdown>
            </Flex>
            <dl className="paper-detail-summary" aria-label="试卷概览">
              <div>
                <dt>资料</dt>
                <dd>{selectedPaper.documents.length}<small>份</small></dd>
              </div>
              <div>
                <dt>作答记录</dt>
                <dd>{selectedPaper.paper_job_count}<small>条</small></dd>
              </div>
              <div>
                <dt>最近更新</dt>
                <dd className="paper-detail-summary-date">{new Date(selectedPaper.updated_at).toLocaleDateString("zh-CN")}</dd>
              </div>
            </dl>
            <section className="paper-detail-section">
              <Flex align="center" justify="space-between"><Title level={4}>资料绑定</Title><Tag>{selectedPaper.documents.length} 份资料</Tag></Flex>
              {selectedPaper.documents.length > 0 ? (
                <ul className="paper-binding-list">
                  {selectedPaper.documents.map((document) => (
                    <li key={document.id}>
                      <PaperDocumentRow document={document} onOpen={() => openDocument(document.id)} />
                    </li>
                  ))}
                </ul>
              ) : (
                <Empty description="暂无绑定资料" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              )}
            </section>
          </Space>
        )}
        {detail?.kind === "document" && selectedDocument && (
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
                  disabled={selectedDocumentStatus === "queued"}
                  icon={<UploadCloud size={16} />}
                  loading={selectedDocumentStatus === "converting"}
                  onClick={() => void convertDocument(selectedDocument)}
                >{
                  selectedDocumentStatus === "queued"
                    ? "排队中"
                    : selectedDocumentStatus === "converting"
                      ? "正在解析并实时刷新"
                      : selectedDocumentStatus === "failed"
                        ? "重新解析"
                        : "解析内容"
                }</Button>
              )}
            </Flex>

            <section className="paper-detail-section paper-document-detail-section">
              <Title level={4}>文件信息</Title>
              <dl className="paper-document-detail-meta">
                <div><dt>资料类型</dt><dd>{documentTypeLabel(selectedDocument.source_type)}</dd></div>
                <div><dt>页数</dt><dd>{selectedDocument.page_count ?? "—"}<small>{selectedDocument.page_count ? "页" : ""}</small></dd></div>
                <div><dt>配对键</dt><dd><Text code copyable>{selectedDocument.pair_key || "未识别"}</Text></dd></div>
                <div><dt>解析状态</dt><dd><Tag color={conversionStatusColor(selectedDocumentStatus ?? selectedDocument.status)}>{documentStatusLabel(selectedDocumentStatus ?? selectedDocument.status)}</Tag></dd></div>
                <div className="paper-document-detail-meta-wide">
                  <dt>原始文件名</dt>
                  <dd><Tooltip placement="topLeft" title={selectedDocument.filename}><span>{selectedDocument.filename}</span></Tooltip></dd>
                </div>
              </dl>
            </section>
          </div>
        )}
        {detail?.kind === "paper" && !selectedPaper && (detailLoading ? <Skeleton active /> : (
          <div className="paper-route-unavailable" role="status">
            <ErrorBanner message={detailError ?? "找不到这份试卷，可能已被移入回收站或永久删除。"} />
            <Button onClick={() => onCloseDetail?.(subjectId)} type="primary">返回试卷列表</Button>
          </div>
        ))}
        {detail?.kind === "document" && !selectedDocument && (!documentsLoaded ? <Skeleton active /> : (
          <div className="paper-route-unavailable" role="status">
            <ErrorBanner message="找不到这份资料，可能已被删除。" />
            <Button onClick={() => onCloseDetail?.(subjectId)} type="primary">
              {detail.parentPaperId ? "返回试卷详情" : "返回试卷列表"}
            </Button>
          </div>
        ))}
      </TaskWorkspaceDialog>}

      {detail?.kind === "answers" && <TaskWorkspaceDialog
        className="paper-domain-modal paper-workflow-modal paper-answer-records-modal"
        onClose={() => {
          onOpenPaper?.(subjectId, detail.paperId);
        }}
        title={selectedPaper ? `作答记录 · ${paperDisplayName(selectedPaper)}` : "作答记录"}
        width={1180}
      >
        {selectedPaper && subject ? (
          <PaperJobHistory
            currentJobId={null}
            embedded
            onDeleted={() => setAnswerHistoryVersion((value) => value + 1)}
            onGrade={(jobId) => onStartGrading?.(subjectId, selectedPaper.id, jobId)}
            onOpen={(jobId) => onOpenJob?.(subjectId, selectedPaper.id, jobId)}
            paperUnitId={selectedPaper.id}
            refreshKey={answerHistoryVersion}
            subject={subject}
          />
        ) : detailLoading ? <Skeleton active /> : (
          <div className="paper-route-unavailable" role="status">
            <ErrorBanner message={detailError ?? "找不到这份试卷，可能已被移入回收站或永久删除。"} />
            <Button onClick={() => onCloseDetail?.(subjectId)} type="primary">返回试卷列表</Button>
          </div>
        )}
      </TaskWorkspaceDialog>}

      {detail?.kind === "job" && <TaskWorkspaceDialog
        className="paper-domain-modal paper-workflow-modal paper-answer-result-modal"
        onClose={() => {
          if (selectedPaper) onOpenAnswers?.(subjectId, detail.paperId);
          else onCloseDetail?.(subjectId);
        }}
        title={selectedPaper ? `作答详情 · ${paperDisplayName(selectedPaper)}` : "作答详情"}
        width={1380}
      >
        {subject ? (
          <Suspense fallback={(
            <div aria-busy="true" role="status">
              <span className="sr-only">正在加载作答详情</span>
              <Skeleton active />
            </div>
          )}>
            <PaperAnswering
              embedded
              enabled={subject.answering_enabled}
              initialJobId={detail.id}
              initialPaperUnitId={detail.paperId}
              initialSubjectId={subject.id}
              onBack={() => {
                if (selectedPaper) onOpenAnswers?.(subject.id, detail.paperId);
                else onCloseDetail?.(subject.id);
              }}
              onOpenJob={(jobId, paperUnitId) => {
                if (paperUnitId) onOpenJob?.(subject.id, paperUnitId, jobId);
              }}
              onOpenPaper={(paperUnitId) => onOpenPaper?.(subject.id, paperUnitId)}
              subjects={subjects}
            />
          </Suspense>
        ) : detailLoading ? <Skeleton active /> : (
          <div className="paper-route-unavailable" role="status">
            <ErrorBanner message={detailError ?? "找不到这份试卷或作答任务，链接可能已失效。"} />
            <Button onClick={() => onCloseDetail?.(subjectId)} type="primary">返回试卷列表</Button>
          </div>
        )}
      </TaskWorkspaceDialog>}

      {detail?.kind === "grading" && <TaskWorkspaceDialog
        className="paper-domain-modal paper-workflow-modal paper-grading-modal"
        onClose={() => onOpenAnswers?.(subjectId, detail.paperId)}
        title={selectedPaper ? `试卷评分 · ${paperDisplayName(selectedPaper)}` : "试卷评分"}
        width={1380}
      >
        {subject ? (
          <Suspense fallback={<Skeleton active />}>
            <Grading
              initialPaperJobId={detail.id}
              initialPaperUnitId={detail.paperId}
              initialSubjectId={subject.id}
              onCreated={onGradingChanged}
              subjects={subjects}
            />
          </Suspense>
        ) : <Skeleton active />}
      </TaskWorkspaceDialog>}

      <Modal
        destroyOnHidden
        footer={null}
        onCancel={() => setEditorOpen(false)}
        open={editorOpen}
        rootClassName="paper-domain-modal paper-editor-modal"
        title={editing ? "编辑试卷" : "添加试卷"}
        width={1180}
        zIndex={1300}
      >
        <form onSubmit={savePaper}>
          <Form className="paper-editor-form" component={false} layout="vertical">
            <div className="paper-editor-name">
              <span className="paper-editor-name-label">试卷名称</span>
              {nameEditing ? (
                <span className="paper-editor-name-edit">
                  <Input
                    aria-label="试卷名称"
                    autoFocus
                    maxLength={200}
                    onChange={(event) => {
                      setNameCustomized(true);
                      setDraft((value) => ({ ...value, displayName: event.target.value }));
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        setNameEditing(false);
                      }
                    }}
                    value={draft.displayName}
                  />
                  <Button aria-label="完成修改试卷名称" icon={<Check size={16} />} onClick={() => setNameEditing(false)} />
                </span>
              ) : (
                <span className={`paper-editor-name-display${draft.displayName ? "" : " is-empty"}`}>
                  <span className="paper-editor-name-value">
                    <FileText size={16} />
                    <Tooltip placement="topLeft" title={draft.displayName || undefined}>
                      <strong>{draft.displayName || "选择 Question Paper 后自动生成"}</strong>
                    </Tooltip>
                  </span>
                  <Button aria-label="修改试卷名称" disabled={!draft.displayName} icon={<Pencil size={15} />} onClick={() => setNameEditing(true)} size="small">修改</Button>
                </span>
              )}
            </div>
            <div className="paper-editor-material-grid">
              {(["question_paper", "mark_scheme", "insert"] as const).map((role) => {
                const titles = { question_paper: "Question Paper", mark_scheme: "Mark Scheme", insert: "Source Booklet" };
                const descriptions = { question_paper: "题目与作答结构", mark_scheme: "官方评分标准", insert: "附加材料与数据" };
                const icons = { question_paper: FileText, mark_scheme: ShieldCheck, insert: Layers3 };
                const valueKey = { question_paper: "questionPaperId", mark_scheme: "markSchemeId", insert: "sourceBookletId" } as const;
                const label = role === "question_paper" ? titles[role] : `${titles[role]}（可选）`;
                const paperRole = role === "insert" ? "source_booklet" : role;
                const currentDocuments = editing?.documents.filter((document) => document.role === paperRole) ?? [];
                const MaterialIcon = icons[role];
                return (
                  <Card
                    className={`paper-editor-material paper-editor-material-${role}`}
                    key={role}
                    size="small"
                    title={(
                      <span className="paper-editor-material-title">
                        <span className="paper-editor-material-title-icon"><MaterialIcon size={18} /></span>
                        <span><strong>{titles[role]}</strong><small>{descriptions[role]} · {role === "question_paper" ? "必需" : "可选"}</small></span>
                      </span>
                    )}
                  >
                    <div className="paper-editor-material-body">
                      {editing ? (
                        <>
                          {currentDocuments.length ? currentDocuments.map((boundDocument) => {
                            const sourceDocument = documents.find((document) => document.id === boundDocument.id);
                            const status = conversionStates[boundDocument.id] ?? sourceDocument?.status ?? boundDocument.status;
                            return (
                              <div className="paper-editor-current-file" key={boundDocument.id}>
                                <span className="paper-editor-current-file-icon"><MaterialIcon size={17} /></span>
                                <span className="paper-editor-current-file-copy">
                                  <Tooltip placement="topLeft" title={documentLabel(boundDocument)}><strong>{documentLabel(boundDocument)}</strong></Tooltip>
                                  <small>{boundDocument.page_count ? `${boundDocument.page_count} 页` : "页数待解析"}</small>
                                </span>
                                <Tag color={conversionStatusColor(status)}>{documentStatusLabel(status)}</Tag>
                                {sourceDocument && status !== "converted" && (
                                  <Button
                                    disabled={status === "queued"}
                                    loading={status === "converting"}
                                    onClick={() => void convertDocument(sourceDocument)}
                                    size="small"
                                  >{status === "queued" ? "排队中" : status === "converting" ? "解析中" : status === "failed" ? "重试" : "解析"}</Button>
                                )}
                              </div>
                            );
                          }) : <div className="paper-editor-missing">尚未上传 {titles[role]}</div>}
                          {!uploadingRoles[role] ? (
                            <Button icon={<UploadCloud size={15} />} onClick={() => setUploadingRoles((current) => ({ ...current, [role]: true }))} type="link">{currentDocuments.length ? "更新文件" : "上传文件"}</Button>
                          ) : currentDocuments.length ? (
                            <Button onClick={() => {
                              setUploadingRoles((current) => ({ ...current, [role]: false }));
                              stageFile(role, null);
                            }} type="link">取消更新</Button>
                          ) : null}
                        </>
                      ) : (
                        <>
                          <Segmented
                            block
                            className="paper-editor-material-source"
                            onChange={(value) => {
                              const upload = value === "upload";
                              setUploadingRoles((current) => ({ ...current, [role]: upload }));
                              if (upload) {
                                setDraft((current) => ({
                                  ...current,
                                  [valueKey[role]]: "",
                                  ...(role === "question_paper" && !nameCustomized ? { displayName: "" } : {}),
                                }));
                                if (role === "question_paper" && !nameCustomized) setNameEditing(false);
                              } else stageFile(role, null);
                            }}
                            options={[
                              { icon: <Database size={14} />, label: "资料库", value: "library" },
                              { icon: <UploadCloud size={14} />, label: "上传文件", value: "upload" },
                            ]}
                            value={uploadingRoles[role] ? "upload" : "library"}
                          />
                          {!uploadingRoles[role] && (
                            <Select
                              allowClear
                              aria-label={label}
                              className="paper-editor-library-select"
                              filterOption={(input, option) => String(option?.label ?? "").toLowerCase().includes(input.toLowerCase())}
                              labelRender={({ label: selectedLabel }) => (
                                <span className="paper-editor-select-value"><MaterialIcon size={15} /><span>{selectedLabel}</span></span>
                              )}
                              notFoundContent={<span className="paper-editor-library-empty">资料库暂无可用的 {titles[role]}</span>}
                              onChange={(value) => {
                                const selectedDocument = candidates[role].find((item) => item.id === value);
                                setDraft((current) => ({
                                  ...current,
                                  [valueKey[role]]: value ?? "",
                                  ...(role === "question_paper" && !nameCustomized
                                    ? { displayName: selectedDocument ? inferredPaperName(documentLabel(selectedDocument)) : "" }
                                    : {}),
                                }));
                                if (role === "question_paper" && !nameCustomized) setNameEditing(false);
                              }}
                              optionRender={(option) => {
                                const document = candidates[role].find((item) => item.id === option.value);
                                if (!document) return option.label;
                                return (
                                  <span className="paper-editor-library-option">
                                    <span className="paper-editor-library-option-icon"><MaterialIcon size={16} /></span>
                                    <span>
                                      <strong title={documentLabel(document)}>{documentLabel(document)}</strong>
                                      <small>{document.pair_key || "未识别配对"} · {document.page_count ? `${document.page_count} 页` : "页数待解析"}</small>
                                    </span>
                                    <em>{documentStatusLabel(document.status)}</em>
                                  </span>
                                );
                              }}
                              options={candidates[role].map((document) => ({ label: documentLabel(document), value: document.id }))}
                              placeholder="从资料库选择"
                              showSearch
                              value={draft[valueKey[role]] || undefined}
                            />
                          )}
                        </>
                      )}
                      {uploadingRoles[role] && !files[role] && (
                        <Upload.Dragger
                          accept=".pdf,.md,.markdown,application/pdf,text/markdown"
                          aria-label={`上传 ${label}`}
                          beforeUpload={(file) => {
                            stageFile(role, file);
                            return false;
                          }}
                          fileList={files[role] ? [files[role] as File & { uid: string }] : []}
                          maxCount={1}
                          onRemove={() => {
                            stageFile(role, null);
                          }}
                        >
                          <p className="paper-upload-drag-icon"><UploadCloud size={22} /></p>
                          <strong>{currentDocuments.length ? "拖拽新文件以更新" : "点击或拖拽文件到这里"}</strong>
                          <small>支持 PDF、Markdown；保存后更新资料状态</small>
                        </Upload.Dragger>
                      )}
                      {uploadingRoles[role] && files[role] && (() => {
                        const stagedFile = files[role];
                        return (
                          <div className="paper-editor-staged-file">
                            <span className="paper-editor-staged-file-icon"><MaterialIcon size={18} /></span>
                            <span className="paper-editor-staged-file-copy">
                              <Tooltip placement="topLeft" title={stagedFile.name}><strong>{stagedFile.name}</strong></Tooltip>
                              <small>{stagedFile.type || "本地文件"} · {fileSizeLabel(stagedFile.size)}</small>
                            </span>
                            <span className="paper-editor-staged-file-actions">
                              <Button icon={<Eye size={15} />} onClick={() => void previewStagedFile(stagedFile)} size="small">预览</Button>
                              <Tooltip title="替换文件">
                                <Upload
                                  accept=".pdf,.md,.markdown,application/pdf,text/markdown"
                                  beforeUpload={(file) => {
                                    stageFile(role, file);
                                    return false;
                                  }}
                                  maxCount={1}
                                  showUploadList={false}
                                >
                                  <Button aria-label={`替换 ${label}`} icon={<UploadCloud size={15} />} size="small" />
                                </Upload>
                              </Tooltip>
                              <Tooltip title="移除文件"><Button aria-label={`移除 ${label}`} danger icon={<X size={15} />} onClick={() => {
                                stageFile(role, null);
                              }} size="small" /></Tooltip>
                            </span>
                          </div>
                        );
                      })()}
                    </div>
                  </Card>
                );
              })}
            </div>
            <ErrorBanner message={dialogError} />
            <Flex className="paper-editor-footer" gap="small" justify="flex-end">
              <Button className="paper-editor-cancel" icon={<X size={16} />} onClick={() => setEditorOpen(false)}>取消</Button>
              <Button className="paper-editor-save" disabled={!draft.questionPaperId && !files.question_paper} htmlType="submit" icon={<Save size={16} />} loading={saving} type="primary">保存试卷</Button>
            </Flex>
          </Form>
        </form>
      </Modal>

      <Modal
        destroyOnHidden
        footer={null}
        onCancel={() => setStagedPreview(null)}
        open={Boolean(stagedPreview)}
        rootClassName="paper-domain-modal paper-local-preview-modal"
        title={stagedPreview ? `文件预览 · ${stagedPreview.file.name}` : "文件预览"}
        width={980}
        zIndex={1450}
      >
        {stagedPreview?.text !== undefined ? (
          <pre className="paper-local-preview-text">{stagedPreview.text}</pre>
        ) : stagedPreview?.url ? (
          <iframe className="paper-local-preview-frame" src={stagedPreview.url} title={stagedPreview.file.name} />
        ) : null}
      </Modal>

      <Modal
        cancelText="取消"
        confirmLoading={importingAnswer}
        okButtonProps={{ disabled: !externalAnswerFile }}
        okText="导入并解析"
        onCancel={() => setExternalImportOpen(false)}
        onOk={() => void importExternalAnswer()}
        open={externalImportOpen}
        rootClassName="paper-domain-modal paper-external-import-modal"
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
          <ErrorBanner message={dialogError} />
        </div>
      </Modal>

      <Modal
        footer={null}
        onCancel={() => setTrashOpen(false)}
        open={trashOpen}
        rootClassName="paper-domain-modal paper-trash-modal"
        title={(
          <span className="paper-trash-title">
            <span><ArchiveRestore size={18} /></span>
            <span><strong>试卷回收站</strong></span>
          </span>
        )}
        width={760}
        zIndex={1350}
      >
        <ErrorBanner message={trashError} />
        <Spin spinning={trashLoading} tip="正在加载回收站…">
          {trash.items.length ? (
            <div className="paper-trash-list">
              {trash.items.map((paper) => {
                const name = paperDisplayName(paper);
                return (
                  <article className="paper-trash-item" key={paper.id}>
                    <span className="paper-trash-item-icon"><FileText size={18} /></span>
                    <span className="paper-trash-item-copy">
                      <Tooltip placement="topLeft" title={name}><strong>{name}</strong></Tooltip>
                      <small>{paper.exam_year} · {sessionLabel(paper.exam_session)} · {paper.unit_code} · {paper.documents.length} 份资料 · {paper.paper_job_count} 条作答</small>
                    </span>
                    <span className="paper-trash-item-actions">
                      <Button disabled={trashBusyId !== null} icon={<RotateCcw size={15} />} loading={trashBusyId === paper.id && !permanentDeleteCandidate} onClick={() => void restoreFromTrash(paper)}>恢复</Button>
                      <Button danger disabled={trashBusyId !== null} icon={<Trash2 size={15} />} onClick={() => { setPermanentDeleteError(null); setPermanentDeleteCandidate(paper); }}>永久删除</Button>
                    </span>
                  </article>
                );
              })}
            </div>
          ) : !trashLoading ? (
            <Empty description="回收站为空" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : <div className="paper-trash-loading-space" />}
        </Spin>
      </Modal>

      <AppConfirmDialog
        busy={archiving}
        confirmLabel="移入回收站"
        error={archiveError}
        description="试卷会从当前列表移入回收站；原始资料、作答、评分和复核记录完整保留，可从回收站恢复。"
        onConfirm={() => void confirmDelete()}
        onOpenChange={(open) => { if (!open && !archiving) setDeletingCandidate(null); }}
        open={Boolean(deletingCandidate)}
        title={`将「${deletingCandidate ? paperDisplayName(deletingCandidate) : "试卷"}」移入回收站？`}
      />

      <AppConfirmDialog
        busy={Boolean(permanentDeleteCandidate && trashBusyId === permanentDeleteCandidate.id)}
        confirmLabel="永久删除"
        danger
        error={permanentDeleteError}
        description={permanentDeleteCandidate
          ? `将永久删除该试卷的 ${permanentDeleteCandidate.documents.length} 份原始资料、${permanentDeleteCandidate.paper_job_count} 条作答，以及全部关联评分、复核记录和文件。此操作无法恢复。`
          : ""}
        onConfirm={() => void permanentlyDeleteFromTrash()}
        onOpenChange={(open) => { if (!open && !trashBusyId) setPermanentDeleteCandidate(null); }}
        open={Boolean(permanentDeleteCandidate)}
        title={`永久删除「${permanentDeleteCandidate ? paperDisplayName(permanentDeleteCandidate) : "试卷"}」？`}
      />
    </div>
  );
}
