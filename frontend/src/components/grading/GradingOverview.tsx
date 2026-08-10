import {
  ArrowLeft,
  CheckCircle2,
  CircleDashed,
  ClipboardCheck,
  LoaderCircle,
  PencilLine,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { type CSSProperties, useEffect, useRef, useState } from "react";

import type { GradingOverviewResponse } from "../../types";
import { Confidence, ErrorBanner } from "../Feedback";
import { Markdown } from "../Markdown";

const STATUS_LABELS: Record<GradingOverviewResponse["questions"][number]["status"], string> = {
  unassessed: "未评分",
  pending_review: "待人工复核",
  confirmed: "已确认",
  overridden: "已改分确认",
};

export function GradingOverview({
  overview,
  loading,
  error,
  onBack,
  onRefresh,
}: {
  overview: GradingOverviewResponse | null;
  loading: boolean;
  error: string | null;
  onBack: () => void;
  onRefresh: () => Promise<void>;
}) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const retryRef = useRef<HTMLButtonElement>(null);
  const refreshSequenceRef = useRef(0);
  const [completedAction, setCompletedAction] = useState<"load" | "retry" | "refresh" | null>(null);

  async function refreshOverview(action: "load" | "retry" | "refresh") {
    const sequence = ++refreshSequenceRef.current;
    await onRefresh();
    if (refreshSequenceRef.current === sequence) setCompletedAction(action);
  }

  useEffect(() => {
    if (!completedAction || loading) return;
    setCompletedAction(null);
    window.requestAnimationFrame(() => {
      if (error) {
        (retryRef.current ?? errorRef.current)?.focus();
      } else {
        headingRef.current?.focus();
      }
    });
  }, [completedAction, error, loading, overview]);

  return (
    <article className="panel grading-stage grading-overview">
      <header className="grading-stage-header">
        <button className="stage-back" onClick={onBack} type="button">
          <ArrowLeft size={16} />
          返回逐题评分
        </button>
        <div>
          <span>步骤 4 · 整卷总览</span>
          <h2 id="grading-stage-4-heading" ref={headingRef} tabIndex={-1}>
            沿试卷顺序检查整卷诊断
          </h2>
          <p>总览来自当前评分规则下每题最新的持久化结果；人工确认与改分状态单独标明。</p>
        </div>
        <button
          className="secondary"
          disabled={loading}
          onClick={() => void refreshOverview("refresh")}
          type="button"
        >
          {loading ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />}
          刷新总览
        </button>
      </header>

      <div
        className="overview-refresh-error"
        ref={overview && error ? errorRef : undefined}
        tabIndex={overview && error ? -1 : undefined}
      >
        <ErrorBanner message={overview ? error : null} />
      </div>
      {loading && !overview ? (
        <div className="empty overview-loading" role="status">
          <LoaderCircle className="spin" size={30} />
          <p>正在汇总当前评分结果…</p>
        </div>
      ) : error && !overview ? (
        <div
          className="empty overview-loading overview-error"
          ref={errorRef}
          role="alert"
          tabIndex={-1}
        >
          <TriangleAlert size={30} />
          <p>整卷总览加载失败：{error}</p>
          <button
            className="secondary"
            onClick={() => void refreshOverview("retry")}
            ref={retryRef}
            type="button"
          >
            <RefreshCw size={15} />
            重试加载总览
          </button>
        </div>
      ) : !overview ? (
        <div className="empty overview-loading">
          <ClipboardCheck size={30} />
          <p>尚未加载整卷总览。加载后会显示当前持久化评分结果。</p>
          <button
            className="secondary"
            onClick={() => void refreshOverview("load")}
            type="button"
          >
            加载总览
          </button>
        </div>
      ) : overview.total_questions === 0 ? (
        <div className="empty overview-loading" role="status">
          <CircleDashed size={30} />
          <p>总览已加载，但当前试卷没有可评分题目。请返回材料步骤检查答卷。</p>
        </div>
      ) : (
        <>
          <section
            className={`overview-baseline ${overview.incomplete ? "partial" : "complete"}`}
            aria-atomic="true"
            aria-label={overview.incomplete ? "整卷结果未完成" : "整卷结果已完成"}
            aria-live="polite"
            role="status"
          >
            <div className="overview-scoreline">
              <div>
                <span>{overview.incomplete ? "当前小计" : "整卷总分"}</span>
                <strong>{overview.total_awarded} / {overview.total_available}</strong>
                <small>{overview.percentage == null ? "暂无得分率" : `${overview.percentage.toFixed(1)}%`}</small>
              </div>
              <div>
                <span>评分进度</span>
                <strong>{overview.completed_questions} / {overview.total_questions}</strong>
                <small>{overview.pending_review_count} 题待复核</small>
              </div>
              <div>
                <span>人工结论</span>
                <strong>{overview.confirmed_count + overview.overridden_count} / {overview.total_questions}</strong>
                <small>{overview.overridden_count} 题已改分</small>
              </div>
            </div>
            <div className="overview-completion-note">
              {overview.incomplete ? <TriangleAlert size={18} /> : <CheckCircle2 size={18} />}
              <div>
                <strong>{overview.incomplete ? "这是部分结果，不是最终整卷结论" : "全部题目已有评分结果"}</strong>
                <p>
                  {overview.incomplete
                    ? `仍有 ${overview.total_questions - overview.completed_questions} 题未评分；当前分数与建议会随后续评分更新。`
                    : overview.pending_review_count > 0
                      ? `判分结果已齐全，但仍有 ${overview.pending_review_count} 题等待人工复核。`
                      : "所有题目均已有评分结果；人工复核状态见下方逐题轨道。"}
                </p>
              </div>
            </div>
          </section>

          <section className="overview-advice" aria-labelledby="overview-advice-title">
            <div>
              <span>总体建议</span>
              <h3 id="overview-advice-title">下一轮订正优先级</h3>
            </div>
            <div className="rubric-rich">
              <Markdown>{overview.overall_suggestion}</Markdown>
            </div>
            {overview.common_error_types.length > 0 && (
              <div className="overview-common-errors" aria-label="共性问题">
                <strong>共性问题</strong>
                {overview.common_error_types.map((type) => <span key={type}>{type}</span>)}
              </div>
            )}
          </section>

          <ol className="grading-diagnostic-track" aria-label="逐题诊断轨">
            {overview.questions.map((question) => {
              const ratio = question.awarded == null || question.available <= 0
                ? 0
                : Math.min(100, Math.max(0, question.awarded / question.available * 100));
              const trackStyle = { "--question-progress": `${ratio}%` } as CSSProperties;
              return (
                <li className={question.status} key={question.position}>
                  <div className="diagnostic-rail" aria-hidden="true">
                    <span>{String(question.position).padStart(2, "0")}</span>
                  </div>
                  <article>
                    <header>
                      <div>
                        <strong>Q{question.question_number}</strong>
                        <span className={`diagnostic-status ${question.status}`}>
                          {question.status === "confirmed" && <CheckCircle2 size={13} />}
                          {question.status === "overridden" && <PencilLine size={13} />}
                          {question.status === "pending_review" && <ShieldCheck size={13} />}
                          {question.status === "unassessed" && <CircleDashed size={13} />}
                          {STATUS_LABELS[question.status]}
                        </span>
                      </div>
                      <div className="diagnostic-score">
                        {question.awarded == null ? <strong>未评分</strong> : (
                          <strong>{question.awarded} / {question.available}</strong>
                        )}
                        {question.confidence != null && <Confidence value={question.confidence} />}
                      </div>
                    </header>
                    <div className="diagnostic-progress" style={trackStyle}>
                      <span />
                    </div>
                    {question.status === "unassessed" ? (
                      <p className="diagnostic-empty">返回逐题判分，为本题生成判分结果。</p>
                    ) : (
                      <div className="diagnostic-detail">
                        <div>
                          <strong>主要问题</strong>
                          {question.error_types.length > 0
                            ? question.error_types.map((type) => <span key={type}>{type}</span>)
                            : <small>未识别到共性错误标签</small>}
                        </div>
                        <div>
                          <strong>下一步</strong>
                          {question.suggestions.length > 0 ? (
                            <ul>
                              {question.suggestions.map((suggestion) => (
                                <li className="rubric-rich" key={suggestion}>
                                  <Markdown>{suggestion}</Markdown>
                                </li>
                              ))}
                            </ul>
                          ) : <small>保持当前解题方法，并在人工复核时核对细节。</small>}
                        </div>
                      </div>
                    )}
                  </article>
                </li>
              );
            })}
          </ol>
        </>
      )}
    </article>
  );
}
