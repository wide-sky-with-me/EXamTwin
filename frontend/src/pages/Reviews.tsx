import { CheckCircle2, LoaderCircle, PencilLine } from "lucide-react";
import { useState } from "react";

import { apiClient, setApiSubject, unwrapApi } from "../lib/api";
import type { ReviewItem } from "../types";
import { Confidence, ErrorBanner } from "../components/Feedback";
import { useToast } from "../components/toast-context";
import { AppConfirmDialog } from "../components/ui/AppConfirmDialog";

const REVIEWER_STORAGE_KEY = "examtwin.reviewerName";

type PendingReview = {
  decision: "confirm" | "override";
  item: ReviewItem;
  overrideMark: number | null;
  reviewer: string;
};

export function Reviews({ items, refresh }: { items: ReviewItem[]; refresh: () => Promise<void> }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reviewer, setReviewer] = useState(() =>
    window.localStorage.getItem(REVIEWER_STORAGE_KEY) ?? "",
  );
  const [overrideMarks, setOverrideMarks] = useState<Record<string, string>>({});
  const [pendingReview, setPendingReview] = useState<PendingReview | null>(null);
  const { notify } = useToast();

  function requestReview(item: ReviewItem, decision: "confirm" | "override") {
    const reviewerName = reviewer.trim();
    if (!reviewerName) {
      setError("请填写复核人名称。");
      return;
    }
    const rawOverride = overrideMarks[item.id] ?? "";
    const overrideMark = Number(rawOverride);
    if (
      decision === "override"
      && (rawOverride.trim() === ""
        || !Number.isFinite(overrideMark)
        || overrideMark < 0
        || overrideMark > item.total_available)
    ) {
      setError(`改分必须在 0–${item.total_available} 之间。`);
      return;
    }
    setPendingReview({
      decision,
      item,
      overrideMark: decision === "override" ? overrideMark : null,
      reviewer: reviewerName,
    });
  }

  async function submitReview() {
    if (!pendingReview) return;
    const { decision, item, overrideMark, reviewer: reviewerName } = pendingReview;
    setBusy(item.id); setError(null);
    setApiSubject(item.subject_code);
    try {
      await unwrapApi(
        apiClient.POST("/api/v1/grading/reviews/{assessment_id}", {
          params: { path: { assessment_id: item.id } },
          body: {
            reviewer: reviewerName,
            decision,
            override_mark: decision === "override" ? overrideMark : null,
          },
        }),
      );
      window.localStorage.setItem(REVIEWER_STORAGE_KEY, reviewerName);
      notify(decision === "confirm" ? "评分已确认并写入审计记录。" : "改分已确认并写入审计记录。");
      setPendingReview(null);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "复核失败");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section>
      <div className="page-heading compact"><div><h1>人工复核队列</h1></div></div>
      <div className="panel review-toolbar">
        <label>
          复核人
          <input
            onChange={(event) => {
              const value = event.target.value;
              setReviewer(value);
              if (value.trim()) window.localStorage.setItem(REVIEWER_STORAGE_KEY, value);
              else window.localStorage.removeItem(REVIEWER_STORAGE_KEY);
            }}
            placeholder="填写教师或复核人名称"
            required
            value={reviewer}
          />
        </label>
        <p>复核人会写入审计记录；确认沿用建议分，改分需要填写最终分数。</p>
      </div>
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
            <div className="review-actions">
              <button className="secondary" onClick={() => requestReview(item, "confirm")} disabled={busy === item.id}>
                {busy === item.id ? <LoaderCircle className="spin" size={17} /> : <CheckCircle2 size={17} />}确认评分
              </button>
              <label>
                最终得分
                <input
                  aria-label={`${item.question_ref ?? item.id} 最终得分`}
                  max={item.total_available}
                  min="0"
                  onChange={(event) => setOverrideMarks((current) => ({
                    ...current,
                    [item.id]: event.target.value,
                  }))}
                  placeholder={String(item.total_awarded)}
                  step="0.5"
                  type="number"
                  value={overrideMarks[item.id] ?? ""}
                />
              </label>
              <button className="secondary override" onClick={() => requestReview(item, "override")} disabled={busy === item.id}>
                <PencilLine size={17} />改分并确认
              </button>
            </div>
          </article>
        ))}
      </div>
      <AppConfirmDialog
        busy={pendingReview ? busy === pendingReview.item.id : false}
        confirmLabel={pendingReview?.decision === "override" ? "确认改分" : "确认评分"}
        description={pendingReview
          ? pendingReview.decision === "override"
            ? `将 Q${pendingReview.item.question_ref?.replace(/^Q/i, "") ?? pendingReview.item.id.slice(0, 8)} 改为 ${pendingReview.overrideMark}/${pendingReview.item.total_available}，并写入最终评分。此操作不能在当前界面撤销。`
            : `将沿用建议分 ${pendingReview.item.total_awarded}/${pendingReview.item.total_available}，并写入最终评分。此操作不能在当前界面撤销。`
          : ""}
        onConfirm={submitReview}
        onOpenChange={(open) => { if (!open) setPendingReview(null); }}
        open={pendingReview !== null}
        title={pendingReview?.decision === "override" ? "确认改分？" : "确认评分？"}
      />
    </section>
  );
}
