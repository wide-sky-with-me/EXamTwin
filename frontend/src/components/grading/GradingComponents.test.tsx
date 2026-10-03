import { type ComponentProps, type ReactElement, useState } from "react";
import { act, render as testingLibraryRender, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import type {
  GradeResult,
  GradingOverviewResponse,
  PaperAssessment,
  PaperJobResult,
  RubricCriterionPatch,
  RubricSet,
} from "../../types";
import { GradingOverview } from "./GradingOverview";
import { GradingMaterialsStage } from "./GradingMaterialsStage";
import { RubricCriterionEditor } from "./RubricCriterionEditor";
import { GradingQuestionStage } from "./GradingQuestionStage";
import { RubricReviewStage } from "./RubricReviewStage";
import { DesignSystemProvider } from "../ui/DesignSystemProvider";
import { chooseSelectOption, selectRoot } from "../../test/antd-select";

function render(ui: ReactElement) {
  return testingLibraryRender(ui, { wrapper: DesignSystemProvider });
}

type Criterion = RubricSet["criteria"][number];

function suggestedPatch(): RubricCriterionPatch {
  return {
    accuracy_requirement: null,
    alternatives: null,
    dependencies: null,
    description: "AI loaded wording",
    follow_through_policy: null,
    mark_type: "A1",
    max_marks: 2,
    scoring_mode: "point_based",
    source_excerpt: "AI loaded source",
    source_page: 2,
    units: null,
  };
}

function criterionFixture(
  id: string,
  questionNumber: string,
  criterionId: string,
  aiReview = false,
): Criterion {
  return {
    id,
    question_number: questionNumber,
    subpart: "whole",
    criterion_id: criterionId,
    scoring_mode: "point_based",
    mark_type: criterionId,
    max_marks: 1,
    description: `Criterion ${criterionId}`,
    dependencies: [],
    alternatives: [],
    accuracy_requirement: null,
    units: [],
    follow_through_policy: null,
    source_page: 1,
    source_excerpt: `Official ${criterionId}`,
    confidence: 1,
    review_status: "pending",
    reviewed_by: null,
    reviewed_at: null,
    ai_review: aiReview ? {
      criterion_fingerprint: "a".repeat(64),
      recommendation: "revise",
      confidence: 0.9,
      rationale: "Use the clearer canonical wording.",
      suggested_updates: suggestedPatch(),
      model: "review-model",
      reviewed_at: "2026-08-08T00:00:00Z",
    } : null,
  };
}

function rubricFixture(criteria: Criterion[]): RubricSet {
  return {
    id: "rubric-components",
    subject_id: "subject",
    paper_job_id: "paper-job",
    source_document_id: "mark-scheme",
    version_number: 1,
    status: "draft",
    identity: {},
    parser_model: "parser",
    parser_version: "1",
    warnings: [],
    created_at: "2026-08-08T00:00:00Z",
    updated_at: "2026-08-08T00:00:00Z",
    confirmed_at: null,
    confirmed_by: null,
    criteria,
  };
}

function reviewStageElement(
  rubric: RubricSet | null,
  overrides: Partial<ComponentProps<typeof RubricReviewStage>> = {},
) {
  return (
    <RubricReviewStage
      busy={null}
      error={null}
      onAiReview={vi.fn(async () => undefined)}
      onBack={vi.fn()}
      onBatchReview={vi.fn(async () => true)}
      onConfirmRubric={vi.fn(async () => undefined)}
      onNext={vi.fn()}
      onReviewerChange={vi.fn()}
      onReviewCriterion={vi.fn(async () => true)}
      onSelectRubric={vi.fn(async () => undefined)}
      reviewer="Teacher"
      rubric={rubric}
      rubrics={[]}
      {...overrides}
    />
  );
}

function renderReviewStage(
  rubric: RubricSet | null,
  overrides: Partial<ComponentProps<typeof RubricReviewStage>> = {},
) {
  return render(reviewStageElement(rubric, overrides));
}

function ReviewerValidationHarness({
  onAiReview = vi.fn(async () => undefined),
  onBatchReview = vi.fn(async () => true),
  onReviewCriterion = vi.fn(async () => true),
}: {
  onAiReview?: ComponentProps<typeof RubricReviewStage>["onAiReview"];
  onBatchReview?: ComponentProps<typeof RubricReviewStage>["onBatchReview"];
  onReviewCriterion?: ComponentProps<typeof RubricReviewStage>["onReviewCriterion"];
}) {
  const [reviewer, setReviewer] = useState("");
  const [rubric] = useState(() => rubricFixture([
    criterionFixture("criterion-validation", "1", "B1"),
  ]));
  return reviewStageElement(rubric, {
    onAiReview,
    onBatchReview,
    onReviewerChange: setReviewer,
    onReviewCriterion,
    reviewer,
  });
}

function BatchPendingHarness({
  onBatchReview,
}: {
  onBatchReview: ComponentProps<typeof RubricReviewStage>["onBatchReview"];
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [rubric] = useState(() => rubricFixture([
    criterionFixture("criterion-batch-pending", "1", "B1"),
  ]));
  return reviewStageElement(rubric, {
    busy,
    onBatchReview: async (request) => {
      setBusy("batch-review");
      try {
        return await onBatchReview(request);
      } finally {
        setBusy(null);
      }
    },
  });
}

const gradeResult: GradeResult = {
    assessment_id: "assessment-one",
    citations: [],
    confidence: 0.9,
    improvement_suggestions: [],
    manual_review_required: true,
    question_ref: "1",
    rubric_awards: [],
    status: "pending_review",
    subject_code: "9709",
    symbolic_checks: [],
    total_available: 1,
    total_awarded: 1,
    warnings: [],
};

const gradingPaper: PaperJobResult = {
    chunks: [],
    completed_questions: 1,
    created_at: "2026-08-09T00:00:00Z",
    error: null,
    failed_questions: 0,
    filename: "student-paper.pdf",
    display_name: null,
    answer_mode: "generated",
    pair_key: null,
    paper_unit_id: null,
    question_paper_document_id: null,
    source_booklet_document_id: null,
    source_booklet_checksum: null,
    source_booklet_filename: null,
    graph_version_id: null,
    job_id: "paper-job",
    knowledge_base_version_ids: [],
    strategy_request: null,
    strategy_plan: null,
    parsed_pages: 1,
    questions: [{
      agent_steps: [],
      answer_markdown: "Student answer",
      skipped_by_strategy: false,
      answer_requirements: [],
      attempts: 1,
      citations: [],
      confidence: 1,
      diagrams: [],
      error: null,
      grounded: true,
      images: [],
      knowledge_points: [],
      number: "1",
      position: 1,
      question_markdown: "Question one",
      requires_visual_context: null,
      source_digest: null,
      source_kind: null,
      source_pages: [1],
      source_warnings: [],
      status: "completed",
      total_marks: 1,
      warnings: [],
    }],
    replaced_by_job_id: null,
    replacement_for_job_id: null,
    source_integrity_status: "verified",
    split_contract_version: null,
    split_source_digest: null,
    stage: "completed",
    status: "completed",
    subject_code: "9709",
    subject_pack_id: "subject",
    total_pages: 1,
    total_questions: 1,
    unit_code: "P2",
    updated_at: "2026-08-09T00:00:00Z",
};

function questionStageElement({
  assessments = [],
  busy = null,
  paper = gradingPaper,
}: {
  assessments?: PaperAssessment[];
  busy?: string | null;
  paper?: PaperJobResult;
} = {}) {
  const acceptedCriterion = {
    ...criterionFixture("criterion-question", "1", "B1"),
    review_status: "accepted" as const,
  };
  const rubric = {
    ...rubricFixture([acceptedCriterion]),
    status: "confirmed" as const,
  };
  return (
    <div className="grading-page">
      <GradingQuestionStage assessments={assessments}
      busy={busy}
      error={null}
      onAssessQuestion={vi.fn(async () => undefined)}
      onBack={vi.fn()}
      onViewRubric={vi.fn()}
      onOverview={vi.fn()}
      onSelectPosition={vi.fn()}
      paper={paper}
      rubric={rubric}
      selectedPosition={1} subjectId="test-subject" />
    </div>
  );
}

function SuccessfulFilteredReviewStage({
  initialRubric,
  onReviewCriterion,
}: {
  initialRubric: RubricSet;
  onReviewCriterion: ComponentProps<typeof RubricReviewStage>["onReviewCriterion"];
}) {
  const [rubric, setRubric] = useState(initialRubric);
  return reviewStageElement(rubric, {
    onReviewCriterion: async (...args) => {
      const completed = await onReviewCriterion(...args);
      if (!completed) return false;
      const [criterionId, reviewStatus] = args;
      setRubric((current) => ({
        ...current,
        criteria: current.criteria.map((criterion) => criterion.id === criterionId
          ? {
              ...criterion,
              review_status: reviewStatus,
              reviewed_at: "2026-08-08T01:00:00Z",
              reviewed_by: "Teacher",
            }
          : criterion),
      }));
      return true;
    },
  });
}
function overviewFixture(): GradingOverviewResponse {
  return {
    grade_estimate: null,
    paper_job_id: "paper-job",
    rubric_set_id: "rubric-components",
    total_awarded: 0,
    total_available: 0,
    percentage: null,
    completed_questions: 0,
    total_questions: 0,
    pending_review_count: 0,
    confirmed_count: 0,
    overridden_count: 0,
    incomplete: false,
    overall_suggestion: "",
    common_error_types: [],
    questions: [],
  };
}

afterEach(() => {
  window.sessionStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("grading component final-review regressions", () => {
  test("keeps saved-answer artifacts beside their anchored subparts", async () => {
    const user = userEvent.setup();
    const anchoredPaper: PaperJobResult = {
      ...gradingPaper,
      questions: [{
        ...gradingPaper.questions[0],
        answer_markdown: "### (a)\n\nFirst working.\n\n### (b)\n\nSecond working.",
        diagrams: [{
          artifact_id: "artifact-1",
          answer_anchor: "(a)",
          answer_order: 1,
          caption: "",
          elements: [{
            arrow_end: false,
            arrow_start: false,
            cx: null,
            cy: null,
            d: null,
            dashed: false,
            emphasis: false,
            fill: "none",
            kind: "point",
            points: [],
            r: null,
            rx: null,
            ry: null,
            text: null,
            tone: "default",
            x: 1,
            x1: null,
            x2: null,
            y: 1,
            y1: null,
            y2: null,
          }],
          legend: [],
          source: null,
          title: "Part A graph",
          tool_name: "math_plot",
          view_box: [0, 0, 600, 360],
        }],
      }],
    };
    render(questionStageElement({ paper: anchoredPaper }));

    await user.click(screen.getByText("已保存答案"));

    const savedAnswer = screen.getByText("已保存答案").closest("details")!;
    const text = savedAnswer.textContent ?? "";
    expect(text.indexOf("First working.")).toBeLessThan(text.indexOf("Part A graph"));
    expect(text.indexOf("Part A graph")).toBeLessThan(text.indexOf("Second working."));
  });

  test("orders questions naturally and keeps M, A, B marks in award sequence", async () => {
    const user = userEvent.setup();
    renderReviewStage(rubricFixture([
      criterionFixture("q10-b1", "10", "Q10-B1"),
      criterionFixture("q2-a2", "2", "Q2-A2"),
      criterionFixture("q2-m2", "2", "Q2-M2"),
      criterionFixture("q1-a1", "1", "Q1-A1"),
      criterionFixture("q2-a1", "2", "Q2-A1"),
      criterionFixture("q2-m1", "2", "Q2-M1"),
      criterionFixture("q1-m1", "1", "Q1-M1"),
    ]));

    const questionNav = screen.getByRole("navigation", { name: "得分点题目导航" });
    expect(within(questionNav).getAllByRole("button").map((button) => button.textContent)).toEqual([
      expect.stringMatching(/^全部题目/),
      expect.stringMatching(/^Q1/),
      expect.stringMatching(/^Q2/),
      expect.stringMatching(/^Q10/),
    ]);

    await user.click(within(questionNav).getByRole("button", { name: /^全部题目/ }));
    expect(
      [...document.querySelectorAll<HTMLElement>("[data-rubric-criterion-id]")]
        .map((element) => element.dataset.rubricCriterionId),
    ).toEqual(["q1-m1", "q1-a1", "q2-m1", "q2-a1", "q2-m2", "q2-a2", "q10-b1"]);
  });

  test("groups criteria by question with review progress and accepted mark totals", async () => {
    const accepted = {
      ...criterionFixture("criterion-accepted", "1", "B1"),
      review_status: "accepted" as const,
    };
    const pending = {
      ...criterionFixture("criterion-pending", "1", "M1"),
      max_marks: 2,
    };
    const rejected = {
      ...criterionFixture("criterion-rejected", "2", "A1"),
      max_marks: 3,
      review_status: "rejected" as const,
    };
    const user = userEvent.setup();
    renderReviewStage(rubricFixture([accepted, pending, rejected]));

    const questionNav = screen.getByRole("navigation", { name: "得分点题目导航" });
    const q1Button = within(questionNav).getByRole("button", { name: /^Q1\b/ });
    const q2Button = within(questionNav).getByRole("button", { name: /^Q2\b/ });
    expect(q1Button).toHaveTextContent("待处理 1 条");
    expect(q1Button).toHaveTextContent("1/3 分");
    expect(q2Button).toHaveTextContent("已处理 · 排除 1 条");
    expect(q2Button).toHaveTextContent("0/3 分");
    expect(screen.getByRole("heading", { name: "Q1 得分点" })).toBeInTheDocument();

    await user.click(q2Button);

    expect(screen.getByRole("heading", { name: "Q2 得分点" })).toBeInTheDocument();
    expect(screen.queryByText("Q1 · B1")).not.toBeInTheDocument();
    expect(screen.getByText("Q2 · A1")).toBeInTheDocument();
  });


  test("restores every dirty criterion field after filter and step unmount", async () => {
    const rubric = rubricFixture([
      criterionFixture("criterion-one", "1", "B1", true),
      criterionFixture("criterion-two", "2", "M1"),
    ]);
    const user = userEvent.setup();
    const mounted = renderReviewStage(rubric);
    const firstCard = screen.getByText("Q1 · B1").closest("article");
    expect(firstCard).not.toBeNull();

    expect(within(firstCard!).queryByText("未设置")).not.toBeInTheDocument();
    expect(within(firstCard!).queryByText("计分方式")).not.toBeInTheDocument();
    await user.click(within(firstCard!).getByRole("button", { name: "载入 Q1 · B1 的建议后继续编辑" }));
    await user.type(within(firstCard!).getByLabelText("审核说明"), "Teacher note");
    expect(within(firstCard!).getByLabelText("判分描述")).toHaveValue("AI loaded wording");
    expect(within(firstCard!).getByLabelText("分值")).toHaveValue(2);
    expect(within(firstCard!).getByLabelText("标记类型")).toHaveValue("A1");
    expect(within(firstCard!).getByLabelText("官方原文依据")).toHaveValue("AI loaded source");

    const questionNav = screen.getByRole("navigation", { name: "得分点题目导航" });
    await user.click(within(questionNav).getByRole("button", { name: /^Q2\b/ }));
    expect(screen.queryByText("Q1 · B1")).not.toBeInTheDocument();
    await user.click(within(questionNav).getByRole("button", { name: /^Q1\b/ }));

    const restoredAfterFilter = screen.getByText("Q1 · B1").closest("article")!;
    expect(within(restoredAfterFilter).getByLabelText("判分描述")).toHaveValue("AI loaded wording");
    expect(within(restoredAfterFilter).getByLabelText("分值")).toHaveValue(2);
    expect(within(restoredAfterFilter).getByLabelText("标记类型")).toHaveValue("A1");
    expect(within(restoredAfterFilter).getByLabelText("官方原文依据")).toHaveValue("AI loaded source");
    expect(within(restoredAfterFilter).getByLabelText("审核说明")).toHaveValue("Teacher note");

    mounted.unmount();
    renderReviewStage(rubric);
    const restoredAfterStep = screen.getByText("Q1 · B1").closest("article")!;
    expect(within(restoredAfterStep).getByLabelText("判分描述")).toHaveValue("AI loaded wording");
    expect(within(restoredAfterStep).getByLabelText("审核说明")).toHaveValue("Teacher note");
    expect(within(restoredAfterStep).getByRole("button", { name: "保存修改并保留 Q1 · B1" })).toBeEnabled();
  });

  test("discards a malformed session draft instead of exposing it to the editor", () => {
    window.sessionStorage.setItem(
      "grading.rubric-criterion-draft.v1:rubric-components:criterion-one",
      "{not-json",
    );
    const criterion = criterionFixture("criterion-one", "1", "B1");
    render(
      <RubricCriterionEditor
        criterion={criterion}
        disabled={false}
        onDirtyChange={vi.fn()}
        onReview={vi.fn(async () => true)}
        onSelectedChange={vi.fn()}
        rubricId="rubric-components"
        selectable
        selected={false}
      />,
    );

    expect(screen.getByLabelText("判分描述")).toHaveValue("Criterion B1");
    expect(window.sessionStorage).toHaveLength(0);
  });

  test("explains invalid criterion fields and associates each error with its control", async () => {
    const criterion = criterionFixture("criterion-invalid", "1", "B1");
    const user = userEvent.setup();
    render(
      <RubricCriterionEditor
        criterion={criterion}
        disabled={false}
        onReview={vi.fn(async () => true)}
        onSelectedChange={vi.fn()}
        rubricId="rubric-components"
        selectable
        selected={false}
      />,
    );

    const description = screen.getByLabelText("判分描述");
    const marks = screen.getByLabelText("分值");
    await user.clear(description);
    expect(description).toHaveAttribute("aria-invalid", "true");
    expect(description).toHaveAccessibleDescription(
      /判分描述不能为空。请输入可判定的得分条件。/,
    );
    expect(screen.getByRole("button", { name: "保存修改并保留 Q1 · B1" })).toBeDisabled();

    await user.type(description, "Award for a correct method.");
    await user.clear(marks);
    expect(marks).toHaveAttribute("aria-invalid", "true");
    expect(marks).toHaveAccessibleDescription(/分值必须是有限数字。/);
    expect(screen.getByRole("button", { name: "保存修改并保留 Q1 · B1" })).toBeDisabled();

    await user.type(marks, "0");
    expect(marks).toHaveAccessibleDescription(/分值必须大于 0。/);
    await user.clear(marks);
    await user.type(marks, "2");
    expect(marks).toHaveAttribute("aria-invalid", "false");
    expect(screen.getByRole("button", { name: "保存修改并保留 Q1 · B1" })).toBeEnabled();
  });

  test("submits a note-only direct reject but gates reject for field edits", async () => {
    const criterion = criterionFixture("criterion-reject", "1", "B1");
    const onReview = vi.fn(async () => true);
    const user = userEvent.setup();
    render(
      <RubricCriterionEditor
        criterion={criterion}
        disabled={false}
        onReview={onReview}
        onSelectedChange={vi.fn()}
        rubricId="rubric-components"
        selectable
        selected={false}
      />,
    );

    const reject = screen.getByRole("button", { name: "排除 Q1 · B1" });
    await user.type(screen.getByLabelText("审核说明"), "Missing official support");
    expect(reject).toBeEnabled();
    await user.click(reject);
    await waitFor(() => expect(onReview).toHaveBeenCalledWith(
      "criterion-reject",
      "rejected",
      "Missing official support",
      undefined,
    ));
    expect(screen.getByLabelText("审核说明")).toHaveValue("");
    expect(window.sessionStorage).toHaveLength(0);

    await user.type(screen.getByLabelText("判分描述"), " revised");
    expect(reject).toBeDisabled();
    expect(reject).toHaveAccessibleDescription(/请保存并保留，或放弃修改后/);
    await user.click(reject);
    expect(onReview).toHaveBeenCalledTimes(1);
  });

  test("drops unsaved text when the server replaces the criterion with a canonical status", async () => {
    const criterion = criterionFixture("criterion-one", "1", "B1");
    const onDirtyChange = vi.fn();
    const user = userEvent.setup();
    const common = {
      onDirtyChange,
      onReview: vi.fn(async () => true),
      onSelectedChange: vi.fn(),
      rubricId: "rubric-components",
      selected: false,
    };
    const mounted = render(
      <RubricCriterionEditor
        {...common}
        criterion={criterion}
        disabled={false}
        selectable
      />,
    );
    const description = screen.getByLabelText("判分描述");
    await user.clear(description);
    await user.type(description, "Accepted-looking unsaved wording");
    await user.type(screen.getByLabelText("审核说明"), "Unsaved note");
    await waitFor(() => expect(window.sessionStorage).toHaveLength(1));

    mounted.rerender(
      <RubricCriterionEditor
        {...common}
        criterion={{
          ...criterion,
          description: "Canonical saved wording",
          review_status: "accepted",
          reviewed_at: "2026-08-08T01:00:00Z",
          reviewed_by: "Teacher",
        }}
        disabled
        selectable={false}
      />,
    );

    expect(screen.getByLabelText("判分描述")).toHaveValue("Canonical saved wording");
    expect(screen.getByLabelText("审核说明")).toHaveValue("");
    await waitFor(() => expect(window.sessionStorage).toHaveLength(0));
    expect(screen.queryByText(/有未保存修改；请保存并保留/)).not.toBeInTheDocument();
    expect(onDirtyChange).toHaveBeenLastCalledWith("rubric-components", "criterion-one", false);
  });

  test("keeps restored drafts dirty only for their rubric identity after switching away and back", async () => {
    const sharedCriterion = criterionFixture("criterion-shared", "1", "B1");
    const rubricA = {
      ...rubricFixture([sharedCriterion]),
      id: "rubric-a",
      version_number: 1,
    };
    const rubricB = {
      ...rubricFixture([{ ...sharedCriterion, description: "Rubric B wording" }]),
      id: "rubric-b",
      version_number: 2,
    };
    const user = userEvent.setup();
    const mounted = renderReviewStage(rubricA);

    const rubricACard = screen.getByRole("heading", { name: "Q1 · B1" }).closest("article")!;
    await user.type(within(rubricACard).getByLabelText("审核说明"), "Restore this draft");
    await waitFor(() => expect(
      within(rubricACard).getByRole("checkbox", { name: "选择 Q1 B1" }),
    ).toBeDisabled());

    mounted.rerender(reviewStageElement(rubricB));
    const rubricBCard = screen.getByRole("heading", { name: "Q1 · B1" }).closest("article")!;
    await waitFor(() => expect(
      within(rubricBCard).getByRole("checkbox", { name: "选择 Q1 B1" }),
    ).toBeEnabled());
    expect(within(rubricBCard).getByLabelText("审核说明")).toHaveValue("");
    expect(screen.queryByText(/未保存修改，已从批量审核/)).not.toBeInTheDocument();

    mounted.rerender(reviewStageElement(rubricA));
    const restoredCard = screen.getByRole("heading", { name: "Q1 · B1" }).closest("article")!;
    expect(within(restoredCard).getByLabelText("审核说明")).toHaveValue("Restore this draft");
    await waitFor(() => expect(
      within(restoredCard).getByRole("checkbox", { name: "选择 Q1 B1" }),
    ).toBeDisabled());
    expect(screen.getByText(/1 条未保存修改，已从批量操作中排除/)).toBeVisible();
    expect(screen.getByRole("button", {
      name: "确认规则并开始评分",
    })).toHaveAccessibleDescription(/仍有 1 条未保存修改/);
  });

  test("keeps a single-review footer mounted and disabled while its POST is pending", async () => {
    let resolveReview: ((completed: boolean) => void) | undefined;
    const review = new Promise<boolean>((resolve) => { resolveReview = resolve; });
    const user = userEvent.setup();
    render(
      <RubricCriterionEditor
        criterion={criterionFixture("criterion-deferred", "1", "B1")}
        disabled={false}
        onReview={vi.fn(() => review)}
        onSelectedChange={vi.fn()}
        rubricId="rubric-components"
        selectable
        selected={false}
      />,
    );

    const accept = screen.getByRole("button", { name: "保留 Q1 · B1" });
    await user.click(accept);
    expect(accept).toBeInTheDocument();
    expect(accept).toBeDisabled();
    expect(screen.getByRole("button", { name: "排除 Q1 · B1" })).toBeDisabled();

    await act(async () => { resolveReview?.(true); await review; });
    expect(accept).toBeInTheDocument();
    expect(accept).toBeEnabled();
  });

  test("excludes dirty criteria from manual and AI batch decisions until revert", async () => {
    const rubric = rubricFixture([
      criterionFixture("criterion-dirty", "1", "B1"),
      criterionFixture("criterion-clean", "1", "M1"),
    ]);

    const onAiReview = vi.fn(async () => undefined);
    const onBatchReview = vi.fn(async () => true);
    const user = userEvent.setup();
    renderReviewStage(rubric, { onAiReview, onBatchReview });

    const dirtyCard = screen.getByText("Q1 · B1").closest("article")!;
    await user.type(within(dirtyCard).getByLabelText("审核说明"), "Unsaved individual note");
    await waitFor(() => expect(
      within(dirtyCard).getByRole("checkbox", { name: "选择 Q1 B1" }),
    ).toBeDisabled());
    expect(screen.getByText(/1 条未保存修改，已从批量操作中排除/)).toBeVisible();

    await user.click(screen.getByRole("button", { name: "AI 检查待处理规则" }));
    expect(onAiReview).toHaveBeenCalledWith({ criterion_ids: ["criterion-clean"] });

    await user.click(screen.getByRole("checkbox", { name: "选择当前筛选下待处理规则" }));
    expect(screen.getByText("1 / 1 已选择")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "保留所选" }));
    expect(onBatchReview).toHaveBeenCalledWith({
      reviewer: "Teacher",
      decisions: [{
        criterion_id: "criterion-clean",
        review_status: "accepted",
        note: null,
      }],
    });

    const discardOpener = within(dirtyCard).getByRole("button", { name: "放弃未保存修改" });
    await user.click(discardOpener);
    expect(within(dirtyCard).getByRole("group", { name: /确认放弃修改/ })).toBeVisible();
    await user.click(within(dirtyCard).getByRole("button", { name: "取消" }));
    await waitFor(() => expect(
      within(dirtyCard).getByRole("button", { name: "放弃未保存修改" }),
    ).toHaveFocus());
    expect(within(dirtyCard).getByLabelText("审核说明")).toHaveValue("Unsaved individual note");

    await user.click(within(dirtyCard).getByRole("button", { name: "放弃未保存修改" }));
    await user.click(within(dirtyCard).getByRole("button", { name: "确认放弃" }));
    expect(within(dirtyCard).getByText("Q1 · B1 的未保存修改已放弃。")).toBeInTheDocument();
    expect(within(dirtyCard).getByLabelText("审核说明")).toHaveValue("");
    await waitFor(() => expect(
      within(dirtyCard).getByRole("heading", { name: "Q1 · B1" }),
    ).toHaveFocus());
    expect(within(dirtyCard).getByRole("checkbox", { name: "选择 Q1 B1" })).toBeEnabled();
  });

  test("blocks final rubric confirmation until every dirty criterion is saved or reverted", async () => {
    const acceptedCriterion = {
      ...criterionFixture("criterion-accepted", "1", "B1"),
      review_status: "accepted" as const,
    };
    const onConfirmRubric = vi.fn(async () => undefined);
    const user = userEvent.setup();
    renderReviewStage(rubricFixture([acceptedCriterion]), { onConfirmRubric });

    const confirmRubric = screen.getByRole("button", {
      name: "确认规则并开始评分",
    });
    expect(confirmRubric).toBeEnabled();
    const card = screen.getByRole("heading", { name: "Q1 · B1" }).closest("article")!;
    await user.type(within(card).getByLabelText("审核说明"), "Unsaved note");

    expect(confirmRubric).toBeDisabled();
    expect(confirmRubric).toHaveAccessibleDescription(
      /仍有 1 条未保存修改。请逐条保存并保留，或确认放弃修改后/,
    );
    await user.click(within(card).getByRole("button", { name: "放弃未保存修改" }));
    await user.click(within(card).getByRole("button", { name: "确认放弃" }));
    await waitFor(() => expect(confirmRubric).toBeEnabled());
  });

  test("clears a successful pending-filter accept before the reviewed card unmounts", async () => {
    const onReviewCriterion = vi.fn(async () => true);
    const user = userEvent.setup();
    render(
      <SuccessfulFilteredReviewStage
        initialRubric={rubricFixture([criterionFixture("criterion-filtered", "1", "B1")])}
        onReviewCriterion={onReviewCriterion}
      />,
    );

    await chooseSelectOption(user, "审核状态", "待处理");
    const card = screen.getByRole("heading", { name: "Q1 · B1" }).closest("article")!;
    await user.type(within(card).getByLabelText("审核说明"), "Checked against source");
    await waitFor(() => expect(window.sessionStorage).toHaveLength(1));
    const confirmRubric = screen.getByRole("button", {
      name: "确认规则并开始评分",
    });
    expect(confirmRubric).toBeDisabled();

    await user.click(within(card).getByRole("button", { name: "保留 Q1 · B1" }));

    await waitFor(() => expect(
      screen.queryByRole("heading", { name: "Q1 · B1" }),
    ).not.toBeInTheDocument());
    expect(onReviewCriterion).toHaveBeenCalledWith(
      "criterion-filtered",
      "accepted",
      "Checked against source",
      undefined,
    );
    expect(confirmRubric).toBeEnabled();
    expect(window.sessionStorage).toHaveLength(0);
  });

  test("announces successful reviews and focuses the next action, then the review heading", async () => {
    const onReviewCriterion = vi.fn(async () => true);
    const user = userEvent.setup();
    render(
      <SuccessfulFilteredReviewStage
        initialRubric={rubricFixture([
          criterionFixture("criterion-first", "1", "B1"),
          criterionFixture("criterion-second", "1", "M1"),
        ])}
        onReviewCriterion={onReviewCriterion}
      />,
    );
    await chooseSelectOption(user, "审核状态", "待处理");

    await user.click(screen.getByRole("button", { name: "保留 Q1 · M1" }));
    const nextAccept = await screen.findByRole("button", { name: "保留 Q1 · B1" });
    await waitFor(() => expect(nextAccept).toHaveFocus());
    expect(screen.getByText("Q1 · M1 已保留。")).toBeInTheDocument();

    await user.click(nextAccept);
    await waitFor(() => expect(
      screen.getByRole("heading", { name: "审核评分标准" }),
    ).toHaveFocus());
    expect(screen.getByText("Q1 · B1 已保留。")).toBeInTheDocument();
  });

  test("preserves local and persisted drafts when an individual accept fails", async () => {
    const acceptedCriterion = {
      ...criterionFixture("criterion-failed", "1", "B1"),
      review_status: "accepted" as const,
    };
    const onReviewCriterion = vi.fn(async () => false);
    const user = userEvent.setup();
    renderReviewStage(rubricFixture([acceptedCriterion]), { onReviewCriterion });

    const card = screen.getByRole("heading", { name: "Q1 · B1" }).closest("article")!;
    await user.type(within(card).getByLabelText("判分描述"), " revised");
    await user.type(within(card).getByLabelText("审核说明"), "Retry this review");
    await waitFor(() => expect(window.sessionStorage).toHaveLength(1));
    const confirmRubric = screen.getByRole("button", {
      name: "确认规则并开始评分",
    });

    await user.click(within(card).getByRole("button", { name: "保存修改并保留 Q1 · B1" }));
    await waitFor(() => expect(onReviewCriterion).toHaveBeenCalledTimes(1));

    expect(within(card).getByLabelText("判分描述")).toHaveValue("Criterion B1 revised");
    expect(within(card).getByLabelText("审核说明")).toHaveValue("Retry this review");
    expect(window.sessionStorage).toHaveLength(1);
    expect(confirmRubric).toBeDisabled();

    await waitFor(() => expect(within(card).getByRole("button", {
      name: "保存修改并保留 Q1 · B1",
    })).toHaveFocus());
  });

  test("freezes batch reviewer, note, selection, and competing controls until snapshot submission", async () => {
    const rubric = rubricFixture([
      criterionFixture("criterion-one", "1", "B1"),
      criterionFixture("criterion-two", "1", "M1"),
    ]);
    const onBatchReview = vi.fn(async () => true);
    const user = userEvent.setup();
    const mounted = renderReviewStage(rubric, { onBatchReview });

    const toolbar = screen.getByRole("region", { name: "批量审核工具" });
    const batchNote = screen.getByLabelText("批量审核说明");
    await user.type(batchNote, "Frozen review note");
    await user.click(screen.getByRole("checkbox", { name: "选择当前筛选下待处理规则" }));
    await user.click(screen.getByRole("button", { name: "排除所选" }));

    expect(screen.getByLabelText("审核人")).toBeDisabled();
    expect(
      within(screen.getByRole("navigation", { name: "得分点题目导航" }))
        .getByRole("button", { name: /^Q1\b/ }),
    ).toBeDisabled();
    expect(screen.getByLabelText("审核状态")).toBeDisabled();
    expect(batchNote).toBeDisabled();
    expect(batchNote).toHaveValue("Frozen review note");
    expect(screen.getByRole("checkbox", { name: "选择当前筛选下待处理规则" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "选择 Q1 B1" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "选择 Q1 M1" })).toBeDisabled();
    for (const action of within(toolbar).getAllByRole("button")) {
      expect(action).toBeDisabled();
    }
    const firstCard = screen.getByRole("heading", { name: "Q1 · B1" }).closest("article")!;
    expect(within(firstCard).getByLabelText("判分描述")).toBeDisabled();
    expect(within(firstCard).getByRole("button", { name: "排除 Q1 · B1" })).toBeDisabled();

    mounted.rerender(reviewStageElement(rubric, {
      busy: "ai-review",
      onBatchReview,
      reviewer: "Changed Teacher",
    }));
    const confirmation = screen.getByRole("group", { name: "确认排除所选规则" });
    expect(confirmation).toHaveTextContent("将由 Teacher 保留 0 条、排除 2 条");
    expect(screen.getByLabelText("审核人")).toHaveValue("Changed Teacher");
    const submit = within(confirmation).getByRole("button", { name: "确认并保存" });
    expect(submit).toBeDisabled();
    await user.click(submit);
    expect(onBatchReview).not.toHaveBeenCalled();

    mounted.rerender(reviewStageElement(rubric, {
      busy: null,
      onBatchReview,
      reviewer: "Changed Teacher",
    }));
    expect(submit).toBeEnabled();
    await user.click(submit);
    expect(onBatchReview).toHaveBeenCalledTimes(1);
    expect(onBatchReview).toHaveBeenCalledWith({
      reviewer: "Teacher",
      decisions: [
        {
          criterion_id: "criterion-two",
          review_status: "rejected",
          note: "Frozen review note",
        },
        {
          criterion_id: "criterion-one",
          review_status: "rejected",
          note: "Frozen review note",
        },
      ],
    });
  });

  test("restores the opener on cancel and the stage heading on successful batch confirmation", async () => {
    const rubric = rubricFixture([criterionFixture("criterion-one", "1", "B1")]);
    const user = userEvent.setup();
    renderReviewStage(rubric);
    await user.click(screen.getByRole("checkbox", { name: "选择当前筛选下待处理规则" }));
    const opener = screen.getByRole("button", { name: "排除所选" });

    await user.click(opener);
    await user.click(screen.getByRole("button", { name: "取消" }));
    await waitFor(() => expect(opener).toHaveFocus());
    expect(screen.getByLabelText("审核人")).toBeEnabled();
    expect(
      within(screen.getByRole("navigation", { name: "得分点题目导航" }))
        .getByRole("button", { name: /^Q1\b/ }),
    ).toBeEnabled();
    expect(screen.getByLabelText("审核状态")).toBeEnabled();
    expect(screen.getByLabelText("批量审核说明")).toBeEnabled();
    expect(screen.getByRole("checkbox", { name: "选择当前筛选下待处理规则" })).toBeEnabled();
    expect(screen.getByLabelText("判分描述")).toBeEnabled();
    expect(opener).toBeEnabled();

    await user.click(opener);
    await user.click(screen.getByRole("button", { name: "确认并保存" }));
    await waitFor(() => expect(
      screen.getByRole("heading", { name: "审核评分标准" }),
    ).toHaveFocus());
  });

  test("keeps rubric failures in the sticky action toolbar", () => {
    const rubric = rubricFixture([criterionFixture("criterion-one", "1", "B1")]);
    renderReviewStage(rubric, { error: "批量审核写入失败" });

    const toolbar = screen.getByRole("region", { name: "批量审核工具" });
    expect(within(toolbar).getByRole("alert")).toHaveTextContent("批量审核写入失败");
    expect(document.querySelector(".rubric-criterion-list")?.contains(screen.getByRole("alert"))).toBe(false);
  });

  test("keeps all four phone-responsive batch actions in one wrapping control group", () => {
    const rubric = rubricFixture([criterionFixture("criterion-one", "1", "B1")]);
    renderReviewStage(rubric);

    const toolbar = screen.getByRole("region", { name: "批量审核工具" });
    const actionGroup = toolbar.querySelector(".rubric-batch-actions");
    expect(actionGroup).toBeInstanceOf(HTMLDivElement);
    const actions = within(actionGroup as HTMLDivElement).getAllByRole("button");
    expect(actions).toHaveLength(4);
    expect(within(toolbar).getAllByRole("button")).toEqual(actions);
  });

  test("renders rubric-version loading as a live busy state instead of an empty-state claim", () => {
    renderReviewStage(null, { busy: "loading-rubric" });

    const loading = screen.getByRole("status");
    expect(loading).toHaveAttribute("aria-busy", "true");
    expect(loading).toHaveTextContent("正在加载评分规则版本，请稍候");
    expect(screen.queryByText("返回材料准备并解析评分标准。")).not.toBeInTheDocument();
  });

  test("shows a provisional unit grade with its exact official source", () => {
    const overview = overviewFixture();
    overview.total_questions = overview.completed_questions = 1;
    overview.grade_estimate = {
      status: "provisional", grade: "C", scope: "unit",
      explanation: "根据待复核分数换算。仅适用于单元试卷。",
      pair_key: "9660:2019:JAN:P1", unit_code: "MA01",
      source_url: "https://www.oxfordaqa.com/boundaries.pdf", source_page: 1,
      thresholds: { A: 64, B: 55, C: 46, D: 37, E: 29 },
      next_grade: "B", marks_to_next_grade: 7,
    };
    const { rerender } = render(<GradingOverview overview={overview} loading={false}
      error={null} onBack={vi.fn()} onRefresh={vi.fn()} />);
    const region = screen.getByRole("region", { name: "单元等级估计" });
    expect(region).toHaveTextContent("暂定单元等级 · 待复核");
    expect(region).toHaveTextContent("距 B 等级还差 7 分");
    expect(within(region).getByRole("link")).toHaveAttribute("href", overview.grade_estimate.source_url);
    overview.grade_estimate = { ...overview.grade_estimate, status: "unavailable", grade: null,
      source_url: null, next_grade: null, marks_to_next_grade: null, thresholds: {},
      explanation: "整卷评分尚未完成，暂不估计等级。" };
    rerender(<GradingOverview overview={overview} loading={false}
      error={null} onBack={vi.fn()} onRefresh={vi.fn()} />);
    expect(region).toHaveTextContent("暂不可估计");
    expect(within(region).queryByRole("link")).not.toBeInTheDocument();
  });

  test("returns focus to the overview heading after a successful Load action", async () => {
    let resolveRefresh: (() => void) | undefined;
    const refresh = new Promise<void>((resolve) => { resolveRefresh = resolve; });
    const onRefresh = vi.fn(() => refresh);
    const common = { error: null, onBack: vi.fn(), onRefresh };
    const user = userEvent.setup();
    const mounted = render(<GradingOverview {...common} loading={false} overview={null} />);

    await user.click(screen.getByRole("button", { name: "加载总览" }));
    mounted.rerender(<GradingOverview {...common} loading overview={null} />);
    mounted.rerender(<GradingOverview {...common} loading={false} overview={overviewFixture()} />);
    await act(async () => { resolveRefresh?.(); await refresh; });

    await waitFor(() => expect(
      screen.getByRole("heading", { name: "沿试卷顺序检查整卷诊断" }),
    ).toHaveFocus());
  });

  test("returns focus to Retry when a retry finishes with another error", async () => {
    let resolveRefresh: (() => void) | undefined;
    const refresh = new Promise<void>((resolve) => { resolveRefresh = resolve; });
    const onRefresh = vi.fn(() => refresh);
    const user = userEvent.setup();
    const mounted = render(
      <GradingOverview
        error="第一次失败"
        loading={false}
        onBack={vi.fn()}
        onRefresh={onRefresh}
        overview={null}
      />,
    );

    await user.click(screen.getByRole("button", { name: "重试加载总览" }));
    mounted.rerender(
      <GradingOverview error={null} loading onBack={vi.fn()} onRefresh={onRefresh} overview={null} />,
    );
    mounted.rerender(
      <GradingOverview
        error="仍然失败"
        loading={false}
        onBack={vi.fn()}
        onRefresh={onRefresh}
        overview={null}
      />,
    );
    await act(async () => { resolveRefresh?.(); await refresh; });

    await waitFor(() => expect(
      screen.getByRole("button", { name: "重试加载总览" }),
    ).toHaveFocus());
  });

  test("owns blank-reviewer validation for a single action and preserves reviewer focus", async () => {
    const onReviewCriterion = vi.fn(async () => true);
    const user = userEvent.setup();
    render(<ReviewerValidationHarness onReviewCriterion={onReviewCriterion} />);

    const reviewer = screen.getByLabelText("审核人");
    await user.click(screen.getByRole("button", { name: "保留 Q1 · B1" }));

    expect(onReviewCriterion).not.toHaveBeenCalled();
    expect(reviewer).toHaveAttribute("aria-invalid", "true");
    expect(reviewer).toHaveAccessibleDescription("请填写审核人。");
    await waitFor(() => expect(reviewer).toHaveFocus());

    await user.type(reviewer, "Teacher");
    expect(reviewer).toHaveAttribute("aria-invalid", "false");
    expect(reviewer).not.toHaveAccessibleDescription("请填写审核人。");
  });

  test("owns blank-reviewer validation for batch and AI actions", async () => {
    const onAiReview = vi.fn(async () => undefined);
    const onBatchReview = vi.fn(async () => true);
    const user = userEvent.setup();
    render(
      <ReviewerValidationHarness
        onAiReview={onAiReview}
        onBatchReview={onBatchReview}
      />,
    );

    await user.click(screen.getByRole("checkbox", {
      name: "选择当前筛选下待处理规则",
    }));
    await user.click(screen.getByRole("button", { name: "保留所选" }));

    const reviewer = screen.getByLabelText("审核人");
    expect(onBatchReview).not.toHaveBeenCalled();
    expect(reviewer).toHaveAttribute("aria-invalid", "true");
    expect(reviewer).toHaveAccessibleDescription("请填写审核人。");
    await waitFor(() => expect(reviewer).toHaveFocus());

    await user.click(screen.getByRole("button", { name: "排除所选" }));
    expect(screen.queryByRole("group", { name: "确认排除所选规则" })).not.toBeInTheDocument();
    await waitFor(() => expect(reviewer).toHaveFocus());

    await user.click(screen.getByRole("button", { name: "AI 检查已选规则" }));
    expect(onAiReview).not.toHaveBeenCalled();
    await waitFor(() => expect(reviewer).toHaveFocus());
  });

  test("announces a frozen direct batch accept with decision-specific pending copy", async () => {
    let resolveBatch: ((completed: boolean) => void) | undefined;
    const batch = new Promise<boolean>((resolve) => { resolveBatch = resolve; });
    const user = userEvent.setup();
    render(<BatchPendingHarness onBatchReview={vi.fn(() => batch)} />);

    await user.click(screen.getByRole("checkbox", {
      name: "选择当前筛选下待处理规则",
    }));
    await user.click(screen.getByRole("button", { name: "保留所选" }));

    const pending = screen.getByRole("button", { name: "正在批量保留…" });
    expect(pending).toHaveAttribute("aria-busy", "true");
    expect(pending).toHaveAttribute("aria-live", "polite");
    expect(pending).toBeDisabled();
    expect(screen.getByLabelText("审核人")).toBeDisabled();

    await act(async () => {
      resolveBatch?.(true);
      await batch;
    });
  });

  test("announces a frozen confirmed batch reject with decision-specific pending copy", async () => {
    let resolveBatch: ((completed: boolean) => void) | undefined;
    const batch = new Promise<boolean>((resolve) => { resolveBatch = resolve; });
    const user = userEvent.setup();
    render(<BatchPendingHarness onBatchReview={vi.fn(() => batch)} />);

    await user.click(screen.getByRole("checkbox", {
      name: "选择当前筛选下待处理规则",
    }));
    await user.click(screen.getByRole("button", { name: "排除所选" }));
    const confirmation = screen.getByRole("group", { name: "确认排除所选规则" });
    await user.click(within(confirmation).getByRole("button", { name: "确认并保存" }));

    const pending = within(confirmation).getByRole("button", { name: "正在排除…" });
    expect(pending).toHaveAttribute("aria-busy", "true");
    expect(pending).toHaveAttribute("aria-live", "polite");
    expect(pending).toBeDisabled();
    expect(screen.getByLabelText("审核人")).toBeDisabled();

    await act(async () => {
      resolveBatch?.(true);
      await batch;
    });
  });

  test("keeps the old report visible while regeneration exposes a live busy status", () => {
    const assessment: PaperAssessment = {
      created_at: "2026-08-09T00:00:00Z",
      id: "assessment-one",
      paper_job_id: "paper-job",
      question_position: 1,
      result: gradeResult,
      rubric_set_id: "rubric-components",
      status: "pending_review",
    };
    render(questionStageElement({ assessments: [assessment], busy: "grade-1" }));

    const report = document.getElementById("grading-question-report");
    expect(report).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText("等待人工复核")).toBeVisible();
    const pending = screen.getByRole("button", { name: "正在重新判分…" });
    expect(pending).toHaveAttribute("aria-busy", "true");
    expect(pending).toHaveAttribute("aria-live", "polite");
    expect(pending).toBeDisabled();
    expect(screen.getByRole("button", { name: "返回材料" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "查看整卷结果" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Q1.*答案已保存/ })).toBeDisabled();
  });

  test("marks the rendered grading primary action with the semantic token class", () => {
    render(questionStageElement());

    const action = screen.getByRole("button", { name: "生成判分结果" });
    expect(action).toHaveClass("primary", "grading-primary-action");
    expect(action.closest(".grading-page")).toBeInTheDocument();
  });

});

function materialStageElement(
  overrides: Partial<ComponentProps<typeof GradingMaterialsStage>> = {},
) {
  const defaults: ComponentProps<typeof GradingMaterialsStage> = {
    papers: [{
      job_id: "paper-ready",
      filename: "paper-ready.pdf",
      display_name: null,
      paper_unit_id: null,
      question_paper_document_id: null,
      unit_code: "P2",
      status: "completed",
      total_questions: 2,
      completed_questions: 2,
      failed_questions: 0,
      updated_at: "2026-08-09T00:00:00Z",
    }],
    documents: [{
      id: "scheme-ready",
      filename: "scheme-ready.pdf",
      display_name: null,
      source_type: "mark_scheme",
      source_role: "assessment_only",
      authority_tier: "official",
      status: "converted",
      checksum: "scheme-ready",
      object_key: "corpus-sources/scheme-ready.pdf",
      knowledge_base_id: null,
      license_confirmed: true,
      page_count: 2,
      pair_key: null,
      unit_code: null,
      exam_year: null,
      exam_session: null,
      identity_status: "not_applicable",
      identity_error: null,
      error: null,
    }],
    papersLoading: false,
    papersError: null,
    paperId: "paper-ready",
    documentId: "scheme-ready",
    documentsLoading: false,
    documentsError: null,
    paper: null,
    rubric: null,
    busy: null,
    error: null,
    onRetryDiscovery: vi.fn(async () => undefined),
    onChoosePaper: vi.fn(),
    onChooseDocument: vi.fn(),
    onDeleteDocument: vi.fn(async () => undefined),
    onDeletePaper: vi.fn(async () => undefined),
    onUploadScheme: vi.fn(async () => undefined),
    onContinue: vi.fn(async () => undefined),
  };
  return (
    <div className="grading-page">
      <GradingMaterialsStage {...defaults} {...overrides} />
    </div>
  );
}

function RetryMaterialsHarness({ succeeds }: { succeeds: boolean }) {
  const [papersLoading, setPapersLoading] = useState(false);
  const [documentsLoading, setDocumentsLoading] = useState(false);
  const [papersError, setPapersError] = useState<string | null>("作答记录发现服务不可用");

  return materialStageElement({
    papersLoading,
    documentsLoading,
    papersError,
    onRetryDiscovery: async () => {
      setPapersLoading(true);
      setDocumentsLoading(true);
      await Promise.resolve();
      setPapersError(succeeds ? null : "作答记录发现服务仍然不可用");
      setPapersLoading(false);
      setDocumentsLoading(false);
    },
  });
}

describe("grading materials UI closure regressions", () => {
  test("renders rich material context and selects an answer record from the manager dialog", async () => {
    const user = userEvent.setup();
    const onChoosePaper = vi.fn();
    render(materialStageElement({
      onChoosePaper,
      papers: [
        {
          job_id: "paper-ready",
          filename: "paper-ready.pdf",
          display_name: null,
          paper_unit_id: null,
          question_paper_document_id: null,
          unit_code: "P2",
          status: "completed",
          total_questions: 2,
          completed_questions: 2,
          failed_questions: 0,
          updated_at: "2026-08-09T00:00:00Z",
        },
        {
          job_id: "paper-second",
          filename: "paper-second.pdf",
          display_name: null,
          paper_unit_id: null,
          question_paper_document_id: null,
          unit_code: "S2",
          status: "partial_failed",
          total_questions: 10,
          completed_questions: 9,
          failed_questions: 1,
          updated_at: "2026-08-10T00:00:00Z",
        },
      ],
    }));

    expect(selectRoot("选择作答记录")).toHaveTextContent("paper-ready.pdf");
    expect(selectRoot("选择作答记录")).toHaveTextContent("P2 · 2/2 题 · 作答完整");

    await user.click(screen.getByRole("button", { name: "管理答卷" }));
    const search = await screen.findByPlaceholderText("搜索文件名、Unit 或状态");
    await user.type(search, "S2");
    expect(screen.getByText("paper-second.pdf")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "设为当前" }));

    expect(onChoosePaper).toHaveBeenCalledWith("paper-second");
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "管理作答记录" })).not.toBeInTheDocument();
    });
  });

  test("deletes a Mark Scheme through the manager confirmation dialog", async () => {
    const user = userEvent.setup();
    const onDeleteDocument = vi.fn(async () => undefined);
    render(materialStageElement({ onDeleteDocument }));

    expect(selectRoot("选择 Mark Scheme")).toHaveTextContent("官方标准 · 2 页 · 内容就绪");
    await user.click(screen.getByRole("button", { name: "管理标准" }));
    await user.click(await screen.findByLabelText("删除 scheme-ready.pdf"));
    await user.click(await screen.findByRole("button", { name: "删除 Mark Scheme" }));

    await waitFor(() => expect(onDeleteDocument).toHaveBeenCalledWith("scheme-ready"));
  });

  test("keeps the official Mark Scheme upload icon-only and accessibly named", () => {
    render(materialStageElement());

    const upload = screen.getByLabelText("上传官方 Mark Scheme");
    expect(upload).toHaveAttribute("type", "file");
    expect(upload.closest(".grading-scheme-upload")).toBeInTheDocument();
    expect(screen.queryByText("上传官方版本")).not.toBeInTheDocument();
  });

  test("locks the answer context when grading from a paper-owned record", () => {
    render(materialStageElement({ allowExternalImport: false, lockPaperSelection: true }));

    expect(screen.queryByRole("button", { name: "上传答卷" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "管理答卷" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("选择作答记录")).toBeDisabled();
    expect(screen.getByRole("button", { name: "解析评分标准" })).toBeInTheDocument();
  });

  test("exposes truthful paper and rubric context loading states", () => {
    const mounted = render(materialStageElement({ busy: "loading-paper" }));
    const stage = screen.getByRole("article");

    expect(stage).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText("正在加载所选答卷及其评分上下文…").closest(
      '[role="status"]',
    )).toBeInTheDocument();

    mounted.rerender(materialStageElement({ busy: "loading-rubric" }));
    expect(stage).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText("正在加载所选 Mark Scheme 对应的评分规则…").closest(
      '[role="status"]',
    )).toBeInTheDocument();

    mounted.rerender(materialStageElement({ busy: null }));
    expect(stage).toHaveAttribute("aria-busy", "false");
    expect(screen.queryByText(/正在加载所选.*评分/)).not.toBeInTheDocument();
  });

  test("announces a successful discovery retry and focuses the first valid material control", async () => {
    const user = userEvent.setup();
    render(<RetryMaterialsHarness succeeds />);

    await user.click(screen.getByRole("button", { name: "重试材料列表" }));

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("材料列表已更新。"));
    await waitFor(() => expect(screen.getByLabelText("选择作答记录")).toHaveFocus());
    expect(screen.queryByRole("button", { name: "重试材料列表" })).not.toBeInTheDocument();
  });

  test("restores retry focus and keeps the discovery alert after another failure", async () => {
    const user = userEvent.setup();
    render(<RetryMaterialsHarness succeeds={false} />);
    const retry = screen.getByRole("button", { name: "重试材料列表" });

    await user.click(retry);

    await waitFor(() => expect(screen.getByText(
      "作答记录加载失败：作答记录发现服务仍然不可用",
    )).toHaveAttribute("role", "alert"));
    await waitFor(() => expect(retry).toHaveFocus());
  });

  test("uses the grading-scoped semantic primary action contract", () => {
    render(materialStageElement());

    expect(screen.getByRole("article")).not.toHaveClass("panel");
    const action = screen.getByRole("button", { name: "解析评分标准" });
    expect(action).toHaveClass("primary", "grading-primary-action");
    expect(action.closest(".grading-page")).toBeInTheDocument();
  });
});
