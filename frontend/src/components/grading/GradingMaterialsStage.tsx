import { Tooltip } from "antd";
import {
  ArrowRight,
  BookOpenCheck,
  FileCheck2,
  FileText,
  LoaderCircle,
  RefreshCw,
  Settings2,
  Sparkles,
  UploadCloud,
} from "lucide-react";
import { type ChangeEvent, useEffect, useRef, useState } from "react";

import type {
  GradingPaper,
  PaperJobResult,
  RubricSet,
  SourceDocument,
} from "../../types";
import { PAPER_JOB_STAGE_LABELS, paperProgress } from "../../lib/paper-job";
import type { TaskStreamState } from "../../lib/task-events";
import { paperMaterialMeta, schemeMaterialMeta } from "../../lib/grading-materials";
import { ErrorBanner } from "../Feedback";
import {
  AnswerRecordManagerDialog,
  MarkSchemeManagerDialog,
} from "./GradingMaterialManagerDialog";

export function GradingMaterialsStage({
  papers,
  documents,
  papersLoading,
  papersError,
  paperId,
  documentId,
  documentsLoading,
  documentsError,
  paper,
  rubric,
  busy,
  error,
  onRetryDiscovery,
  onChoosePaper,
  onChooseDocument,
  onDeleteDocument,
  onDeletePaper,
  onRenameDocument = async () => undefined,
  onRenamePaper = async () => undefined,
  onUploadScheme,
  onGenerateScheme = async () => undefined,
  onImportExternal = async () => false,
  importJob = null,
  importStreamState = "idle",
  onReconnectImport = () => undefined,
  sourceBookletRequired = false,
  onContinue,
}: {
  papers: GradingPaper[];
  documents: SourceDocument[];
  papersLoading: boolean;
  papersError: string | null;
  paperId: string;
  documentId: string;
  documentsLoading: boolean;
  documentsError: string | null;
  paper: PaperJobResult | null;
  rubric: RubricSet | null;
  busy: string | null;
  error: string | null;
  onRetryDiscovery: () => Promise<void>;
  onChoosePaper: (paperId: string) => void;
  onChooseDocument: (documentId: string) => void;
  onDeleteDocument: (documentId: string) => Promise<void>;
  onDeletePaper: (paperId: string) => Promise<void>;
  onRenameDocument?: (documentId: string, displayName: string) => Promise<void>;
  onRenamePaper?: (paperId: string, displayName: string) => Promise<void>;
  onUploadScheme: (event: ChangeEvent<HTMLInputElement>) => Promise<void>;
  onGenerateScheme?: () => Promise<void>;
  onImportExternal?: (
    questionFile: File,
    answerFile: File,
    sourceBooklet?: File | null,
  ) => Promise<boolean>;
  importJob?: PaperJobResult | null;
  importStreamState?: TaskStreamState;
  onReconnectImport?: () => void;
  sourceBookletRequired?: boolean;
  onContinue: () => Promise<void>;
}) {
  const paperSelectRef = useRef<HTMLSelectElement>(null);
  const documentSelectRef = useRef<HTMLSelectElement>(null);
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const retryButtonRef = useRef<HTMLButtonElement>(null);
  const [retryPhase, setRetryPhase] = useState<"idle" | "pending" | "settled">("idle");
  const [retryAnnouncement, setRetryAnnouncement] = useState("");
  const [sourceMode, setSourceMode] = useState<"system" | "upload">("system");
  const [paperManagerOpen, setPaperManagerOpen] = useState(false);
  const [schemeManagerOpen, setSchemeManagerOpen] = useState(false);
  const [questionFile, setQuestionFile] = useState<File | null>(null);
  const [answerFile, setAnswerFile] = useState<File | null>(null);
  const [sourceBooklet, setSourceBooklet] = useState<File | null>(null);
  const [importNotice, setImportNotice] = useState("");
  const importRunning = Boolean(
    importJob && !["completed", "partial_failed", "failed"].includes(importJob.status),
  );
  const matchingRubric = rubric?.paper_job_id === paperId && rubric.source_document_id === documentId
    ? rubric
    : null;
  const confirmedRubric = matchingRubric?.status === "confirmed";
  const materialSelectionBusy = busy === "upload" || busy === "create-rubric";
  const discoveryLoading = papersLoading || documentsLoading;
  const discoveryError = papersError !== null || documentsError !== null;
  const paperContextLoading = busy === "loading-paper";
  const rubricContextLoading = busy === "loading-rubric";
  const contextLoading = paperContextLoading || rubricContextLoading;
  const paperPlaceholder = papersLoading
    ? "正在加载作答记录…"
    : papersError
      ? "作答记录加载失败"
      : papers.length
        ? "请选择作答记录"
        : "暂无可评分作答记录";
  const documentPlaceholder = documentsLoading
    ? "正在加载 Mark Scheme…"
    : documentsError
      ? "Mark Scheme 加载失败"
      : documents.length
        ? "请选择 Mark Scheme"
        : "暂无可用 Mark Scheme";

  async function retryDiscovery() {
    setRetryAnnouncement("");
    setRetryPhase("pending");
    try {
      await onRetryDiscovery();
    } catch {
      // Discovery errors are rendered from the paper and document error props.
    } finally {
      setRetryPhase("settled");
    }
  }

  async function importExternal() {
    if (!questionFile || !answerFile) return;
    setImportNotice("");
    const created = await onImportExternal(questionFile, answerFile, sourceBooklet);
    if (!created) return;
    setImportNotice("后台任务已创建，本页会持续显示解析进度，完成后自动进入作答记录。");
    setQuestionFile(null);
    setAnswerFile(null);
  }

  useEffect(() => {
    if (retryPhase !== "settled" || discoveryLoading) return;
    setRetryPhase("idle");
    if (discoveryError) {
      window.requestAnimationFrame(() => retryButtonRef.current?.focus());
      return;
    }
    setRetryAnnouncement("材料列表已更新。");
    window.requestAnimationFrame(() => {
      const firstValidControl = [
        paperSelectRef.current,
        documentSelectRef.current,
        uploadInputRef.current,
      ].find((control) => control !== null && !control.disabled);
      firstValidControl?.focus();
    });
  }, [discoveryError, discoveryLoading, retryPhase]);

  useEffect(() => {
    if (
      importJob
      && ["completed", "partial_failed"].includes(importJob.status)
      && papers.some((item) => item.job_id === importJob.job_id)
    ) {
      setSourceMode("system");
    }
  }, [importJob, papers]);

  return (
    <article
      aria-busy={contextLoading}
      className="panel grading-stage grading-materials-stage"
    >
      <header className="grading-stage-header">
        <div>
          <h2>评分材料</h2>
        </div>
      </header>
      <div className="segmented-control grading-source-mode" role="group" aria-label="答卷来源">
        <button aria-pressed={sourceMode === "system"} onClick={() => setSourceMode("system")} type="button">系统记录</button>
        <button aria-pressed={sourceMode === "upload"} onClick={() => setSourceMode("upload")} type="button">上传答卷</button>
      </div>
      {contextLoading && (
        <div
          aria-atomic="true"
          aria-live="polite"
          className="grading-discovery-state is-loading grading-context-loading"
          role="status"
        >
          <LoaderCircle aria-hidden="true" className="spin" size={15} />
          {paperContextLoading
            ? "正在加载所选答卷及其评分上下文…"
            : "正在加载所选 Mark Scheme 对应的评分规则…"}
        </div>
      )}

      {sourceMode === "system" ? (
      <div className="grading-source-cards">
        <section aria-busy={papersLoading} className="grading-source-card grading-contrast-boundary">
          <div className="grading-source-heading">
            <span className="grading-source-icon"><FileCheck2 aria-hidden="true" size={18} /></span>
            <div>
              <strong>作答记录</strong>
            </div>
            <button
              className="secondary grading-manage-materials"
              disabled={materialSelectionBusy || papersLoading}
              onClick={() => setPaperManagerOpen(true)}
              type="button"
            >
              <Settings2 aria-hidden="true" size={15} />管理答卷
            </button>
          </div>
          <select
            aria-label="选择作答记录"
            className="grading-control-boundary grading-material-select-trigger"
            disabled={materialSelectionBusy || papersLoading || papersError !== null || papers.length === 0}
            onChange={(event) => onChoosePaper(event.target.value)}
            ref={paperSelectRef}
            value={paperId}
          >
            <option value="">{paperPlaceholder}</option>
            {papers.map((item) => (
              <option key={item.job_id} value={item.job_id}>
                {item.display_name || item.filename} · {paperMaterialMeta(item)}
              </option>
            ))}
          </select>
          {papersLoading ? (
            <div className="grading-discovery-state is-loading" role="status">
              <LoaderCircle aria-hidden="true" className="spin" size={15} />
              正在查找可评分的作答记录…
            </div>
          ) : papersError ? (
            <div className="grading-discovery-state is-error" role="alert">
              作答记录加载失败：{papersError}
            </div>
          ) : papers.length === 0 ? (
            <div className="grading-discovery-state is-empty" role="status">
              还没有已完成的作答记录。请先完成整卷作答，再返回此处评分。
            </div>
          ) : null}
          {paper && (
            <div className="grading-question-sample" aria-label="所选答卷内容">
              {paper.questions.slice(0, 4).map((item) => (
                <span key={item.position}>
                  <b>Q{item.number}</b>
                  {item.status === "completed" ? "答案已保存" : "暂无完整答案"}
                </span>
              ))}
              {paper.questions.length > 4 && <small>另有 {paper.questions.length - 4} 题</small>}
            </div>
          )}
        </section>

        <section aria-busy={documentsLoading} className="grading-source-card grading-contrast-boundary">
          <div className="grading-source-heading">
            <span className="grading-source-icon"><BookOpenCheck aria-hidden="true" size={18} /></span>
            <div>
              <strong>Mark Scheme</strong>
            </div>
            <button
              className="secondary grading-manage-materials"
              disabled={materialSelectionBusy || documentsLoading}
              onClick={() => setSchemeManagerOpen(true)}
              type="button"
            >
              <Settings2 aria-hidden="true" size={15} />管理标准
            </button>
          </div>
          <div className="scheme-picker">
            <select
              aria-label="选择 Mark Scheme"
              className="grading-control-boundary grading-material-select-trigger"
              disabled={
                materialSelectionBusy
                || documentsLoading
                || documentsError !== null
                || documents.length === 0
              }
              onChange={(event) => onChooseDocument(event.target.value)}
              ref={documentSelectRef}
              value={documentId}
            >
              <option value="">{documentPlaceholder}</option>
              {documents.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.display_name || item.filename} · {schemeMaterialMeta(item)}
                </option>
              ))}
            </select>
            <Tooltip mouseEnterDelay={0.3} title="上传官方版本">
              <label
                aria-disabled={busy !== null}
                className="secondary file-button grading-control-boundary grading-scheme-upload"
              >
                {busy === "upload"
                  ? <LoaderCircle aria-hidden="true" className="spin" size={17} />
                  : <UploadCloud aria-hidden="true" size={17} />}
                <input
                  aria-label="上传官方 Mark Scheme"
                  accept=".pdf,.md,.markdown"
                  disabled={busy !== null}
                  onChange={(event) => void onUploadScheme(event)}
                  ref={uploadInputRef}
                  type="file"
                />
              </label>
            </Tooltip>
            <button
              className="secondary grading-control-boundary"
              disabled={!paperId || busy !== null}
              onClick={() => void onGenerateScheme()}
              type="button"
            >
              {busy === "generate-rubric"
                ? <LoaderCircle className="spin" size={15} />
                : <Sparkles size={15} />}
              AI 生成临时标准
            </button>
          </div>
          {documentsLoading ? (
            <div className="grading-discovery-state is-loading" role="status">
              <LoaderCircle aria-hidden="true" className="spin" size={15} />
              正在查找可用的 Mark Scheme…
            </div>
          ) : documentsError ? (
            <div className="grading-discovery-state is-error" role="alert">
              Mark Scheme 加载失败：{documentsError}
            </div>
          ) : documents.length === 0 ? (
            <div className="grading-discovery-state is-empty" role="status">
              还没有已转换的 Mark Scheme。你可以在此上传官方文件并完成转换。
            </div>
          ) : null}
        </section>
      </div>
      ) : (
        <section className="grading-external-upload">
          <div className="grading-source-card grading-contrast-boundary">
            <div className="grading-source-heading"><span className="grading-source-icon"><FileText aria-hidden="true" size={18} /></span><div><strong>试卷文件</strong><small>PDF 或 Markdown</small></div></div>
            <input aria-label="上传待评分试卷" accept=".pdf,.md,.markdown" onChange={(event) => setQuestionFile(event.target.files?.[0] ?? null)} type="file" />
          </div>
          <div className="grading-source-card grading-contrast-boundary">
            <div className="grading-source-heading"><span className="grading-source-icon"><FileCheck2 aria-hidden="true" size={18} /></span><div><strong>答案文件</strong><small>PDF 或 Markdown</small></div></div>
            <input aria-label="上传答案文件" accept=".pdf,.md,.markdown" onChange={(event) => setAnswerFile(event.target.files?.[0] ?? null)} type="file" />
          </div>
          <div className="grading-source-card grading-contrast-boundary">
            <div className="grading-source-heading"><span className="grading-source-icon"><BookOpenCheck aria-hidden="true" size={18} /></span><div><strong>Source Booklet{sourceBookletRequired ? "（必需）" : "（可选）"}</strong><small>Extract、数据或案例资料</small></div></div>
            <input aria-label="上传 Source Booklet" accept=".pdf" onChange={(event) => setSourceBooklet(event.target.files?.[0] ?? null)} type="file" />
          </div>
          <button className="primary" disabled={!questionFile || !answerFile || busy !== null || importRunning || (sourceBookletRequired && !sourceBooklet)} onClick={() => void importExternal()} type="button">
            {busy === "import-answer" ? <LoaderCircle className="spin" size={16} /> : <UploadCloud size={16} />}
            导入并解析答卷
          </button>
          {importNotice && <div className="notice" role="status">{importNotice}</div>}
          {importJob && (
            <div
              className={`grading-import-task ${importJob.status}`}
              role={importJob.status === "failed" ? "alert" : "status"}
            >
              <div>
                {importRunning && <LoaderCircle aria-hidden="true" className="spin" size={17} />}
                <strong>
                  {importJob.status === "completed"
                    ? "答卷解析完成"
                    : importJob.status === "partial_failed"
                      ? "答卷部分解析完成"
                      : importJob.status === "failed"
                        ? "答卷解析失败"
                        : PAPER_JOB_STAGE_LABELS[importJob.stage]}
                </strong>
                <span>
                  {importJob.completed_questions} / {importJob.total_questions || "—"} 题
                  {importRunning ? ` · ${paperProgress(importJob)}%` : ""}
                </span>
              </div>
              {importJob.error && <p>{importJob.error}</p>}
              {importRunning && importStreamState === "idle" && (
                <button className="secondary" onClick={onReconnectImport} type="button">
                  <RefreshCw size={15} />重新连接进度
                </button>
              )}
            </div>
          )}
        </section>
      )}
      {sourceMode === "system" && discoveryError && (
        <div className="grading-discovery-retry">
          <button
            className="secondary grading-control-boundary"
            disabled={discoveryLoading}
            onClick={() => void retryDiscovery()}
            type="button"
            ref={retryButtonRef}
          >
            {discoveryLoading
              ? <LoaderCircle aria-hidden="true" className="spin" size={15} />
              : <RefreshCw aria-hidden="true" size={15} />}
            {discoveryLoading ? "正在重试材料列表…" : "重试材料列表"}
          </button>
        </div>
      )}
      <div
        aria-atomic="true"
        aria-live="polite"
        className="sr-only"
        role="status"
      >
        {retryAnnouncement}
      </div>

      <ErrorBanner message={error} />
      {sourceMode === "system" && <footer className="grading-stage-actions">
        <button
          className="primary grading-primary-action"
          disabled={
            !paperId
            || !documentId
            || papersLoading
            || documentsLoading
            || discoveryError
            || busy !== null
          }
          onClick={() => void onContinue()}
          type="button"
        >
          {busy === "create-rubric"
            ? <LoaderCircle className="spin" size={17} />
            : <ArrowRight size={17} />}
          {confirmedRubric
            ? "开始逐题判分"
            : matchingRubric
              ? "审核评分标准"
              : "解析评分标准"}
        </button>
      </footer>}
      <AnswerRecordManagerDialog
        onDelete={onDeletePaper}
        onOpenChange={setPaperManagerOpen}
        onRename={onRenamePaper}
        onSelect={onChoosePaper}
        open={paperManagerOpen}
        papers={papers}
        selectedId={paperId}
      />
      <MarkSchemeManagerDialog
        documents={documents}
        onDelete={onDeleteDocument}
        onOpenChange={setSchemeManagerOpen}
        onRename={onRenameDocument}
        onSelect={onChooseDocument}
        open={schemeManagerOpen}
        selectedId={documentId}
      />
    </article>
  );
}
