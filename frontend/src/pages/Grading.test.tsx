import type { ReactElement } from "react";
import { act, fireEvent, render as testingLibraryRender, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import type {
  AiReviewRubricCriteriaRequest,
  GradeResult,
  BatchReviewRubricCriteriaRequest,
  GradingOverviewResponse,
  PaperAssessment,
  RubricSet,
  SubjectPack,
  PaperJobResult,
} from "../types";
import { GradingOverview } from "../components/grading/GradingOverview";
import { GradingQuestionStage } from "../components/grading/GradingQuestionStage";
import { RubricCriterionEditor } from "../components/grading/RubricCriterionEditor";
import { ToastContext } from "../components/toast-context";
import { DesignSystemProvider } from "../components/ui/DesignSystemProvider";
import { subscribeTaskSnapshots } from "../lib/task-events";
import { Grading } from "./Grading";

vi.mock("../lib/task-events", () => ({
  subscribeTaskSnapshots: vi.fn(),
}));

const subscribeMock = vi.mocked(subscribeTaskSnapshots);

function render(ui: ReactElement) {
  return testingLibraryRender(ui, { wrapper: DesignSystemProvider });
}

const subject: SubjectPack = {
  id: "oxfordaqa-mathematics-9660",
  subject_code: "9660",
  title: "OxfordAQA Mathematics",
  board_name: "OxfordAQA",
  version: "1",
  digest: "test",
  capability_profile_id: "oxfordaqa-mathematics-9660",
  generic_qa_enabled: true,
  answering_enabled: true,
  answering_disabled_reason: null,
  active_graph_version_id: null,
  knowledge_bases: [],
  units: [],
};
const AI_RECOMMENDATIONS = ["accept", "reject", "revise"] as const;


function response(payload: unknown) {
  return Promise.resolve(new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  }));
}

async function chooseMaterialOption(
  user: ReturnType<typeof userEvent.setup>,
  label: "选择作答记录" | "选择 Mark Scheme",
  filename: string,
) {
  const select = screen.getByLabelText<HTMLSelectElement>(label);
  const escapedFilename = filename.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const option = within(select).getByRole<HTMLOptionElement>("option", { name: new RegExp(escapedFilename) });
  await user.selectOptions(select, option.value);
}

function criterionFixture(
  id: string,
  questionNumber: string,
  criterionId: string,
): RubricSet["criteria"][number] {
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
    ai_review: null,
  };
}

function questionFixture(
  position: number,
  number = String(position),
): PaperJobResult["questions"][number] {
  return {
    position,
    number,
    question_markdown: `Question ${number}`,
    answer_markdown: `Answer ${number}`,
    diagrams: [],
    images: [],
    citations: [],
    knowledge_points: [],
    confidence: 1,
    grounded: true,
    warnings: [],
    attempts: 1,
    requires_visual_context: false,
    source_pages: [1],
    source_warnings: [],
    answer_requirements: [],
    agent_steps: [],
    source_digest: null,
    source_kind: "primary",
    status: "completed",
    total_marks: 1,
    error: null,
  };
}

function paperFixture(
  jobId: string,
  questions: PaperJobResult["questions"] = [questionFixture(1)],
): PaperJobResult {
  return {
    job_id: jobId,
    filename: `${jobId}.pdf`,
    subject_pack_id: subject.id,
    subject_code: subject.subject_code,
    knowledge_base_version_ids: [],
    graph_version_id: null,
    replaced_by_job_id: null,
    replacement_for_job_id: null,
    source_integrity_status: "verified",
    split_contract_version: null,
    split_source_digest: null,
    unit_code: "P2",
    status: "completed",
    stage: "completed",
    total_pages: 1,
    parsed_pages: 1,
    total_questions: questions.length,
    completed_questions: questions.length,
    failed_questions: 0,
    created_at: "2026-08-05T00:00:00Z",
    updated_at: "2026-08-05T00:00:00Z",
    chunks: [],
    questions,
    error: null,
  };
}

function rubricFixture({
  id = "rubric-fixture",
  paperJobId = "job-fixture",
  sourceDocumentId = "ms-fixture",
  status = "confirmed",
  criteria = [criterionFixture("criterion-fixture", "1", "M1")],
}: {
  id?: string;
  paperJobId?: string;
  sourceDocumentId?: string;
  status?: RubricSet["status"];
  criteria?: RubricSet["criteria"];
} = {}): RubricSet {
  return {
    id,
    subject_id: subject.id,
    paper_job_id: paperJobId,
    source_document_id: sourceDocumentId,
    version_number: 1,
    status,
    identity: {},
    parser_model: "test-model",
    parser_version: "test",
    warnings: [],
    created_at: "2026-08-05T00:00:00Z",
    updated_at: "2026-08-05T00:00:00Z",
    confirmed_at: status === "confirmed" ? "2026-08-05T00:00:00Z" : null,
    confirmed_by: status === "confirmed" ? "Teacher" : null,
    criteria: criteria.map((criterion) => ({
      ...criterion,
      review_status: status === "confirmed" ? "accepted" : criterion.review_status,
    })),
  };
}

function sourceFixture(id: string, filename = `${id}.pdf`) {
  return {
    id,
    filename,
    source_type: "mark_scheme",
    source_role: "assessment_only",
    authority_tier: "official",
    status: "converted",
    checksum: id,
    object_key: `corpus-sources/${filename}`,
    knowledge_base_id: null,
    license_confirmed: false,
    page_count: 1,
    error: null,
  };
}

function paperSummaryFixture(jobId: string, questionCount = 1) {
  return {
    job_id: jobId,
    filename: `${jobId}.pdf`,
    unit_code: "P2",
    status: "completed",
    total_questions: questionCount,
    completed_questions: questionCount,
    failed_questions: 0,
    updated_at: "2026-08-05T00:00:00Z",
  };
}

function gradeResultFixture(assessmentId = "assessment-fixture"): GradeResult {
  return {
    assessment_id: assessmentId,
    subject_code: subject.subject_code,
    question_ref: "paper-fixture:Q1",
    total_awarded: 1,
    total_available: 1,
    confidence: 0.95,
    status: "pending_review",
    rubric_awards: [{
      criterion_id: "M1",
      description: "Award the method mark.",
      mark_type: "M1",
      max_marks: 1,
      awarded: 1,
      student_evidence: "Answer 1",
      rationale: "The required method is present.",
      confidence: 0.95,
      source_ref: "mark-scheme.pdf#page=1",
      knowledge_codes: [],
      error_types: [],
      improvement_suggestion: null,
    }],
    symbolic_checks: [],
    citations: [],
    warnings: [],
    improvement_suggestions: [],
    manual_review_required: true,
  };
}

function assessmentFixture(
  position: number,
  status: PaperAssessment["status"],
  result: GradeResult,
): PaperAssessment {
  return {
    id: result.assessment_id,
    paper_job_id: "job-question-stage",
    question_position: position,
    rubric_set_id: "rubric-question-stage",
    status,
    result,
    created_at: "2026-08-05T00:00:00Z",
  };
}

function installReviewScenario(criteria: RubricSet["criteria"]) {
  let rubric = {
    id: "rubric-batch",
    subject_id: subject.id,
    paper_job_id: "job-batch",
    source_document_id: "ms-batch",
    version_number: 1,
    status: "draft",
    identity: {},
    parser_model: "test-model",
    parser_version: "test",
    warnings: [],
    created_at: "2026-08-05T00:00:00Z",
    updated_at: "2026-08-05T00:00:00Z",
    confirmed_at: null,
    confirmed_by: null,
    criteria,
  };
  const numbers = Array.from(new Set(criteria.map((item) => item.question_number)));
  const questions = numbers.map((number, index) => ({
    position: index + 1,
    number,
    question_markdown: `Question ${number}`,
    answer_markdown: `Answer ${number}`,
    diagrams: [],
    images: [],
    citations: [],
    knowledge_points: [],
    confidence: 1,
    grounded: true,
    warnings: [],
    attempts: 1,
    source_pages: [1],
    source_warnings: [],
    answer_requirements: [],
    agent_steps: [],
    status: "completed",
    total_marks: 1,
    error: null,
  }));
  const batchBodies: BatchReviewRubricCriteriaRequest[] = [];
  const aiBodies: AiReviewRubricCriteriaRequest[] = [];
  const fetch = vi.fn(async (input: RequestInfo | URL) => {
    const request = input instanceof Request ? input : new Request(String(input));
    const url = new URL(request.url);
    if (url.pathname === "/api/v1/grading/papers") {
      return response([{
        job_id: "job-batch",
        filename: "batch-paper.pdf",
        unit_code: "P2",
        status: "completed",
        total_questions: questions.length,
        completed_questions: questions.length,
        failed_questions: 0,
        updated_at: "2026-08-05T00:00:00Z",
      }]);
    }
    if (url.pathname === "/api/v1/corpus/documents") {
      return response([{
        id: "ms-batch",
        filename: "batch-mark-scheme.pdf",
        source_type: "mark_scheme",
        source_role: "assessment_only",
        authority_tier: "official",
        status: "converted",
        checksum: "batch",
        object_key: "corpus-sources/batch.pdf",
        knowledge_base_id: null,
        license_confirmed: false,
        page_count: 1,
        error: null,
      }]);
    }
    if (url.pathname === "/api/v1/papers/jobs/job-batch") {
      return response({
        job_id: "job-batch",
        filename: "batch-paper.pdf",
        subject_pack_id: subject.id,
        subject_code: subject.subject_code,
        knowledge_base_version_ids: [],
        graph_version_id: null,
        unit_code: "P2",
        status: "completed",
        stage: "completed",
        total_pages: 1,
        parsed_pages: 1,
        total_questions: questions.length,
        completed_questions: questions.length,
        failed_questions: 0,
        created_at: "2026-08-05T00:00:00Z",
        updated_at: "2026-08-05T00:00:00Z",
        chunks: [],
        questions,
        error: null,
      });
    }
    if (url.pathname === "/api/v1/grading/rubrics" && request.method === "GET") {
      return response([rubric]);
    }
    if (url.pathname === "/api/v1/grading/rubrics/rubric-batch" && request.method === "GET") {
      return response(rubric);
    }
    if (url.pathname === "/api/v1/grading/papers/job-batch/assessments") return response([]);
    if (url.pathname.endsWith("/rubrics/rubric-batch/batch-review")) {
      const body = await request.clone().json() as BatchReviewRubricCriteriaRequest;
      batchBodies.push(body);
      const decisions = new Map(body.decisions.map((decision) => [decision.criterion_id, decision]));
      rubric = {
        ...rubric,
        criteria: rubric.criteria.map((item) => {
          const decision = decisions.get(item.id);
          return decision
            ? {
                ...item,
                review_status: decision.review_status,
                reviewed_by: body.reviewer,
                reviewed_at: "2026-08-05T01:00:00Z",
              }
            : item;
        }),
      };
      return response(rubric);
    }
    if (url.pathname.endsWith("/rubrics/rubric-batch/ai-review")) {
      const body = await request.clone().json() as AiReviewRubricCriteriaRequest;
      aiBodies.push(body);
      const targetIds = new Set(body.criterion_ids);
      let suggestionIndex = 0;
      rubric = {
        ...rubric,
        criteria: rubric.criteria.map((item) => {
          if (!targetIds.has(item.id)) return item;
          const recommendation = AI_RECOMMENDATIONS[suggestionIndex++ % AI_RECOMMENDATIONS.length];
          return {
            ...item,
            ai_review: {
              criterion_fingerprint: String(suggestionIndex).padStart(64, "0"),
              recommendation,
              confidence: recommendation === "accept" ? 0.92 : 0.81,
              rationale: `AI rationale for ${item.criterion_id}`,
              suggested_updates: null,
              model: "test-review-model",
              reviewed_at: "2026-08-05T01:05:00Z",
            },
          };
        }),
      };
      return response(rubric);
    }
    return response([]);
  });
  vi.stubGlobal("fetch", fetch);
  return { aiBodies, batchBodies };
}

afterEach(() => {
  window.localStorage.clear();
  subscribeMock.mockReset();
  vi.unstubAllGlobals();
});

describe("Grading", () => {
  test("uses the routed paper context without a duplicate subject step", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response([])));
    subscribeMock.mockImplementation(() => () => undefined);
    render(
      <Grading
        initialSubjectId={subject.id}
        onCreated={vi.fn()}
        subjects={[subject]}
      />,
    );

    expect(screen.queryByRole("button", { name: /选择科目/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /准备材料/ })).toBeVisible();
    expect(screen.getByRole("button", { name: /逐题判分/ })).toBeVisible();
    expect(screen.getByRole("button", { name: /整卷结果/ })).toBeVisible();
  });

  test("tracks an imported answer job and selects it when parsing completes", async () => {
    const importedJobId = "job-imported-answer";
    const importedPaper = paperFixture(importedJobId);
    let papersReady = false;
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(String(input));
      const url = new URL(request.url);
      if (url.pathname === "/api/v1/papers/import-answer") {
        return response({ job_id: importedJobId, status: "queued", stage: "queued" });
      }
      if (url.pathname === "/api/v1/grading/papers") {
        return response(papersReady ? [paperSummaryFixture(importedJobId)] : []);
      }
      if (url.pathname === "/api/v1/corpus/documents") return response([]);
      if (url.pathname === `/api/v1/papers/jobs/${importedJobId}`) {
        return response(importedPaper);
      }
      if (url.pathname === "/api/v1/grading/rubrics") return response([]);
      if (url.pathname.endsWith("/assessments")) return response([]);
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);
    subscribeMock.mockImplementation(() => () => undefined);
    const user = userEvent.setup();
    render(<Grading subject={subject} onCreated={vi.fn()} />);

    await user.click(await screen.findByRole("button", { name: "上传答卷" }));
    await user.upload(
      screen.getByLabelText("上传待评分试卷"),
      new File(["question"], "question.pdf", { type: "application/pdf" }),
    );
    await user.upload(
      screen.getByLabelText("上传答案文件"),
      new File(["answer"], "answer.md", { type: "text/markdown" }),
    );
    await user.click(screen.getByRole("button", { name: "导入并解析答卷" }));

    await waitFor(() => expect(subscribeMock).toHaveBeenCalled());
    const subscription = subscribeMock.mock.calls.at(-1)?.[0];
    act(() => {
      subscription?.onSnapshot({
        ...importedPaper,
        status: "queued",
        stage: "queued",
        total_questions: 0,
        completed_questions: 0,
      });
    });
    expect(await screen.findByText("等待处理")).toBeInTheDocument();
    expect(screen.getByText("0 / — 题 · 4%")).toBeInTheDocument();

    papersReady = true;
    await act(async () => {
      subscription?.onSnapshot(importedPaper);
    });

    await waitFor(() => expect(screen.getByLabelText("选择作答记录")).toHaveTextContent(
      `${importedJobId}.pdf`,
    ));
    expect(window.localStorage.getItem(
      `examtwin.gradingImportJobId.${subject.id}`,
    )).toBeNull();
  });

  test("keeps a failed imported answer task visible with its persisted error", async () => {
    const importedJobId = "job-import-failed";
    const failedPaper: PaperJobResult = {
      ...paperFixture(importedJobId, []),
      status: "failed",
      stage: "splitting",
      completed_questions: 0,
      total_questions: 0,
      error: "答案题号无法与试卷题号闭合",
    };
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(String(input));
      const url = new URL(request.url);
      if (url.pathname === "/api/v1/papers/import-answer") {
        return response({ job_id: importedJobId, status: "queued", stage: "queued" });
      }
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);
    subscribeMock.mockImplementation(() => () => undefined);
    const user = userEvent.setup();
    render(<Grading subject={subject} onCreated={vi.fn()} />);

    await user.click(await screen.findByRole("button", { name: "上传答卷" }));
    await user.upload(
      screen.getByLabelText("上传待评分试卷"),
      new File(["question"], "question.pdf", { type: "application/pdf" }),
    );
    await user.upload(
      screen.getByLabelText("上传答案文件"),
      new File(["answer"], "answer.md", { type: "text/markdown" }),
    );
    await user.click(screen.getByRole("button", { name: "导入并解析答卷" }));
    await waitFor(() => expect(subscribeMock).toHaveBeenCalled());

    act(() => {
      subscribeMock.mock.calls.at(-1)?.[0].onSnapshot(failedPaper);
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("答卷解析失败");
    expect(screen.getByRole("alert")).toHaveTextContent("答案题号无法与试卷题号闭合");
  });

  test("shows pending discovery copy before rendering truly empty guidance", async () => {
    let resolvePapers: ((value: Response) => void) | undefined;
    let resolveDocuments: ((value: Response) => void) | undefined;
    const papersPending = new Promise<Response>((resolve) => {
      resolvePapers = resolve;
    });
    const documentsPending = new Promise<Response>((resolve) => {
      resolveDocuments = resolve;
    });
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input instanceof Request ? input.url : input));
      if (url.pathname === "/api/v1/grading/papers") return papersPending;
      if (url.pathname === "/api/v1/corpus/documents") return documentsPending;
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);
    const { container } = render(<Grading subject={subject} onCreated={vi.fn()} />);

    expect(container.querySelector(".grading-page")).toBeInTheDocument();
    expect(screen.getByText("正在查找可评分的作答记录…")).toHaveClass(
      "grading-discovery-state",
      "is-loading",
    );
    expect(screen.getByText("正在查找可用的 Mark Scheme…")).toHaveClass(
      "grading-discovery-state",
      "is-loading",
    );
    expect(screen.queryByText(/还没有已完成的作答记录/)).not.toBeInTheDocument();
    expect(screen.queryByText(/还没有已转换的 Mark Scheme/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("选择作答记录")).toHaveClass("grading-control-boundary");
    expect(screen.getByLabelText("选择 Mark Scheme")).toHaveClass("grading-control-boundary");
    expect(screen.getByRole("heading", { name: "评分材料" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "解析评分标准" })).toBeDisabled();

    await act(async () => {
      resolvePapers?.(await response([]));
      resolveDocuments?.(await response([]));
    });

    expect(await screen.findByText(
      "还没有已完成的作答记录。请先完成整卷作答，再返回此处评分。",
    )).toHaveClass("grading-discovery-state", "is-empty");
    expect(screen.getByText(
      "还没有已转换的 Mark Scheme。你可以在此上传官方文件并完成转换。",
    )).toHaveClass("grading-discovery-state", "is-empty");
    expect(screen.getByLabelText("选择作答记录")).toHaveTextContent("暂无可评分作答记录");
    expect(screen.getByLabelText("选择 Mark Scheme")).toHaveTextContent("暂无可用 Mark Scheme");
  });

  test("retries both discovery lists after the paper list fails", async () => {
    const user = userEvent.setup();
    let paperRequests = 0;
    let documentRequests = 0;
    let resolvePaperRetry: ((value: Response) => void) | undefined;
    const paperRetryPending = new Promise<Response>((resolve) => {
      resolvePaperRetry = resolve;
    });
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input instanceof Request ? input.url : input));
      if (url.pathname === "/api/v1/grading/papers") {
        paperRequests += 1;
        return paperRequests === 1
          ? Promise.reject(new Error("答卷列表暂时不可用"))
          : paperRetryPending;
      }
      if (url.pathname === "/api/v1/corpus/documents") {
        documentRequests += 1;
        return response([]);
      }
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);
    render(<Grading subject={subject} onCreated={vi.fn()} />);

    expect(await screen.findByText("作答记录加载失败：答卷列表暂时不可用")).toHaveClass(
      "grading-discovery-state",
      "is-error",
    );
    await user.click(screen.getByRole("button", { name: "重试材料列表" }));
    expect(await screen.findByRole("button", {
      name: "正在重试材料列表…",
    })).toBeDisabled();
    await act(async () => {
      resolvePaperRetry?.(await response([]));
    });

    expect(await screen.findByText(/还没有已完成的作答记录/)).toBeInTheDocument();
    expect(paperRequests).toBe(2);
    expect(documentRequests).toBe(2);
  });

  test("retries both discovery lists after the Mark Scheme list fails", async () => {
    const user = userEvent.setup();
    let paperRequests = 0;
    let documentRequests = 0;
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input instanceof Request ? input.url : input));
      if (url.pathname === "/api/v1/grading/papers") {
        paperRequests += 1;
        return response([]);
      }
      if (url.pathname === "/api/v1/corpus/documents") {
        documentRequests += 1;
        return documentRequests === 1
          ? Promise.reject(new Error("评分标准列表暂时不可用"))
          : response([sourceFixture("ms-retry", "retry-scheme.pdf")]);
      }
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);
    render(<Grading subject={subject} onCreated={vi.fn()} />);

    expect(await screen.findByText(
      "Mark Scheme 加载失败：评分标准列表暂时不可用",
    )).toHaveClass("grading-discovery-state", "is-error");
    await user.click(screen.getByRole("button", { name: "重试材料列表" }));

    await waitFor(() => expect(screen.getByLabelText("选择 Mark Scheme"))
      .toHaveTextContent("retry-scheme.pdf"));
    expect(paperRequests).toBe(2);
    expect(documentRequests).toBe(2);
  });

  test("reconciles an existing rubric when source discovery finishes after paper context", async () => {
    const paper = paperFixture("job-deferred-source");
    const scheme = sourceFixture("ms-deferred-source", "deferred-scheme.pdf");
    const rubric = rubricFixture({
      id: "rubric-deferred-source",
      paperJobId: paper.job_id,
      sourceDocumentId: scheme.id,
      status: "draft",
      criteria: [criterionFixture("criterion-deferred-source", "1", "D1")],
    });
    let resolveDocuments: ((value: Response) => void) | undefined;
    const documentsRequest = new Promise<Response>((resolve) => {
      resolveDocuments = resolve;
    });
    let rubricDetailRequests = 0;
    let rubricCreateRequests = 0;
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(String(input));
      const url = new URL(request.url);
      if (url.pathname === "/api/v1/grading/papers") {
        return response([paperSummaryFixture(paper.job_id)]);
      }
      if (url.pathname === "/api/v1/corpus/documents") return documentsRequest;
      if (url.pathname === `/api/v1/papers/jobs/${paper.job_id}`) return response(paper);
      if (url.pathname === "/api/v1/grading/rubrics" && request.method === "GET") {
        return response([rubric]);
      }
      if (url.pathname === "/api/v1/grading/rubrics" && request.method === "POST") {
        rubricCreateRequests += 1;
        return response(rubric);
      }
      if (url.pathname === `/api/v1/grading/rubrics/${rubric.id}`) {
        rubricDetailRequests += 1;
        return response(rubric);
      }
      if (url.pathname.endsWith("/assessments")) return response([]);
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);

    const user = userEvent.setup();
    render(<Grading subject={subject} onCreated={vi.fn()} />);
    expect(await screen.findByLabelText("所选答卷内容")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "解析评分标准" })).toBeDisabled();

    await act(async () => {
      resolveDocuments?.(await response([scheme]));
      await documentsRequest;
    });

    await user.click(await screen.findByRole("button", { name: "审核评分标准" }));
    expect(await screen.findByText("Criterion D1")).toBeInTheDocument();
    expect(rubricDetailRequests).toBe(1);
    expect(rubricCreateRequests).toBe(0);
  });

  test("reconciles an existing rubric when failed source discovery recovers", async () => {
    const paper = paperFixture("job-recovered-source");
    const scheme = sourceFixture("ms-recovered-source", "recovered-scheme.pdf");
    const rubric = rubricFixture({
      id: "rubric-recovered-source",
      paperJobId: paper.job_id,
      sourceDocumentId: scheme.id,
      status: "draft",
      criteria: [criterionFixture("criterion-recovered-source", "1", "R1")],
    });
    let documentRequests = 0;
    let rubricDetailRequests = 0;
    let rubricCreateRequests = 0;
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(String(input));
      const url = new URL(request.url);
      if (url.pathname === "/api/v1/grading/papers") {
        return response([paperSummaryFixture(paper.job_id)]);
      }
      if (url.pathname === "/api/v1/corpus/documents") {
        documentRequests += 1;
        return documentRequests === 1
          ? Promise.reject(new Error("Mark Scheme 发现暂时失败"))
          : response([scheme]);
      }
      if (url.pathname === `/api/v1/papers/jobs/${paper.job_id}`) return response(paper);
      if (url.pathname === "/api/v1/grading/rubrics" && request.method === "GET") {
        return response([rubric]);
      }
      if (url.pathname === "/api/v1/grading/rubrics" && request.method === "POST") {
        rubricCreateRequests += 1;
        return response(rubric);
      }
      if (url.pathname === `/api/v1/grading/rubrics/${rubric.id}`) {
        rubricDetailRequests += 1;
        return response(rubric);
      }
      if (url.pathname.endsWith("/assessments")) return response([]);
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);

    const user = userEvent.setup();
    render(<Grading subject={subject} onCreated={vi.fn()} />);
    expect(await screen.findByText(
      "Mark Scheme 加载失败：Mark Scheme 发现暂时失败",
    )).toBeInTheDocument();
    expect(await screen.findByLabelText("所选答卷内容")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "重试材料列表" }));
    await user.click(await screen.findByRole("button", { name: "审核评分标准" }));

    expect(await screen.findByText("Criterion R1")).toBeInTheDocument();
    expect(documentRequests).toBe(2);
    expect(rubricDetailRequests).toBe(1);
    expect(rubricCreateRequests).toBe(0);
  });

  test("does not let successful paper context erase a discovery error", async () => {
    const paper = paperFixture("job-discovery-error");
    let resolvePaperContext: ((value: Response) => void) | undefined;
    const paperContextPending = new Promise<Response>((resolve) => {
      resolvePaperContext = resolve;
    });
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input instanceof Request ? input.url : input));
      if (url.pathname === "/api/v1/grading/papers") {
        return response([paperSummaryFixture(paper.job_id)]);
      }
      if (url.pathname === "/api/v1/corpus/documents") {
        return Promise.reject(new Error("Mark Scheme 发现服务不可用"));
      }
      if (url.pathname === `/api/v1/papers/jobs/${paper.job_id}`) {
        return paperContextPending;
      }
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);
    render(<Grading subject={subject} onCreated={vi.fn()} />);

    expect(await screen.findByText(
      "Mark Scheme 加载失败：Mark Scheme 发现服务不可用",
    )).toBeInTheDocument();
    await act(async () => {
      resolvePaperContext?.(await response(paper));
    });

    expect(await screen.findByLabelText("所选答卷内容")).toBeInTheDocument();
    expect(screen.getByText(
      "Mark Scheme 加载失败：Mark Scheme 发现服务不可用",
    )).toBeInTheDocument();
  });

  test("loads completed paper-answer records instead of asking for pasted answers", async () => {
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const url = String(input instanceof Request ? input.url : input);
      if (url.includes("/grading/papers") && !url.includes("assessments")) {
        return response([{
          job_id: "job-1",
          filename: "paper.pdf",
          unit_code: "P2",
          status: "completed",
          total_questions: 1,
          completed_questions: 1,
          failed_questions: 0,
          updated_at: "2026-08-05T00:00:00Z",
        }]);
      }
      if (url.includes("/corpus/documents")) {
        if (url.includes("status=converted")) return response([]);
        return response([{
          id: "ms-1",
          filename: "mark-scheme.pdf",
          source_type: "mark_scheme",
          source_role: "assessment_context",
          authority_tier: "official",
          status: "indexed",
          checksum: "abc",
          knowledge_base_id: null,
          license_confirmed: false,
          page_count: 4,
          error: null,
        }]);
      }
      if (url.includes("/papers/jobs/job-1")) {
        return response({
          job_id: "job-1",
          filename: "paper.pdf",
          subject_pack_id: subject.id,
          subject_code: subject.subject_code,
          knowledge_base_version_ids: [],
          graph_version_id: null,
          unit_code: "P2",
          status: "completed",
          stage: "completed",
          total_pages: 1,
          parsed_pages: 1,
          total_questions: 1,
          completed_questions: 1,
          failed_questions: 0,
          created_at: "2026-08-05T00:00:00Z",
          updated_at: "2026-08-05T00:00:00Z",
          chunks: [],
          questions: [{
            position: 1,
            number: "1",
            question_markdown: "Solve x + 1 = 2.",
            answer_markdown: "x = 1",
            diagrams: [], images: [], citations: [], knowledge_points: [],
            confidence: 0.9, grounded: true, warnings: [], attempts: 1,
            source_pages: [1], source_warnings: [], answer_requirements: [],
            agent_steps: [], status: "completed", total_marks: 1, error: null,
          }],
          error: null,
        });
      }
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);
    render(<Grading subject={subject} onCreated={vi.fn()} />);

    await waitFor(() => expect(screen.getByLabelText("选择作答记录")).toHaveTextContent("paper.pdf"));
    await waitFor(() => expect(screen.getByLabelText("选择 Mark Scheme")).toHaveTextContent("mark-scheme.pdf"));
    await waitFor(() => expect(screen.getByLabelText("所选答卷内容")).toHaveTextContent("Q1答案已保存"));
    expect(screen.queryByPlaceholderText("粘贴学生作答内容")).not.toBeInTheDocument();
  });

  test("accepts a 204 Mark Scheme deletion and clears the current selection", async () => {
    const currentScheme = sourceFixture("scheme-current", "current-scheme.pdf");
    const otherScheme = sourceFixture("scheme-other", "other-scheme.pdf");
    let documents = [currentScheme, otherScheme];
    const deleteRequests: string[] = [];
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(String(input));
      const url = new URL(request.url);
      if (url.pathname === "/api/v1/grading/papers") {
        return response([paperSummaryFixture("job-delete")]);
      }
      if (url.pathname === "/api/v1/corpus/documents") return response(documents);
      if (
        request.method === "DELETE"
        && url.pathname.endsWith("/documents/scheme-current")
      ) {
        deleteRequests.push(url.pathname);
        documents = [otherScheme];
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      if (url.pathname === "/api/v1/papers/jobs/job-delete") {
        return response(paperFixture("job-delete"));
      }
      if (url.pathname === "/api/v1/grading/rubrics") return response([]);
      if (url.pathname.endsWith("/assessments")) return response([]);
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);
    const user = userEvent.setup();
    render(<Grading
      subject={subject}
      onCreated={vi.fn(async () => { throw new Error("queue refresh failed"); })}
    />);

    const schemeSelector = await screen.findByLabelText("选择 Mark Scheme");
    await waitFor(() => expect(schemeSelector).toHaveValue("scheme-current"));
    await user.click(screen.getByRole("button", { name: "管理标准" }));
    await user.click(await screen.findByLabelText("删除 current-scheme.pdf"));
    await user.click(await screen.findByRole("button", { name: "删除 Mark Scheme" }));

    await waitFor(() => expect(deleteRequests).toHaveLength(1));
    await waitFor(() => expect(schemeSelector).toHaveValue(""));
    expect(schemeSelector).toHaveTextContent("请选择 Mark Scheme");
    expect(screen.getByText("other-scheme.pdf")).toBeInTheDocument();
  });

  test("ignores a slower response from the previously selected paper", async () => {
    const detailA = {
      job_id: "job-a",
      filename: "a.pdf",
      subject_pack_id: subject.id,
      subject_code: subject.subject_code,
      knowledge_base_version_ids: [],
      graph_version_id: null,
      unit_code: "P2",
      status: "completed",
      stage: "completed",
      total_pages: 1,
      parsed_pages: 1,
      total_questions: 1,
      completed_questions: 1,
      failed_questions: 0,
      created_at: "2026-08-05T00:00:00Z",
      updated_at: "2026-08-05T00:00:00Z",
      chunks: [],
      questions: [{
        position: 1,
        number: "A",
        question_markdown: "Question A",
        answer_markdown: "Answer A",
        diagrams: [],
        images: [],
        citations: [],
        knowledge_points: [],
        confidence: 0.9,
        grounded: true,
        warnings: [],
        attempts: 1,
        source_pages: [1],
        source_warnings: [],
        answer_requirements: [],
        agent_steps: [],
        status: "completed",
        total_marks: 1,
        error: null,
      }],
      error: null,
    };
    const detailB = {
      ...detailA,
      job_id: "job-b",
      filename: "b.pdf",
      questions: [{
        ...detailA.questions[0],
        number: "B",
        question_markdown: "Question B",
        answer_markdown: "Answer B",
      }],
    };
    let requestedA = false;
    let resolveA: ((value: Response) => void) | undefined;
    const slowA = new Promise<Response>((resolve) => {
      resolveA = resolve;
    });
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input instanceof Request ? input.url : input));
      if (url.pathname === "/api/v1/grading/papers") {
        return response([
          {
            job_id: "job-a",
            filename: "a.pdf",
            unit_code: "P2",
            status: "completed",
            total_questions: 1,
            completed_questions: 1,
            failed_questions: 0,
            updated_at: "2026-08-05T00:00:00Z",
          },
          {
            job_id: "job-b",
            filename: "b.pdf",
            unit_code: "P2",
            status: "completed",
            total_questions: 1,
            completed_questions: 1,
            failed_questions: 0,
            updated_at: "2026-08-05T00:00:00Z",
          },
        ]);
      }
      if (url.pathname === "/api/v1/papers/jobs/job-a") {
        requestedA = true;
        return slowA;
      }
      if (url.pathname === "/api/v1/papers/jobs/job-b") return response(detailB);
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);

    const user = userEvent.setup();
    render(<Grading subject={subject} onCreated={vi.fn()} />);
    await screen.findByLabelText("选择作答记录");
    await waitFor(() => expect(requestedA).toBe(true));
    await chooseMaterialOption(user, "选择作答记录", "b.pdf");
    await waitFor(() => expect(screen.getByLabelText("所选答卷内容")).toHaveTextContent("QB答案已保存"));

    await act(async () => {
      resolveA?.(new Response(JSON.stringify(detailA), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
      await slowA;
    });
    expect(screen.getByLabelText("所选答卷内容")).toHaveTextContent("QB答案已保存");
  });

  test("clears paper A immediately and does not restore it when paper B fails to load", async () => {
    const paperA = paperFixture("job-a", [questionFixture(1, "A")]);
    let resolvePaperB: ((value: Response) => void) | undefined;
    const paperBRequest = new Promise<Response>((resolve) => {
      resolvePaperB = resolve;
    });
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input instanceof Request ? input.url : input));
      if (url.pathname === "/api/v1/grading/papers") {
        return response([paperSummaryFixture("job-a"), paperSummaryFixture("job-b")]);
      }
      if (url.pathname === "/api/v1/corpus/documents") return response([]);
      if (url.pathname === "/api/v1/papers/jobs/job-a") return response(paperA);
      if (url.pathname === "/api/v1/papers/jobs/job-b") return paperBRequest;
      if (url.pathname === "/api/v1/grading/rubrics") return response([]);
      if (url.pathname.endsWith("/assessments")) return response([]);
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);

    const user = userEvent.setup();
    render(<Grading subject={subject} onCreated={vi.fn()} />);
    expect(await screen.findByLabelText("所选答卷内容")).toHaveTextContent("QA答案已保存");

    await chooseMaterialOption(user, "选择作答记录", "job-b.pdf");
    expect(screen.queryByLabelText("所选答卷内容")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /02.*逐题判分/ })).toBeDisabled();

    await act(async () => {
      resolvePaperB?.(new Response(JSON.stringify({ detail: "paper B unavailable" }), {
        status: 503,
        headers: { "Content-Type": "application/json" },
      }));
      await paperBRequest;
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("paper B unavailable");
    expect(screen.queryByLabelText("所选答卷内容")).not.toBeInTheDocument();
  });

  test("retries a failed selected-paper load in-page before enabling its matching rubric", async () => {
    const paper = paperFixture("job-retry");
    const scheme = sourceFixture("ms-retry");
    const rubric = rubricFixture({
      id: "rubric-retry",
      paperJobId: paper.job_id,
      sourceDocumentId: scheme.id,
      status: "draft",
      criteria: [criterionFixture("criterion-retry", "1", "R1")],
    });
    let paperDetailRequests = 0;
    let resolveRetry: ((value: Response) => void) | undefined;
    const retryRequest = new Promise<Response>((resolve) => {
      resolveRetry = resolve;
    });
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(String(input));
      const url = new URL(request.url);
      if (url.pathname === "/api/v1/grading/papers") {
        return response([paperSummaryFixture(paper.job_id)]);
      }
      if (url.pathname === "/api/v1/corpus/documents") return response([scheme]);
      if (url.pathname === `/api/v1/papers/jobs/${paper.job_id}`) {
        paperDetailRequests += 1;
        return paperDetailRequests === 1
          ? Promise.resolve(new Response(JSON.stringify({ detail: "paper unavailable" }), {
              status: 503,
              headers: { "Content-Type": "application/json" },
            }))
          : retryRequest;
      }
      if (url.pathname === "/api/v1/grading/rubrics" && request.method === "GET") {
        return response([rubric]);
      }
      if (url.pathname === `/api/v1/grading/rubrics/${rubric.id}`) return response(rubric);
      if (url.pathname.endsWith("/assessments")) return response([]);
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);

    const user = userEvent.setup();
    render(<Grading subject={subject} onCreated={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("paper unavailable");
    const retryButton = screen.getByRole("button", { name: "解析评分标准" });
    expect(retryButton).toBeEnabled();
    expect(fetch).not.toHaveBeenCalledWith(
      expect.objectContaining({ method: "POST" }),
    );

    await user.click(retryButton);
    expect(retryButton).toBeDisabled();
    fireEvent.click(retryButton);
    expect(paperDetailRequests).toBe(2);

    await act(async () => {
      resolveRetry?.(await response(paper));
      await retryRequest;
    });

    const continueButton = await screen.findByRole("button", {
      name: "审核评分标准",
    });
    expect(continueButton).toBeEnabled();
    await user.click(continueButton);
    expect(await screen.findByText("Criterion R1")).toBeInTheDocument();
  });

  test("locks material selection while the Mark Scheme is being parsed", async () => {
    const paper = paperFixture("job-parse");
    const createdRubric = rubricFixture({
      id: "rubric-ms-a",
      paperJobId: paper.job_id,
      sourceDocumentId: "ms-a",
      status: "draft",
    });
    let createBody: unknown;
    let resolveCreate: ((value: Response) => void) | undefined;
    const createRequest = new Promise<Response>((resolve) => {
      resolveCreate = resolve;
    });
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(String(input));
      const url = new URL(request.url);
      if (url.pathname === "/api/v1/grading/papers") {
        return response([paperSummaryFixture(paper.job_id)]);
      }
      if (url.pathname === "/api/v1/corpus/documents") {
        return response([
          sourceFixture("ms-a", "scheme-a.pdf"),
          sourceFixture("ms-b", "scheme-b.pdf"),
        ]);
      }
      if (url.pathname === `/api/v1/papers/jobs/${paper.job_id}`) return response(paper);
      if (url.pathname === "/api/v1/grading/rubrics" && request.method === "GET") {
        return response([]);
      }
      if (url.pathname.endsWith("/assessments")) return response([]);
      if (url.pathname === "/api/v1/grading/rubrics" && request.method === "POST") {
        createBody = await request.clone().json();
        return createRequest;
      }
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);

    const user = userEvent.setup();
    render(<Grading subject={subject} onCreated={vi.fn()} />);
    await screen.findByLabelText("所选答卷内容");
    const schemeSelector = await screen.findByLabelText("选择 Mark Scheme");
    await waitFor(() => expect(schemeSelector).toHaveValue("ms-a"));
    await user.click(screen.getByRole("button", { name: "解析评分标准" }));
    await waitFor(() => expect(createBody).toEqual({
      paper_job_id: paper.job_id,
      source_document_id: "ms-a",
    }));

    expect(schemeSelector).toBeDisabled();
    expect(screen.getByRole("button", { name: "管理标准" })).toBeDisabled();
    await act(async () => {
      resolveCreate?.(await response(createdRubric));
      await createRequest;
    });

    expect(screen.getByLabelText("选择 Mark Scheme")).toHaveValue("ms-a");
    expect(await screen.findByText("Criterion M1")).toBeInTheDocument();
  });

  test("keeps the newest source response when an older source request finishes last", async () => {
    const oldSource = sourceFixture("ms-old", "old-scheme.pdf");
    const uploadedSource = sourceFixture("ms-new", "new-scheme.pdf");
    let sourceRequests = 0;
    let resolveOldSources: ((value: Response) => void) | undefined;
    const oldSourcesRequest = new Promise<Response>((resolve) => {
      resolveOldSources = resolve;
    });
    const fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(String(input), init);
      const url = new URL(request.url);
      if (url.pathname === "/api/v1/grading/papers") return response([]);
      if (url.pathname === "/api/v1/corpus/documents") {
        sourceRequests += 1;
        return sourceRequests === 1 ? oldSourcesRequest : response([uploadedSource]);
      }
      if (url.pathname.includes("/subject-workspaces/") && request.method === "POST") {
        return response(uploadedSource);
      }
      if (url.pathname === "/api/v1/corpus/convert") {
        return response({ errors: [], failed: 0, processed: 1, skipped: 0, succeeded: 1 });
      }
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);

    const user = userEvent.setup();
    render(<Grading subject={subject} onCreated={vi.fn()} />);
    await user.upload(
      screen.getByLabelText("上传官方 Mark Scheme"),
      new File(["scheme"], "new-scheme.pdf", { type: "application/pdf" }),
    );
    await waitFor(() => expect(screen.getByLabelText("选择 Mark Scheme"))
      .toHaveTextContent("new-scheme.pdf"));

    await act(async () => {
      resolveOldSources?.(await response([oldSource]));
      await oldSourcesRequest;
    });
    expect(screen.getByLabelText("选择 Mark Scheme")).not.toHaveTextContent("old-scheme.pdf");
    expect(screen.getByLabelText("选择 Mark Scheme")).toHaveValue("ms-new");
  });

  test("keeps the selected scheme and surfaces backend errors when conversion reports failure", async () => {
    const existingSource = sourceFixture("ms-existing", "existing-scheme.pdf");
    const uploadedSource = sourceFixture("ms-upload-failed", "failed-scheme.pdf");
    let sourceRequests = 0;
    const fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(String(input), init);
      const url = new URL(request.url);
      if (url.pathname === "/api/v1/grading/papers") return response([]);
      if (url.pathname === "/api/v1/corpus/documents") {
        sourceRequests += 1;
        return response([existingSource]);
      }
      if (url.pathname.includes("/subject-workspaces/") && request.method === "POST") {
        return response(uploadedSource);
      }
      if (url.pathname === "/api/v1/corpus/convert") {
        return response({
          errors: ["PDF 无法转换"],
          failed: 1,
          processed: 1,
          skipped: 0,
          succeeded: 0,
        });
      }
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);

    const notify = vi.fn();
    const user = userEvent.setup();
    render(
      <ToastContext.Provider value={{ notify }}>
        <Grading subject={subject} onCreated={vi.fn()} />
      </ToastContext.Provider>,
    );
    const schemeSelector = await screen.findByLabelText("选择 Mark Scheme");
    await waitFor(() => expect(schemeSelector).toHaveValue(existingSource.id));

    await user.upload(
      screen.getByLabelText("上传官方 Mark Scheme"),
      new File(["scheme"], "failed-scheme.pdf", { type: "application/pdf" }),
    );

    expect(await screen.findByText("PDF 无法转换")).toBeInTheDocument();
    expect(schemeSelector).toHaveValue(existingSource.id);
    expect(sourceRequests).toBe(1);
    expect(notify).not.toHaveBeenCalled();
  });

  test.each([
    { label: "converted", skipped: 0, succeeded: 1 },
    { label: "skipped", skipped: 1, succeeded: 0 },
  ])("selects a ready uploaded scheme after a $label conversion result", async ({
    skipped,
    succeeded,
  }) => {
    const existingSource = sourceFixture("ms-before-upload", "before-upload.pdf");
    const uploadedSource = sourceFixture(
      `ms-upload-${succeeded ? "converted" : "skipped"}`,
      "uploaded-scheme.pdf",
    );
    let sourceRequests = 0;
    const fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(String(input), init);
      const url = new URL(request.url);
      if (url.pathname === "/api/v1/grading/papers") return response([]);
      if (url.pathname === "/api/v1/corpus/documents") {
        sourceRequests += 1;
        return response(
          sourceRequests === 1
            ? [existingSource]
            : [existingSource, uploadedSource],
        );
      }
      if (url.pathname.includes("/subject-workspaces/") && request.method === "POST") {
        return response(uploadedSource);
      }
      if (url.pathname === "/api/v1/corpus/convert") {
        return response({
          errors: [],
          failed: 0,
          processed: 1,
          skipped,
          succeeded,
        });
      }
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);

    const notify = vi.fn();
    const user = userEvent.setup();
    render(
      <ToastContext.Provider value={{ notify }}>
        <Grading subject={subject} onCreated={vi.fn()} />
      </ToastContext.Provider>,
    );
    const schemeSelector = await screen.findByLabelText("选择 Mark Scheme");
    await waitFor(() => expect(schemeSelector).toHaveValue(existingSource.id));

    await user.upload(
      screen.getByLabelText("上传官方 Mark Scheme"),
      new File(["scheme"], "uploaded-scheme.pdf", { type: "application/pdf" }),
    );

    await waitFor(() => expect(schemeSelector).toHaveValue(uploadedSource.id));
    expect(screen.getByLabelText("选择 Mark Scheme")).toHaveTextContent("uploaded-scheme.pdf");
    expect(sourceRequests).toBe(2);
    expect(notify).toHaveBeenCalledWith(
      "Mark Scheme 已上传并完成转换，可开始解析评分规则。",
    );
  });

  test("does not fall back to a rubric whose source is absent from ready documents", async () => {
    const paper = paperFixture("job-stale-rubric");
    const readyScheme = sourceFixture("ms-ready", "ready-scheme.pdf");
    const staleRubric = rubricFixture({
      id: "rubric-stale-source",
      paperJobId: paper.job_id,
      sourceDocumentId: "ms-invalidated",
    });
    let staleRubricDetailRequests = 0;
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(String(input));
      const url = new URL(request.url);
      if (url.pathname === "/api/v1/grading/papers") {
        return response([paperSummaryFixture(paper.job_id)]);
      }
      if (url.pathname === "/api/v1/corpus/documents") return response([readyScheme]);
      if (url.pathname === `/api/v1/papers/jobs/${paper.job_id}`) return response(paper);
      if (url.pathname === "/api/v1/grading/rubrics") return response([staleRubric]);
      if (url.pathname === `/api/v1/grading/rubrics/${staleRubric.id}`) {
        staleRubricDetailRequests += 1;
        return response(staleRubric);
      }
      if (url.pathname.endsWith("/assessments")) return response([]);
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);

    render(<Grading subject={subject} onCreated={vi.fn()} />);

    const schemeSelector = await screen.findByLabelText("选择 Mark Scheme");
    await waitFor(() => expect(schemeSelector).toHaveValue(readyScheme.id));
    expect(await screen.findByRole("button", { name: "解析评分标准" })).toBeEnabled();
    expect(staleRubricDetailRequests).toBe(0);
  });

  test("pairs the initial rubric with its Mark Scheme instead of selecting independent first items", async () => {
    const paper = paperFixture("job-paired");
    const schemeA = sourceFixture("ms-a", "scheme-a.pdf");
    const schemeB = sourceFixture("ms-b", "scheme-b.pdf");
    const rubricA = rubricFixture({
      id: "rubric-a",
      paperJobId: paper.job_id,
      sourceDocumentId: schemeA.id,
      criteria: [criterionFixture("criterion-a", "1", "A1")],
    });
    const rubricB = {
      ...rubricFixture({
        id: "rubric-b",
        paperJobId: paper.job_id,
        sourceDocumentId: schemeB.id,
        criteria: [criterionFixture("criterion-b", "1", "B1")],
      }),
      version_number: 2,
    };
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(String(input));
      const url = new URL(request.url);
      if (url.pathname === "/api/v1/grading/papers") {
        return response([paperSummaryFixture(paper.job_id)]);
      }
      if (url.pathname === "/api/v1/corpus/documents") return response([schemeA, schemeB]);
      if (url.pathname === `/api/v1/papers/jobs/${paper.job_id}`) return response(paper);
      if (url.pathname === "/api/v1/grading/rubrics") return response([rubricB, rubricA]);
      if (url.pathname === `/api/v1/grading/rubrics/${rubricA.id}`) return response(rubricA);
      if (url.pathname === `/api/v1/grading/rubrics/${rubricB.id}`) return response(rubricB);
      if (url.pathname.endsWith("/assessments")) return response([]);
      if (url.pathname.endsWith("/overview")) return response({});
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);

    const user = userEvent.setup();
    render(<Grading subject={subject} onCreated={vi.fn()} />);
    await waitFor(() => expect(screen.getByLabelText("选择 Mark Scheme")).toHaveValue(schemeA.id));
    await user.click(await screen.findByRole("button", { name: "开始逐题判分" }));
    await user.click(screen.getByRole("button", { name: "查看评分标准" }));

    expect(await screen.findByText("Criterion A1")).toBeInTheDocument();
    expect(screen.queryByText("Criterion B1")).not.toBeInTheDocument();
  });

  test("keeps an explicitly selected Mark Scheme while an older rubric detail resolves", async () => {
    const paper = paperFixture("job-explicit-scheme");
    const schemeA = sourceFixture("ms-explicit-a", "scheme-a.pdf");
    const schemeB = sourceFixture("ms-explicit-b", "scheme-b.pdf");
    const rubricA = rubricFixture({
      id: "rubric-explicit-a",
      paperJobId: paper.job_id,
      sourceDocumentId: schemeA.id,
      criteria: [criterionFixture("criterion-explicit-a", "1", "A1")],
    });
    let rubricDetailRequests = 0;
    let resolveRubricA: (() => void) | undefined;
    let rubricARequest: Promise<Response> | undefined;
    const rubricAGate = new Promise<void>((resolve) => {
      resolveRubricA = resolve;
    });
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(String(input));
      const url = new URL(request.url);
      if (url.pathname === "/api/v1/grading/papers") {
        return response([paperSummaryFixture(paper.job_id)]);
      }
      if (url.pathname === "/api/v1/corpus/documents") return response([schemeA, schemeB]);
      if (url.pathname === `/api/v1/papers/jobs/${paper.job_id}`) return response(paper);
      if (url.pathname === "/api/v1/grading/rubrics" && request.method === "GET") {
        return response([rubricA]);
      }
      if (url.pathname === `/api/v1/grading/rubrics/${rubricA.id}`) {
        rubricDetailRequests += 1;
        const pendingRequest = rubricAGate.then(() => new Response(JSON.stringify(rubricA), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }));
        rubricARequest ??= pendingRequest;
        return pendingRequest;
      }
      if (url.pathname.endsWith("/assessments")) return response([]);
      if (url.pathname.endsWith("/overview")) return response({});
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);

    const user = userEvent.setup();
    render(<Grading subject={subject} onCreated={vi.fn()} />);
    const schemeSelector = await screen.findByLabelText("选择 Mark Scheme");
    await waitFor(() => {
      expect(schemeSelector).toHaveValue(schemeA.id);
      expect(rubricDetailRequests).toBe(1);
    });

    await chooseMaterialOption(user, "选择 Mark Scheme", schemeB.filename);
    await waitFor(() => {
      expect(screen.getByLabelText("所选答卷内容")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "解析评分标准" })).toBeEnabled();
    });

    await act(async () => {
      resolveRubricA?.();
      await rubricARequest;
    });

    expect(screen.getByLabelText("选择 Mark Scheme")).toHaveValue(schemeB.id);
    expect(screen.getByRole("button", { name: "解析评分标准" })).toBeEnabled();
    expect(screen.getByRole("button", { name: /02.*逐题判分/ })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "开始逐题判分" })).not.toBeInTheDocument();
  });

  test("invalidates confirmed Scheme A immediately when selecting Mark Scheme B", async () => {
    const paper = paperFixture("job-document-identity");
    const schemeA = sourceFixture("ms-document-a", "scheme-a.pdf");
    const schemeB = sourceFixture("ms-document-b", "scheme-b.pdf");
    const rubricA = rubricFixture({
      id: "rubric-document-a",
      paperJobId: paper.job_id,
      sourceDocumentId: schemeA.id,
      criteria: [criterionFixture("criterion-document-a", "1", "A1")],
    });
    const rubricB = rubricFixture({
      id: "rubric-document-b",
      paperJobId: paper.job_id,
      sourceDocumentId: schemeB.id,
      status: "draft",
      criteria: [criterionFixture("criterion-document-b", "1", "B1")],
    });
    let resolveRubricB: ((value: Response) => void) | undefined;
    const rubricBRequest = new Promise<Response>((resolve) => {
      resolveRubricB = resolve;
    });
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(String(input));
      const url = new URL(request.url);
      if (url.pathname === "/api/v1/grading/papers") {
        return response([paperSummaryFixture(paper.job_id)]);
      }
      if (url.pathname === "/api/v1/corpus/documents") return response([schemeA, schemeB]);
      if (url.pathname === `/api/v1/papers/jobs/${paper.job_id}`) return response(paper);
      if (url.pathname === "/api/v1/grading/rubrics") return response([rubricA, rubricB]);
      if (url.pathname === `/api/v1/grading/rubrics/${rubricA.id}`) return response(rubricA);
      if (url.pathname === `/api/v1/grading/rubrics/${rubricB.id}`) return rubricBRequest;
      if (url.pathname.endsWith("/assessments")) return response([]);
      if (url.pathname.endsWith("/overview")) return response({});
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);

    const user = userEvent.setup();
    render(<Grading subject={subject} onCreated={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "开始逐题判分" }));
    await user.click(screen.getByRole("button", { name: "返回材料" }));
    await chooseMaterialOption(user, "选择 Mark Scheme", schemeB.filename);

    expect(screen.getByLabelText("选择 Mark Scheme")).toHaveValue(schemeB.id);
    expect(screen.getByRole("button", { hidden: true, name: /02.*逐题判分/ })).toBeDisabled();
    expect(screen.getByRole("button", { hidden: true, name: /03.*整卷结果/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "解析评分标准" })).toBeDisabled();

    await act(async () => {
      resolveRubricB?.(await response(rubricB));
      await rubricBRequest;
    });
    expect(await screen.findByRole("button", { name: "审核评分标准" })).toBeEnabled();
    expect(screen.getByRole("button", { hidden: true, name: /02.*逐题判分/ })).toBeDisabled();
  });


  test("clears confirmed Scheme A while Scheme B loads and keeps later steps gated for draft B", async () => {
    const paper = paperFixture("job-version");
    const scheme = sourceFixture("ms-version");
    const rubricA = rubricFixture({
      id: "rubric-version-a",
      paperJobId: paper.job_id,
      sourceDocumentId: scheme.id,
      criteria: [criterionFixture("criterion-version-a", "1", "A1")],
    });
    const rubricB = {
      ...rubricFixture({
        id: "rubric-version-b",
        paperJobId: paper.job_id,
        sourceDocumentId: scheme.id,
        status: "draft",
        criteria: [criterionFixture("criterion-version-b", "1", "B1")],
      }),
      version_number: 2,
    };
    let resolveRubricB: ((value: Response) => void) | undefined;
    const rubricBRequest = new Promise<Response>((resolve) => {
      resolveRubricB = resolve;
    });
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(String(input));
      const url = new URL(request.url);
      if (url.pathname === "/api/v1/grading/papers") {
        return response([paperSummaryFixture(paper.job_id)]);
      }
      if (url.pathname === "/api/v1/corpus/documents") return response([scheme]);
      if (url.pathname === `/api/v1/papers/jobs/${paper.job_id}`) return response(paper);
      if (url.pathname === "/api/v1/grading/rubrics") return response([rubricA, rubricB]);
      if (url.pathname === `/api/v1/grading/rubrics/${rubricA.id}`) return response(rubricA);
      if (url.pathname === `/api/v1/grading/rubrics/${rubricB.id}`) return rubricBRequest;
      if (url.pathname.endsWith("/assessments")) return response([]);
      if (url.pathname.endsWith("/overview")) return response({});
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);

    const user = userEvent.setup();
    render(<Grading subject={subject} onCreated={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "开始逐题判分" }));
    await user.click(screen.getByRole("button", { name: "查看评分标准" }));
    const versionSelector = await screen.findByLabelText("选择评分规则版本");
    await user.selectOptions(versionSelector, rubricB.id);

    expect(versionSelector).toBeDisabled();
    expect(screen.queryByText("Criterion A1")).not.toBeInTheDocument();
    const journeyButtons = document.querySelectorAll<HTMLButtonElement>(
      'nav[aria-label="评分流程"] button',
    );
    expect(journeyButtons[1]).toBeDisabled();
    expect(journeyButtons[2]).toBeDisabled();

    await act(async () => {
      resolveRubricB?.(await response(rubricB));
      await rubricBRequest;
    });
    expect(await screen.findByText("Criterion B1")).toBeInTheDocument();
    expect(screen.getAllByText("待处理").length).toBeGreaterThan(0);
    expect(journeyButtons[1]).toBeDisabled();
  });

  test("keeps the newest rubric version when an older version load finishes last", async () => {
    const paper = paperFixture("job-version-race");
    const scheme = sourceFixture("ms-version-race");
    const rubricA = rubricFixture({
      id: "rubric-race-a",
      paperJobId: paper.job_id,
      sourceDocumentId: scheme.id,
      criteria: [criterionFixture("criterion-race-a", "1", "A1")],
    });
    const rubricB = {
      ...rubricFixture({
        id: "rubric-race-b",
        paperJobId: paper.job_id,
        sourceDocumentId: scheme.id,
        criteria: [criterionFixture("criterion-race-b", "1", "B1")],
      }),
      version_number: 2,
    };
    const rubricC = {
      ...rubricFixture({
        id: "rubric-race-c",
        paperJobId: paper.job_id,
        sourceDocumentId: scheme.id,
        status: "draft",
        criteria: [criterionFixture("criterion-race-c", "1", "C1")],
      }),
      version_number: 3,
    };
    let resolveRubricB: ((value: Response) => void) | undefined;
    const rubricBRequest = new Promise<Response>((resolve) => {
      resolveRubricB = resolve;
    });
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(String(input));
      const url = new URL(request.url);
      if (url.pathname === "/api/v1/grading/papers") {
        return response([paperSummaryFixture(paper.job_id)]);
      }
      if (url.pathname === "/api/v1/corpus/documents") return response([scheme]);
      if (url.pathname === `/api/v1/papers/jobs/${paper.job_id}`) return response(paper);
      if (url.pathname === "/api/v1/grading/rubrics") return response([rubricA, rubricB, rubricC]);
      if (url.pathname === `/api/v1/grading/rubrics/${rubricA.id}`) return response(rubricA);
      if (url.pathname === `/api/v1/grading/rubrics/${rubricB.id}`) return rubricBRequest;
      if (url.pathname === `/api/v1/grading/rubrics/${rubricC.id}`) return response(rubricC);
      if (url.pathname.endsWith("/assessments")) return response([]);
      if (url.pathname.endsWith("/overview")) return response({});
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);

    const user = userEvent.setup();
    render(<Grading subject={subject} onCreated={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "开始逐题判分" }));
    await user.click(screen.getByRole("button", { name: "查看评分标准" }));
    const versionSelector = await screen.findByLabelText("选择评分规则版本");
    fireEvent.change(versionSelector, { target: { value: rubricB.id } });
    fireEvent.change(versionSelector, { target: { value: rubricC.id } });
    expect(await screen.findByText("Criterion C1")).toBeInTheDocument();

    await act(async () => {
      resolveRubricB?.(await response(rubricB));
      await rubricBRequest;
    });
    expect(screen.getByText("Criterion C1")).toBeInTheDocument();
    expect(screen.queryByText("Criterion B1")).not.toBeInTheDocument();
    const journeyButtons = document.querySelectorAll<HTMLButtonElement>(
      'nav[aria-label="评分流程"] button',
    );
    expect(journeyButtons[1]).toBeDisabled();
  });

  test("disables every material control while rubric creation is pending", async () => {
    const paper = paperFixture("job-operation-overlap");
    const scheme = sourceFixture("ms-operation-old");
    let resolveCreate: ((value: Response) => void) | undefined;
    const createdRubric = rubricFixture({
      id: "rubric-operation-old",
      paperJobId: paper.job_id,
      sourceDocumentId: scheme.id,
      status: "draft",
    });
    const createRequest = new Promise<Response>((resolve) => {
      resolveCreate = resolve;
    });
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(String(input));
      const url = new URL(request.url);
      if (url.pathname === "/api/v1/grading/papers") {
        return response([paperSummaryFixture(paper.job_id)]);
      }
      if (url.pathname === "/api/v1/corpus/documents") return response([scheme]);
      if (url.pathname === `/api/v1/papers/jobs/${paper.job_id}`) return response(paper);
      if (url.pathname === "/api/v1/grading/rubrics" && request.method === "GET") {
        return response([]);
      }
      if (url.pathname === "/api/v1/grading/rubrics" && request.method === "POST") {
        return createRequest;
      }
      if (url.pathname.endsWith("/assessments")) return response([]);
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);

    const user = userEvent.setup();
    render(<Grading subject={subject} onCreated={vi.fn()} />);
    await screen.findByLabelText("所选答卷内容");
    const paperSelector = screen.getByLabelText("选择作答记录");
    const schemeSelector = screen.getByLabelText("选择 Mark Scheme");
    const uploadInput = screen.getByLabelText("上传官方 Mark Scheme");
    await user.click(screen.getByRole("button", { name: "解析评分标准" }));

    expect(paperSelector).toBeDisabled();
    expect(schemeSelector).toBeDisabled();
    expect(uploadInput).toBeDisabled();
    expect(screen.getByRole("button", { name: "解析评分标准" })).toBeDisabled();

    await act(async () => {
      resolveCreate?.(await response(createdRubric));
      await createRequest;
    });
  });

  test("locks grading context navigation until an assessment write settles", async () => {
    const paper = paperFixture("job-assessment-lock");
    const scheme = sourceFixture("ms-assessment-lock");
    const rubric = rubricFixture({
      id: "rubric-assessment-lock",
      paperJobId: paper.job_id,
      sourceDocumentId: scheme.id,
      criteria: [criterionFixture("criterion-assessment-lock", "1", "M1")],
    });
    const result = gradeResultFixture("assessment-lock");
    let resolveAssessment: ((value: Response) => void) | undefined;
    const assessmentRequest = new Promise<Response>((resolve) => {
      resolveAssessment = resolve;
    });
    let assessmentGets = 0;
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(String(input));
      const url = new URL(request.url);
      if (url.pathname === "/api/v1/grading/papers") {
        return response([paperSummaryFixture(paper.job_id)]);
      }
      if (url.pathname === "/api/v1/corpus/documents") return response([scheme]);
      if (url.pathname === `/api/v1/papers/jobs/${paper.job_id}`) return response(paper);
      if (url.pathname === "/api/v1/grading/rubrics") return response([rubric]);
      if (url.pathname === `/api/v1/grading/rubrics/${rubric.id}`) return response(rubric);
      if (url.pathname.endsWith("/assessments")) {
        assessmentGets += 1;
        return response([]);
      }
      if (url.pathname.endsWith("/questions/1/assess")) return assessmentRequest;
      if (url.pathname.endsWith("/overview")) return response({});
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);

    const user = userEvent.setup();
    render(<Grading subject={subject} onCreated={vi.fn().mockResolvedValue(undefined)} />);
    await user.click(await screen.findByRole("button", { name: "开始逐题判分" }));
    await user.click(screen.getByRole("button", { name: "生成判分结果" }));

    const materialStep = screen.getByRole("button", { name: /01.*准备材料/ });
    const gradingStep = screen.getByRole("button", { name: /02.*逐题判分/ });
    const overviewStep = screen.getByRole("button", { name: /03.*整卷结果/ });
    const backButton = screen.getByRole("button", { name: "返回材料" });
    const questionButton = screen.getByRole("button", { name: /Q1/ });
    expect(materialStep).toBeDisabled();
    expect(gradingStep).toBeDisabled();
    expect(overviewStep).toBeDisabled();
    expect(backButton).toBeDisabled();
    expect(questionButton).toBeDisabled();

    await act(async () => {
      resolveAssessment?.(await response(result));
      await assessmentRequest;
    });

    await waitFor(() => {
      expect(materialStep).toBeEnabled();
      expect(gradingStep).toBeEnabled();
      expect(overviewStep).toBeEnabled();
      expect(backButton).toBeEnabled();
      expect(questionButton).toBeEnabled();
    });
    expect(assessmentGets).toBeGreaterThanOrEqual(2);
  });

  test("shows and announces the persisted grade before reconciliation settles", async () => {
    const paper = paperFixture("job-immediate-grade");
    const scheme = sourceFixture("ms-immediate-grade");
    const rubric = rubricFixture({
      id: "rubric-immediate-grade",
      paperJobId: paper.job_id,
      sourceDocumentId: scheme.id,
      criteria: [criterionFixture("criterion-immediate-grade", "1", "M1")],
    });
    const result = gradeResultFixture("assessment-immediate-grade");
    const unresolvedQueueRefresh = new Promise<void>(() => undefined);
    let assessmentGets = 0;
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(String(input));
      const url = new URL(request.url);
      if (url.pathname === "/api/v1/grading/papers") {
        return response([paperSummaryFixture(paper.job_id)]);
      }
      if (url.pathname === "/api/v1/corpus/documents") return response([scheme]);
      if (url.pathname === `/api/v1/papers/jobs/${paper.job_id}`) return response(paper);
      if (url.pathname === "/api/v1/grading/rubrics") return response([rubric]);
      if (url.pathname === `/api/v1/grading/rubrics/${rubric.id}`) return response(rubric);
      if (url.pathname.endsWith("/assessments")) {
        assessmentGets += 1;
        return response(assessmentGets === 1 ? [] : []);
      }
      if (url.pathname.endsWith("/questions/1/assess")) return response(result);
      if (url.pathname.endsWith("/overview")) return response({});
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);

    const user = userEvent.setup();
    render(<Grading subject={subject} onCreated={() => unresolvedQueueRefresh} />);
    await user.click(await screen.findByRole("button", { name: "开始逐题判分" }));
    await user.click(screen.getByRole("button", { name: "生成判分结果" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Q1 判分结果已生成，得分 1 / 1。",
    );
    expect(await screen.findByText("等待人工复核")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "生成判分结果" })).not.toBeInTheDocument();
    await waitFor(() => expect(
      screen.getByRole("heading", { name: "Q1 判分结果" }),
    ).toHaveFocus());
  });

  test("renders inline question images, bare LaTeX, and collapsible materials", async () => {
    const paper = paperFixture("job-loose-latex");
    const imageUrl = (
      `/api/v1/papers/jobs/${paper.job_id}/question-images/`
      + `p0001-${"a".repeat(64)}.png`
    );
    paper.questions[0].question_markdown = (
      `Read the diagram.\n\n![Question diagram](${imageUrl})\n\nCalculate the force.`
    );
    const rubric = rubricFixture({
      id: "rubric-loose-latex",
      paperJobId: paper.job_id,
    });
    const result = gradeResultFixture("assessment-loose-latex");
    result.rubric_awards[0] = {
      ...result.rubric_awards[0],
      student_evidence: String.raw`"a=\frac{5.2}{0.55}"`,
      rationale: String.raw`The exact result is \boxed{9.45\ \mathrm{m\,s^{-2}}}.`,
    };
    const assessment = {
      ...assessmentFixture(1, "pending_review", result),
      paper_job_id: paper.job_id,
      rubric_set_id: rubric.id,
    };
    const user = userEvent.setup();
    const { container } = render(
      <GradingQuestionStage assessments={[assessment]}
      busy={null}
      error={null}
      onAssessQuestion={vi.fn(async () => undefined)}
      onBack={vi.fn()}
      onOverview={vi.fn()}
      onSelectPosition={vi.fn()}
      onViewRubric={vi.fn()}
      paper={paper}
      rubric={rubric}
      selectedPosition={1} subjectId="test-subject" />,
    );

    expect(container.querySelectorAll(".grading-award-evidence .katex")).toHaveLength(1);
    expect(container.querySelectorAll(".grading-award-rationale .katex")).toHaveLength(1);
    const question = screen.getByText("原题").closest("details");
    const answer = screen.getByText("已保存答案").closest("details");
    expect(question).not.toHaveAttribute("open");
    expect(answer).not.toHaveAttribute("open");
    await user.click(screen.getByText("原题"));
    expect(screen.getByRole("img", { name: "Question diagram" })).toHaveAttribute(
      "src",
      `${imageUrl}?subject=test-subject`,
    );
    expect(answer).not.toHaveAttribute("open");
  });

  test("announces every identical regeneration completion with a fresh live-region entry", async () => {
    const paper = paperFixture("job-question-stage");
    const rubric = rubricFixture({
      id: "rubric-question-stage",
      paperJobId: paper.job_id,
    });
    const result = gradeResultFixture("assessment-repeat");
    const onAssessQuestion = vi.fn(async () => result);
    const user = userEvent.setup();
    render(
      <GradingQuestionStage assessments={[assessmentFixture(1, "pending_review", result)]}
      busy={null}
      error={null}
      onAssessQuestion={onAssessQuestion}
      onBack={vi.fn()}
      onViewRubric={vi.fn()}
      onOverview={vi.fn()}
      onSelectPosition={vi.fn()}
      paper={paper}
      rubric={rubric}
      selectedPosition={1} subjectId="test-subject" />,
    );
    const awardEvidence = screen.getByText("学生证据").closest("section")!;
    expect(within(awardEvidence).getByText("Answer 1")).toBeVisible();
    expect(screen.getByText("判分理由")).toBeInTheDocument();
    const criterionDetails = screen.getByText("查看原始得分点").closest("details");
    expect(criterionDetails).not.toHaveAttribute("open");
    await user.click(screen.getByText("查看原始得分点"));
    expect(criterionDetails).toHaveAttribute("open");
    expect(screen.getByText("Award the method mark.")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "重新判分" }));
    const firstAnnouncement = await screen.findByRole("status");
    expect(firstAnnouncement).toHaveTextContent("Q1 判分结果已生成，得分 1 / 1。");

    await user.click(screen.getByRole("button", { name: "重新判分" }));
    await waitFor(() => expect(screen.getByRole("status")).not.toBe(firstAnnouncement));
    expect(screen.getByRole("status")).toHaveTextContent("Q1 判分结果已生成，得分 1 / 1。");
    expect(onAssessQuestion).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(
      screen.getByRole("heading", { name: "Q1 判分结果" }),
    ).toHaveFocus());
  });

  test("renders confirmed and overridden persisted assessment states without pending-review claims", () => {
    const paper = paperFixture(
      "job-question-stage",
      [questionFixture(1), questionFixture(2)],
    );
    const rubric = rubricFixture({
      id: "rubric-question-stage",
      paperJobId: paper.job_id,
      criteria: [
        criterionFixture("criterion-confirmed", "1", "M1"),
        criterionFixture("criterion-overridden", "2", "M2"),
      ],
    });
    const confirmedResult: GradeResult = {
      ...gradeResultFixture("assessment-confirmed"),
      manual_review_required: false,
      status: "confirmed",
    };
    const overriddenResult: GradeResult = {
      ...gradeResultFixture("assessment-overridden"),
      manual_review_required: false,
      question_ref: "paper-fixture:Q2",
      status: "overridden",
    };
    const assessments = [
      assessmentFixture(1, "confirmed", confirmedResult),
      assessmentFixture(2, "overridden", overriddenResult),
    ];
    const common = {
      assessments,
      busy: null,
      error: null,
      onAssessQuestion: vi.fn(async () => undefined),
      onBack: vi.fn(),
      onViewRubric: vi.fn(),
      onOverview: vi.fn(),
      onSelectPosition: vi.fn(),
      paper,
      rubric,
    };
    const mounted = render(<GradingQuestionStage {...common} selectedPosition={1} subjectId="test-subject" />);

    expect(screen.getByText("人工复核已确认")).toBeInTheDocument();
    expect(screen.getByText("评分结果已由人工确认")).toBeInTheDocument();
    expect(screen.queryByText("等待人工复核")).not.toBeInTheDocument();
    expect(screen.queryByText("判分结果已进入人工复核队列")).not.toBeInTheDocument();

    mounted.rerender(<GradingQuestionStage {...common} selectedPosition={2} subjectId="test-subject" />);
    expect(screen.getByText("人工改分已确认")).toBeInTheDocument();
    expect(screen.getByText("评分结果已由人工改分确认")).toBeInTheDocument();
    expect(screen.queryByText("等待人工复核")).not.toBeInTheDocument();
  });

  test("keeps a persisted POST result when reconciliation fails without moving the current question", async () => {
    const questions = [questionFixture(1), questionFixture(2)];
    const paper = paperFixture("job-grade", questions);
    const rubric = rubricFixture({
      id: "rubric-grade",
      paperJobId: paper.job_id,
      sourceDocumentId: "ms-grade",
      criteria: [
        criterionFixture("criterion-grade-1", "1", "M1"),
        criterionFixture("criterion-grade-2", "2", "M2"),
      ],
    });
    const gradeResult = gradeResultFixture("assessment-grade");
    let assessmentGets = 0;
    let resolveAssessment: ((value: Response) => void) | undefined;
    const assessmentRequest = new Promise<Response>((resolve) => {
      resolveAssessment = resolve;
    });
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(String(input));
      const url = new URL(request.url);
      if (url.pathname === "/api/v1/grading/papers") {
        return response([paperSummaryFixture(paper.job_id, questions.length)]);
      }
      if (url.pathname === "/api/v1/corpus/documents") {
        return response([sourceFixture("ms-grade")]);
      }
      if (url.pathname === `/api/v1/papers/jobs/${paper.job_id}`) return response(paper);
      if (url.pathname === "/api/v1/grading/rubrics") return response([rubric]);
      if (url.pathname === `/api/v1/grading/rubrics/${rubric.id}`) return response(rubric);
      if (url.pathname.endsWith("/assessments")) {
        assessmentGets += 1;
        if (assessmentGets === 1) return response([]);
        return new Response(JSON.stringify({ detail: "assessment refresh unavailable" }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.pathname.endsWith("/questions/1/assess")) return assessmentRequest;
      if (url.pathname.endsWith("/overview")) return response({});
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);

    const user = userEvent.setup();
    render(<Grading subject={subject} onCreated={vi.fn().mockResolvedValue(undefined)} />);
    await user.click(await screen.findByRole("button", { name: "开始逐题判分" }));
    await user.click(screen.getByRole("button", { name: "生成判分结果" }));
    const questionOne = screen.getByRole("button", { name: /Q1/ });
    const questionTwo = screen.getByRole("button", { name: /Q2/ });
    expect(questionTwo).toBeDisabled();
    await user.click(questionTwo);
    expect(questionOne).toHaveClass("active");
    expect(questionTwo).not.toHaveClass("active");

    await act(async () => {
      resolveAssessment?.(await response(gradeResult));
      await assessmentRequest;
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "评分已生成，但最新结果列表刷新失败",
    );
    expect(questionOne).toHaveClass("active");
    await user.click(questionTwo);
    expect(questionTwo).toHaveClass("active");
    await user.click(questionOne);
    expect(await screen.findByText("等待人工复核")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "生成判分结果" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新判分" })).toBeInTheDocument();
  });

  test("renders formulas and image artifacts throughout a completed grading report", async () => {
    const criterion = {
      id: "criterion-1",
      question_number: "1",
      subpart: "",
      criterion_id: "M1",
      scoring_mode: "point_based",
      mark_type: "M1",
      max_marks: 1,
      description: String.raw`Award for \(x = 1\).`,
      dependencies: [],
      alternatives: [],
      accuracy_requirement: null,
      units: [],
      follow_through_policy: null,
      source_page: 1,
      source_excerpt: String.raw`\(x = 1\)`,
      confidence: 1,
      review_status: "accepted",
    };
    const rubric = {
      id: "rubric-1",
      subject_id: subject.id,
      paper_job_id: "job-1",
      source_document_id: "ms-1",
      version_number: 1,
      status: "confirmed",
      identity: {},
      parser_model: "test-model",
      parser_version: "test",
      warnings: [],
      created_at: "2026-08-05T00:00:00Z",
      updated_at: "2026-08-05T00:00:00Z",
      confirmed_at: "2026-08-05T00:00:00Z",
      criteria: [
        criterion,
        { ...criterion, id: "criterion-2", question_number: "2", criterion_id: "M2" },
      ],
    };
    const question = {
      position: 1,
      number: "1",
      question_markdown: String.raw`Solve \(x + 1 = 2\).`,
      answer_markdown: String.raw`Therefore, \(x = 1\).`,
      diagrams: [],
      images: [{
        artifact_id: null,
        answer_anchor: null,
        answer_order: null,
        title: "Generated working graph",
        caption: String.raw`The intercept is \(x = 1\).`,
        content_url: "/api/v1/papers/jobs/job-1/images/graph.png",
        generated: true,
        height: 512,
        media_type: "image/png",
        tool_name: "image_generate",
        width: 768,
      }],
      citations: [],
      knowledge_points: [],
      confidence: 0.9,
      grounded: true,
      warnings: [],
      attempts: 1,
      source_pages: [1],
      source_warnings: [],
      answer_requirements: [],
      agent_steps: [],
      status: "completed",
      total_marks: 1,
      error: null,
    };
    const questionTwo = {
      ...question,
      position: 2,
      number: "2",
      question_markdown: "Show the next step.",
      answer_markdown: "A complete second answer.",
      images: [],
    };
    const questionThree = {
      ...questionTwo,
      position: 3,
      number: "3",
      question_markdown: "Explain the conclusion.",
      answer_markdown: "A complete third answer.",
    };
    const result = {
      assessment_id: "assessment-1",
      subject_code: subject.subject_code,
      question_ref: "paper-1:Q1",
      total_awarded: 1,
      total_available: 1,
      confidence: 0.95,
      status: "pending_review",
      rubric_awards: [{
        criterion_id: "M1",
        description: String.raw`Award for \(x = 1\).`,
        mark_type: "M1",
        max_marks: 1,
        awarded: 1,
        student_evidence: String.raw`The answer states \(x = 1\).`,
        rationale: String.raw`Substitution gives \(1 + 1 = 2\). ![Substitution diagram](https://example.com/substitution.png)`,
        confidence: 0.95,
        source_ref: "mark-scheme.pdf#page=1",
        knowledge_codes: [],
        error_types: [],
        improvement_suggestion: String.raw`Keep the equality \(x = 1\) explicit.`,
      }],
      symbolic_checks: [],
      citations: [],
      warnings: [],
      improvement_suggestions: [String.raw`Keep the equality \(x = 1\) explicit.`],
      manual_review_required: true,
    };
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input instanceof Request ? input.url : input));
      if (url.pathname === "/api/v1/grading/papers") {
        return response([{
          job_id: "job-1",
          filename: "paper.pdf",
          unit_code: "P2",
          status: "completed",
          total_questions: 3,
          completed_questions: 3,
          failed_questions: 0,
          updated_at: "2026-08-05T00:00:00Z",
        }]);
      }
      if (url.pathname === "/api/v1/corpus/documents") {
        expect(url.searchParams.get("status")).toBeNull();
        return response([{
          id: "ms-1",
          filename: "mark-scheme.pdf",
          source_type: "mark_scheme",
          source_role: "assessment_context",
          authority_tier: "official",
          status: "converted",
          checksum: "abc",
          knowledge_base_id: null,
          license_confirmed: false,
          page_count: 4,
          error: null,
        }]);
      }
      if (url.pathname === "/api/v1/papers/jobs/job-1") {
        return response({
          job_id: "job-1",
          filename: "paper.pdf",
          subject_pack_id: subject.id,
          subject_code: subject.subject_code,
          knowledge_base_version_ids: [],
          graph_version_id: null,
          unit_code: "P2",
          status: "completed",
          stage: "completed",
          total_pages: 1,
          parsed_pages: 1,
          total_questions: 3,
          completed_questions: 3,
          failed_questions: 0,
          created_at: "2026-08-05T00:00:00Z",
          updated_at: "2026-08-05T00:00:00Z",
          chunks: [],
          questions: [question, questionTwo, questionThree],
          error: null,
        });
      }
      if (url.pathname === "/api/v1/grading/rubrics") return response([rubric]);
      if (url.pathname === "/api/v1/grading/rubrics/rubric-1") return response(rubric);
      if (url.pathname === "/api/v1/grading/papers/job-1/assessments") {
        const oldResult = { ...result, assessment_id: "assessment-old", total_awarded: 0 };
        return response([
          {
            id: "assessment-old",
            paper_job_id: "job-1",
            question_position: 1,
            rubric_set_id: "rubric-old",
            status: "pending_review",
            result: oldResult,
            created_at: "2026-08-04T00:00:00Z",
          },
          {
            id: "assessment-1",
            paper_job_id: "job-1",
            question_position: 1,
            rubric_set_id: "rubric-1",
            status: "pending_review",
            result,
            created_at: "2026-08-05T00:00:00Z",
          },
        ]);
      }
      if (url.pathname.endsWith("/questions/2/assess")) {
        return Promise.resolve(new Response(JSON.stringify({ detail: "模型不可用" }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        }));
      }
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);

    const user = userEvent.setup();
    const { container } = render(<Grading subject={subject} onCreated={vi.fn()} />);

    await user.click(await screen.findByRole("button", { name: "开始逐题判分" }));
    await waitFor(() => expect(
      screen.getByRole("heading", { name: "核对判分结果" }),
    ).toHaveFocus());
    await user.click(screen.getByRole("button", { name: "返回材料" }));
    await waitFor(() => expect(
      screen.getByRole("heading", { name: "评分材料" }),
    ).toHaveFocus());
    await user.click(screen.getByRole("button", { name: "开始逐题判分" }));
    await waitFor(() => expect(
      screen.getByRole("heading", { name: "核对判分结果" }),
    ).toHaveFocus());
    expect(await screen.findByText("等待人工复核")).toBeInTheDocument();
    expect(container.querySelector(".score-hero strong")).toHaveTextContent("1");
    const q2Button = screen.getByRole("button", { name: /Q2/ });
    await user.click(q2Button);
    expect(q2Button).toHaveAttribute("aria-current", "true");
    expect(q2Button).toHaveAttribute("aria-controls", "grading-question-report");
    await waitFor(() => expect(
      screen.getByRole("heading", { name: "开始本题判分" }),
    ).toHaveFocus());
    await user.click(screen.getByRole("button", { name: "生成判分结果" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("模型不可用");
    await user.click(screen.getByRole("button", { name: /Q3/ }));
    expect(screen.getByText(/没有匹配 Q3 的已接受得分点/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "生成判分结果" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /Q1/ }));
    expect(container.querySelectorAll(".katex").length).toBeGreaterThanOrEqual(6);
    expect(container.querySelector('img[alt="Generated working graph"]')).toHaveAttribute(
      "src",
      `/api/v1/papers/jobs/job-1/images/graph.png?subject=${subject.id}`,
    );
    expect(container.querySelector('img[alt="Substitution diagram"]')).toHaveAttribute(
      "src",
      "https://example.com/substitution.png",
    );
  });

  test("requires per-criterion review records before confirming a rubric", async () => {
    const criterion = {
      id: "criterion-1",
      question_number: "1",
      subpart: "whole",
      criterion_id: "1-B1",
      scoring_mode: "point_based",
      mark_type: "B1",
      max_marks: 1,
      description: "Original criterion.",
      dependencies: [],
      alternatives: [],
      accuracy_requirement: null,
      units: [],
      follow_through_policy: null,
      source_page: 1,
      source_excerpt: "Official B1 wording.",
      confidence: 1,
      review_status: "pending",
      reviewed_by: null,
      reviewed_at: null,
    };
    const rubric = {
      id: "rubric-1",
      subject_id: subject.id,
      paper_job_id: "job-1",
      source_document_id: "ms-1",
      version_number: 1,
      status: "draft",
      identity: {},
      parser_model: "test-model",
      parser_version: "test",
      warnings: [],
      created_at: "2026-08-05T00:00:00Z",
      updated_at: "2026-08-05T00:00:00Z",
      confirmed_at: null,
      confirmed_by: null,
      criteria: [criterion],
    };
    const paper = {
      job_id: "job-1",
      filename: "paper.pdf",
      subject_pack_id: subject.id,
      subject_code: subject.subject_code,
      knowledge_base_version_ids: [],
      graph_version_id: null,
      unit_code: "P2",
      status: "completed",
      stage: "completed",
      total_pages: 1,
      parsed_pages: 1,
      total_questions: 1,
      completed_questions: 1,
      failed_questions: 0,
      created_at: "2026-08-05T00:00:00Z",
      updated_at: "2026-08-05T00:00:00Z",
      chunks: [],
      questions: [{
        position: 1,
        number: "1",
        question_markdown: "Question",
        answer_markdown: "Answer",
        diagrams: [],
        images: [],
        citations: [],
        knowledge_points: [],
        confidence: 1,
        grounded: true,
        warnings: [],
        attempts: 1,
        source_pages: [1],
        source_warnings: [],
        answer_requirements: [],
        agent_steps: [],
        status: "completed",
        total_marks: 1,
        error: null,
      }],
      error: null,
    };
    const reviewBodies: unknown[] = [];
    const confirmBodies: unknown[] = [];
    const paths: string[] = [];
    let releaseReview: (() => void) | undefined;
    const reviewGate = new Promise<void>((resolve) => {
      releaseReview = resolve;
    });
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(String(input));
      const url = new URL(request.url);
      paths.push(url.pathname);
      if (url.pathname === "/api/v1/grading/papers") {
        return response([{
          job_id: "job-1",
          filename: "paper.pdf",
          unit_code: "P2",
          status: "completed",
          total_questions: 1,
          completed_questions: 1,
          failed_questions: 0,
          updated_at: "2026-08-05T00:00:00Z",
        }]);
      }
      if (url.pathname === "/api/v1/corpus/documents") {
        return response([{
          id: "ms-1",
          filename: "mark-scheme.pdf",
          source_type: "mark_scheme",
          source_role: "assessment_only",
          authority_tier: "official",
          status: "converted",
          checksum: "abc",
          object_key: "corpus-sources/ms.pdf",
          knowledge_base_id: null,
          license_confirmed: false,
          page_count: 1,
          error: null,
        }]);
      }
      if (url.pathname === "/api/v1/papers/jobs/job-1") return response(paper);
      if (url.pathname === "/api/v1/grading/rubrics" && request.method === "GET") {
        return response([rubric]);
      }
      if (url.pathname === "/api/v1/grading/rubrics/rubric-1" && request.method === "GET") {
        return response(rubric);
      }
      if (url.pathname === "/api/v1/grading/papers/job-1/assessments") return response([]);
      if (url.pathname.endsWith("/criteria/criterion-1/review")) {
        reviewBodies.push(await request.clone().json());
        await reviewGate;
        Object.assign(criterion, {
          description: "Edited criterion.",
          review_status: "accepted",
          reviewed_by: "Teacher",
          reviewed_at: "2026-08-05T01:00:00Z",
        });
        return response({
          ...rubric,
          criteria: [{
            ...criterion,
            description: "Edited criterion.",
            review_status: "accepted",
            reviewed_by: "Teacher",
            reviewed_at: "2026-08-05T01:00:00Z",
          }],
        });
      }
      if (url.pathname.endsWith("/rubrics/rubric-1/confirm")) {
        confirmBodies.push(await request.clone().json());
        Object.assign(rubric, {
          status: "confirmed",
          confirmed_at: "2026-08-05T01:01:00Z",
          confirmed_by: "Teacher",
        });
        return response({
          ...rubric,
          status: "confirmed",
          confirmed_at: "2026-08-05T01:01:00Z",
          confirmed_by: "Teacher",
          criteria: [{
            ...criterion,
            description: "Edited criterion.",
            review_status: "accepted",
            reviewed_by: "Teacher",
            reviewed_at: "2026-08-05T01:00:00Z",
          }],
        });
      }
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);

    const user = userEvent.setup();
    render(<Grading subject={subject} onCreated={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "审核评分标准" }));
    await user.type(screen.getByPlaceholderText("填写教师或复核人名称"), "Teacher");
    const description = screen.getByLabelText("判分描述");
    await user.clear(description);
    await user.type(description, "Edited criterion.");
    await user.click(screen.getByRole("button", { name: /保存修改并保留 Q1 · 1-B1/ }));
    await waitFor(() => expect(reviewBodies).toHaveLength(1));
    const journey = document.querySelector<HTMLElement>('nav[aria-label="评分流程"]');
    expect(journey).not.toBeNull();
    for (const navigationButton of journey!.querySelectorAll("button")) {
      expect(navigationButton).toBeDisabled();
    }
    expect(screen.getByRole("button", { name: "关闭评分标准审核" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "关闭" })).toBeDisabled();
    await act(async () => {
      releaseReview?.();
      await reviewGate;
    });
    await waitFor(() => expect(
      screen.getByRole("button", { name: "确认规则并开始评分" }),
    ).toBeEnabled());

    expect(reviewBodies).toHaveLength(1);
    expect(reviewBodies[0]).toMatchObject({
      review_status: "accepted",
      reviewer: "Teacher",
      updates: { description: "Edited criterion.", max_marks: 1 },
    });
    expect(paths.some((path) => path.endsWith("/review-all"))).toBe(false);
    await user.click(screen.getByRole("button", { name: "确认规则并开始评分" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "开始本题判分" })).toBeInTheDocument());
    expect(confirmBodies).toEqual([{ reviewer: "Teacher" }]);
  });

  test("caps visible pending batches at 200 and explains how to continue", async () => {
    const criteria = Array.from({ length: 201 }, (_, index) =>
      criterionFixture(`criterion-limit-${index}`, "1", `M${index + 1}`));
    const { aiBodies, batchBodies } = installReviewScenario(criteria);
    const user = userEvent.setup();
    render(<Grading subject={subject} onCreated={vi.fn()} />);

    await user.click(await screen.findByRole("button", { name: "审核评分标准" }));
    await user.click(screen.getByRole("checkbox", { name: "选择当前筛选下待处理规则" }));
    expect(screen.getByText("200 / 200 已选择")).toBeInTheDocument();
    expect(screen.getByText(/当前筛选有 201 条可批量处理的规则；单次最多处理 200 条/)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "选择 Q1 M200" })).toBeEnabled();
    expect(screen.getByRole("checkbox", { name: "选择 Q1 M201" })).toBeDisabled();

    await user.type(screen.getByPlaceholderText("填写教师或复核人名称"), "Teacher");

    await user.click(screen.getByRole("button", { name: "AI 检查已选规则" }));
    await waitFor(() => expect(aiBodies).toHaveLength(1));
    expect(aiBodies[0].criterion_ids).toHaveLength(200);
    expect(aiBodies[0].criterion_ids).not.toContain("criterion-limit-200");

    await user.click(screen.getByRole("button", { name: "保留所选" }));
    await waitFor(() => expect(batchBodies).toHaveLength(1));
    expect(batchBodies[0].decisions).toHaveLength(200);
  }, 15_000);

  test("scopes selection to the current filter and sends one atomic batch request", async () => {
    const { batchBodies } = installReviewScenario([
      criterionFixture("criterion-q1", "1", "B1"),
      criterionFixture("criterion-q2", "2", "M1"),
    ]);
    const user = userEvent.setup();
    render(<Grading subject={subject} onCreated={vi.fn()} />);

    await user.click(await screen.findByRole("button", { name: "审核评分标准" }));
    const questionNav = screen.getByRole("navigation", { name: "得分点题目导航" });
    await user.click(within(questionNav).getByRole("button", { name: /^Q1\b/ }));
    await user.click(screen.getByRole("checkbox", { name: "选择当前筛选下待处理规则" }));
    expect(screen.getByText("1 / 1 已选择")).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText("填写教师或复核人名称"), "Teacher");
    await user.click(screen.getByRole("button", { name: "保留所选" }));

    await waitFor(() => expect(batchBodies).toHaveLength(1));
    expect(batchBodies[0]).toEqual({
      reviewer: "Teacher",
      decisions: [{
        criterion_id: "criterion-q1",
        review_status: "accepted",
        note: null,
      }],
    });
  });

  test("keeps AI review advisory until a named mixed-decision confirmation is submitted", async () => {
    const { aiBodies, batchBodies } = installReviewScenario([
      criterionFixture("criterion-ai-1", "1", "B1"),
      criterionFixture("criterion-ai-2", "2", "M1"),
      criterionFixture("criterion-ai-3", "3", "A1"),
    ]);
    const user = userEvent.setup();
    render(<Grading subject={subject} onCreated={vi.fn()} />);

    await user.click(await screen.findByRole("button", { name: "审核评分标准" }));
    const questionNav = screen.getByRole("navigation", { name: "得分点题目导航" });
    await user.click(within(questionNav).getByRole("button", { name: /^全部题目\b/ }));
    await user.type(screen.getByPlaceholderText("填写教师或复核人名称"), "Teacher");
    await user.click(screen.getByRole("button", { name: "AI 检查待处理规则" }));
    await waitFor(() => expect(aiBodies).toEqual([{
      criterion_ids: ["criterion-ai-1", "criterion-ai-2", "criterion-ai-3"],
    }]));

    const acceptAdvice = await screen.findByText("AI rationale for B1");
    const advisoryCard = acceptAdvice.closest("article");
    expect(advisoryCard).toHaveTextContent("待处理");
    expect(advisoryCard).toHaveTextContent("AI 审核批注");
    expect(advisoryCard).toHaveTextContent("建议保留");
    expect(screen.getByRole("button", { name: "确认规则并开始评分" })).toBeDisabled();
    const reviseAdvice = screen.getByText("AI rationale for A1").closest("article");
    expect(reviseAdvice).toHaveTextContent("待处理");
    expect(reviseAdvice).toHaveTextContent("建议修改");

    await user.click(screen.getByRole("button", { name: "应用 AI 检查" }));
    expect(screen.getByRole("group", { name: "确认应用 AI 检查结果" })).toHaveTextContent(
      "保留 1 条、排除 1 条",
    );
    expect(screen.getByRole("group", { name: "确认应用 AI 检查结果" })).toHaveTextContent(
      "另有 1 条“建议修改”保持待处理",
    );
    expect(batchBodies).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "确认并保存" }));

    await waitFor(() => expect(batchBodies).toHaveLength(1));
    expect(batchBodies[0].decisions).toEqual([
      expect.objectContaining({
        criterion_id: "criterion-ai-1",
        review_status: "accepted",
      }),
      expect.objectContaining({
        criterion_id: "criterion-ai-2",
        review_status: "rejected",
      }),
    ]);
    expect(batchBodies[0].decisions[0]).toHaveProperty(
      "expected_criterion_fingerprint",
      "1".padStart(64, "0"),
    );
    expect(batchBodies[0].decisions[1]).toHaveProperty(
      "expected_criterion_fingerprint",
      "2".padStart(64, "0"),
    );
  });

  test("distinguishes partial and complete whole-paper overviews on the diagnostic track", () => {
    const partial: GradingOverviewResponse = {
      paper_job_id: "job-overview",
      rubric_set_id: "rubric-overview",
      total_awarded: 3,
      total_available: 8,
      percentage: 37.5,
      completed_questions: 1,
      total_questions: 2,
      pending_review_count: 1,
      confirmed_count: 0,
      overridden_count: 0,
      incomplete: true,
      overall_suggestion: "Complete Q2 before treating this as a final result.",
      common_error_types: ["algebra"],
      questions: [
        {
          position: 1,
          question_number: "1",
          status: "pending_review",
          awarded: 3,
          available: 5,
          confidence: 0.8,
          error_types: ["algebra"],
          suggestions: ["Check the sign in the final line."],
        },
        {
          position: 2,
          question_number: "2",
          status: "unassessed",
          awarded: null,
          available: 3,
          confidence: null,
          error_types: [],
          suggestions: [],
        },
      ],
    };
    const complete: GradingOverviewResponse = {
      ...partial,
      total_awarded: 6,
      percentage: 75,
      completed_questions: 2,
      pending_review_count: 0,
      confirmed_count: 2,
      incomplete: false,
      overall_suggestion: "Review algebra signs, then preserve the complete reasoning used in Q2.",
      questions: partial.questions.map((question) => ({
        ...question,
        status: "confirmed" as const,
        awarded: 3,
        confidence: 0.9,
      })),
    };
    const { rerender } = render(
      <GradingOverview
        error={null}
        loading={false}
        onBack={vi.fn()}
        onRefresh={vi.fn()}
        overview={partial}
      />,
    );

    expect(screen.getByText("这是部分结果，不是最终整卷结论")).toBeInTheDocument();
    expect(screen.getByText("仍有 1 题未评分；当前分数与建议会随后续评分更新。")).toBeInTheDocument();
    expect(screen.getByText("返回逐题判分，为本题生成判分结果。")).toBeInTheDocument();

    rerender(
      <GradingOverview
        error={null}
        loading={false}
        onBack={vi.fn()}
        onRefresh={vi.fn()}
        overview={complete}
      />,
    );
    expect(screen.getByText("全部题目已有评分结果")).toBeInTheDocument();
    expect(screen.queryByText("这是部分结果，不是最终整卷结论")).not.toBeInTheDocument();
    expect(screen.getByText("整卷总分")).toBeInTheDocument();
  });

  test("announces a completed grading request and focuses its report heading", async () => {
    const paper = paperFixture("job-announcement");
    const rubric = rubricFixture({
      id: "rubric-announcement",
      paperJobId: paper.job_id,
      criteria: [criterionFixture("criterion-announcement", "1", "M1")],
    });
    const result = gradeResultFixture("assessment-announcement");
    let resolveAssessment: ((value: GradeResult | undefined) => void) | undefined;
    const assessmentRequest = new Promise<GradeResult | undefined>((resolve) => {
      resolveAssessment = resolve;
    });
    const onAssessQuestion = vi.fn(() => assessmentRequest);
    const commonProps = {
      busy: null,
      error: null,
      onAssessQuestion,
      onBack: vi.fn(),
      onViewRubric: vi.fn(),
      onOverview: vi.fn(),
      onSelectPosition: vi.fn(),
      paper,
      rubric,
      selectedPosition: 1,
    };
    const { rerender } = render(
      <GradingQuestionStage {...commonProps} assessments={[]} subjectId="test-subject" />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "生成判分结果" }));

    const assessment: PaperAssessment = {
      created_at: "2026-08-05T03:00:00Z",
      id: result.assessment_id,
      paper_job_id: paper.job_id,
      question_position: 1,
      result,
      rubric_set_id: rubric.id,
      status: "pending_review",
    };
    await act(async () => {
      resolveAssessment?.(result);
      rerender(<GradingQuestionStage {...commonProps} assessments={[assessment]} subjectId="test-subject" />);
      await assessmentRequest;
    });

    expect(screen.getByRole("status")).toHaveTextContent(
      "Q1 判分结果已生成，得分 1 / 1。",
    );
    await waitFor(() => expect(
      screen.getByRole("heading", { name: "Q1 判分结果" }),
    ).toHaveFocus());
  });

  test("preserves dirty criterion fields across unrelated refreshes and reconciles after save", async () => {
    const criterion = criterionFixture("criterion-draft", "1", "B1");
    const onReview = vi.fn(async () => true);
    const user = userEvent.setup();
    const { rerender } = render(
      <RubricCriterionEditor
        criterion={criterion}
        disabled={false}
        onReview={onReview}
        onSelectedChange={vi.fn()}
        selectable
        selected={false}
      />,
    );

    expect(screen.getByRole("group", { name: "编辑 Q1 · B1 得分点" })).toBeInTheDocument();
    const description = screen.getByLabelText("判分描述");
    await user.clear(description);
    await user.type(description, "Unsaved teacher wording");
    await user.type(screen.getByLabelText("审核说明"), "Keep this note");

    const refreshed = {
      ...criterion,
      ai_review: {
        criterion_fingerprint: "a".repeat(64),
        recommendation: "revise" as const,
        confidence: 0.82,
        rationale: "Unrelated AI refresh",
        suggested_updates: null,
        model: "review-model",
        reviewed_at: "2026-08-05T02:00:00Z",
      },
    };
    rerender(
      <RubricCriterionEditor
        criterion={refreshed}
        disabled={false}
        onReview={onReview}
        onSelectedChange={vi.fn()}
        selectable
        selected={false}
      />,
    );

    expect(screen.getByLabelText("判分描述")).toHaveValue("Unsaved teacher wording");
    expect(screen.getByLabelText("审核说明")).toHaveValue("Keep this note");
    await user.click(screen.getByRole("button", { name: "保存修改并保留 Q1 · B1" }));
    expect(onReview).toHaveBeenCalledWith(
      "criterion-draft",
      "accepted",
      "Keep this note",
      expect.objectContaining({ description: "Unsaved teacher wording" }),
    );

    rerender(
      <RubricCriterionEditor
        criterion={{
          ...refreshed,
          description: "Saved canonical wording",
          review_status: "accepted",
          reviewed_by: "Teacher",
          reviewed_at: "2026-08-05T02:05:00Z",
        }}
        disabled={false}
        onReview={onReview}
        onSelectedChange={vi.fn()}
        selectable={false}
        selected={false}
      />,
    );
    await waitFor(() => expect(screen.getByLabelText("判分描述")).toHaveValue("Saved canonical wording"));
    expect(screen.getByLabelText("审核说明")).toHaveValue("");
  });

  test("distinguishes an overview request failure from a successful empty result and retries", async () => {
    const onRefresh = vi.fn(async () => undefined);
    const user = userEvent.setup();
    const { rerender } = render(
      <GradingOverview
        error="网络连接中断"
        loading={false}
        onBack={vi.fn()}
        onRefresh={onRefresh}
        overview={null}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("整卷总览加载失败：网络连接中断");
    await user.click(screen.getByRole("button", { name: "重试加载总览" }));
    expect(onRefresh).toHaveBeenCalledOnce();

    rerender(
      <GradingOverview
        error={null}
        loading={false}
        onBack={vi.fn()}
        onRefresh={onRefresh}
        overview={{
          paper_job_id: "empty-paper",
          rubric_set_id: "empty-rubric",
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
        }}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("总览已加载，但当前试卷没有可评分题目");
    expect(screen.queryByText(/加载失败/)).not.toBeInTheDocument();
  });
});
