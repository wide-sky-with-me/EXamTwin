import {
  ArrowRight,
  BookOpenCheck,
  FileCheck2,
  LoaderCircle,
  RefreshCw,
  UploadCloud,
} from "lucide-react";
import { type ChangeEvent, useEffect, useRef, useState } from "react";

import type {
  GradingPaper,
  PaperJobResult,
  RubricSet,
  SourceDocument,
} from "../../types";
import { ErrorBanner } from "../Feedback";

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
  onUploadScheme,
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
  onUploadScheme: (event: ChangeEvent<HTMLInputElement>) => Promise<void>;
  onContinue: () => Promise<void>;
}) {
  const paperSelectRef = useRef<HTMLSelectElement>(null);
  const documentSelectRef = useRef<HTMLSelectElement>(null);
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const retryButtonRef = useRef<HTMLButtonElement>(null);
  const [retryPhase, setRetryPhase] = useState<"idle" | "pending" | "settled">("idle");
  const [retryAnnouncement, setRetryAnnouncement] = useState("");
  const selectedPaperSummary = papers.find((item) => item.job_id === paperId) ?? null;
  const selectedDocument = documents.find((item) => item.id === documentId) ?? null;
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

  return (
    <article
      aria-busy={contextLoading}
      className="panel grading-stage grading-materials-stage"
    >
      <header className="grading-stage-header">
        <div>
          <span className="grading-accent-text">步骤 1 · 材料准备</span>
          <h2>先确认本次评分使用的两份材料</h2>
          <p>答卷来自已完成的整卷作答；Mark Scheme 必须是对应试卷的官方版本。</p>
        </div>
      </header>
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

      <div className="grading-source-cards">
        <section aria-busy={papersLoading} className="grading-source-card grading-contrast-boundary">
          <div className="grading-source-heading">
            <span className="grading-accent-text">A</span>
            <div>
              <strong>已完成作答</strong>
              <small>选择需要评分的答卷记录</small>
            </div>
          </div>
          <select
            aria-label="选择作答记录"
            className="grading-control-boundary"
            disabled={materialSelectionBusy || papersLoading || papersError !== null || papers.length === 0}
            onChange={(event) => onChoosePaper(event.target.value)}
            value={paperId}
            ref={paperSelectRef}
          >
            <option value="">{paperPlaceholder}</option>
            {papers.map((item) => (
              <option key={item.job_id} value={item.job_id}>
                {item.filename} · {item.completed_questions}/{item.total_questions} 题
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
          {selectedPaperSummary && (
            <div className="grading-source-summary">
              <FileCheck2 size={19} />
              <div>
                <strong>{selectedPaperSummary.filename}</strong>
                <span>
                  {selectedPaperSummary.completed_questions} / {selectedPaperSummary.total_questions}
                  {" "}题已有答案
                  {selectedPaperSummary.failed_questions
                    ? ` · ${selectedPaperSummary.failed_questions} 题需处理`
                    : " · 作答完整"}
                </span>
              </div>
            </div>
          )}
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
            <span className="grading-accent-text">B</span>
            <div>
              <strong>官方 Mark Scheme</strong>
              <small>选择已转换版本，或上传新文件</small>
            </div>
          </div>
          <div className="scheme-picker">
            <select
              aria-label="选择 Mark Scheme"
              className="grading-control-boundary"
              disabled={
                materialSelectionBusy
                || documentsLoading
                || documentsError !== null
                || documents.length === 0
              }
              onChange={(event) => onChooseDocument(event.target.value)}
              value={documentId}
              ref={documentSelectRef}
            >
              <option value="">{documentPlaceholder}</option>
              {documents.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.filename} · {item.status}
                </option>
              ))}
            </select>
            <label
              aria-disabled={busy !== null}
              className="secondary file-button grading-control-boundary"
            >
              {busy === "upload"
                ? <LoaderCircle className="spin" size={15} />
                : <UploadCloud size={15} />}
              上传
              <input
                accept=".pdf,.md,.markdown"
                disabled={busy !== null}
                onChange={(event) => void onUploadScheme(event)}
                type="file"
                ref={uploadInputRef}
              />
            </label>
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
          {selectedDocument && (
            <div className="grading-source-summary">
              <BookOpenCheck size={19} />
              <div>
                <strong>{selectedDocument.filename}</strong>
                <span>
                  {(["converted", "indexed"] as string[]).includes(selectedDocument.status)
                    ? "内容已就绪，可解析评分标准"
                    : selectedDocument.status}
                  {selectedDocument.page_count ? ` · ${selectedDocument.page_count} 页` : ""}
                </span>
              </div>
            </div>
          )}
        </section>
      </div>
      {discoveryError && (
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
          <small>将同时重新检查作答记录和 Mark Scheme。</small>
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
      <footer className="grading-stage-actions">
        <small>
          {confirmedRubric
            ? "评分标准已经确认，可直接核对这份答卷的判分结果。"
            : matchingRubric
              ? "这版评分标准尚未确认，开始判分前需要先核对得分点。"
              : "解析后需要先确认评分标准；此步骤不会立即给答案评分。"}
        </small>
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
              ? "确认评分标准"
              : "解析评分标准"}
        </button>
      </footer>
    </article>
  );
}
