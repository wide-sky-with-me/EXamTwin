import {
  Eye,
  FileText,
  LoaderCircle,
  MessageSquareText,
  RefreshCw,
  SearchCheck,
  TriangleAlert,
  UploadCloud,
} from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { AnswerDiagramView } from "../components/AnswerDiagramView";
import { AnswerImageView } from "../components/AnswerImageView";
import {
  CitationMarkdown,
  CitationReferenceList,
} from "../components/CitationReferences";
import { Confidence, ErrorBanner } from "../components/Feedback";
import {
  KnowledgeEvidenceCard,
  SourcePreviewDialog,
} from "../components/KnowledgeEvidence";
import { QuestionMarkdown } from "../components/Markdown";
import { apiClient, apiUrl, unwrapApi, uploadPaper } from "../lib/api";
import { canRetryQuestion, paperProgress } from "../lib/paper-job";
import {
  subscribeTaskSnapshots,
  type TaskStreamState,
} from "../lib/task-events";
import type { PaperJobResult, SubjectPack } from "../types";

export function PaperAnswering({ enabled }: { enabled: boolean }) {
  const [file, setFile] = useState<File | null>(null);
  const [unit, setUnit] = useState("");
  const [jobId, setJobId] = useState<string | null>(() =>
    window.localStorage.getItem("examtwin.paperJobId"),
  );
  const [job, setJob] = useState<PaperJobResult | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [retryingQuestion, setRetryingQuestion] = useState<number | null>(null);
  const [streamVersion, setStreamVersion] = useState(0);
  const [streamState, setStreamState] = useState<TaskStreamState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [sourcePreviewOpen, setSourcePreviewOpen] = useState(false);
  const [subject, setSubject] = useState<SubjectPack | null>(null);
  const sourcePreviewButtonRef = useRef<HTMLButtonElement>(null);
  const sourcePreviewDialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!enabled) return;
    let active = true;
    void unwrapApi(apiClient.GET("/api/v1/subject"))
      .then((value) => {
        if (active) setSubject(value);
      })
      .catch((cause) => {
        if (active) {
          setError(cause instanceof Error ? cause.message : "科目元数据加载失败");
        }
      });
    return () => {
      active = false;
    };
  }, [enabled]);

  useEffect(() => {
    if (!jobId || !enabled) return;
    return subscribeTaskSnapshots<PaperJobResult>({
      path: `/papers/jobs/${jobId}/events`,
      onSnapshot: (next) => {
        setJob(next);
        setError(null);
        if (next.status === "completed") {
          window.localStorage.removeItem("examtwin.paperJobId");
        }
      },
      isTerminal: (next) =>
        ["completed", "partial_failed", "failed"].includes(next.status),
      onState: setStreamState,
      onUnavailable: (message) => {
        window.localStorage.removeItem("examtwin.paperJobId");
        setJobId(null);
        setJob(null);
        setError(message);
      },
      onError: setError,
    });
  }, [enabled, jobId, streamVersion]);

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

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || !enabled) return;
    setUploading(true);
    setError(null);
    try {
      const created = await uploadPaper(file, unit);
      window.localStorage.setItem("examtwin.paperJobId", created.job_id);
      setJob(null);
      setJobId(created.job_id);
      setStreamVersion((version) => version + 1);
      setSelectedIndex(0);
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
      window.localStorage.setItem("examtwin.paperJobId", job.job_id);
      setStreamVersion((version) => version + 1);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "重试失败");
    } finally {
      setRetrying(false);
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
      window.localStorage.setItem("examtwin.paperJobId", job.job_id);
      setStreamVersion((version) => version + 1);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "本题重试失败");
    } finally {
      setRetryingQuestion(null);
    }
  }

  const selected = job?.questions[selectedIndex] ?? null;
  const selectedAgentSteps = selected
    ? selected.agent_steps.filter((step) => step.run_attempt === selected.attempts)
    : [];
  const selectedSourcePages = selected?.source_pages ?? [];
  const overallProgress = job ? paperProgress(job) : 0;
  const selectedCanRetry = selected ? terminal && canRetryQuestion(selected) : false;
  const failedChunks = job?.chunks.filter((chunk) => chunk.status === "failed") ?? [];
  const stageLabels: Record<string, string> = {
    queued: "等待 Worker",
    parsing: "分段解析",
    splitting: "识别题目",
    answering: "逐题作答",
    completed: "处理完成",
  };

  return (
    <section>
      <div className="page-heading compact">
        <div>
          <p className="eyebrow">PAPER GROUNDING</p>
          <h1>上传试卷，逐题给出证据化解答</h1>
          <p>自动识别顶层题目；每题独立检索、作答，并展示知识点难度和参考证据。</p>
        </div>
      </div>
      <form className="panel paper-upload" onSubmit={submit}>
        <label className={`drop-zone ${file ? "has-file" : ""}`}>
          <input
            type="file"
            accept=".md,.markdown,.pdf,text/markdown,application/pdf"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
          <UploadCloud size={30} />
          <strong>{file ? file.name : "选择或拖入一份 9660 试卷"}</strong>
          <span>{file ? `${(file.size / 1024 / 1024).toFixed(2)} MB` : "Markdown 或 PDF，最大 25 MB"}</span>
        </label>
        <div className="paper-options">
          <label>限定单元（可选）
            <select value={unit} onChange={(e) => setUnit(e.target.value)}>
              <option value="">全部单元</option>
              {subject?.units.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.code} · {item.title}
                </option>
              ))}
            </select>
          </label>
          <button className="primary" disabled={uploading || !file || !enabled}>
            {uploading ? <LoaderCircle className="spin" size={18} /> : <SearchCheck size={18} />}
            {uploading ? "正在创建任务…" : "开始整卷作答"}
          </button>
        </div>
        <ErrorBanner
          message={
            enabled
              ? error
              : "当前 FastAPI 尚未加载答题 Agent 与实时任务协议，已阻止上传。请重启 API 后再试。"
          }
        />
      </form>
      {job && (
        <article className={`panel paper-progress ${job.status}`}>
          <div>
            <span>{stageLabels[job.stage] ?? job.stage}</span>
            <strong>
              {job.stage === "parsing" && job.total_pages
                ? `${job.parsed_pages} / ${job.total_pages} 页`
                : job.stage === "answering"
                  ? `${job.completed_questions + job.failed_questions} / ${job.total_questions} 题`
                  : job.status === "queued"
                    ? "任务已保存，可离开页面"
                    : job.status}
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
            <button className="secondary" onClick={() => void retry()} disabled={retrying}>
              {retrying ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />}
              仅重试失败步骤
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
        </article>
      )}
      {!job ? (
        <article className="panel empty paper-empty">
          <MessageSquareText size={36} />
          <p>{uploading ? "正在保存试卷任务。" : "逐题答案、知识点与证据会显示在这里"}</p>
        </article>
      ) : (
        <>
          <div className="paper-summary">
            <strong>{job.total_questions}</strong><span>识别题目</span>
            <strong>{job.completed_questions}</strong><span>完成</span>
            <strong className={job.failed_questions ? "failed" : ""}>{job.failed_questions}</strong><span>失败</span>
            <em>{job.filename}</em>
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
                >
                  <b>Q{item.number}</b>
                  <span>
                    {item.status === "pending" ? (item.attempts ? `等待自动重试 · 已尝试 ${item.attempts} 次` : "等待作答")
                      : item.status === "answering" ? (latestStep?.message ?? `正在作答 · 第 ${item.attempts} 次`)
                        : item.error ? `自动重试 ${item.attempts} 次后失败`
                          : item.grounded ? "证据充分" : "证据不足"}
                  </span>
                  <i className={item.error ? "failed" : item.status === "completed" ? "done" : "warn"} />
                </button>
                );
              })}
            </div>
            <article className="panel paper-answer">
              {!selected && <div className="empty"><LoaderCircle className={terminal ? "" : "spin"} size={30} /><p>等待题目识别结果</p></div>}
              {selected && (
                <>
                  <div className="result-meta">
                    <span className={selected.grounded ? "grounded" : "ungrounded"}>
                      Q{selected.number} · {selected.status === "completed" ? (selected.grounded ? "Grounded" : "Insufficient") : selected.status}
                    </span>
                    <div>
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
                        <strong id="current-question-title">Question {selected.number}</strong>
                      </div>
                      <small>
                        完整题干 · 数学排版
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
                      href={apiUrl(`/papers/jobs/${job.job_id}/source`)}
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
                  {selectedAgentSteps.length > 0 && (
                    <div className="agent-step-panel" aria-live="polite">
                      <div>
                        <strong>答题 Agent 进度</strong>
                        <span>第 {selected.attempts} 次尝试</span>
                      </div>
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
                    </div>
                  )}
                  {selected.status === "pending" || selected.status === "answering" ? (
                    <div className="answer-block pending-answer"><LoaderCircle className="spin" size={18} />等待后台完成本题</div>
                  ) : selected.error ? <ErrorBanner message={selected.error} /> : (
                    <div className="answer-block">
                      <span>AI 分步解答</span>
                      <div className="markdown">
                        <CitationMarkdown
                          citations={selected.citations}
                          query={selected.question_markdown.slice(0, 300)}
                        >
                          {selected.answer_markdown}
                        </CitationMarkdown>
                      </div>
                    </div>
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
                  <h3>关联知识点与难度</h3>
                  <div className="paper-knowledge">
                    {selected.knowledge_points.length === 0 && <p>未能可靠映射知识点。</p>}
                    {selected.knowledge_points.map((point, index) => (
                      <KnowledgeEvidenceCard point={point} index={index} key={point.code} />
                    ))}
                  </div>
                  <h3>本题答案引用</h3>
                  <div className="citations">
                    {selected.citations.length === 0 && <p>没有检索到可展示的引用。</p>}
                    <CitationReferenceList
                      citations={selected.citations}
                      query={selected.question_markdown.slice(0, 300)}
                    />
                  </div>
                </>
              )}
            </article>
          </div>
        </>
      )}
    </section>
  );
}
