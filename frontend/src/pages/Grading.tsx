import {
  BookOpenCheck,
  GraduationCap,
  LoaderCircle,
  ShieldCheck,
} from "lucide-react";
import { type FormEvent, useState } from "react";

import { api } from "../lib/api";
import type { GradeResult } from "../types";
import { ErrorBanner } from "../components/Feedback";

export function Grading({ onCreated }: { onCreated: () => Promise<void> }) {
  const [question, setQuestion] = useState("Solve the equation shown and give all working.");
  const [scheme, setScheme] = useState("1.M1 Award 1 mark for a valid method.\n1.A1 Award 1 mark for the correct final answer.");
  const [answer, setAnswer] = useState("I rearranged the equation and obtained the final answer.");
  const [maxMarks, setMaxMarks] = useState("2");
  const [result, setResult] = useState<GradeResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const payload = await api<GradeResult>("/grading/assess", {
        method: "POST",
        body: JSON.stringify({
          question_markdown: question,
          mark_scheme_markdown: scheme,
          answer_markdown: answer,
          max_marks: Number(maxMarks),
        }),
      });
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
          <label className="short-field">满分<input type="number" min="0.5" step="0.5" value={maxMarks} onChange={(e) => setMaxMarks(e.target.value)} /></label>
          <button className="primary" disabled={loading}>
            {loading ? <LoaderCircle className="spin" size={18} /> : <GraduationCap size={18} />}
            生成逐项评分
          </button>
          <ErrorBanner message={error} />
        </form>
        <article className="panel result-panel">
          {!result ? <div className="empty"><BookOpenCheck size={34} /><p>Rubric 逐项得分会显示在这里</p></div> : (
            <>
              <div className="score-hero"><div><strong>{result.total_awarded}</strong><span>/ {result.total_available}</span></div><p>等待人工复核</p></div>
              <div className="rubric-list">{result.rubric_awards.map((item) => (
                <div className="rubric" key={item.criterion_id}>
                  <div><span>{item.mark_type ?? item.criterion_id}</span><b>{item.awarded}/{item.max_marks}</b></div>
                  <strong>{item.description}</strong>
                  <p>{item.rationale}</p>
                  {item.student_evidence && <blockquote>“{item.student_evidence}”</blockquote>}
                </div>
              ))}</div>
              <div className="review-required"><ShieldCheck size={18} /> 评分已进入人工复核队列</div>
            </>
          )}
        </article>
      </div>
    </section>
  );
}
