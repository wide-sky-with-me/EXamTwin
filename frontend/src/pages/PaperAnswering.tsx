import {
  ArrowLeft,
  BookOpen,
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
import {
  type DragEvent as ReactDragEvent,
  type FormEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import { AnswerDiagramView } from "../components/AnswerDiagramView";
import { AnswerImageView } from "../components/AnswerImageView";
import { PaperJobHistory } from "../components/PaperJobHistory";
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
  setApiSubject,
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

function isSupportedPaper(file: File) {
  const name = file.name.toLowerCase();
  return name.endsWith(".pdf") || name.endsWith(".md") || name.endsWith(".markdown");
}

export function PaperAnswering({
  enabled,
  subjects: providedSubjects,
  subject: legacySubject,
}: {
  enabled: boolean;
  subjects?: SubjectPack[];
  subject?: SubjectPack | null;
}) {
  const subjects = useMemo(
    () => providedSubjects ?? (legacySubject ? [legacySubject] : []),
    [legacySubject, providedSubjects],
  );
  const [subjectId, setSubjectId] = useState(legacySubject?.id ?? subjects[0]?.id ?? "");
  const [draftSubjectId, setDraftSubjectId] = useState("");
  const subject = subjects.find((item) => item.id === subjectId) ?? null;
  const canAnswer = enabled && Boolean(subject?.answering_enabled);
  const [createOpen, setCreateOpen] = useState(false);
  const [createStep, setCreateStep] = useState<1 | 2>(1);
  const jobStorageKey = `examtwin.paperJobId.${subjectId || "unselected"}`;
  const [file, setFile] = useState<File | null>(null);
  const [unit, setUnit] = useState("");
  const [jobId, setJobId] = useState<string | null>(() =>
    window.localStorage.getItem(jobStorageKey),
  );
  const [job, setJob] = useState<PaperJobResult | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [replacing, setReplacing] = useState(false);
  const [retryingQuestion, setRetryingQuestion] = useState<number | null>(null);
  const [streamVersion, setStreamVersion] = useState(0);
  const [streamState, setStreamState] = useState<TaskStreamState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [historyVersion, setHistoryVersion] = useState(0);
  const [sourcePreviewOpen, setSourcePreviewOpen] = useState(false);
  const sourcePreviewButtonRef = useRef<HTMLButtonElement>(null);
  const sourcePreviewDialogRef = useRef<HTMLDivElement>(null);
  const terminalNoticeRef = useRef<string | null>(null);
  const { notify } = useToast();
  useEffect(() => {
    if (!subjectId && subjects[0]) setSubjectId(subjects[0].id);
  }, [subjectId, subjects]);

  useEffect(() => {
    setApiSubject(subjectId || null);
    setJobId(window.localStorage.getItem(jobStorageKey));
    setJob(null);
    setSelectedIndex(0);
    setError(null);
  }, [jobStorageKey, subjectId]);


  useEffect(() => {
    if (!jobId || !enabled) return;
    return subscribeTaskSnapshots<PaperJobResult>({
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
        if (next.status === "completed") {
          window.localStorage.removeItem(jobStorageKey);
        }
        if (["completed", "partial_failed", "failed"].includes(next.status)) {
          setHistoryVersion((version) => version + 1);
        }
      },
      isTerminal: (next) =>
        ["completed", "partial_failed", "failed"].includes(next.status),
      onState: setStreamState,
      onUnavailable: (message) => {
        window.localStorage.removeItem(jobStorageKey);
        setJobId(null);
        setJob(null);
        setError(message);
      },
      onError: setError,
    });
  }, [enabled, jobId, jobStorageKey, notify, streamVersion]);

  useEffect(() => {
    setSourcePreviewOpen(false);
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
      const created = await uploadPaper(file, unit);
      window.localStorage.setItem(jobStorageKey, created.job_id);
      setJob(null);
      setJobId(created.job_id);
      setStreamVersion((version) => version + 1);
      setSelectedIndex(0);
      setHistoryVersion((version) => version + 1);
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
          params: { path: { job_id: job.job_id } },
        }),
      );
      window.localStorage.setItem(jobStorageKey, job.job_id);
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
      const replacement = await replacePaperJob(job.job_id);
      notify("已创建替代任务；旧结果将保留用于审计。");
      setHistoryVersion((version) => version + 1);
      openHistoryJob(replacement.job_id);
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
          params: { path: { job_id: job.job_id, position } },
        }),
      );
      window.localStorage.setItem(jobStorageKey, job.job_id);
      setStreamVersion((version) => version + 1);
      notify("本题已重新排队，旧答案记录会保留。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "本题重试失败");
    } finally {
      setRetryingQuestion(null);
    }
  }

  function resetPaper() {
    window.localStorage.removeItem(jobStorageKey);
    setFile(null);
    setUnit("");
    setJobId(null);
    setJob(null);
    setSelectedIndex(0);
    setStreamState("idle");
    setError(null);
  }

  function openHistoryJob(nextJobId: string) {
    terminalNoticeRef.current = null;
    window.localStorage.setItem(jobStorageKey, nextJobId);
    setJob(null);
    setJobId(nextJobId);
    setSelectedIndex(0);
    setStreamState("idle");
    setStreamVersion((version) => version + 1);
    setError(null);
  }

  function openCreateWorkflow() {
    setDraftSubjectId("");
    setCreateStep(1);
    setFile(null);
    setUnit("");
    setError(null);
    setCreateOpen(true);
  }

  function continueToPaper() {
    if (!draftSubjectId) return;
    setApiSubject(draftSubjectId);
    setSubjectId(draftSubjectId);
    setCreateStep(2);
    setError(null);
  }

  function changeRecordSubject(nextSubjectId: string) {
    setApiSubject(nextSubjectId || null);
    setSubjectId(nextSubjectId);
  }

  function startAnotherPaper() {
    resetPaper();
    openCreateWorkflow();
  }

  function handleHistoryDeleted(deletedJobId: string) {
    if (jobId === deletedJobId || job?.job_id === deletedJobId) resetPaper();
  }

  const selected = job?.questions[selectedIndex] ?? null;
  const selectedAgentSteps = selected
    ? selected.agent_steps.filter((step) => step.run_attempt === selected.attempts)
    : [];
  const selectedSourcePages = selected?.source_pages ?? [];
  const overallProgress = job ? paperProgress(job) : 0;
  const selectedCanRetry = selected ? terminal && canRetryQuestion(selected) : false;
  const failedChunks = job?.chunks.filter((chunk) => chunk.status === "failed") ?? [];
  const failedBeforeQuestionDetection = Boolean(
    job?.status === "failed" && job.total_questions === 0,
  );

  return (
    <section className="paper-page">
      <header className="page-heading">
        <div>
          <h1>试卷作答</h1>
          <p>查看整卷作答记录，或按步骤创建新任务。</p>
        </div>
        <button className="primary" disabled={!subjects.length} onClick={openCreateWorkflow} type="button">
          <Plus size={17} />新建作答
        </button>
      </header>

      {!job && (
        <>
          <div className="records-toolbar">
            <label>科目
              <select onChange={(event) => changeRecordSubject(event.target.value)} value={subjectId}>
                {subjects.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
              </select>
            </label>
          </div>
          <PaperJobHistory
            currentJobId={jobId}
            onDeleted={handleHistoryDeleted}
            onOpen={openHistoryJob}
            refreshKey={historyVersion}
            subject={subject}
          />
        </>
      )}

      {job && (
        <div className="selected-context-bar paper-current-context">
          <div>
            <span>
              当前任务 · {subject?.title ?? job.subject_code} · {PAPER_JOB_STAGE_LABELS[job.stage]}
            </span>
            <strong title={job.display_name || job.filename}>{job.display_name || job.filename}</strong>
          </div>
          <button className="secondary" onClick={resetPaper} type="button">
            <ArrowLeft size={15} />返回作答记录
          </button>
        </div>
      )}

      {job && (
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
                  <label>参考单元（可选）
                    <select onChange={(event) => setUnit(event.target.value)} value={unit}>
                      <option value="">全部单元与当前知识库版本</option>
                      {subject?.units.map((item) => <option key={item.code} value={item.code}>{item.code} · {item.title}</option>)}
                    </select>
                  </label>
                  <ErrorBanner message={canAnswer ? error : "该科目尚未配置可用的试卷作答能力。"} />
                  <footer className="modal-actions">
                    <button className="secondary" onClick={() => setCreateStep(1)} type="button">上一步</button>
                    <button className="primary" disabled={uploading || !file || !canAnswer} type="submit">
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
              if (job.replaced_by_job_id) openHistoryJob(job.replaced_by_job_id);
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
        <article className={`panel paper-progress ${job.status}`}>
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
      {job && !failedBeforeQuestionDetection && (
        <>
          <div className="paper-summary">
            <strong>{job.total_questions}</strong><span>题目</span>
            <strong>{job.completed_questions}</strong><span>已处理</span>
            <strong className={job.failed_questions ? "failed" : ""}>{job.failed_questions}</strong><span>处理失败</span>
            <em>{job.display_name || job.filename}</em>
            {terminal && (
              <button className="secondary" onClick={startAnotherPaper} type="button">
                <UploadCloud size={15} />
                {job.status === "failed" ? "上传另一份试卷" : "作答另一份试卷"}
              </button>
            )}
          </div>
          <div className="paper-workspace">
            <div className="question-nav">
              {job.questions.length === 0 && <p className="question-waiting">解析完成后将在这里逐题出现。</p>}
              {job.questions.map((item, index) => {
                const latestStep = item.agent_steps[item.agent_steps.length - 1];
                return (
                <button
                  className={selectedIndex === index ? "active" : ""}
                  key={`${item.position}-${item.number}`}
                  onClick={() => setSelectedIndex(index)}
                  aria-pressed={selectedIndex === index}
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
            </div>
            <article className="panel paper-answer">
              {!selected && <div className="empty"><LoaderCircle className={terminal ? "" : "spin"} size={30} /><p>等待题目识别结果</p></div>}
              {selected && (
                <>
                  <div className="result-meta">
                    <span
                      className={
                        selected.status === "completed" && selected.grounded
                          ? "grounded"
                          : "ungrounded"
                      }
                    >
                      Q{selected.number} · {paperQuestionStatusLabel(selected)}
                    </span>
                    <div>
                      <span className="confidence-label">答案可信度</span>
                      <Confidence value={selected.confidence} />
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
                      <small>
                        完整题干 · 公式与图表排版
                        {selected.total_marks != null ? ` · ${selected.total_marks} marks` : ""}
                      </small>
                    </div>
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
                      <QuestionMarkdown>{selected.question_markdown}</QuestionMarkdown>
                    </div>
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
                      href={backendResourceUrl(`/papers/jobs/${job.job_id}/source`)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <FileText size={15} />
                      完整 PDF 兜底
                    </a>
                  </div>
                  {sourcePreviewOpen && selectedSourcePages.length > 0 && createPortal(
                    <SourcePreviewDialog
                      jobId={job.job_id}
                      onClose={() => setSourcePreviewOpen(false)}
                      pages={selectedSourcePages}
                      questionNumber={selected.number}
                      ref={sourcePreviewDialogRef}
                    />,
                    document.body,
                  )}
                  {selected.status === "pending" || selected.status === "answering" ? (
                    <div className="answer-block pending-answer"><LoaderCircle className="spin" size={18} />{paperQuestionStatusLabel(selected)}</div>
                  ) : selected.error ? <ErrorBanner message={selected.error} /> : (
                    <section className="answer-block" aria-labelledby="current-answer-title">
                      <h2 id="current-answer-title">证据化解答</h2>
                      <div className="markdown">
                        <CitationMarkdown
                          citations={selected.citations}
                          query={selected.question_markdown.slice(0, 300)}
                        >
                          {selected.answer_markdown}
                        </CitationMarkdown>
                      </div>
                    </section>
                  )}
                  {(selected.diagrams ?? []).length > 0 && (
                    <div className="answer-diagrams">
                      {(selected.diagrams ?? []).map((diagram, index) => (
                        <AnswerDiagramView
                          diagram={diagram}
                          jobId={job.job_id}
                          key={`${diagram.title}-${index}`}
                        />
                      ))}
                    </div>
                  )}
                  {(selected.images ?? []).length > 0 && (
                    <div className="answer-diagrams">
                      {(selected.images ?? []).map((image, index) => (
                        <AnswerImageView
                          image={image}
                          key={`${image.content_url}-${index}`}
                        />
                      ))}
                    </div>
                  )}
                  {selectedAgentSteps.length > 0 && (
                    <details className="agent-step-panel">
                      <summary>
                        <div>
                          <strong>作答过程</strong>
                          <span>第 {selected.attempts} 次尝试 · 展开查看检索与解题记录</span>
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
                              <span>
                                {step.message}
                                {recovered ? "，后续已自动恢复" : ""}
                              </span>
                            </li>
                          );
                        })}
                      </ol>
                    </details>
                  )}
                  <details className="paper-evidence-section">
                    <summary>
                      <h3>关联知识点与难度</h3>
                      <span>
                        {selected.knowledge_points.length
                          ? `${selected.knowledge_points.length} 个知识点`
                          : "未可靠映射"}
                      </span>
                      <ChevronDown aria-hidden="true" size={17} />
                    </summary>
                    <div className="paper-knowledge">
                      {selected.knowledge_points.length === 0 && <p>未能可靠映射知识点。</p>}
                      {selected.knowledge_points.map((point, index) => (
                        <KnowledgeEvidenceCard point={point} index={index} key={point.code} />
                      ))}
                    </div>
                  </details>
                  <details className="paper-evidence-section">
                    <summary>
                      <h3>本题答案引用</h3>
                      <span>
                        {selected.citations.length
                          ? `${selected.citations.length} 条引用`
                          : "暂无引用"}
                      </span>
                      <ChevronDown aria-hidden="true" size={17} />
                    </summary>
                    <div className="citations">
                      {selected.citations.length === 0 && <p>没有检索到可展示的引用。</p>}
                      <CitationReferenceList
                        citations={selected.citations}
                        query={selected.question_markdown.slice(0, 300)}
                      />
                    </div>
                  </details>
                </>
              )}
            </article>
          </div>
        </>
      )}
    </section>
  );
}
