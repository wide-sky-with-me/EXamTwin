import type { ReviewItem } from "../types";

// Decision: .agents/notes/implemented/simplification/2026-10-14-review-queue-grouping.md
type PendingReviewGroup = {
  key: string;
  kind: "paper" | "standalone";
  label: string;
  paperFilename: string | null;
  paperJobId: string | null;
  items: ReviewItem[];
};

const REVIEW_COLLATOR = new Intl.Collator("zh-CN", {
  numeric: true,
  sensitivity: "base",
});

export function reviewItemLabel(item: ReviewItem): string {
  if (item.question_ref?.trim()) return item.question_ref.trim();
  if (item.question_position !== null) return `Q${item.question_position + 1}`;
  return item.id.slice(0, 8);
}

function compareReviewItems(left: ReviewItem, right: ReviewItem): number {
  const leftPosition = left.question_position ?? Number.MAX_SAFE_INTEGER;
  const rightPosition = right.question_position ?? Number.MAX_SAFE_INTEGER;
  if (leftPosition !== rightPosition) return leftPosition - rightPosition;
  const question = REVIEW_COLLATOR.compare(reviewItemLabel(left), reviewItemLabel(right));
  if (question !== 0) return question;
  const created = REVIEW_COLLATOR.compare(left.created_at, right.created_at);
  return created !== 0 ? created : REVIEW_COLLATOR.compare(left.id, right.id);
}

export function groupPendingReviews(items: ReviewItem[]): PendingReviewGroup[] {
  const linked = new Map<string, ReviewItem[]>();
  const standalone: ReviewItem[] = [];

  for (const item of items) {
    if (!item.paper_job_id) {
      standalone.push(item);
      continue;
    }
    const groupItems = linked.get(item.paper_job_id);
    if (groupItems) groupItems.push(item);
    else linked.set(item.paper_job_id, [item]);
  }

  const paperGroups = [...linked.entries()]
    .sort(([leftId], [rightId]) => REVIEW_COLLATOR.compare(leftId, rightId))
    .map<PendingReviewGroup>(([paperJobId, groupItems]) => {
      const orderedItems = [...groupItems].sort(compareReviewItems);
      const displayName = groupItems
        .map((item) => item.paper_display_name?.trim())
        .filter((value): value is string => Boolean(value))
        .sort(REVIEW_COLLATOR.compare)[0] ?? null;
      const filename = groupItems
        .map((item) => item.paper_filename?.trim())
        .filter((value): value is string => Boolean(value))
        .sort(REVIEW_COLLATOR.compare)[0] ?? null;
      return {
        key: `paper:${paperJobId}`,
        kind: "paper",
        label: displayName || filename || "未命名试卷",
        paperFilename: filename,
        paperJobId,
        items: orderedItems,
      };
    });

  const standaloneGroups = [...standalone]
    .sort(compareReviewItems)
    .map<PendingReviewGroup>((item) => ({
      key: `legacy:${item.id}`,
      kind: "standalone",
      label: `独立评估 · ${reviewItemLabel(item)}`,
      paperFilename: null,
      paperJobId: null,
      items: [item],
    }));

  return [...paperGroups, ...standaloneGroups];
}
