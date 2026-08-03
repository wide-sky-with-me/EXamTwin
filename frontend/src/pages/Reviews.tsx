import { CheckCircle2, LoaderCircle } from "lucide-react";
import { useState } from "react";

import { api } from "../lib/api";
import type { ReviewItem } from "../types";
import { Confidence, ErrorBanner } from "../components/Feedback";

export function Reviews({ items, refresh }: { items: ReviewItem[]; refresh: () => Promise<void> }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function confirm(id: string) {
    setBusy(id); setError(null);
    try {
      await api(`/grading/reviews/${id}`, {
        method: "POST",
        body: JSON.stringify({ reviewer: "teacher", decision: "confirm" }),
      });
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "复核失败");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section>
      <div className="page-heading compact"><div><p className="eyebrow">HUMAN REVIEW</p><h1>人工复核队列</h1><p>确认或改分后才成为最终评分；自动结果不直接发布。</p></div></div>
      <ErrorBanner message={error} />
      <div className="review-list">
        {items.length === 0 && <article className="panel empty"><CheckCircle2 size={36} /><p>当前没有待复核评分</p></article>}
        {items.map((item) => (
          <article className="panel review-card" key={item.id}>
            <div className="review-score"><strong>{item.total_awarded}</strong><span>/ {item.total_available}</span></div>
            <div className="review-body">
              <div><code>{item.question_ref ?? item.id.slice(0, 8)}</code><Confidence value={item.confidence} /></div>
              <p>{item.result.rubric_awards.length} 个 rubric 原子 · {new Date(item.created_at).toLocaleString("zh-CN")}</p>
            </div>
            <button className="secondary" onClick={() => confirm(item.id)} disabled={busy === item.id}>
              {busy === item.id ? <LoaderCircle className="spin" size={17} /> : <CheckCircle2 size={17} />}确认评分
            </button>
          </article>
        ))}
      </div>
    </section>
  );
}
