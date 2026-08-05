import { expect, test } from "@playwright/test";

const infrastructure = {
  postgresql: true,
  qdrant: true,
  object_storage: true,
};

test("starts without a default subject and switches subject and theme in place", async ({
  page,
}) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.route("**/api/v1/health", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({
      status: "ok",
      subject_code: null,
      api_contract_version: "test",
      capabilities: [
        "paper_jobs_v1",
        "task_events_v1",
        "answering_agent_v1",
        "knowledge_graph_v1",
        "grading_assessment_v1",
        "human_review_v1",
      ],
      llm_model: "test",
      embedding_model: "test",
      rerank_model: "test",
      credentials: {},
      object_storage_backend: "local",
      infrastructure,
    }),
  }));
  await page.route("**/api/v1/subjects/status", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({
      infrastructure,
      subjects: [{
        id: "oxfordaqa-economics-9640",
        version: "1",
        digest: "test",
        subject_code: "9640",
        title: "OxfordAQA International AS/A-level Economics (9640)",
        board_name: "OxfordAQA International",
        answering_enabled: true,
        answering_disabled_reason: null,
        units: [{ code: "U1", title: "Markets", strand: "Economics" }],
        vector_alias: "examtwin_9640_live",
        vector_index_ready: true,
        vector_points: 822,
        stats: {
          documents_total: 4,
          documents_by_type: { syllabus: 1, question_paper: 1, mark_scheme: 1 },
          documents_by_status: { converted: 4 },
          strict_pairs: 1,
          orphan_question_papers: 0,
          orphan_mark_schemes: 0,
          knowledge_points: 484,
          relations: 568,
          question_difficulty_rows: 0,
          pending_reviews: 0,
          exam_identity_incomplete: 0,
        },
      }],
    }),
  }));
  await page.route("**/api/v1/grading/reviews", (route) => route.fulfill({
    contentType: "application/json",
    body: "[]",
  }));

  await page.goto("/");

  const subject = page.getByLabel("科目上下文");
  await expect(subject).toHaveValue("");
  await subject.selectOption("oxfordaqa-economics-9640");
  await expect(page.locator(".header-context > span")).toHaveText("状态总览");
  await expect(page.locator(".header-context small")).toContainText("9640");

  await page.getByRole("button", { name: "深色主题" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("keeps the 1024px application viewport free of page-level horizontal scrolling", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto("/");
  await page.getByRole("button", { name: "状态总览" }).click();

  const overflow = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));

  expect(overflow.document).toBeLessThanOrEqual(overflow.viewport);
  expect(overflow.body).toBeLessThanOrEqual(overflow.viewport);
});
