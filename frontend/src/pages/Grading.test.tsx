import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import type { SubjectPack } from "../types";
import { Grading } from "./Grading";

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

function response(payload: unknown) {
  return Promise.resolve(new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  }));
}

afterEach(() => {
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

describe("Grading", () => {
  test("explains the independent grading workflow when no paper records exist", async () => {
    vi.stubGlobal("fetch", vi.fn(() => response([])));
    render(<Grading subject={subject} onCreated={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "自动评分工作台" })).toBeInTheDocument();
    expect(screen.getByText("已完成作答")).toBeInTheDocument();
    expect(screen.getByText("官方 Mark Scheme")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("option", { name: "暂无可评分试卷" })).toBeInTheDocument());
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

    await waitFor(() => expect(screen.getByText("paper.pdf · 1/1 题")).toBeInTheDocument());
    expect(await screen.findByRole("option", { name: "mark-scheme.pdf · indexed" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("所选答卷内容")).toHaveTextContent("Q1答案已保存"));
    expect(screen.queryByPlaceholderText("粘贴学生作答内容")).not.toBeInTheDocument();
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
    const selector = await screen.findByLabelText("选择作答记录");
    await waitFor(() => expect(requestedA).toBe(true));
    await user.selectOptions(selector, "job-b");
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

    await user.click(await screen.findByRole("button", { name: "查看已解析得分点" }));
    expect(screen.getByRole("heading", { name: "核对解析出的得分点" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "上一步" }));
    expect(screen.getByRole("heading", { name: "先确认本次评分使用的两份材料" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "查看已解析得分点" }));
    await user.click(screen.getByRole("button", { name: "进入逐题评分建议" }));
    expect(await screen.findByText("等待人工复核")).toBeInTheDocument();
    expect(container.querySelector(".score-hero strong")).toHaveTextContent("1");
    await user.click(screen.getByRole("button", { name: /Q2/ }));
    await user.click(screen.getByRole("button", { name: "生成评分建议" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("模型不可用");
    await user.click(screen.getByRole("button", { name: /Q3/ }));
    expect(screen.getByText(/没有匹配 Q3 的已接受得分点/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "生成评分建议" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /Q1/ }));
    await user.click(screen.getByRole("button", { name: "返回得分点" }));
    expect(screen.getByRole("heading", { name: "核对解析出的得分点" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "进入逐题评分建议" }));
    expect(container.querySelectorAll(".katex").length).toBeGreaterThanOrEqual(6);
    expect(screen.getByRole("img", { name: "Generated working graph" })).toHaveAttribute(
      "src",
      "/api/v1/papers/jobs/job-1/images/graph.png",
    );
    expect(screen.getByRole("img", { name: "Substitution diagram" })).toHaveAttribute(
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
    await user.click(await screen.findByRole("button", { name: "查看已解析得分点" }));
    await user.type(screen.getByPlaceholderText("填写教师或复核人名称"), "Teacher");
    const description = screen.getByLabelText("判分描述");
    await user.clear(description);
    await user.type(description, "Edited criterion.");
    await user.click(screen.getByRole("button", { name: "保存修改并接受" }));
    await waitFor(() => expect(
      screen.getByRole("button", { name: "确认已审核规则并进入评分" }),
    ).toBeEnabled());

    expect(reviewBodies).toHaveLength(1);
    expect(reviewBodies[0]).toMatchObject({
      review_status: "accepted",
      reviewer: "Teacher",
      updates: { description: "Edited criterion.", max_marks: 1 },
    });
    expect(paths.some((path) => path.endsWith("/review-all"))).toBe(false);
    await user.click(screen.getByRole("button", { name: "确认已审核规则并进入评分" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "生成并复核评分建议" })).toBeInTheDocument());
    expect(confirmBodies).toEqual([{ reviewer: "Teacher" }]);
  });
});
