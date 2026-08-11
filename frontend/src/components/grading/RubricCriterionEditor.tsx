import { CheckCircle2, Sparkles, XCircle } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import type { RubricCriterionPatch, RubricSet } from "../../types";
import { Confidence } from "../Feedback";
import { Markdown } from "../Markdown";

type RubricCriterion = RubricSet["criteria"][number];

type CriterionDraft = {
  version: 1;
  rubricId: string;
  criterionId: string;
  canonicalFingerprint: string;
  description: string;
  maxMarks: string;
  markType: string;
  sourceExcerpt: string;
  note: string;
  loadedSuggestedUpdates: RubricCriterionPatch | null;
};

const DRAFT_STORAGE_PREFIX = "grading.rubric-criterion-draft.v1";

type UnknownRubricCriterionPatch = {
  [Field in keyof RubricCriterionPatch]?: unknown;
};

function isNullableString(value: unknown): value is string | null {
  return typeof value === "string" || value === null;
}

function isNullableStringArray(value: unknown): value is string[] | null {
  return value === null || (Array.isArray(value) && value.every((item) => typeof item === "string"));
}

function isRubricCriterionPatch(value: unknown): value is RubricCriterionPatch {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const patch = value as UnknownRubricCriterionPatch;
  return (patch.accuracy_requirement === undefined || isNullableString(patch.accuracy_requirement))
    && (patch.alternatives === undefined || isNullableStringArray(patch.alternatives))
    && (patch.dependencies === undefined || isNullableStringArray(patch.dependencies))
    && (patch.description === undefined || isNullableString(patch.description))
    && (patch.follow_through_policy === undefined || isNullableString(patch.follow_through_policy))
    && (patch.mark_type === undefined || isNullableString(patch.mark_type))
    && (
      patch.max_marks === undefined
      || typeof patch.max_marks === "number"
      || patch.max_marks === null
    )
    && (
      patch.scoring_mode === undefined
      || patch.scoring_mode === null
      || patch.scoring_mode === "point_based"
      || patch.scoring_mode === "levels_based"
    )
    && (patch.source_excerpt === undefined || isNullableString(patch.source_excerpt))
    && (
      patch.source_page === undefined
      || typeof patch.source_page === "number"
      || patch.source_page === null
    )
    && (patch.units === undefined || isNullableStringArray(patch.units));
}

function criterionFingerprint(criterion: RubricCriterion): string {
  return JSON.stringify([
    criterion.accuracy_requirement,
    criterion.alternatives,
    criterion.dependencies,
    criterion.description,
    criterion.follow_through_policy,
    criterion.mark_type,
    criterion.max_marks,
    criterion.scoring_mode,
    criterion.source_excerpt,
    criterion.source_page,
    criterion.units,
    criterion.review_status,
    criterion.reviewed_at,
    criterion.reviewed_by,
  ]);
}

function storageKey(rubricId: string, criterionId: string): string {
  return `${DRAFT_STORAGE_PREFIX}:${encodeURIComponent(rubricId)}:${encodeURIComponent(criterionId)}`;
}

function removeStoredDraft(rubricId: string, criterionId: string) {
  try {
    window.sessionStorage.removeItem(storageKey(rubricId, criterionId));
  } catch {
    // Session storage can be unavailable in privacy-restricted browsing contexts.
  }
}

function readStoredDraft(rubricId: string, criterionId: string): CriterionDraft | null {
  try {
    const raw = window.sessionStorage.getItem(storageKey(rubricId, criterionId));
    if (!raw) return null;
    const value: unknown = JSON.parse(raw);
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      removeStoredDraft(rubricId, criterionId);
      return null;
    }
    const draft = value as Partial<CriterionDraft> & { loadedSuggestedUpdates?: unknown };
    if (
      draft.version !== 1
      || draft.rubricId !== rubricId
      || draft.criterionId !== criterionId
      || typeof draft.canonicalFingerprint !== "string"
      || typeof draft.description !== "string"
      || typeof draft.maxMarks !== "string"
      || typeof draft.markType !== "string"
      || typeof draft.sourceExcerpt !== "string"
      || typeof draft.note !== "string"
      || !(draft.loadedSuggestedUpdates === null || isRubricCriterionPatch(draft.loadedSuggestedUpdates))
    ) {
      removeStoredDraft(rubricId, criterionId);
      return null;
    }
    return value as CriterionDraft;
  } catch {
    removeStoredDraft(rubricId, criterionId);
    return null;
  }
}


function canonicalDraft(rubricId: string, criterion: RubricCriterion): CriterionDraft {
  return {
    version: 1,
    rubricId,
    criterionId: criterion.id,
    canonicalFingerprint: criterionFingerprint(criterion),
    description: criterion.description,
    maxMarks: String(criterion.max_marks),
    markType: criterion.mark_type ?? "",
    sourceExcerpt: criterion.source_excerpt,
    note: "",
    loadedSuggestedUpdates: null,
  };
}

function initialDraft(rubricId: string, criterion: RubricCriterion): CriterionDraft {
  const stored = readStoredDraft(rubricId, criterion.id);
  if (stored?.canonicalFingerprint === criterionFingerprint(criterion)) return stored;
  if (stored) removeStoredDraft(rubricId, criterion.id);
  return canonicalDraft(rubricId, criterion);
}

function draftIsDirty(draft: CriterionDraft, criterion: RubricCriterion): boolean {
  return draft.description.trim() !== criterion.description
    || Number(draft.maxMarks) !== criterion.max_marks
    || draft.markType.trim() !== (criterion.mark_type ?? "")
    || draft.sourceExcerpt !== criterion.source_excerpt
    || draft.note !== ""
    || draft.loadedSuggestedUpdates !== null;
}

const UPDATE_LABELS: Record<string, string> = {
  accuracy_requirement: "精度要求",
  alternatives: "替代答案",
  dependencies: "依赖得分点",
  description: "判分描述",
  follow_through_policy: "后续跟随规则",
  mark_type: "标记类型",
  max_marks: "分值",
  scoring_mode: "计分方式",
  source_excerpt: "官方原文依据",
  source_page: "来源页",
  units: "单位",
};

function updateValue(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join("、") : "空";
  return String(value);
}

function samePatchValue(current: unknown, proposed: unknown): boolean {
  if (Array.isArray(current) && Array.isArray(proposed)) {
    return current.length === proposed.length
      && current.every((item, index) => item === proposed[index]);
  }
  return current === proposed;
}

function actionableSuggestedUpdates(
  criterion: RubricCriterion,
  patch: RubricCriterionPatch | null | undefined,
): RubricCriterionPatch | null {
  if (!patch) return null;
  const entries = Object.entries(patch).filter(([field, value]) => (
    value !== null
    && value !== undefined
    && !samePatchValue(criterion[field as keyof RubricCriterion], value)
  ));
  return entries.length ? Object.fromEntries(entries) as RubricCriterionPatch : null;
}

export function RubricCriterionEditor({
  criterion,
  disabled,
  selected,
  selectable,
  reviewable = true,
  rubricId = "standalone",
  onDirtyChange,
  onSelectedChange,
  onReview,
}: {
  criterion: RubricCriterion;
  disabled: boolean;
  selected: boolean;
  selectable: boolean;
  rubricId?: string;
  reviewable?: boolean;
  onDirtyChange?: (rubricId: string, criterionId: string, dirty: boolean) => void;
  onSelectedChange: (criterionId: string, selected: boolean) => void;
  onReview: (
    criterionId: string,
    reviewStatus: "accepted" | "rejected",
    note: string,
    updates: RubricCriterionPatch | undefined,
  ) => Promise<boolean | "focus-handled">;
}) {
  const fingerprint = criterionFingerprint(criterion);
  const [draft, setDraft] = useState<CriterionDraft>(() => initialDraft(rubricId, criterion));
  const previousCriterionRef = useRef(criterion);
  const previousRubricIdRef = useRef(rubricId);
  const submittedReviewRef = useRef<{
    criterionId: string;
    reviewedAt: string | null;
    reviewedBy: string | null;
    reviewStatus: RubricCriterion["review_status"];
  } | null>(null);
  const headingId = useId();
  const statusId = useId();
  const dirtyId = useId();
  const descriptionErrorId = useId();
  const marksErrorId = useId();
  const headingRef = useRef<HTMLElement>(null);
  const discardOpenerRef = useRef<HTMLButtonElement>(null);
  const discardCancelRef = useRef<HTMLButtonElement>(null);
  const acceptActionRef = useRef<HTMLButtonElement>(null);
  const rejectActionRef = useRef<HTMLButtonElement>(null);
  const discardSequenceRef = useRef(0);
  const [discardConfirming, setDiscardConfirming] = useState(false);
  const [discardAnnouncement, setDiscardAnnouncement] = useState<{
    sequence: number;
    message: string;
  } | null>(null);
  const submittingRef = useRef(false);
  const [submitting, setSubmitting] = useState(false);
  const [failureFocusTarget, setFailureFocusTarget] = useState<"accept" | "reject" | null>(null);

  const activeDraft = (
    draft.rubricId === rubricId
    && draft.criterionId === criterion.id
    && draft.canonicalFingerprint === fingerprint
  ) ? draft : canonicalDraft(rubricId, criterion);
  const {
    description,
    maxMarks,
    markType,
    sourceExcerpt,
    note,
    loadedSuggestedUpdates,
  } = activeDraft;
  const parsedMarks = Number(maxMarks);
  const descriptionError = description.trim()
    ? null
    : "判分描述不能为空。请输入可判定的得分条件。";
  const marksError = !maxMarks.trim() || !Number.isFinite(parsedMarks)
    ? "分值必须是有限数字。"
    : parsedMarks <= 0 ? "分值必须大于 0。" : null;
  const invalid = descriptionError !== null || marksError !== null;
  const fieldDirty = (
    description.trim() !== criterion.description
    || parsedMarks !== criterion.max_marks
    || markType.trim() !== (criterion.mark_type ?? "")
    || sourceExcerpt !== criterion.source_excerpt
    || loadedSuggestedUpdates !== null
  );
  const dirty = draftIsDirty(activeDraft, criterion);
  const controlsDisabled = disabled || submitting;
  const suggestedUpdates = actionableSuggestedUpdates(
    criterion,
    criterion.ai_review?.suggested_updates,
  );

  useEffect(() => {
    const previous = previousCriterionRef.current;
    const previousRubricId = previousRubricIdRef.current;
    const submission = submittedReviewRef.current;
    const savedSubmission = submission?.criterionId === criterion.id
      && (
        submission.reviewedAt !== criterion.reviewed_at
        || submission.reviewedBy !== criterion.reviewed_by
        || submission.reviewStatus !== criterion.review_status
      );

    if (previousRubricId !== rubricId || previous.id !== criterion.id) {
      setDraft(initialDraft(rubricId, criterion));
      submittedReviewRef.current = null;
    } else if (criterionFingerprint(previous) !== fingerprint || savedSubmission) {
      removeStoredDraft(rubricId, criterion.id);
      setDraft(canonicalDraft(rubricId, criterion));
      submittedReviewRef.current = null;
    }
    previousCriterionRef.current = criterion;
    previousRubricIdRef.current = rubricId;
  }, [criterion, fingerprint, rubricId]);

  useEffect(() => {
    setDiscardConfirming(false);
    setDiscardAnnouncement(null);
  }, [criterion.id, rubricId]);

  useEffect(() => {
    if (discardConfirming) discardCancelRef.current?.focus();
  }, [discardConfirming]);

  useEffect(() => {
    if (
      draft.rubricId !== rubricId
      || draft.criterionId !== criterion.id
      || draft.canonicalFingerprint !== fingerprint
    ) return;
    const draftDirty = draftIsDirty(draft, criterion);
    if (draftDirty) {
      try {
        window.sessionStorage.setItem(storageKey(rubricId, criterion.id), JSON.stringify(draft));
      } catch {
        // The in-memory draft remains usable when session storage is unavailable.
      }
    } else {
      removeStoredDraft(rubricId, criterion.id);
    }
    onDirtyChange?.(rubricId, criterion.id, draftDirty);
  }, [criterion, draft, fingerprint, onDirtyChange, rubricId]);

  useEffect(() => {
    if (!failureFocusTarget || controlsDisabled) return;
    const frame = window.requestAnimationFrame(() => {
      const target = failureFocusTarget === "accept"
        ? acceptActionRef.current
        : rejectActionRef.current;
      target?.focus();
      setFailureFocusTarget(null);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [controlsDisabled, failureFocusTarget]);

  function updates(): RubricCriterionPatch | undefined {
    if (!fieldDirty) return undefined;
    return {
      accuracy_requirement: criterion.accuracy_requirement,
      alternatives: criterion.alternatives,
      dependencies: criterion.dependencies,
      follow_through_policy: criterion.follow_through_policy,
      scoring_mode: criterion.scoring_mode,
      source_page: criterion.source_page,
      units: criterion.units,
      ...loadedSuggestedUpdates,
      description: description.trim(),
      mark_type: markType.trim() || null,
      max_marks: parsedMarks,
      source_excerpt: sourceExcerpt,
    };
  }

  function loadSuggestedUpdates() {
    const suggested = suggestedUpdates;
    if (!suggested) return;
    setDraft((current) => ({
      ...current,
      loadedSuggestedUpdates: suggested,
      description: typeof suggested.description === "string"
        ? suggested.description
        : current.description,
      maxMarks: typeof suggested.max_marks === "number"
        ? String(suggested.max_marks)
        : current.maxMarks,
      markType: suggested.mark_type !== undefined
        ? suggested.mark_type ?? ""
        : current.markType,
      sourceExcerpt: suggested.source_excerpt !== undefined
        ? suggested.source_excerpt ?? ""
        : current.sourceExcerpt,
    }));
  }

  async function applySuggestedUpdates() {
    const suggested = suggestedUpdates;
    if (!suggested) return;
    await submitReview(
      "accepted",
      "已核对并应用 AI 审核建议",
      suggested,
    );
  }

  function revertDraft() {
    removeStoredDraft(rubricId, criterion.id);
    setDraft(canonicalDraft(rubricId, criterion));
  }

  function requestDiscard() {
    setDiscardAnnouncement(null);
    setDiscardConfirming(true);
  }

  function cancelDiscard() {
    setDiscardConfirming(false);
    window.requestAnimationFrame(() => discardOpenerRef.current?.focus());
  }

  function confirmDiscard() {
    revertDraft();
    setDiscardConfirming(false);
    setDiscardAnnouncement({
      sequence: ++discardSequenceRef.current,
      message: `Q${criterion.question_number} · ${criterion.criterion_id} 的未保存修改已放弃。`,
    });
    window.requestAnimationFrame(() => headingRef.current?.focus());
  }

  async function submitReview(
    reviewStatus: "accepted" | "rejected",
    reviewNote: string,
    criterionUpdates: RubricCriterionPatch | undefined,
  ) {
    if (controlsDisabled || submittingRef.current) return;
    submittingRef.current = true;
    setSubmitting(true);
    setFailureFocusTarget(null);
    try {
      const outcome = await onReview(criterion.id, reviewStatus, reviewNote, criterionUpdates);
      if (outcome !== true) {
        if (outcome !== "focus-handled") {
          setFailureFocusTarget(reviewStatus === "accepted" ? "accept" : "reject");
        }
        return;
      }
      submittedReviewRef.current = {
        criterionId: criterion.id,
        reviewedAt: criterion.reviewed_at,
        reviewedBy: criterion.reviewed_by,
        reviewStatus: criterion.review_status,
      };
      removeStoredDraft(rubricId, criterion.id);
      setDraft(canonicalDraft(rubricId, criterion));
      onDirtyChange?.(rubricId, criterion.id, false);
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  }

  const aiReview = criterion.ai_review;
  const suggestionLabel = aiReview?.recommendation === "accept"
    ? "建议保留"
    : aiReview?.recommendation === "reject" ? "建议排除" : "建议修改";

  return (
    <article
      aria-busy={submitting || undefined}
      aria-describedby={`${statusId}${dirty ? ` ${dirtyId}` : ""}`}
      aria-labelledby={headingId}
      className={`rubric-criterion-card ${criterion.review_status}${dirty ? " is-dirty" : ""}`}
      data-rubric-criterion-id={criterion.id}
    >
      <header>
        <div>
          <label className="criterion-selection">
            <input
              aria-label={`选择 Q${criterion.question_number} ${criterion.criterion_id}`}
              checked={selected}
              disabled={!selectable}
              data-rubric-pending-control=""
              onChange={(event) => onSelectedChange(criterion.id, event.target.checked)}
              type="checkbox"
            />
            <span className="sr-only">选择当前得分点</span>
          </label>
          <strong aria-level={3} id={headingId} ref={headingRef} role="heading" tabIndex={-1}>
            Q{criterion.question_number} · {criterion.criterion_id}
          </strong>
          <span>{criterion.subpart === "whole" ? "整题" : `小问 ${criterion.subpart}`}</span>
        </div>
        <div className="rubric-criterion-score">
          <span className={`criterion-status ${criterion.review_status}`} id={statusId}>
            {criterion.review_status === "accepted"
              ? "已保留"
              : criterion.review_status === "rejected" ? "已排除" : "待处理"}
          </span>
          <b>{criterion.max_marks} 分</b>
        </div>
      </header>
      <fieldset className="rubric-criterion-fields">
        <legend className="sr-only">
          编辑 Q{criterion.question_number} · {criterion.criterion_id} 得分点
        </legend>
        <label className="rubric-description-field">
          判分描述
          <textarea
            aria-describedby={`${headingId}${descriptionError ? ` ${descriptionErrorId}` : ""}`}
            aria-invalid={descriptionError !== null}
            disabled={controlsDisabled}
            onChange={(event) => setDraft((current) => ({
              ...current,
              description: event.target.value,
            }))}
            rows={3}
            value={description}
          />
          {descriptionError && (
            <small className="field-error" id={descriptionErrorId}>{descriptionError}</small>
          )}
        </label>
        <label>
          分值
          <input
            aria-describedby={`${headingId}${marksError ? ` ${marksErrorId}` : ""}`}
            aria-invalid={marksError !== null}
            disabled={controlsDisabled}
            min="0.1"
            onChange={(event) => setDraft((current) => ({
              ...current,
              maxMarks: event.target.value,
            }))}
            step="0.1"
            type="number"
            value={maxMarks}
          />
          {marksError && (
            <small className="field-error" id={marksErrorId}>{marksError}</small>
          )}
        </label>
        <label>
          标记类型
          <input
            aria-describedby={headingId}
            disabled={controlsDisabled}
            onChange={(event) => setDraft((current) => ({
              ...current,
              markType: event.target.value,
            }))}
            placeholder="例如 M1 / A1 / B1"
            value={markType}
          />
        </label>
        <label className="rubric-source-field">
          官方原文依据
          <textarea
            aria-describedby={headingId}
            disabled={controlsDisabled}
            onChange={(event) => setDraft((current) => ({
              ...current,
              sourceExcerpt: event.target.value,
            }))}
            rows={2}
            value={sourceExcerpt}
          />
        </label>
        <label className="rubric-note-field">
          审核说明
          <input
            aria-describedby={headingId}
            disabled={controlsDisabled}
            onChange={(event) => setDraft((current) => ({
              ...current,
              note: event.target.value,
            }))}
            placeholder="可选；修改或排除时建议填写"
            value={note}
          />
        </label>
      </fieldset>
      {dirty && !discardConfirming && (
        <div className="criterion-dirty-notice" id={dirtyId} role="status">
          <span>
            {fieldDirty
              ? "有未保存字段修改；请保存并保留，或放弃修改后再使用排除和批量操作。"
              : "有未提交审核说明；可直接排除并提交说明，或放弃说明后再使用批量操作。"}
          </span>
          <button
            className="secondary"
            disabled={controlsDisabled}
            onClick={requestDiscard}
            ref={discardOpenerRef}
            type="button"
          >
            放弃未保存修改
          </button>
        </div>
      )}
      {dirty && discardConfirming && (
        <div
          aria-labelledby={`${dirtyId}-confirmation`}
          className="criterion-dirty-notice"
          id={dirtyId}
          onKeyDown={(event) => {
            if (event.key === "Escape" && !controlsDisabled) cancelDiscard();
          }}
          role="group"
        >
          <span id={`${dirtyId}-confirmation`}>
            <strong>确认放弃修改？</strong> 所有未保存字段和审核说明都会恢复为已保存内容。
          </span>
          <button className="secondary" disabled={controlsDisabled} onClick={cancelDiscard} ref={discardCancelRef} type="button">
            取消
          </button>
          <button className="secondary danger" disabled={controlsDisabled} onClick={confirmDiscard} type="button">
            确认放弃
          </button>
        </div>
      )}
      {discardAnnouncement && (
        <p
          aria-live="polite"
          className="sr-only"
          key={discardAnnouncement.sequence}
          role="status"
        >
          {discardAnnouncement.message}
        </p>
      )}
      {aiReview && (
        <aside
          aria-label={`Q${criterion.question_number} · ${criterion.criterion_id} 的 AI 审核建议`}
          className={`criterion-ai-review ${aiReview.recommendation}`}
        >
          <header>
            <span><Sparkles size={14} />AI 审核批注</span>
            <strong>{suggestionLabel}</strong>
            <Confidence value={aiReview.confidence} />
          </header>
          <div className="rubric-rich criterion-ai-rationale">
            <Markdown>{aiReview.rationale}</Markdown>
          </div>
          {suggestedUpdates && (
            <div className="criterion-ai-updates">
              <strong>建议修改</strong>
              <dl>
                {Object.entries(suggestedUpdates).map(([field, value]) => (
                  <div key={field}>
                    <dt>{UPDATE_LABELS[field] ?? field}</dt>
                    <dd><Markdown>{updateValue(value)}</Markdown></dd>
                  </div>
                ))}
              </dl>
              {reviewable && (
                <div className="criterion-ai-update-actions">
                  <button
                    aria-label={`载入 Q${criterion.question_number} · ${criterion.criterion_id} 的建议后继续编辑`}
                    className="secondary"
                    disabled={controlsDisabled}
                    onClick={loadSuggestedUpdates}
                    type="button"
                  >
                    载入后编辑
                  </button>
                  <button
                    aria-label={`应用 Q${criterion.question_number} · ${criterion.criterion_id} 的建议修改并保留规则`}
                    className="primary"
                    disabled={controlsDisabled}
                    onClick={() => void applySuggestedUpdates()}
                    type="button"
                  >
                    应用修改并保留
                  </button>
                </div>
              )}
            </div>
          )}
          <small>{aiReview.model} · {new Date(aiReview.reviewed_at).toLocaleString("zh-CN")}</small>
        </aside>
      )}
      {criterion.reviewed_by && (
        <small className="rubric-review-meta">
          最近由 {criterion.reviewed_by} 于{" "}
          {criterion.reviewed_at
            ? new Date(criterion.reviewed_at).toLocaleString("zh-CN")
            : "未知时间"}审核
        </small>
      )}
      {reviewable && (
        <footer>
          <button
            aria-label={`排除 Q${criterion.question_number} · ${criterion.criterion_id}`}
            aria-describedby={dirty ? dirtyId : undefined}
            className="secondary danger"
            data-rubric-review-action="reject"
            disabled={controlsDisabled || fieldDirty}
            ref={rejectActionRef}
            onClick={() => void submitReview("rejected", note, undefined)}
            type="button"
          >
            <XCircle size={16} />
            排除规则
          </button>
          <button
            aria-describedby={[
              descriptionError ? descriptionErrorId : null,
              marksError ? marksErrorId : null,
            ].filter(Boolean).join(" ") || undefined}
            aria-label={`${fieldDirty ? "保存修改并保留" : "保留"} Q${criterion.question_number} · ${criterion.criterion_id}`}
            className="secondary"
            data-rubric-review-action="accept"
            disabled={controlsDisabled || invalid}
            ref={acceptActionRef}
            onClick={() => void submitReview("accepted", note, updates())}
            type="button"
          >
            <CheckCircle2 size={16} />
            {fieldDirty ? "保存修改并保留" : "保留规则"}
          </button>
        </footer>
      )}
    </article>
  );
}
