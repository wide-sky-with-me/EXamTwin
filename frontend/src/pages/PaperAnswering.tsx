import {
  ArrowLeft,
  BookOpen,
  CircleHelp,
  ChevronDown,
  Eye,
  FileText,
  LoaderCircle,
  Plus,
  RefreshCw,
  SearchCheck,
  TriangleAlert,
  UploadCloud,
  X,
} from "lucide-react";
import { Tooltip } from "antd";
import {
  type DragEvent as ReactDragEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type FormEvent,
  type ReactNode,
  useEffect,
  useMemo,
  useRef,
  useState,
  lazy,
  Suspense,
} from "react";
import { createPortal } from "react-dom";

import { AnswerArtifactFlow } from "../components/AnswerArtifactFlow";
import { PaperJobHistory } from "../components/PaperJobHistory";
import { TargetScoreFields, TargetScoreReport, type StrategyRequest } from "../components/TargetScoreStrategy";
import { AppDialog } from "../components/ui/AppDialog";
import {
  CitationMarkdown,
  CitationReferenceList,
} from "../components/CitationReferences";
import { Confidence, ErrorBanner } from "../components/Feedback";
import { useToast } from "../components/toast-context";
import {
  KnowledgeEvidenceCard,
  SourcePreviewDialog,
} from "../components/KnowledgeEvidence";
import { QuestionMarkdown } from "../components/Markdown";
import {
  apiClient,
  backendResourceUrl,
  replacePaperJob,
  subjectHeaders,
  unwrapApi,
  uploadPaper,
} from "../lib/api";
import {
  canRetryQuestion,
  PAPER_JOB_STAGE_LABELS,
  paperProgress,
  paperQuestionStatusLabel,
} from "../lib/paper-job";
import {
  subscribeTaskSnapshots,
  type TaskStreamState,
} from "../lib/task-events";
import type { PaperJobResult, SubjectPack } from "../types";

const MAX_PAPER_BYTES = 25 * 1024 * 1024;
const PaperAnswerPdf = lazy(() => import("../components/PaperAnswerPdf").then((module) => ({ default: module.PaperAnswerPdf })));

function isSupportedPaper(file: File) {
  const name = file.name.toLowerCase();
  return name.endsWith(".pdf") || name.endsWith(".md") || name.endsWith(".markdown");
}

type PaperQuestion = PaperJobResult["questions"][number];
type MobilePane = "answer" | "evidence";

function QuestionNavigator({
  onSelect,
  questions,
  selectedIndex,
}: {
  onSelect: (index: number) => void;
  questions: PaperQuestion[];
  selectedIndex: number;
}) {
  return (
    <nav aria-label="题目导航" className="question-nav">
      {questions.map((item, index) => {
        const latestStep = item.agent_steps[item.agent_steps.length - 1];
        return (
          <button
            aria-current={selectedIndex === index ? "true" : undefined}
            aria-pressed={selectedIndex === index}
            className={selectedIndex === index ? "active" : ""}
            key={`${item.position}-${item.number}`}
            onClick={() => onSelect(index)}
            type="button"
          >
            <b>Q{item.number}</b>
            <span>
              {item.status === "answering"
                ? (latestStep?.message ?? paperQuestionStatusLabel(item))
                : paperQuestionStatusLabel(item)}
            </span>
            <i className={item.error ? "failed" : item.status === "completed" && item.grounded ? "done" : "warn"} />
          </button>
        );
      })}
    </nav>
  );
}

function MobileReadingTabs({
  evidenceCount,
  onChange,
  pane,
}: {
  evidenceCount: number;
  onChange: (pane: MobilePane) => void;
  pane: MobilePane;
}) {
  function handleKeyDown(event: ReactKeyboardEvent<HTMLButtonElement>) {
    let nextPane: MobilePane | null = null;
    if (event.key === "ArrowLeft" || event.key === "Home") nextPane = "answer";
    if (event.key === "ArrowRight" || event.key === "End") nextPane = "evidence";
    if (!nextPane) return;
    event.preventDefault();
    onChange(nextPane);
    window.requestAnimationFrame(() => {
      document.getElementById(`paper-${nextPane}-tab`)?.focus();
    });
  }

  return (
    <div aria-label="答案与证据" aria-orientation="horizontal" className="paper-mobile-reading-tabs" role="tablist">
      <button
        aria-controls="paper-answer-panel"
        aria-selected={pane === "answer"}
        id="paper-answer-tab"
        onClick={() => onChange("answer")}
        onKeyDown={handleKeyDown}
        role="tab"
        tabIndex={pane === "answer" ? 0 : -1}
        type="button"
      >
        答案
      </button>
      <button
        aria-controls="paper-evidence-panel"
        aria-selected={pane === "evidence"}
        id="paper-evidence-tab"
        onClick={() => onChange("evidence")}
        onKeyDown={handleKeyDown}
        role="tab"
        tabIndex={pane === "evidence" ? 0 : -1}
        type="button"
      >
        证据
        <span>{evidenceCount}</span>
      </button>
    </div>
  );
}

function AnswerReadingPane({ active, children }: { active: boolean; children: ReactNode }) {
  return (
    <article
      aria-labelledby="paper-answer-tab"
      className={`paper-answer paper-reading-panel paper-answer-pane${active ? " is-mobile-active" : ""}`}
      id="paper-answer-panel"
      role="tabpanel"
    >
      {children}
    </article>
  );
}

function EvidenceReadingPane({ active, children }: { active: boolean; children: ReactNode }) {
  return (
    <aside
      aria-labelledby="paper-evidence-tab"
      className={`paper-reading-panel paper-evidence-pane${active ? " is-mobile-active" : ""}`}
      id="paper-evidence-panel"
      role="tabpanel"
    >
      {children}
    </aside>
  );
}

export function PaperAnswering({
  enabled,
  subjects: providedSubjects,
  subject: legacySubject,
  initialSubjectId,
  initialJobId,
  initialPaperUnitId,
  onBack,
  onOpenJob,
  onOpenPaper,
  embedded = false,
}: {
  enabled: boolean;
  subjects?: SubjectPack[];
  subject?: SubjectPack | null;
  initialSubjectId?: string;
  initialJobId?: string;
  initialPaperUnitId?: string;
  onBack?: (paperUnitId?: string) => void;
  onOpenJob: (jobId: string, paperUnitId?: string | null) => void;
  onOpenPaper?: (paperUnitId: string) => void;
  embedded?: boolean;
}) {
  const subjects = useMemo(
    () => providedSubjects ?? (legacySubject ? [legacySubject] : []),
    [legacySubject, providedSubjects],
  );
  const [subjectId, setSubjectId] = useState(initialSubjectId ?? legacySubject?.id ?? subjects[0]?.id ?? "");
  const [draftSubjectId, setDraftSubjectId] = useState("");
  const subject = subjects.find((item) => item.id === subjectId) ?? null;
  const canAnswer = enabled && Boolean(subject?.answering_enabled);
  const [createOpen, setCreateOpen] = useState(false);
  const [createStep, setCreateStep] = useState<1 | 2>(1);
  const [file, setFile] = useState<File | null>(null);
  const [sourceBooklet, setSourceBooklet] = useState<File | null>(null);
  const [unit, setUnit] = useState("");
  const jobId = initialJobId ?? null;
  const [jobSnapshot, setJob] = useState<PaperJobResult | null>(null);
  const job = jobSnapshot?.job_id === jobId ? jobSnapshot : null;
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [questionExpanded, setQuestionExpanded] = useState(true);
  const [mobilePane, setMobilePane] = useState<"answer" | "evidence">("answer");
  const [uploading, setUploading] = useState(false);
  const [strategy, setStrategy] = useState<StrategyRequest | null>(null);
  const [dragging, setDragging] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [replacing, setReplacing] = useState(false);
  const [retryingQuestion, setRetryingQuestion] = useState<number | null>(null);
  const [streamVersion, setStreamVersion] = useState(0);
  const [streamState, setStreamState] = useState<TaskStreamState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [historyVersion, setHistoryVersion] = useState(0);
  const [sourcePreviewOpen, setSourcePreviewOpen] = useState(false);
  const [pdfJobId, setPdfJobId] = useState<string | null>(null);
  const sourcePreviewButtonRef = useRef<HTMLButtonElement>(null);
  const sourcePreviewDialogRef = useRef<HTMLDivElement>(null);
  const terminalNoticeRef = useRef<string | null>(null);
  const { notify } = useToast();
  const integratedWithPapers = Boolean(onBack);
  useEffect(() => {
    if (!subjectId && subjects[0]) setSubjectId(subjects[0].id);
  }, [subjectId, subjects]);

  useEffect(() => {
    if (!initialSubjectId) return;
    setSubjectId(initialSubjectId);
  }, [initialSubjectId]);

  useEffect(() => {
    terminalNoticeRef.current = null;
    setJob(null);
    setSelectedIndex(0);
    setStreamState("idle");
    setError(null);
  }, [initialJobId]);


  useEffect(() => {
    if (!jobId || !subjectId) return;
    return subscribeTaskSnapshots<PaperJobResult>({
      subjectId,
      path: `/papers/jobs/${jobId}/events`,
      onSnapshot: (next) => {
        setJob(next);
        setError(null);
        const terminalKey = `${next.job_id}:${next.status}`;
        if (
          ["completed", "partial_failed"].includes(next.status)
          && terminalNoticeRef.current !== terminalKey
        ) {
          terminalNoticeRef.current = terminalKey;
          notify(
            next.status === "completed"
              ? `整卷处理完成：${next.completed_questions} 题已处理。`
              : `整卷处理结束：${next.completed_questions} 题已处理，${next.failed_questions} 题处理失败。`,
          );
        }
        if (["completed", "partial_failed", "failed"].includes(next.status)) {
          setHistoryVersion((version) => version + 1);
        }
      },
      isTerminal: (next) =>
        ["completed", "partial_failed", "failed"].includes(next.status),
      onState: setStreamState,
      onUnavailable: (message) => {
        setJob(null);
        setError(message);
      },
      onError: setError,
    });
  }, [jobId, notify, streamVersion, subjectId]);

  useEffect(() => {
    setSourcePreviewOpen(false);
    setQuestionExpanded(true);
    setMobilePane("answer");
  }, [jobId, selectedIndex]);

  useEffect(() => {
    if (!sourcePreviewOpen) return;
    const previousOverflow = document.body.style.overflow;
    const previousFocus = document.activeElement as HTMLElement | null;
    const previewButton = sourcePreviewButtonRef.current;
    document.body.style.overflow = "hidden";
    sourcePreviewDialogRef.current
      ?.querySelector<HTMLElement>("button, a[href]")
      ?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        setSourcePreviewOpen(false);
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        sourcePreviewDialogRef.current?.querySelectorAll<HTMLElement>(
          "button:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])",
        ) ?? [],
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
      (previewButton ?? previousFocus)?.focus();
    };
  }, [sourcePreviewOpen]);

  const terminal = job
    ? ["completed", "partial_failed", "failed"].includes(job.status)
    : true;

  function selectPaper(candidate: File | null) {
    if (!candidate) {
      setFile(null);
      return;
    }
    if (!isSupportedPaper(candidate)) {
      setFile(null);
      setError("仅支持 Markdown（.md/.markdown）或 PDF 试卷。");
      return;
    }
    if (candidate.size > MAX_PAPER_BYTES) {
      setFile(null);
      setError("试卷超过 25 MB，请压缩或拆分后再上传。");
      return;
    }
    setFile(candidate);
    setError(null);
  }

  function dropPaper(event: ReactDragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    selectPaper(event.dataTransfer.files[0] ?? null);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || !canAnswer) return;
    setUploading(true);
    setError(null);
    try {
      const created = await uploadPaper(subjectId, file, unit, sourceBooklet, strategy);
      setHistoryVersion((version) => version + 1);
      onOpenJob(created.job_id);
      notify("试卷已保存，后台开始解析与逐题作答。");
      setCreateOpen(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "试卷任务创建失败");
    } finally {
      setUploading(false);
    }
  }

  async function retry() {
    if (!job) return;
    setRetrying(true);
    setError(null);
    try {
      await unwrapApi(
        apiClient.POST("/api/v1/papers/jobs/{job_id}/retry", {
          headers: subjectHeaders(subjectId),
          params: { path: { job_id: job.job_id } },
        }),
      );
      setStreamVersion((version) => version + 1);
      notify("失败步骤已重新排队。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "重试失败");
    } finally {
      setRetrying(false);
    }
  }

  async function replaceCurrentJob() {
    if (!job) return;
    setReplacing(true);
    setError(null);
    try {
      const replacement = await replacePaperJob(subjectId, job.job_id);
      notify("已创建替代任务；旧结果将保留用于审计。");
      setHistoryVersion((version) => version + 1);
      onOpenJob(replacement.job_id, initialPaperUnitId);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "替代任务创建失败");
    } finally {
      setReplacing(false);
    }
  }

  async function retryQuestion(position: number) {
    if (!job) return;
    setRetryingQuestion(position);
    setError(null);
    try {
      await unwrapApi(
        apiClient.POST("/api/v1/papers/jobs/{job_id}/questions/{position}/retry", {
          headers: subjectHeaders(subjectId),
          params: { path: { job_id: job.job_id, position } },
        }),
      );
      setStreamVersion((version) => version + 1);
      notify("本题已重新排队，旧答案记录会保留。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "本题重试失败");
    } finally {
      setRetryingQuestion(null);
    }
  }

  function resetPaperDraft() {
    setFile(null);
    setSourceBooklet(null);
    setUnit("");
    setJob(null);
    setSelectedIndex(0);
    setStreamState("idle");
    setError(null);
  }

  function openCreateWorkflow() {
    setDraftSubjectId("");
    setCreateStep(1);
    setFile(null);
    setSourceBooklet(null);
    setUnit("");
    setError(null);
    setCreateOpen(true);
  }

  function continueToPaper() {
    if (!draftSubjectId) return;
    setSubjectId(draftSubjectId);
    setCreateStep(2);
    setError(null);
  }

  function changeRecordSubject(nextSubjectId: string) {
    setSubjectId(nextSubjectId);
  }

  function startAnotherPaper() {
    if (initialPaperUnitId && onOpenPaper) {
      onOpenPaper(initialPaperUnitId);
      return;
    }
    if (onBack) {
      onBack(initialPaperUnitId);
      return;
    }
    resetPaperDraft();
    openCreateWorkflow();
  }

  function handleHistoryDeleted(deletedJobId: string) {
    if (jobId === deletedJobId || job?.job_id === deletedJobId) {
      onBack?.(initialPaperUnitId);
    }
  }


  const selected = job?.questions[selectedIndex] ?? null;
  const selectedAgentSteps = selected
    ? selected.agent_steps.filter((step) => step.run_attempt === selected.attempts)
    : [];
  const selectedSourcePages = selected?.source_pages ?? [];
  const overallProgress = job ? paperProgress(job) : 0;
  const selectedCanRetry = selected ? terminal && canRetryQuestion(selected)
    && !(job?.strategy_plan && selected.status === "completed") : false;
  const failedChunks = job?.chunks.filter((chunk) => chunk.status === "failed") ?? [];
  const failedBeforeQuestionDetection = Boolean(
    job?.status === "failed" && job.total_questions === 0,
  );

  return (
    <section className={`paper-page${embedded ? " paper-page-embedded" : ""}`}>
      {!embedded && <header className="page-heading">
        <div>
          <h1>{job ? (job.answer_mode === "uploaded" ? "外部答卷" : "AI 作答") : "作答记录"}</h1>
        </div>
        {integratedWithPapers ? (
          <button className="secondary" onClick={() => onBack?.(initialPaperUnitId)} type="button">
            <ArrowLeft size={15} />{initialPaperUnitId ? "返回试卷详情" : "返回作答记录"}
          </button>
        ) : (
          <button className="primary" disabled={!subjects.length} onClick={openCreateWorkflow} type="button">
            <Plus size={17} />新建作答
          </button>
        )}
      </header>}

      {!job && !jobId && (
        <PaperJobHistory
          embedded={embedded}
          currentJobId={jobId}
          onDeleted={handleHistoryDeleted}
          onOpen={(nextJobId, paperUnitId) => onOpenJob(nextJobId, paperUnitId)}
          onSubjectChange={changeRecordSubject}
          refreshKey={historyVersion}
          subject={subject}
          paperUnitId={initialPaperUnitId}
          subjects={subjects}
        />
      )}
      {jobId && !job && !error && (
        <div className="paper-processing-empty paper-detail-loading" role="status">
          <span className="paper-processing-empty-icon"><LoaderCircle className="spin" size={24} /></span>
          <strong>正在加载作答详情</strong>
          <p>正在连接任务进度并同步逐题答案与证据。</p>
        </div>
      )}
      {jobId && !job && error && (
        <div className="paper-unavailable-state" role="status">
          <ErrorBanner message={error} />
          <p>作答详情暂时不可用。建议先重新加载；若任务已被删除，请返回作答记录选择其他任务。</p>
          <button className="secondary" onClick={() => setStreamVersion((version) => version + 1)} type="button">
            <RefreshCw size={15} />重新加载作答详情
          </button>
        </div>
      )}

      {job && (
        <header className="paper-current-context">
          <button className="stage-back paper-current-back" onClick={() => onBack?.(initialPaperUnitId)} type="button">
            <ArrowLeft size={15} />{embedded ? "返回作答记录" : initialPaperUnitId ? "返回试卷详情" : "返回作答记录"}
          </button>
          <div className="paper-current-meta">
            <strong title={job.display_name || job.filename}>{job.display_name || job.filename}</strong>
            <span className="paper-current-meta-line">
              <b className={`paper-answer-origin ${job.answer_mode === "uploaded" ? "uploaded" : "generated"}`}>
                {job.answer_mode === "uploaded" ? "外部答卷" : "AI 作答"}
              </b>
              <span title={subject?.title ?? job.subject_code}>{subject?.title ?? job.subject_code}</span>
              <i aria-hidden="true" />
              <span>{PAPER_JOB_STAGE_LABELS[job.stage]}</span>
            </span>
            <small title={job.filename}>
              {job.display_name && job.display_name !== job.filename ? `原文件 · ${job.filename} · ` : ""}
              任务 {job.job_id}
            </small>
            {job.source_booklet_filename && (
              <small title={job.source_booklet_filename}><BookOpen size={13} />资料册 · {job.source_booklet_filename}</small>
            )}
          </div>
        </header>
      )}

      {job && !integratedWithPapers && (
        <div className="workflow-stepper compact-stepper" aria-label="作答流程">
          <span className="complete"><b>1</b>选择科目</span>
          <span className="complete"><b>2</b>试卷与参考范围</span>
          <span className={job.status === "failed" ? "failed" : "active"}>
            <b>3</b>{job.status === "failed" ? "处理失败，可继续" : "作答进度与结果"}
          </span>
        </div>
      )}

      {createOpen && (
        <AppDialog
          contentClassName="modal-card workflow-modal"
          dismissible={!uploading}
          initialFocusSelector="#paper-workflow-title"
          onOpenChange={setCreateOpen}
          rootClassName="app-viewport-dialog app-dialog-root"
          open
          title={createStep === 1 ? "选择科目" : "上传试卷并设置参考范围"}
        >
            <header className="modal-header">
              <div><span>新建作答</span><h2 id="paper-workflow-title">{createStep === 1 ? "选择科目" : "上传试卷并设置参考范围"}</h2></div>
              <button aria-label="关闭" className="icon-button" data-modal-close onClick={() => setCreateOpen(false)} type="button"><X size={19} /></button>
            </header>
            <div className="workflow-stepper">
              <span className={createStep >= 1 ? "active" : ""}><b>1</b>选择科目</span>
              <span className={createStep >= 2 ? "active" : ""}><b>2</b>试卷与参考范围</span>
              <span><b>3</b>作答进度与结果</span>
            </div>
            <div className="workflow-modal-body">
              {createStep === 1 ? (
                <>
                  <div className="workflow-subject-list">
                    {subjects.map((item) => (
                      <button aria-pressed={draftSubjectId === item.id} className={draftSubjectId === item.id ? "active" : ""} disabled={!item.answering_enabled} key={item.id} onClick={() => setDraftSubjectId(item.id)} type="button">
                        <BookOpen size={20} /><span><strong>{item.title}</strong><small>{item.subject_code} · {item.board_name}</small></span>
                      </button>
                    ))}
                  </div>
                  <footer className="modal-actions"><button className="primary" disabled={!draftSubjectId} onClick={continueToPaper} type="button">下一步</button></footer>
                </>
              ) : (
                <form className="paper-upload" onSubmit={submit}>
                  <label
                    className={`drop-zone ${file ? "has-file" : ""}${dragging ? " is-dragging" : ""}`}
                    onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
                    onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false); }}
                    onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }}
                    onDrop={dropPaper}
                  >
                    <input accept=".md,.markdown,.pdf,text/markdown,application/pdf" onChange={(event) => selectPaper(event.target.files?.[0] ?? null)} type="file" />
                    <UploadCloud size={30} />
                    <strong>{file ? file.name : `选择或拖入一份 ${subject?.subject_code ?? ""} 试卷`}</strong>
                    <span>{file ? `${(file.size / 1024 / 1024).toFixed(2)} MB` : "Markdown 或 PDF，最大 25 MB"}</span>
                  </label>
                  <label className={`paper-companion-upload ${sourceBooklet ? "has-file" : ""}`}>
                    <span>
                      <BookOpen size={18} />
                      <strong>配套 Source Booklet{subject?.source_booklet_required ? "（必需）" : "（可选）"}</strong>
                      <small>上传本卷引用的 Extract、数据或案例资料；系统会核对年份、考季和 Unit。</small>
                    </span>
                    <input
                      accept=".pdf,application/pdf"
                      onChange={(event) => setSourceBooklet(event.target.files?.[0] ?? null)}
                      required={subject?.source_booklet_required}
                      type="file"
                    />
                    {sourceBooklet && <em>{sourceBooklet.name}</em>}
                  </label>
                  <label>参考单元（可选）
                    <select onChange={(event) => setUnit(event.target.value)} value={unit}>
                      <option value="">全部单元与当前知识库版本</option>
                      {subject?.units.map((item) => <option key={item.code} value={item.code}>{item.code} · {item.title}</option>)}
                    </select>
                  </label>
                  <TargetScoreFields value={strategy} onChange={setStrategy} economics={subject?.subject_code === "9640"} />
                  <ErrorBanner message={canAnswer ? error : "该科目尚未配置可用的试卷作答能力。"} />
                  <footer className="modal-actions">
                    <button className="secondary" onClick={() => setCreateStep(1)} type="button">上一步</button>
                    <button className="primary" disabled={uploading || !file || !canAnswer || Boolean(subject?.source_booklet_required && !sourceBooklet)} type="submit">
                      {uploading ? <LoaderCircle className="spin" size={18} /> : <SearchCheck size={18} />}
                      {uploading ? "正在创建任务…" : "开始整卷作答"}
                    </button>
                  </footer>
                </form>
              )}
            </div>
        </AppDialog>
      )}
      {job && (
        job.source_integrity_status === "legacy_unverified"
        || job.source_integrity_status === "replacement_queued"
      ) && (
        <div className="paper-integrity-warning" role="alert">
          <TriangleAlert size={19} />
          <div>
            <strong>这份历史结果未通过当前来源完整性契约</strong>
            <p>题干可能存在旧版无声遗漏。旧答案仅供审计，不应作为可信作答结果。</p>
          </div>
          <button
            className="secondary"
            disabled={replacing}
            onClick={() => {
              if (job.replaced_by_job_id) onOpenJob(job.replaced_by_job_id, initialPaperUnitId);
              else void replaceCurrentJob();
            }}
            type="button"
          >
            {replacing
              ? <LoaderCircle className="spin" size={15} />
              : <RefreshCw size={15} />}
            {job.replaced_by_job_id ? "查看替代任务" : "修复并重跑"}
          </button>
        </div>
      )}
      {job && (
        <article className={`paper-progress ${job.status}`}>
          <div>
            <span>{PAPER_JOB_STAGE_LABELS[job.stage]}</span>
            <strong>
              {job.status === "completed"
                ? `${job.completed_questions} 题已处理`
                : job.status === "partial_failed"
                  ? `${job.completed_questions} 题已处理 · ${job.failed_questions} 题处理失败`
                  : job.status === "failed"
                    ? job.stage === "parsing" && job.total_pages
                      ? `解析中断 · 已完成 ${job.parsed_pages} / ${job.total_pages} 页`
                      : "整卷处理失败"
                    : job.stage === "parsing" && job.total_pages
                      ? `${job.parsed_pages} / ${job.total_pages} 页`
                      : job.stage === "vision_review"
                        ? `${job.parsed_pages} 页已解析 · 核对题面中`
                        : job.stage === "answering"
                          ? `${job.completed_questions + job.failed_questions} / ${job.total_questions} 题`
                          : job.status === "queued"
                            ? "任务已保存，等待处理"
                            : PAPER_JOB_STAGE_LABELS[job.stage]}
            </strong>
          </div>
          <div
            aria-label={`整卷处理进度 ${overallProgress}%`}
            aria-valuemax={100}
            aria-valuemin={0}
            aria-valuenow={overallProgress}
            className="progress-track"
            role="progressbar"
          >
            <i style={{ width: `${overallProgress}%` }} />
          </div>
          {!terminal && (
            <small>
              <LoaderCircle className="spin" size={13} />
              {streamState === "live"
                ? "后台处理中 · 实时进度已连接"
                : streamState === "reconnecting"
                  ? "实时连接正在恢复，任务仍在后台运行"
                  : "正在连接实时进度"}
            </small>
          )}
          {!terminal && streamState === "idle" && (
            <button
              className="secondary"
              onClick={() => setStreamVersion((version) => version + 1)}
              type="button"
            >
              <RefreshCw size={15} />重新连接进度
            </button>
          )}
          {(job.status === "failed" || job.status === "partial_failed") && (
            <button
              className={failedBeforeQuestionDetection ? "primary" : "secondary"}
              onClick={() => void retry()}
              disabled={retrying}
            >
              {retrying ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />}
              {failedBeforeQuestionDetection ? "从失败步骤继续" : "仅重试失败步骤"}
            </button>
          )}
          {terminal && job.filename.toLowerCase().endsWith(".pdf")
            && job.source_integrity_status === "verified" && job.completed_questions > 0 && (
              <button className="secondary" type="button" onClick={() => setPdfJobId(job.job_id)}>
                <FileText size={15} />导出原卷作答 PDF
              </button>
            )}
          <ErrorBanner message={job.error ?? null} />
          {failedChunks.length > 0 && (
            <div className="paper-chunk-errors">
              {failedChunks.map((chunk) => (
                <span key={chunk.chunk_index}>
                  第 {chunk.page_start}–{chunk.page_end} 页解析失败
                  {chunk.attempts > 0 ? ` · 已尝试 ${chunk.attempts} 次` : ""}
                </span>
              ))}
            </div>
          )}
          {failedBeforeQuestionDetection && (
            <p className="paper-recovery-note">
              已完成的页段会保留；继续后只重新处理失败页段，无需重新上传试卷。
            </p>
          )}
        </article>
      )}
      {job && failedBeforeQuestionDetection && (
        <article className="panel paper-terminal-empty" role="status">
          <div className="paper-terminal-empty-icon"><TriangleAlert size={22} /></div>
          <div>
            <span>暂无逐题结果</span>
            <h2>任务在题目识别前中断</h2>
            <p>
              前 {job.parsed_pages} / {job.total_pages} 页解析结果已经保存。
              修复后可从失败页段继续，不会重复处理已完成页段。
            </p>
            <small>{job.display_name || job.filename}</small>
          </div>
          <button className="secondary" onClick={startAnotherPaper} type="button">
            <UploadCloud size={15} />上传另一份试卷
          </button>
        </article>
      )}
      {job?.strategy_plan && <TargetScoreReport plan={job.strategy_plan} />}
      {job?.strategy_request && !job.strategy_plan && <p>目标 {job.strategy_request.target_score} 分：分题后将先规划学习投入和考试时间，再按策略作答。</p>}
      {job && !failedBeforeQuestionDetection && (
        <>
          {job.questions.length === 0 && (
            <div className={`paper-processing-empty${terminal ? " is-terminal" : ""}`} role="status">
              <span className="paper-processing-empty-icon">
                {terminal ? <FileText size={24} /> : <LoaderCircle className="spin" size={24} />}
              </span>
              <strong>{terminal ? "未识别到可作答题目" : "正在识别试卷题目"}</strong>
              <p>{terminal ? "任务已结束，但没有生成逐题结果。建议检查原卷是否包含清晰题面，再重新上传。" : "完成后将自动展示逐题结果；任务会继续在后台处理。"}</p>
              {terminal && <button className="secondary" onClick={startAnotherPaper} type="button"><UploadCloud size={15} />重新选择试卷</button>}
            </div>
          )}
          {job.questions.length > 0 && (
            <div className="paper-workspace">
              <QuestionNavigator
                onSelect={setSelectedIndex}
                questions={job.questions}
                selectedIndex={selectedIndex}
              />
              <MobileReadingTabs
                evidenceCount={selected ? selected.citations.length + selected.knowledge_points.length : 0}
                onChange={setMobilePane}
                pane={mobilePane}
              />

              <AnswerReadingPane active={mobilePane === "answer"}>
                {selected && (
                  <>
                    <div className="result-meta">
                      <span className={selected.status === "completed" && selected.grounded ? "grounded" : "ungrounded"}>
                        Q{selected.number} · {paperQuestionStatusLabel(selected)}
                      </span>
                      <div>
                        <Tooltip title="这是模型对本次生成结果的内部置信信号，不代表引用质量、证据充分性或答案正确性。">
                          <span className="confidence-label" tabIndex={0}>模型置信信号 <CircleHelp aria-hidden="true" size={13} /></span>
                        </Tooltip>
                        <Confidence
                          accessibleLabel="模型置信信号"
                          helpText="模型对本次生成结果的内部信号；不代表引用质量、证据充分性或答案正确性"
                          value={selected.confidence}
                        />
                        {selectedCanRetry && (
                          <button
                            className="secondary question-retry"
                            disabled={retryingQuestion === selected.position}
                            onClick={() => void retryQuestion(selected.position)}
                            type="button"
                          >
                            {retryingQuestion === selected.position
                              ? <LoaderCircle className="spin" size={15} />
                              : <RefreshCw size={15} />}
                            重试本题
                          </button>
                        )}
                      </div>
                    </div>
                    <section className="question-block" aria-labelledby="current-question-title">
                      <div className="question-block-header">
                        <div>
                          <span>原题</span>
                          <h2 id="current-question-title">Question {selected.number}</h2>
                        </div>
                        <div className="question-block-actions">
                          {selected.total_marks != null && <small>{selected.total_marks} marks</small>}
                          <button
                            aria-expanded={questionExpanded}
                            className="question-collapse-button"
                            onClick={() => setQuestionExpanded((expanded) => !expanded)}
                            type="button"
                          >
                            {questionExpanded ? "收起题目" : "展开题目"}
                            <ChevronDown aria-hidden="true" className={questionExpanded ? "expanded" : ""} size={15} />
                          </button>
                        </div>
                      </div>
                      {questionExpanded && (
                        <div className="question-block-content">
                          {selected.answer_requirements.length > 0 && (
                            <div className="answer-requirements" aria-label="答案交付要求">
                              {selected.answer_requirements.map((requirement, index) => (
                                <span key={`${requirement.label}-${index}`}>
                                  <b>{requirement.label}</b>
                                  {requirement.marks != null ? `${requirement.marks}分` : ""}
                                  {requirement.accuracy ? ` · ${requirement.accuracy}` : ""}
                                  {requirement.required_tool ? " · 需图形产物" : ""}
                                </span>
                              ))}
                            </div>
                          )}
                          <div className="question-copy">
                            <QuestionMarkdown subjectId={subjectId}>{selected.question_markdown}</QuestionMarkdown>
                          </div>
                        </div>
                      )}
                    </section>
                    {selected.source_warnings.length > 0 && (
                      <div className="question-source-warnings">
                        {selected.source_warnings.map((warning) => (
                          <p key={warning}><TriangleAlert size={16} />{warning}</p>
                        ))}
                      </div>
                    )}
                    <div className="question-source-actions">
                      {job.filename.toLowerCase().endsWith(".pdf") && selectedSourcePages.length > 0 && (
                        <button
                          className="source-preview-button"
                          onClick={() => setSourcePreviewOpen(true)}
                          ref={sourcePreviewButtonRef}
                          type="button"
                        >
                          <Eye size={17} />
                          查看原题 / 原卷 · {selectedSourcePages.length} 页
                        </button>
                      )}
                      <a
                        className="source-paper-link"
                        href={backendResourceUrl(`/papers/jobs/${job.job_id}/source`, subjectId)}
                        target="_blank"
                        rel="noreferrer"
                      >
                        <FileText size={15} />
                        打开完整原卷
                      </a>
                    </div>
                    {sourcePreviewOpen && selectedSourcePages.length > 0 && createPortal(
                      <SourcePreviewDialog
                        jobId={job.job_id}
                        onClose={() => setSourcePreviewOpen(false)}
                        pages={selectedSourcePages}
                        questionNumber={selected.number}
                        subjectId={subjectId}
                        ref={sourcePreviewDialogRef}
                      />,
                      document.body,
                    )}
                    {selected.status === "pending" || selected.status === "answering" ? (
                      <div className="answer-block pending-answer"><LoaderCircle className="spin" size={18} />{paperQuestionStatusLabel(selected)}</div>
                    ) : selected.skipped_by_strategy ? (
                      <div className="answer-block">本题按目标分数策略留空，未调用 AI 作答。可在策略报告中查看拿分路线。</div>
                    ) : selected.error ? (
                      <div className="paper-question-error">
                        <ErrorBanner message={selected.error} />
                        <p>{selectedCanRetry ? "建议仅重试本题；其他题目的结果不会被重新处理。" : "本题当前不可重试。建议核对原题，并返回作答记录查看任务状态。"}</p>
                      </div>
                    ) : (
                      <section className="answer-block" aria-labelledby="current-answer-title">
                        <h2 id="current-answer-title">证据化解答</h2>
                        <AnswerArtifactFlow
                          answerMarkdown={selected.answer_markdown}
                          diagrams={selected.diagrams ?? []}
                          images={selected.images ?? []}
                          jobId={job.job_id}
                          subjectId={subjectId}
                          renderMarkdown={(markdown, key) => (
                            <div className="markdown" key={key}>
                              <CitationMarkdown
                                citations={selected.citations}
                                query={selected.question_markdown.slice(0, 300)}
                                subjectId={subjectId}
                              >
                                {markdown}
                              </CitationMarkdown>
                            </div>
                          )}
                        />
                      </section>
                    )}
                  </>
                )}
              </AnswerReadingPane>

              <EvidenceReadingPane active={mobilePane === "evidence"}>
                {selected && (
                  <>
                    <header className="paper-evidence-header">
                      <div>
                        <span>同步依据</span>
                        <h2>证据与知识</h2>
                      </div>
                      <span>{selected.citations.length} 条引用 · {selected.knowledge_points.length} 个知识点</span>
                    </header>
                    <section className="paper-evidence-group" aria-labelledby="paper-citations-title">
                      <div className="paper-evidence-group-heading">
                        <h3 id="paper-citations-title">答案引用</h3>
                        <span>{selected.citations.length ? "可打开并核对原文" : "未检索到可展示引用"}</span>
                      </div>
                      {selected.citations.length === 0 ? (
                        <p className="paper-evidence-empty">当前答案没有可定位引用。建议结合原题与答案内容人工核对。</p>
                      ) : (
                        <CitationReferenceList
                          citations={selected.citations}
                          query={selected.question_markdown.slice(0, 300)}
                          subjectId={subjectId}
                        />
                      )}
                    </section>
                    <section className="paper-evidence-group" aria-labelledby="paper-knowledge-title">
                      <div className="paper-evidence-group-heading">
                        <h3 id="paper-knowledge-title">知识与难度</h3>
                        <span>{selected.knowledge_points.length ? "展开条目查看难度依据" : "未可靠映射"}</span>
                      </div>
                      <div className="paper-knowledge">
                        {selected.knowledge_points.length === 0 && <p className="paper-evidence-empty">当前题目未能可靠映射知识点。建议以题面和引用原文为准。</p>}
                        {selected.knowledge_points.map((point, index) => (
                          <KnowledgeEvidenceCard point={point} index={index} key={point.code} subjectId={subjectId} />
                        ))}
                      </div>
                    </section>
                    {selectedAgentSteps.length > 0 && (
                      <details className="agent-step-panel">
                        <summary>
                          <div>
                            <strong>运行轨迹</strong>
                            <span>第 {selected.attempts} 次尝试 · 检索与解题诊断</span>
                          </div>
                          <ChevronDown aria-hidden="true" size={16} />
                        </summary>
                        <ol>
                          {selectedAgentSteps.map((step, index) => {
                            const recovered = step.status === "failed"
                              && Boolean(step.tool_name)
                              && selectedAgentSteps.slice(index + 1).some(
                                (later) => later.tool_name === step.tool_name
                                  && later.status === "completed",
                              );
                            return (
                              <li
                                className={recovered ? "recovered" : step.status}
                                key={`${step.run_attempt}-${step.sequence}`}
                              >
                                <i />
                                <span>{step.message}{recovered ? "，后续已自动恢复" : ""}</span>
                              </li>
                            );
                          })}
                        </ol>
                      </details>
                    )}
                  </>
                )}
              </EvidenceReadingPane>
            </div>
          )}
        </>
      )}
      {job && terminal && pdfJobId === job.job_id && <Suspense fallback={<span role="status">正在加载 PDF 导出…</span>}>
        <PaperAnswerPdf key={`${subjectId}:${job.job_id}`} job={job} subjectId={subjectId} onClose={() => setPdfJobId(null)} />
      </Suspense>}
    </section>
  );
}
