import {
  ArrowRight,
  BookOpenCheck,
  CheckCircle2,
  LoaderCircle,
  Sparkles,
  TriangleAlert,
  X,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

import type {
  AiReviewRubricCriteriaRequest,
  BatchReviewRubricCriteriaRequest,
  BatchRubricCriterionDecision,
  RubricCriterionPatch,
  RubricSet,
  RubricSetSummary,
} from "../../types";

import { ErrorBanner } from "../Feedback";
import { RubricCriterionEditor } from "./RubricCriterionEditor";

const BATCH_CRITERIA_LIMIT = 200;

type Confirmation = {
  kind: "reject" | "ai";
  reviewer: string;
  decisions: BatchRubricCriterionDecision[];
  acceptedCount: number;
  rejectedCount: number;
  reviseCount: number;
};

type DirtyCriterionState = {
  rubricId: string | null;
  criterionIds: Set<string>;
};

type ReviewCompletion = {
  sequence: number;
  message: string;
  nextCriterionIds: string[];
};

type RubricCriterion = RubricSet["criteria"][number];

type QuestionReviewSummary = {
  number: string;
  criteria: RubricCriterion[];
  totalMarks: number;
  acceptedMarks: number;
  acceptedCount: number;
  rejectedCount: number;
  pendingCount: number;
};

const EMPTY_CRITERION_IDS = new Set<string>();
const NATURAL_COLLATOR = new Intl.Collator("zh-CN", { numeric: true, sensitivity: "base" });
const MARK_SEQUENCE: Record<string, number> = { M: 0, A: 1, B: 2 };

function criterionSequence(criterionId: string): [number, number] {
  const match = criterionId.match(/(?:^|[_-])([MAB])(\d+)$/i);
  return match
    ? [Number(match[2]), MARK_SEQUENCE[match[1].toUpperCase()] ?? 9]
    : [Number.MAX_SAFE_INTEGER, 9];
}

function compareCriteria(left: RubricCriterion, right: RubricCriterion): number {
  const question = NATURAL_COLLATOR.compare(left.question_number, right.question_number);
  if (question !== 0) return question;
  const subpart = NATURAL_COLLATOR.compare(left.subpart, right.subpart);
  if (subpart !== 0) return subpart;
  const [leftIndex, leftType] = criterionSequence(left.criterion_id);
  const [rightIndex, rightType] = criterionSequence(right.criterion_id);
  if (leftIndex !== rightIndex) return leftIndex - rightIndex;
  if (leftType !== rightType) return leftType - rightType;
  return NATURAL_COLLATOR.compare(left.criterion_id, right.criterion_id);
}

export function RubricReviewStage({
  rubric,
  rubrics,
  reviewer,
  busy,
  error,
  onReviewerChange,
  onSelectRubric,
  onReviewCriterion,
  onBatchReview,
  onAiReview,
  onConfirmRubric,
  onBack,
  onNext,
}: {
  rubric: RubricSet | null;
  rubrics: RubricSetSummary[];
  reviewer: string;
  busy: string | null;
  error: string | null;
  onReviewerChange: (reviewer: string) => void;
  onSelectRubric: (rubricId: string) => Promise<void>;
  onReviewCriterion: (
    criterionId: string,
    reviewStatus: "accepted" | "rejected",
    note: string,
    updates: RubricCriterionPatch | undefined,
  ) => Promise<boolean>;
  onBatchReview: (request: BatchReviewRubricCriteriaRequest) => Promise<boolean>;
  onAiReview: (request: AiReviewRubricCriteriaRequest) => Promise<void>;
  onConfirmRubric: () => Promise<void>;
  onBack: () => void;
  onNext: () => void;
}) {
  const [questionFilter, setQuestionFilter] = useState(() => (
    rubric ? [...rubric.criteria].sort(compareCriteria)[0]?.question_number ?? "ALL" : "ALL"
  ));
  const [statusFilter, setStatusFilter] = useState("all");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [dirtyCriterionState, setDirtyCriterionState] = useState<DirtyCriterionState>(() => ({
    rubricId: null,
    criterionIds: new Set(),
  }));
  const [batchNote, setBatchNote] = useState("");
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [confirmSubmitting, setConfirmSubmitting] = useState(false);
  const [reviewCompletion, setReviewCompletion] = useState<ReviewCompletion | null>(null);
  const [reviewerInvalid, setReviewerInvalid] = useState(false);
  const [pendingBatchDecision, setPendingBatchDecision] = useState<
    "accepted" | "rejected" | "ai" | null
  >(null);
  const confirmSubmittingRef = useRef(false);
  const selectAllRef = useRef<HTMLInputElement>(null);
  const cancelConfirmationRef = useRef<HTMLButtonElement>(null);
  const confirmationOpenerRef = useRef<HTMLButtonElement | null>(null);
  const stageHeadingRef = useRef<HTMLHeadingElement>(null);
  const reviewerInputRef = useRef<HTMLInputElement>(null);
  const reviewerErrorId = useId();
  const stageRef = useRef<HTMLElement>(null);
  const reviewCompletionSequenceRef = useRef(0);
  const selectedRubricIdRef = useRef(rubric?.id);

  const currentRubricId = rubric?.id ?? null;
  const currentRubricIdRef = useRef(currentRubricId);
  currentRubricIdRef.current = currentRubricId;
  const dirtyCriterionIds = dirtyCriterionState.rubricId === currentRubricId
    ? dirtyCriterionState.criterionIds
    : EMPTY_CRITERION_IDS;
  const acceptedCriteria = rubric?.criteria.filter((item) => item.review_status === "accepted").length ?? 0;
  const pendingCriteria = rubric?.criteria.filter((item) => item.review_status === "pending").length ?? 0;
  const rejectedCriteria = rubric?.criteria.filter((item) => item.review_status === "rejected").length ?? 0;
  const orderedCriteria = useMemo(
    () => [...(rubric?.criteria ?? [])].sort(compareCriteria),
    [rubric],
  );
  const questionSummaries = useMemo<QuestionReviewSummary[]>(() => {
    const summaries = new Map<string, QuestionReviewSummary>();
    for (const criterion of orderedCriteria) {
      let summary = summaries.get(criterion.question_number);
      if (!summary) {
        summary = {
          number: criterion.question_number,
          criteria: [],
          totalMarks: 0,
          acceptedMarks: 0,
          acceptedCount: 0,
          rejectedCount: 0,
          pendingCount: 0,
        };
        summaries.set(criterion.question_number, summary);
      }
      summary.criteria.push(criterion);
      summary.totalMarks += criterion.max_marks;
      if (criterion.review_status === "accepted") {
        summary.acceptedMarks += criterion.max_marks;
        summary.acceptedCount += 1;
      } else if (criterion.review_status === "rejected") {
        summary.rejectedCount += 1;
      } else {
        summary.pendingCount += 1;
      }
    }
    return [...summaries.values()];
  }, [orderedCriteria]);
  const visibleQuestionGroups = useMemo(
    () => questionSummaries
      .filter((summary) => questionFilter === "ALL" || summary.number === questionFilter)
      .map((summary) => ({
        ...summary,
        visibleCriteria: summary.criteria.filter(
          (item) => statusFilter === "all" || item.review_status === statusFilter,
        ),
      }))
      .filter((summary) => questionFilter !== "ALL" || summary.visibleCriteria.length > 0),
    [questionFilter, questionSummaries, statusFilter],
  );
  const visibleCriteria = useMemo(
    () => visibleQuestionGroups.flatMap((summary) => summary.visibleCriteria),
    [visibleQuestionGroups],
  );
  const totalRubricMarks = questionSummaries.reduce(
    (total, summary) => total + summary.totalMarks,
    0,
  );
  const acceptedRubricMarks = questionSummaries.reduce(
    (total, summary) => total + summary.acceptedMarks,
    0,
  );
  const visiblePendingCriteria = useMemo(
    () => visibleCriteria.filter(
      (item) => rubric?.status === "draft" && item.review_status === "pending",
    ),
    [rubric?.status, visibleCriteria],
  );
  const dirtyVisibleCriteria = useMemo(
    () => visiblePendingCriteria.filter((item) => dirtyCriterionIds.has(item.id)),
    [dirtyCriterionIds, visiblePendingCriteria],
  );
  const batchEligibleVisibleCriteria = useMemo(
    () => visiblePendingCriteria.filter((item) => !dirtyCriterionIds.has(item.id)),
    [dirtyCriterionIds, visiblePendingCriteria],
  );
  const selectableVisibleCriteria = useMemo(
    () => batchEligibleVisibleCriteria.slice(0, BATCH_CRITERIA_LIMIT),
    [batchEligibleVisibleCriteria],
  );
  const selectableVisibleIds = useMemo(
    () => new Set(selectableVisibleCriteria.map((item) => item.id)),
    [selectableVisibleCriteria],
  );
  const selectionOverflowCount = batchEligibleVisibleCriteria.length - selectableVisibleCriteria.length;
  const selectedVisibleIds = useMemo(
    () => [...selectedIds].filter((id) => selectableVisibleIds.has(id)),
    [selectableVisibleIds, selectedIds],
  );
  const selectedVisibleCriteria = useMemo(() => {
    const ids = new Set(selectedVisibleIds);
    return visibleCriteria.filter((item) => ids.has(item.id));
  }, [selectedVisibleIds, visibleCriteria]);
  const allVisibleSelected = selectableVisibleIds.size > 0
    && selectedVisibleIds.length === selectableVisibleIds.size;

  const confirmationOpen = confirmation !== null;
  const controlsLocked = busy !== null || confirmationOpen || pendingBatchDecision !== null;
  const batchAcceptPending = pendingBatchDecision === "accepted";
  const reportDirtyCriterion = useCallback((
    reportedRubricId: string,
    criterionId: string,
    dirty: boolean,
  ) => {
    if (reportedRubricId !== currentRubricIdRef.current) return;
    setDirtyCriterionState((current) => {
      const currentIds = current.rubricId === reportedRubricId
        ? current.criterionIds
        : EMPTY_CRITERION_IDS;
      if (currentIds.has(criterionId) === dirty) return current;
      const next = new Set(currentIds);
      if (dirty) next.add(criterionId);
      else next.delete(criterionId);
      return { rubricId: reportedRubricId, criterionIds: next };
    });
  }, []);

  useEffect(() => {
    const rubricChanged = selectedRubricIdRef.current !== rubric?.id;
    selectedRubricIdRef.current = rubric?.id;
    if (rubricChanged) {
      setQuestionFilter(orderedCriteria[0]?.question_number ?? "ALL");
    }
    setSelectedIds((current) => {
      if (rubricChanged) return current.size === 0 ? current : new Set();
      const next = new Set([...current].filter((id) => selectableVisibleIds.has(id)));
      if (next.size === current.size && [...next].every((id) => current.has(id))) return current;
      return next;
    });
    setConfirmation(null);
  }, [orderedCriteria, questionFilter, rubric?.id, selectableVisibleIds, statusFilter]);

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = selectedVisibleIds.length > 0 && !allVisibleSelected;
    }
  }, [allVisibleSelected, selectedVisibleIds.length]);

  useEffect(() => {
    if (confirmation) cancelConfirmationRef.current?.focus();
  }, [confirmation]);

  useEffect(() => {
    if (reviewer.trim()) setReviewerInvalid(false);
  }, [reviewer]);

  useEffect(() => {
    if (!reviewCompletion) return;
    const frame = window.requestAnimationFrame(() => {
      const stage = stageRef.current;
      let target: HTMLButtonElement | null = null;
      if (stage) {
        const cards = Array.from(
          stage.querySelectorAll<HTMLElement>("[data-rubric-criterion-id]"),
        );
        for (const criterionId of reviewCompletion.nextCriterionIds) {
          const card = cards.find(
            (candidate) => candidate.dataset.rubricCriterionId === criterionId,
          );
          target = card?.querySelector<HTMLButtonElement>(
            '[data-rubric-review-action="accept"]:not(:disabled)',
          ) ?? null;
          if (target) break;
        }
      }
      (target ?? stageHeadingRef.current)?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [reviewCompletion]);

  function requireReviewer(): string | null {
    const validReviewer = reviewer.trim();
    if (validReviewer) {
      setReviewerInvalid(false);
      return validReviewer;
    }
    setReviewerInvalid(true);
    reviewerInputRef.current?.focus();
    return null;
  }

  async function reviewCriterionAndRestoreFocus(
    criterionId: string,
    reviewStatus: "accepted" | "rejected",
    note: string,
    updates: RubricCriterionPatch | undefined,
  ): Promise<boolean | "focus-handled"> {
    if (!requireReviewer()) return "focus-handled";
    const currentIndex = visibleCriteria.findIndex((item) => item.id === criterionId);
    const nextCriterionIds = currentIndex < 0
      ? []
      : visibleCriteria.slice(currentIndex + 1).map((item) => item.id);
    const criterion = currentIndex < 0 ? null : visibleCriteria[currentIndex];
    setReviewCompletion(null);
    const completed = await onReviewCriterion(criterionId, reviewStatus, note, updates);
    if (!completed) return false;
    setReviewCompletion({
      sequence: ++reviewCompletionSequenceRef.current,
      message: criterion
        ? `Q${criterion.question_number} · ${criterion.criterion_id} 已${reviewStatus === "accepted" ? "保留" : "排除"}。`
        : `得分规则已${reviewStatus === "accepted" ? "保留" : "排除"}。`,
      nextCriterionIds,
    });
    return true;
  }
  function cancelConfirmation() {
    setConfirmation(null);
    window.requestAnimationFrame(() => confirmationOpenerRef.current?.focus());
  }

  function toggleSelection(criterionId: string, selected: boolean) {
    if (controlsLocked) return;
    setSelectedIds((current) => {
      const next = new Set(current);
      if (selected && selectableVisibleIds.has(criterionId) && next.size < BATCH_CRITERIA_LIMIT) {
        next.add(criterionId);
      } else if (!selected) {
        next.delete(criterionId);
      }
      return next;
    });
  }

  function toggleAllVisible(selected: boolean) {
    if (controlsLocked) return;
    setSelectedIds(selected ? new Set(selectableVisibleIds) : new Set());
  }

  function decisionsFor(status: "accepted" | "rejected"): BatchRubricCriterionDecision[] {
    const note = batchNote.trim() || null;
    return selectedVisibleIds.map((criterionId) => ({
      criterion_id: criterionId,
      review_status: status,
      note,
    }));
  }

  async function runBatchAccept() {
    if (controlsLocked || selectedVisibleIds.length === 0) return;
    const snapshotReviewer = requireReviewer();
    if (!snapshotReviewer) return;
    setPendingBatchDecision("accepted");
    try {
      await onBatchReview({
        reviewer: snapshotReviewer,
        decisions: decisionsFor("accepted"),
      });
    } finally {
      setPendingBatchDecision(null);
    }
  }

  function requestBatchReject() {
    if (controlsLocked || selectedVisibleIds.length === 0) return;
    const snapshotReviewer = requireReviewer();
    if (!snapshotReviewer) return;
    confirmationOpenerRef.current = document.activeElement instanceof HTMLButtonElement
      ? document.activeElement
      : null;
    setConfirmation({
      kind: "reject",
      reviewer: snapshotReviewer,
      decisions: decisionsFor("rejected"),
      acceptedCount: 0,
      rejectedCount: selectedVisibleIds.length,
      reviseCount: 0,
    });
  }

  const aiTargetCriteria = selectedVisibleCriteria.length > 0
    ? selectedVisibleCriteria
    : selectableVisibleCriteria;
  const aiSuggestionCriteria = aiTargetCriteria.filter((item) => item.ai_review);
  const aiAcceptedCount = aiSuggestionCriteria.filter(
    (item) => item.ai_review?.recommendation === "accept",
  ).length;
  const aiRejectedCount = aiSuggestionCriteria.filter(
    (item) => item.ai_review?.recommendation === "reject",
  ).length;
  const aiReviseCount = aiSuggestionCriteria.filter(
    (item) => item.ai_review?.recommendation === "revise",
  ).length;

  function requestAiReview() {
    if (controlsLocked || aiTargetCriteria.length === 0 || !requireReviewer()) return;
    void onAiReview({ criterion_ids: aiTargetCriteria.map((item) => item.id) });
  }

  function requestApplyAi() {
    if (controlsLocked) return;
    const snapshotReviewer = requireReviewer();
    if (!snapshotReviewer) return;
    confirmationOpenerRef.current = document.activeElement instanceof HTMLButtonElement
      ? document.activeElement
      : null;
    const note = batchNote.trim() || "按已保存的 AI 审核建议批量处理";
    const decisions = aiSuggestionCriteria.flatMap<BatchRubricCriterionDecision>((item) => {
      const aiReview = item.ai_review;
      const recommendation = aiReview?.recommendation;
      if (!aiReview || (recommendation !== "accept" && recommendation !== "reject")) return [];
      return [{
        criterion_id: item.id,
        expected_criterion_fingerprint: aiReview.criterion_fingerprint,
        review_status: recommendation === "accept" ? "accepted" : "rejected",
        note,
      }];
    });
    if (!decisions.length) return;
    setConfirmation({
      kind: "ai",
      reviewer: snapshotReviewer,
      decisions,
      acceptedCount: aiAcceptedCount,
      rejectedCount: aiRejectedCount,
      reviseCount: aiReviseCount,
    });
  }

  async function confirmBatch() {
    if (!confirmation || busy !== null || confirmSubmittingRef.current) return;
    confirmSubmittingRef.current = true;
    setConfirmSubmitting(true);
    setPendingBatchDecision(confirmation.kind === "reject" ? "rejected" : "ai");
    try {
      const completed = await onBatchReview({
        reviewer: confirmation.reviewer,
        decisions: confirmation.decisions,
      });
      if (!completed) return;
      setConfirmation(null);
      window.requestAnimationFrame(() => stageHeadingRef.current?.focus());
    } finally {
      confirmSubmittingRef.current = false;
      setConfirmSubmitting(false);
      setPendingBatchDecision(null);
    }
  }

  const actionsDisabled = controlsLocked || selectedVisibleIds.length === 0;

  return (
    <article className="panel grading-stage rubric-review" ref={stageRef}>
      <header className="grading-stage-header">
        <button
          aria-label="关闭评分标准审核"
          className="rubric-modal-close"
          data-modal-close=""
          disabled={controlsLocked}
          onClick={onBack}
          type="button"
        >
          <X size={17} />
        </button>
        <div>
          <span>评分标准</span>
          <h2 id="grading-stage-2-heading" ref={stageHeadingRef} tabIndex={-1}>
            审核评分标准
          </h2>
        </div>
        {rubric && (
          <b className={`status-pill ${rubric.status}`}>
            {rubric.status === "confirmed" ? "已确认" : "规则草稿"}
          </b>
        )}
      </header>

      {rubrics.length > 1 && (
        <label className="rubric-version-picker">
          <span>评分规则版本</span>
          <select
            aria-label="选择评分规则版本"
            disabled={controlsLocked}
            onChange={(event) => void onSelectRubric(event.target.value)}
            value={rubric?.id ?? ""}
          >
            {rubrics.map((item) => (
              <option key={item.id} value={item.id}>
                版本 {item.version_number} · {item.status}
              </option>
            ))}
          </select>
        </label>
      )}

      {!rubric ? (
        busy === "loading-rubric" ? (
          <div aria-busy="true" aria-live="polite" className="empty compact-empty" role="status">
            <LoaderCircle className="spin" size={30} />
            <p>正在加载评分规则版本，请稍候…</p>
          </div>
        ) : (
          <div className="empty compact-empty">
            <BookOpenCheck size={30} />
            <p>返回材料准备并解析评分标准。</p>
          </div>
        )
      ) : (
        <>
          <div className="rubric-stats">
            <span><b>{rubric.criteria.length}</b> 条规则</span>
            <span><b>{acceptedCriteria}</b> 已保留</span>
            <span><b>{rejectedCriteria}</b> 已排除</span>
            <span><b>{pendingCriteria}</b> 待处理</span>
          </div>
          <div className="rubric-review-filters">
            <label>
              审核人
              <input
                aria-label="审核人"
                aria-describedby={reviewerInvalid ? reviewerErrorId : undefined}
                aria-invalid={reviewerInvalid}
                disabled={rubric.status !== "draft" || controlsLocked}
                onChange={(event) => {
                  const value = event.target.value;
                  if (value.trim()) setReviewerInvalid(false);
                  onReviewerChange(value);
                }}
                placeholder="填写教师或复核人名称"
                ref={reviewerInputRef}
                required
                value={reviewer}
              />
              {reviewerInvalid && (
                <small className="field-error" id={reviewerErrorId}>请填写审核人。</small>
              )}
            </label>
            <label>
              审核状态
              <select
                disabled={controlsLocked}
                onChange={(event) => setStatusFilter(event.target.value)}
                value={statusFilter}
              >
                <option value="all">全部状态</option>
                <option value="pending">待处理</option>
                <option value="accepted">已保留</option>
                <option value="rejected">已排除</option>
              </select>
            </label>
          </div>
          {rubric.status === "draft" && (
            <section className="rubric-batch-toolbar" aria-label="批量审核工具">
              <div className="rubric-batch-selection">
                <label>
                  <input
                    aria-describedby={[
                      dirtyVisibleCriteria.length > 0 ? "rubric-dirty-selection-guidance" : null,
                      selectionOverflowCount > 0 ? "rubric-selection-limit" : null,
                    ].filter(Boolean).join(" ") || undefined}
                    checked={allVisibleSelected}
                    disabled={selectableVisibleIds.size === 0 || controlsLocked}
                    onChange={(event) => toggleAllVisible(event.target.checked)}
                    ref={selectAllRef}
                    type="checkbox"
                  />
                  选择当前筛选下待处理规则
                </label>
                <strong aria-live="polite">
                  {selectedVisibleIds.length} / {selectableVisibleIds.size} 已选择
                </strong>
              </div>
              {dirtyVisibleCriteria.length > 0 && (
                <small
                  className="rubric-dirty-selection-guidance"
                  id="rubric-dirty-selection-guidance"
                  role="status"
                >
                  当前筛选有 {dirtyVisibleCriteria.length} 条未保存修改，已从批量操作中排除。
                  请逐条保存并保留，或放弃修改后再批量处理。
                </small>
              )}
              {selectionOverflowCount > 0 && (
                <small className="rubric-selection-guidance" id="rubric-selection-limit">
                  当前筛选有 {batchEligibleVisibleCriteria.length} 条可批量处理的规则；单次最多处理{" "}
                  {BATCH_CRITERIA_LIMIT} 条，仅前 {BATCH_CRITERIA_LIMIT} 条可选。完成本批后再处理其余{" "}
                  {selectionOverflowCount} 条。
                </small>
              )}
              <label className="rubric-batch-note">
                批量审核说明
                <input
                  disabled={controlsLocked}
                  onChange={(event) => setBatchNote(event.target.value)}
                  placeholder="可选；将写入每条审计记录"
                  value={batchNote}
                />
              </label>
              <div className="rubric-batch-actions">
                <button
                  className="secondary"
                  disabled={controlsLocked || aiTargetCriteria.length === 0}
                  onClick={requestAiReview}
                  type="button"
                >
                  {busy === "ai-review"
                    ? <LoaderCircle className="spin" size={15} />
                    : <Sparkles size={15} />}
                  {selectedVisibleIds.length > 0 ? "AI 检查已选规则" : "AI 检查待处理规则"}
                </button>
                <button
                  aria-busy={batchAcceptPending || undefined}
                  aria-live="polite"
                  className="secondary"
                  disabled={actionsDisabled}
                  onClick={() => void runBatchAccept()}
                  type="button"
                >
                  {batchAcceptPending
                    ? <LoaderCircle className="spin" size={15} />
                    : <CheckCircle2 size={15} />}
                  {batchAcceptPending ? "正在批量保留…" : "保留所选"}
                </button>
                <button
                  className="secondary danger"
                  disabled={actionsDisabled}
                  onClick={requestBatchReject}
                  type="button"
                >
                  <XCircle size={15} />排除所选
                </button>
                <button
                  className="secondary"
                  disabled={controlsLocked || aiAcceptedCount + aiRejectedCount === 0}
                  onClick={requestApplyAi}
                  type="button"
                >
                  <Sparkles size={15} />应用 AI 检查
                </button>
              </div>
              {error && (
                <div className="rubric-toolbar-error">
                  <ErrorBanner message={error} />
                </div>
              )}
            </section>
          )}
          {confirmation && (
            <section
              aria-labelledby="rubric-confirmation-title"
              aria-live="assertive"
              className="rubric-batch-confirmation"
              onKeyDown={(event) => {
                if (event.key === "Escape" && !confirmSubmitting) cancelConfirmation();
              }}
              role="group"
            >
              <div>
                <strong id="rubric-confirmation-title">
                  {confirmation.kind === "reject" ? "确认排除所选规则" : "确认应用 AI 检查结果"}
                </strong>
                <p>
                  将由 {confirmation.reviewer} 保留 {confirmation.acceptedCount} 条、排除{" "}
                  {confirmation.rejectedCount} 条，并为每条创建独立审计记录。
                  {confirmation.kind === "ai" && confirmation.reviseCount > 0
                    ? `另有 ${confirmation.reviseCount} 条“建议修改”保持待处理，需逐条编辑。`
                    : ""}
                </p>
              </div>
              <div>
                <button
                  className="secondary"
                  disabled={confirmSubmitting}
                  onClick={cancelConfirmation}
                  ref={cancelConfirmationRef}
                  type="button"
                >
                  取消
                </button>
                <button
                  aria-busy={confirmSubmitting || undefined}
                  aria-live="polite"
                  className={confirmation.kind === "reject" ? "secondary danger" : "primary grading-primary-action"}
                  disabled={busy !== null || confirmSubmitting}
                  onClick={() => void confirmBatch()}
                  type="button"
                >
                  {confirmSubmitting && <LoaderCircle className="spin" size={15} />}
                  {confirmSubmitting
                    ? confirmation.kind === "reject"
                      ? "正在排除…"
                      : "正在应用 AI 建议…"
                    : "确认并保存"}
                </button>
              </div>
            </section>
          )}
          <div className="rubric-review-workspace">
            <nav
              aria-label="得分点题目导航"
              className="panel grading-question-nav rubric-question-nav"
            >
              <div className="panel-title">
                <div>
                  <span>题目索引</span>
                  <h2>按题查看规则</h2>
                </div>
              </div>
              <div className="grading-question-picker">
                <button
                  aria-controls="rubric-question-review"
                  aria-current={questionFilter === "ALL" ? "true" : undefined}
                  className={questionFilter === "ALL" ? "active" : ""}
                  disabled={controlsLocked}
                  onClick={() => setQuestionFilter("ALL")}
                  type="button"
                >
                  <span>
                    <b>全部题目</b>
                    <small>
                      {rubric.criteria.length - pendingCriteria}/{rubric.criteria.length} 条已处理
                    </small>
                  </span>
                  <em>{acceptedRubricMarks}/{totalRubricMarks} 分保留</em>
                </button>
                {questionSummaries.map((summary) => {
                  const reviewedCount = summary.criteria.length - summary.pendingCount;
                  const reviewState = summary.pendingCount > 0
                    ? `待处理 ${summary.pendingCount} 条`
                    : summary.rejectedCount > 0
                      ? `已处理 · 排除 ${summary.rejectedCount} 条`
                      : "全部保留";
                  return (
                    <button
                      aria-controls="rubric-question-review"
                      aria-current={questionFilter === summary.number ? "true" : undefined}
                      className={[
                        questionFilter === summary.number ? "active" : "",
                        summary.pendingCount > 0
                          ? "pending"
                          : summary.rejectedCount > 0
                            ? "reviewed"
                            : "accepted",
                      ].filter(Boolean).join(" ")}
                      disabled={controlsLocked}
                      key={summary.number}
                      onClick={() => setQuestionFilter(summary.number)}
                      type="button"
                    >
                      <span>
                        <b>Q{summary.number}</b>
                        <small>{reviewState} · {reviewedCount}/{summary.criteria.length}</small>
                      </span>
                      <em>{summary.acceptedMarks}/{summary.totalMarks} 分</em>
                    </button>
                  );
                })}
              </div>
            </nav>

            <div className="rubric-question-review" id="rubric-question-review">
              {rubric.warnings.length > 0 && (
                <details className="rubric-warning-summary">
                  <summary>
                    <TriangleAlert size={14} />
                    解析提示 <b>{rubric.warnings.length}</b> 条
                  </summary>
                  <div>
                    {rubric.warnings.map((warning) => (
                      <p className="inline-warning" key={warning}>{warning}</p>
                    ))}
                  </div>
                </details>
              )}
              {visibleQuestionGroups.map((group) => {
                const reviewedCount = group.criteria.length - group.pendingCount;
                return (
                  <section
                    aria-labelledby={`rubric-question-heading-${group.number}`}
                    className="rubric-question-group"
                    key={group.number}
                  >
                    <header className="rubric-question-group-header">
                      <div>
                        <span>题目 {group.number}</span>
                        <h3 id={`rubric-question-heading-${group.number}`}>
                          Q{group.number} 得分点
                        </h3>
                        <p>
                          已处理 {reviewedCount}/{group.criteria.length} 条
                          {group.pendingCount > 0 ? ` · 还有 ${group.pendingCount} 条` : " · 本题规则已完成"}
                        </p>
                      </div>
                      <div
                        aria-label={`Q${group.number} 已保留 ${group.acceptedMarks} 分，共 ${group.totalMarks} 分`}
                        className="rubric-question-mark-ledger"
                      >
                        <strong>{group.acceptedMarks}<span> / {group.totalMarks} 分</span></strong>
                        <small>已保留分值</small>
                      </div>
                    </header>
                    <div className="rubric-question-status-row">
                      <span className="accepted">{group.acceptedCount} 条已保留</span>
                      <span className="rejected">{group.rejectedCount} 条已排除</span>
                      <span className="pending">{group.pendingCount} 条待处理</span>
                    </div>
                    <div className="rubric-criterion-list">
                      {group.visibleCriteria.map((item) => (
                        <RubricCriterionEditor
                          criterion={item}
                          disabled={rubric.status !== "draft" || controlsLocked}
                          key={`${rubric.id}:${item.id}`}
                          onDirtyChange={reportDirtyCriterion}
                          onReview={reviewCriterionAndRestoreFocus}
                          onSelectedChange={toggleSelection}
                          reviewable={rubric.status === "draft"}
                          rubricId={rubric.id}
                          selectable={selectableVisibleIds.has(item.id) && !controlsLocked}
                          selected={selectedIds.has(item.id)}
                        />
                      ))}
                      {group.visibleCriteria.length === 0 && (
                        <div className="empty compact-empty">
                          <BookOpenCheck size={26} />
                          <p>本题在当前审核状态筛选下没有得分点。</p>
                        </div>
                      )}
                    </div>
                  </section>
                );
              })}
              {visibleQuestionGroups.length === 0 && (
                <div className="empty compact-empty">
                  <BookOpenCheck size={26} />
                  <p>当前审核状态筛选下没有得分点。</p>
                </div>
              )}
            </div>
          </div>
          {reviewCompletion && (
            <p
              aria-live="polite"
              className="sr-only"
              key={reviewCompletion.sequence}
              role="status"
            >
              {reviewCompletion.message}
            </p>
          )}
        </>
      )}

      {rubric?.status !== "draft" && (
        <div className="rubric-action-error">
          <ErrorBanner message={error} />
        </div>
      )}
      {rubric?.status === "draft" && dirtyCriterionIds.size > 0 && (
        <div className="criterion-dirty-notice" id="rubric-final-confirm-guidance" role="status">
          <span>
            仍有 {dirtyCriterionIds.size} 条未保存修改。请逐条保存并保留，或确认放弃修改后，
            才能确认整套评分规则。
          </span>
        </div>
      )}
      <footer className="grading-stage-actions">
        <button className="secondary" disabled={controlsLocked} onClick={onBack} type="button">
          <X size={16} />
          关闭
        </button>
        {rubric?.status === "draft" ? (
          <button
            aria-describedby={dirtyCriterionIds.size > 0 ? "rubric-final-confirm-guidance" : undefined}
            className="primary grading-primary-action"
            disabled={
              busy !== null
              || confirmationOpen
              || dirtyCriterionIds.size > 0
              || pendingCriteria > 0
              || acceptedCriteria === 0
              || !reviewer.trim()
            }
            onClick={() => void onConfirmRubric()}
            type="button"
          >
            {busy === "confirm-rubric"
              ? <LoaderCircle className="spin" size={17} />
              : <CheckCircle2 size={17} />}
            确认规则并开始评分
          </button>
        ) : (
          <button className="primary grading-primary-action" disabled={!rubric} onClick={onNext} type="button">
            返回逐题判分
            <ArrowRight size={17} />
          </button>
        )}
      </footer>
    </article>
  );
}
