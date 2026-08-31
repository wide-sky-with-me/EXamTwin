import {
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";

import type { GradeResult, PaperJobQuestion } from "../../types";
import { AnswerArtifactFlow } from "../AnswerArtifactFlow";
import { Confidence } from "../Feedback";
import { Markdown, QuestionMarkdown } from "../Markdown";

export function GradingSubmission({
  jobId,
  subjectId,
  question,
}: {
  jobId: string;
  subjectId: string;
  question: PaperJobQuestion;
}) {
  return (
    <div className="grading-submission">
      <details className="grading-submission-section grading-submission-answer" open>
        <summary>已保存答案</summary>
        <div className="grading-submission-content">
          <AnswerArtifactFlow
            answerMarkdown={question.answer_markdown}
            diagrams={question.diagrams}
            images={question.images}
            jobId={jobId}
            subjectId={subjectId}
            renderMarkdown={(markdown, key) => (
              <div className="grading-rich" key={key}>
                <Markdown>{markdown}</Markdown>
              </div>
            )}
          />
        </div>
      </details>
      <details className="grading-submission-section grading-submission-question">
        <summary>原题</summary>
        <div className="grading-submission-content grading-rich grading-question">
          <QuestionMarkdown subjectId={subjectId}>{question.question_markdown}</QuestionMarkdown>
        </div>
      </details>
    </div>
  );
}

export function GradingReportWorkspace({
  busy,
  jobId,
  onRegenerate,
  question,
  regenerating,
  result,
  reviewBanner,
  scoreStatus,
  subjectId,
}: {
  busy: boolean;
  jobId: string;
  onRegenerate: () => void;
  question: PaperJobQuestion;
  regenerating: boolean;
  result: GradeResult;
  reviewBanner: string;
  scoreStatus: string;
  subjectId: string;
}) {
  const knowledgeCodeSet = new Set<string>();
  for (const award of result.rubric_awards) {
    for (const code of award.knowledge_codes) {
      const value = code.trim();
      if (value) knowledgeCodeSet.add(value);
    }
  }
  const knowledgeCodes = [...knowledgeCodeSet].sort();
  return (
    <div className="grading-report-layout">
      <section aria-label="作答与判分" className="grading-primary-column">
        <div className="grading-score-summary">
          <div className="score-hero">
            <div>
              <strong>{result.total_awarded}</strong>
              <span>/ {result.total_available}</span>
            </div>
            <p>{scoreStatus}</p>
          </div>
          <div className="grading-assurance">
            <span>模型置信度 <Confidence value={result.confidence} /></span>
            <span>{result.rubric_awards.length} 个得分点判定</span>
            <span>{result.symbolic_checks.length} 项独立检查</span>
          </div>
        </div>

        <GradingSubmission
          jobId={jobId}
          key={question.position}
          question={question}
          subjectId={subjectId}
        />

        {result.warnings.length > 0 && (
          <div className="grading-warnings">
            {result.warnings.map((warning) => (
              <p className="inline-warning" key={warning}>
                <TriangleAlert size={14} />
                {warning}
              </p>
            ))}
          </div>
        )}

        <section className="grading-rubric-work" aria-labelledby="grading-rubric-work-heading">
          <header>
            <div>
              <span>当前评分标准</span>
              <h3 id="grading-rubric-work-heading">得分点判定</h3>
            </div>
            <b>{result.rubric_awards.length} 项</b>
          </header>
          {result.rubric_awards.length === 0 ? (
            <p className="grading-evidence-empty">本题没有可展示的得分点判定。</p>
          ) : (
            <div className="rubric-list grading-award-list">
              {result.rubric_awards.map((item) => {
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
          )}
        </section>
      </section>

      <aside aria-label="引用、知识点与校验证据" className="grading-evidence-column">
        <header className="grading-evidence-heading">
          <span>辅助证据</span>
          <h3>引用与知识校验</h3>
          <p>用于复核判分依据，不替代当前得分点判定。</p>
        </header>

        <section className="grading-evidence-section">
          <header>
            <h4>关联知识点</h4>
            <span>{knowledgeCodes.length}</span>
          </header>
          {knowledgeCodes.length === 0 ? (
            <p className="grading-evidence-empty">本题得分点没有关联知识代码。</p>
          ) : (
            <ul className="grading-knowledge-list">
              {knowledgeCodes.map((code) => <li key={code}>{code}</li>)}
            </ul>
          )}
        </section>

        <section className="grading-evidence-section">
          <header>
            <h4>引用证据</h4>
            <span>{result.citations.length}</span>
          </header>
          {result.citations.length === 0 ? (
            <p className="grading-evidence-empty">本次判分没有返回引用片段。</p>
          ) : (
            <ol className="grading-citation-list">
              {result.citations.map((citation, index) => (
                <li key={`${citation.source}-${citation.page ?? "none"}-${index}`}>
                  <strong>
                    {citation.source}
                    {citation.page ? ` · 第 ${citation.page} 页` : ""}
                  </strong>
                  <blockquote>{citation.excerpt}</blockquote>
                </li>
              ))}
            </ol>
          )}
        </section>

        <section className="grading-evidence-section">
          <header>
            <h4>独立校验</h4>
            <span>{result.symbolic_checks.length}</span>
          </header>
          {result.symbolic_checks.length === 0 ? (
            <p className="grading-evidence-empty">本题没有额外的符号校验。</p>
          ) : (
            <ul className="grading-symbolic-list">
              {result.symbolic_checks.map((check, index) => (
                <li key={`${check.student}-${check.expected}-${index}`}>
                  <span className={check.equivalent === true
                    ? "passed"
                    : check.equivalent === false
                      ? "failed"
                      : "unknown"}
                  >
                    {check.equivalent === true
                      ? "等价"
                      : check.equivalent === false
                        ? "不等价"
                        : "未判定"}
                  </span>
                  <p>{check.detail}</p>
                  <small>学生：{check.student} · 期望：{check.expected}</small>
                </li>
              ))}
            </ul>
          )}
        </section>

        {result.improvement_suggestions.length > 0 && (
          <section className="grading-evidence-section grading-improvements">
            <header>
              <h4>针对性改进建议</h4>
              <span>{result.improvement_suggestions.length}</span>
            </header>
            {result.improvement_suggestions.map((item) => (
              <div className="rubric-rich" key={item}>
                <Markdown>{item}</Markdown>
              </div>
            ))}
          </section>
        )}
      </aside>

      <footer className="grading-report-actions">
        <div className="review-required">
          <ShieldCheck size={18} />
          {reviewBanner}
        </div>
        <button
          aria-busy={regenerating || undefined}
          aria-live="polite"
          className="secondary"
          disabled={busy}
          onClick={onRegenerate}
          type="button"
        >
          {regenerating
            ? <LoaderCircle className="spin" size={15} />
            : <RefreshCw size={15} />}
          {regenerating ? "正在重新判分…" : "重新判分"}
        </button>
      </footer>
    </div>
  );
}
