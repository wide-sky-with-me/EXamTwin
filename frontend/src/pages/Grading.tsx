import {
  BookOpenCheck,
  GraduationCap,
  LoaderCircle,
  ShieldCheck,
  Sigma,
  TriangleAlert,
} from "lucide-react";
import { type FormEvent, useState } from "react";

import { apiClient, unwrapApi } from "../lib/api";
import type { GradeResult } from "../types";
import { SourceEvidence } from "../components/Evidence";
import { Confidence, ErrorBanner } from "../components/Feedback";

export function Grading({ onCreated }: { onCreated: () => Promise<void> }) {
  const [question, setQuestion] = useState("Solve the equation shown and give all working.");
  const [scheme, setScheme] = useState("1.M1 Award 1 mark for a valid method.\n1.A1 Award 1 mark for the correct final answer.");
  const [answer, setAnswer] = useState("I rearranged the equation and obtained the final answer.");
  const [maxMarks, setMaxMarks] = useState("2");
  const [result, setResult] = useState<GradeResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const parsedMaxMarks = Number(maxMarks);
  const maxMarksInvalid =
    maxMarks.trim() === ""
    || !Number.isFinite(parsedMaxMarks)
    || parsedMaxMarks <= 0;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (maxMarksInvalid) {
      setError("满分必须是大于 0 的数字。");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const payload = await unwrapApi(
        apiClient.POST("/api/v1/grading/assess", {
          body: {
          question_markdown: question,
          mark_scheme_markdown: scheme,
          answer_markdown: answer,
          max_marks: parsedMaxMarks,
          },
        }),
      );
      setResult(payload);
      await onCreated();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "评分失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section>
      <div className="page-heading compact">
        <div><p className="eyebrow">MARK SCHEME FIRST</p><h1>自动初评</h1><p>当前支持学生 Markdown 答案；逐条 rubric 给分并保留证据。</p></div>
      </div>
      <div className="grade-layout">
        <form className="panel form-panel grade-form" onSubmit={submit}>
          <label>题目 Markdown<textarea rows={4} value={question} onChange={(e) => setQuestion(e.target.value)} /></label>
          <label>Mark scheme Markdown<textarea rows={7} value={scheme} onChange={(e) => setScheme(e.target.value)} /></label>
          <label>学生答案 Markdown<textarea rows={8} value={answer} onChange={(e) => setAnswer(e.target.value)} /></label>
          <label className="short-field">
            满分
            <input
              aria-invalid={maxMarksInvalid}
              min="0.5"
              onChange={(e) => setMaxMarks(e.target.value)}
              required
              step="0.5"
              type="number"
              value={maxMarks}
            />
            {maxMarksInvalid && <small className="field-error">请输入大于 0 的满分。</small>}
          </label>
          <button className="primary" disabled={loading || maxMarksInvalid}>
            {loading ? <LoaderCircle className="spin" size={18} /> : <GraduationCap size={18} />}
            生成逐项评分
          </button>
          <ErrorBanner message={error} />
        </form>
        <article className="panel result-panel">
          {!result ? <div className="empty"><BookOpenCheck size={34} /><p>Rubric 逐项得分会显示在这里</p></div> : (
            <>
              <div className="score-hero"><div><strong>{result.total_awarded}</strong><span>/ {result.total_available}</span></div><p>等待人工复核</p></div>
              <div className="grading-assurance">
                <span>模型置信度 <Confidence value={result.confidence} /></span>
                <span>{result.citations.length} 条评分依据</span>
                <span>{result.symbolic_checks.length} 项符号检查</span>
              </div>
              {result.warnings.length > 0 && (
                <div className="grading-warnings" aria-label="评分风险提示">
                  {result.warnings.map((warning) => (
                    <p key={warning}><TriangleAlert size={15} />{warning}</p>
                  ))}
                </div>
              )}
              <div className="rubric-list">{result.rubric_awards.map((item) => (
                <div className="rubric" key={item.criterion_id}>
                  <div><span>{item.mark_type ?? item.criterion_id}</span><b>{item.awarded}/{item.max_marks}</b></div>
                  <strong>{item.description}</strong>
                  <p>{item.rationale}</p>
                  {item.student_evidence && <blockquote>“{item.student_evidence}”</blockquote>}
                </div>
              ))}</div>
              {result.symbolic_checks.length > 0 && (
                <section className="symbolic-checks">
                  <h3><Sigma size={15} />符号等价佐证</h3>
                  {result.symbolic_checks.map((check, index) => (
                    <div className="symbolic-check" key={`${check.student}-${check.expected}-${index}`}>
                      <strong>
                        {check.equivalent === true
                          ? "等价"
                          : check.equivalent === false
                            ? "不等价"
                            : "无法判定"}
                      </strong>
                      <code>{check.student} → {check.expected}</code>
                      <p>{check.detail}</p>
                    </div>
                  ))}
                </section>
              )}
              {result.citations.length > 0 && (
                <section className="grading-citations">
                  <h3>Mark Scheme 与证据引用</h3>
                  {result.citations.map((citation, index) => (
                    <SourceEvidence
                      citation={citation}
                      index={index}
                      key={`${citation.source}-${citation.page ?? "section"}-${index}`}
                      query={question.slice(0, 300)}
                    />
                  ))}
                </section>
              )}
              <div className="review-required"><ShieldCheck size={18} /> 评分已进入人工复核队列</div>
            </>
          )}
        </article>
      </div>
    </section>
  );
}
