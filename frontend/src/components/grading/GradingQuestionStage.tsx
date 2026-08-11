import {
  ArrowLeft,
  ArrowRight,
  BookOpenCheck,
  GraduationCap,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type {
  GradeResult,
  PaperAssessment,
  PaperJobQuestion,
  PaperJobResult,
  RubricSet,
} from "../../types";
import { Confidence, ErrorBanner } from "../Feedback";
import { Markdown, QuestionMarkdown } from "../Markdown";
import { AnswerDiagramView } from "../AnswerDiagramView";
import { AnswerImageView } from "../AnswerImageView";

function GradingSubmission({
  jobId,
  question,
}: {
  jobId: string;
  question: PaperJobQuestion;
}) {
  return (
    <div className="grading-submission">
      <details className="grading-submission-section">
        <summary>原题</summary>
        <div className="grading-submission-content grading-rich grading-question">
          <QuestionMarkdown>{question.question_markdown}</QuestionMarkdown>
        </div>
      </details>
      <details className="grading-submission-section">
        <summary>已保存答案</summary>
        <div className="grading-submission-content">
          <div className="grading-rich">
            <Markdown>{question.answer_markdown}</Markdown>
          </div>
          {question.diagrams.length > 0 && (
            <div className="answer-diagrams">
              {question.diagrams.map((diagram, index) => (
                <AnswerDiagramView
                  diagram={diagram}
                  jobId={jobId}
                  key={`${diagram.title}-${index}`}
                />
              ))}
            </div>
          )}
          {question.images.length > 0 && (
            <div className="answer-diagrams">
              {question.images.map((image, index) => (
                <AnswerImageView image={image} key={`${image.content_url}-${index}`} />
              ))}
            </div>
          )}
        </div>
      </details>
    </div>
  );
}

export function GradingQuestionStage({
  paper,
  rubric,
  assessments,
  selectedPosition,
  busy,
  error,
  onSelectPosition,
  onAssessQuestion,
  onBack,
  onViewRubric,
  onOverview,
}: {
  paper: PaperJobResult | null;
  rubric: RubricSet | null;
  assessments: PaperAssessment[];
  selectedPosition: number | null;
  busy: string | null;
  error: string | null;
  onSelectPosition: (position: number) => void;
  onAssessQuestion: (position: number) => Promise<GradeResult | undefined>;
  onBack: () => void;
  onViewRubric: () => void;
  onOverview: () => void;
}) {
  const latestByPosition = useMemo(() => {
    const map = new Map<number, PaperAssessment>();
    if (!rubric) return map;
    for (const item of assessments) {
      if (item.rubric_set_id !== rubric.id) continue;
      if (!map.has(item.question_position)) map.set(item.question_position, item);
    }
    return map;
  }, [assessments, rubric]);
  const selectedQuestion = paper?.questions.find((item) => item.position === selectedPosition) ?? null;
  const selectedAssessment = selectedPosition == null ? null : latestByPosition.get(selectedPosition) ?? null;
  const selectedResult: GradeResult | null = selectedAssessment?.result ?? null;
  const regenerating = selectedQuestion !== null
    && selectedResult !== null
    && busy === `grade-${selectedQuestion.position}`;
  const selectedAcceptedCriteria = selectedQuestion && rubric
    ? rubric.criteria.filter(
        (item) =>
          item.review_status === "accepted"
          && item.question_number === selectedQuestion.number,
      ).length
    : 0;
  const persistedStatus = selectedAssessment?.status ?? selectedResult?.status ?? null;
  const reviewStatusCopy = persistedStatus === "confirmed"
    ? {
        score: "人工复核已确认",
        banner: "评分结果已由人工确认",
      }
    : persistedStatus === "overridden"
      ? {
          score: "人工改分已确认",
          banner: "评分结果已由人工改分确认",
        }
      : selectedResult?.manual_review_required === false
        ? {
            score: "评分已完成",
            banner: "评分结果已完成，无需人工复核",
          }
        : {
            score: "等待人工复核",
            banner: "判分结果已进入人工复核队列",
          };
  const reportHeadingRef = useRef<HTMLHeadingElement>(null);
  const pendingSelectionFocusRef = useRef<number | null>(null);
  const activeContextRef = useRef({
    paperJobId: paper?.job_id ?? null,
    rubricId: rubric?.id ?? null,
    selectedPosition,
  });
  activeContextRef.current = {
    paperJobId: paper?.job_id ?? null,
    rubricId: rubric?.id ?? null,
    selectedPosition,
  };
  const completionSequenceRef = useRef(0);
  const [completionAnnouncement, setCompletionAnnouncement] = useState<{
    sequence: number;
    message: string;
  } | null>(null);

  useEffect(() => {
    if (
      selectedPosition == null
      || pendingSelectionFocusRef.current !== selectedPosition
    ) return;
    pendingSelectionFocusRef.current = null;
    setCompletionAnnouncement(null);
    window.requestAnimationFrame(() => reportHeadingRef.current?.focus());
  }, [selectedPosition]);

  function selectQuestion(position: number) {
    pendingSelectionFocusRef.current = position;
    onSelectPosition(position);
    if (position === selectedPosition) {
      pendingSelectionFocusRef.current = null;
      setCompletionAnnouncement(null);
      window.requestAnimationFrame(() => reportHeadingRef.current?.focus());
    }
  }

  async function assessQuestion(position: number) {
    const paperJobId = paper?.job_id ?? null;
    const rubricId = rubric?.id ?? null;
    const result = await onAssessQuestion(position);
    if (
      !result
      || activeContextRef.current.paperJobId !== paperJobId
      || activeContextRef.current.rubricId !== rubricId
      || activeContextRef.current.selectedPosition !== position
    ) return;
    setCompletionAnnouncement({
      sequence: ++completionSequenceRef.current,
      message: `Q${selectedQuestion?.number ?? position} 判分结果已生成，得分 ${result.total_awarded} / ${result.total_available}。`,
    });
    window.requestAnimationFrame(() => reportHeadingRef.current?.focus());
  }

  return (
    <div className="grading-stage-three">
      <header className="grading-stage-header grading-stage-three-header">
        <button className="stage-back" disabled={busy !== null} onClick={onBack} type="button">
          <ArrowLeft size={16} />
          返回材料
        </button>
        <div>
          <span>步骤 2 · 逐题判分</span>
          <h2 id="grading-stage-3-heading" tabIndex={-1}>核对判分结果</h2>
          <p>先看学生证据和判分结论；原始得分点仅在需要追溯时展开。</p>
        </div>
        <div className="grading-stage-header-actions">
          <button className="secondary" disabled={busy !== null} onClick={onViewRubric} type="button">
            <BookOpenCheck size={16} />
            查看评分标准
          </button>
          <button className="secondary stage-overview-link" disabled={busy !== null} onClick={onOverview} type="button">
            查看整卷结果
            <ArrowRight size={16} />
          </button>
        </div>
      </header>
      <ErrorBanner message={error} />

      <div className="grading-paper-workspace">
        <nav className="panel grading-question-nav" aria-label="可评分题目">
          <div className="panel-title">
            <div>
              <span>作答记录</span>
              <h2>{paper?.display_name || paper?.filename || "未选择试卷"}</h2>
            </div>
          </div>
          <div className="grading-question-picker">
            {paper?.questions.map((item) => {
              const assessment = latestByPosition.get(item.position);
              return (
                <button
                  aria-controls="grading-question-report"
                  disabled={busy !== null}
                  aria-current={selectedPosition === item.position ? "true" : undefined}
                  className={selectedPosition === item.position ? "active" : ""}
                  key={item.position}
                  onClick={() => selectQuestion(item.position)}
                  type="button"
                >
                  <span>
                    <b>Q{item.number}</b>
                    <small>{item.status === "completed" ? "答案已保存" : "暂无完整答案"}</small>
                  </span>
                  {assessment
                    ? <em>{assessment.result.total_awarded}/{assessment.result.total_available}</em>
                    : <i />}
                </button>
              );
            })}
          </div>
        </nav>

        <article
          aria-labelledby="grading-report-heading"
          aria-busy={regenerating || undefined}
          className="panel grading-report"
          id="grading-question-report"
        >
          <div aria-atomic="true" aria-live="polite" className="sr-only">
            {completionAnnouncement && (
              <span key={completionAnnouncement.sequence} role="status">
                {completionAnnouncement.message}
              </span>
            )}
          </div>
          {!selectedQuestion ? (
            <div className="empty">
              <GraduationCap size={34} />
              <h2 className="sr-only" id="grading-report-heading" ref={reportHeadingRef} tabIndex={-1}>
                评分报告
              </h2>
              <p>选择一道已有答案的题目。</p>
            </div>
          ) : !selectedResult ? (
            <div className="grade-ready">
              <div>
                <span>Q{selectedQuestion.number}</span>
                <h2 id="grading-report-heading" ref={reportHeadingRef} tabIndex={-1}>
                  开始本题判分
                </h2>
              </div>
              <GradingSubmission jobId={paper!.job_id} key={selectedQuestion.position} question={selectedQuestion} />
              {selectedAcceptedCriteria === 0 && (
                <p className="inline-warning">
                  <TriangleAlert size={14} />
                  当前评分标准没有匹配 Q{selectedQuestion.number} 的已接受得分点。
                </p>
              )}
              <button
                className="primary grading-primary-action"
                disabled={
                  rubric?.status !== "confirmed"
                  || selectedQuestion.status !== "completed"
                  || selectedAcceptedCriteria === 0
                  || busy !== null
                }
                onClick={() => void assessQuestion(selectedQuestion.position)}
                type="button"
              >
                {busy === `grade-${selectedQuestion.position}`
                  ? <LoaderCircle className="spin" size={18} />
                  : <GraduationCap size={18} />}
                生成判分结果
              </button>
            </div>
          ) : (
            <>
              <h2 className="sr-only" id="grading-report-heading" ref={reportHeadingRef} tabIndex={-1}>
                Q{selectedQuestion.number} 判分结果
              </h2>
              
              <div className="score-hero">
                <div>
                  <strong>{selectedResult.total_awarded}</strong>
                  <span>/ {selectedResult.total_available}</span>
                </div>
                <p>{reviewStatusCopy.score}</p>
              </div>
              <GradingSubmission jobId={paper!.job_id} key={selectedQuestion.position} question={selectedQuestion} />
              <div className="grading-assurance">
                <span>模型置信度 <Confidence value={selectedResult.confidence} /></span>
                <span>{selectedResult.rubric_awards.length} 个得分点判定</span>
                <span>{selectedResult.symbolic_checks.length} 项独立检查</span>
              </div>
              {selectedResult.warnings.map((warning) => (
                <p className="inline-warning" key={warning}>
                  <TriangleAlert size={14} />
                  {warning}
                </p>
              ))}
              <div className="rubric-list grading-award-list">
                {selectedResult.rubric_awards.map((item) => {
                  const verdict = item.awarded <= 0
                    ? "未得分"
                    : item.awarded >= item.max_marks
                      ? "已得分"
                      : "部分得分";
                  return (
                    <article
                      className={`grading-award ${item.awarded > 0 ? "awarded" : "missed"}`}
                      key={item.criterion_id}
                    >
                      <header>
                        <div>
                          <span>{item.mark_type ?? item.criterion_id}</span>
                          <strong>{verdict}</strong>
                        </div>
                        <b>{item.awarded}/{item.max_marks} 分</b>
                      </header>
                      <section className="grading-award-evidence">
                        <span>学生证据</span>
                        {item.student_evidence
                          ? <blockquote><Markdown normalizeBareLatex>{item.student_evidence}</Markdown></blockquote>
                          : <p>答案中未找到支持该得分点的直接证据。</p>}
                      </section>
                      <section className="grading-award-rationale">
                        <span>判分理由</span>
                        <div className="rubric-rich">
                          <Markdown normalizeBareLatex>{item.rationale}</Markdown>
                        </div>
                      </section>
                      {item.error_types.length > 0 && (
                        <div className="error-tags">
                          {item.error_types.map((type) => <span key={type}>{type}</span>)}
                        </div>
                      )}
                      {item.improvement_suggestion && (
                        <div className="improvement">
                          <span>改进：</span>
                          <Markdown>{item.improvement_suggestion}</Markdown>
                        </div>
                      )}
                      <details className="grading-award-criterion">
                        <summary>查看原始得分点</summary>
                        <div className="rubric-rich rubric-description">
                          <Markdown>{item.description}</Markdown>
                        </div>
                        <small>{item.criterion_id}</small>
                      </details>
                    </article>
                  );
                })}
              </div>
              {selectedResult.improvement_suggestions.length > 0 && (
                <section className="improvement-summary">
                  <h3>针对性改进建议</h3>
                  {selectedResult.improvement_suggestions.map((item) => (
                    <div className="rubric-rich" key={item}>
                      <Markdown>{item}</Markdown>
                    </div>
                  ))}
                </section>
              )}
              <div className="review-required">
                <ShieldCheck size={18} />
                {reviewStatusCopy.banner}
              </div>
              <button
                aria-busy={regenerating || undefined}
                aria-live="polite"
                className="secondary"
                disabled={busy !== null}
                onClick={() => void assessQuestion(selectedQuestion.position)}
                type="button"
              >
                {regenerating
                  ? <LoaderCircle className="spin" size={15} />
                  : <RefreshCw size={15} />}
                {regenerating ? "正在重新判分…" : "重新判分"}
              </button>
            </>
          )}
        </article>
      </div>
    </div>
  );
}
