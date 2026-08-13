import { expect, test } from "@playwright/test";

const infrastructure = {
  postgresql: true,
  qdrant: true,
  object_storage: true,
};

test("starts in subject management and switches theme in place", async ({
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
        active_graph_version_id: null,
        answering_enabled: true,
        answering_disabled_reason: null,
        capability_profile_id: "oxfordaqa-economics-9640",
        color: "#0F766E",
        generic_qa_enabled: true,
        icon: "chart-no-axes-combined",
        knowledge_bases: [],
        source_booklet_required: true,
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
  await page.route("**/api/v1/grading/reviews/all", (route) => route.fulfill({
    contentType: "application/json",
    body: "[]",
  }));

  await page.goto("/");

  const subjectToolbar = page.getByRole("form", { name: "科目搜索与筛选" });
  await expect(page.getByRole("heading", { name: "科目" })).toHaveCount(0);
  await expect(subjectToolbar).toBeVisible();
  await expect(subjectToolbar).toBeInViewport();
  const courseName = page.getByText("OxfordAQA International AS/A-level Economics (9640)");
  await expect(courseName).toBeVisible();
  await expect(courseName).toHaveCSS("text-overflow", "ellipsis");
  await courseName.hover();
  await expect(page.getByRole("tooltip")).toHaveText("OxfordAQA International AS/A-level Economics (9640)");
  await page.getByRole("button", { name: "删除 OxfordAQA International AS/A-level Economics (9640)" }).click();
  await expect(page.getByRole("alertdialog", { name: "确认删除科目" })).toBeVisible();
  await page.getByRole("button", { name: "取消" }).click();
  const sidebar = page.getByRole("complementary", { name: "应用侧边栏" });
  const navigation = page.getByRole("navigation", { name: "主导航" });
  const pageShell = page.locator(".app-page-shell");
  await expect(sidebar).toBeVisible();
  await expect(navigation).toBeVisible();
  await expect(sidebar.getByText("工作空间")).toHaveCount(0);
  const sidebarBox = await sidebar.boundingBox();
  const toolbarBox = await subjectToolbar.boundingBox();
  expect(sidebarBox?.x).toBeLessThan(toolbarBox?.x ?? 0);
  expect((toolbarBox?.x ?? 0) - ((sidebarBox?.x ?? 0) + (sidebarBox?.width ?? 0))).toBeLessThanOrEqual(32);
  expect(await pageShell.evaluate((node) => getComputedStyle(node).borderTopWidth)).toBe("0px");
  expect(await sidebar.evaluate((node) => getComputedStyle(node).backdropFilter)).toContain("blur");
  expect(await navigation.getByRole("menu").evaluate((node) => getComputedStyle(node).borderInlineEndWidth)).toBe("0px");

  const systemTheme = page.getByRole("radio", { name: "跟随系统" });
  const systemThemeLabel = page.getByText("跟随", { exact: true });
  const systemThemeBox = await systemThemeLabel.boundingBox();
  await systemThemeLabel.hover();
  const themeTooltip = page.getByRole("tooltip");
  await expect(themeTooltip).toHaveText("跟随系统");
  const themeTooltipBox = await themeTooltip.boundingBox();
  expect(themeTooltipBox?.width).toBeLessThan(160);
  expect(themeTooltipBox?.height).toBeLessThan(80);
  expect(await systemThemeLabel.boundingBox()).toEqual(systemThemeBox);
  await expect(systemTheme).toBeChecked();

  const darkTheme = page.getByRole("radio", { name: "深色主题" });
  await page.getByText("深色", { exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(darkTheme).toBeChecked();
});

test("keeps the 1024px application viewport free of page-level horizontal scrolling", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto("/");
  await expect(page.getByRole("complementary", { name: "应用侧边栏" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "主导航" })).toBeVisible();
  await expect(page.getByRole("form", { name: "科目搜索与筛选" })).toBeInViewport();

  const overflow = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));

  expect(overflow.document).toBeLessThanOrEqual(overflow.viewport);
  expect(overflow.body).toBeLessThanOrEqual(overflow.viewport);
});

test("shows rich grading selectors and manages Mark Schemes without leaving the page", async ({
  page,
}) => {
  await page.route("**/api/v1/**", (route) => {
    const url = new URL(route.request().url());
    const fulfill = (payload: unknown) => route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(payload),
    });
    if (url.pathname === "/api/v1/health") {
      return fulfill({
        status: "ok",
        subject_code: null,
        api_contract_version: "test",
        capabilities: ["grading_assessment_v1", "human_review_v1"],
        llm_model: "test",
        embedding_model: "test",
        rerank_model: "test",
        credentials: {},
        object_storage_backend: "local",
        infrastructure,
      });
    }
    if (url.pathname === "/api/v1/subjects/status") {
      return fulfill({
        infrastructure,
        subjects: [{
          id: "oxfordaqa-economics-9640",
          version: "1",
          digest: "test",
          subject_code: "9640",
          title: "OxfordAQA International AS/A-level Economics (9640)",
          board_name: "OxfordAQA International",
          active_graph_version_id: null,
          answering_enabled: true,
          answering_disabled_reason: null,
          capability_profile_id: "oxfordaqa-economics-9640",
          color: "#0F766E",
          generic_qa_enabled: true,
          icon: "chart-no-axes-combined",
          knowledge_bases: [],
          source_booklet_required: true,
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
      });
    }
    if (url.pathname === "/api/v1/grading/reviews/all") return fulfill([]);
    if (url.pathname === "/api/v1/grading/papers") {
      return fulfill([{
        job_id: "paper-ui",
        filename: "Economics-9640-U1-June-2026.pdf",
        unit_code: "U1",
        status: "completed",
        total_questions: 12,
        completed_questions: 12,
        failed_questions: 0,
        updated_at: "2026-08-11T00:00:00Z",
      }]);
    }
    if (url.pathname === "/api/v1/corpus/documents") {
      return fulfill([{
        id: "scheme-ui",
        filename: "Economics-9640-U1-June-2026-MS.pdf",
        source_type: "mark_scheme",
        source_role: "assessment_only",
        authority_tier: "official",
        status: "converted",
        checksum: "scheme-ui",
        object_key: "scheme-ui.pdf",
        knowledge_base_id: null,
        license_confirmed: true,
        page_count: 18,
        error: null,
      }]);
    }
    if (url.pathname === "/api/v1/papers/jobs/paper-ui") {
      return fulfill({
        job_id: "paper-ui",
        filename: "Economics-9640-U1-June-2026.pdf",
        subject_pack_id: "oxfordaqa-economics-9640",
        subject_code: "9640",
        knowledge_base_version_ids: [],
        graph_version_id: null,
        replaced_by_job_id: null,
        replacement_for_job_id: null,
        source_integrity_status: "verified",
        split_contract_version: null,
        split_source_digest: null,
        unit_code: "U1",
        status: "completed",
        stage: "completed",
        total_pages: 18,
        parsed_pages: 18,
        total_questions: 12,
        completed_questions: 12,
        failed_questions: 0,
        created_at: "2026-08-11T00:00:00Z",
        updated_at: "2026-08-11T00:00:00Z",
        chunks: [],
        questions: [],
        error: null,
      });
    }
    if (url.pathname === "/api/v1/grading/rubrics") return fulfill([]);
    if (url.pathname.endsWith("/assessments")) return fulfill([]);
    return fulfill([]);
  });

  await page.goto("/subjects/oxfordaqa-economics-9640/grading");

  const paperSelector = page.getByLabel("选择作答记录");
  const schemeSelector = page.getByLabel("选择 Mark Scheme");
  await expect(paperSelector).toContainText("Economics-9640-U1-June-2026.pdf");
  await expect(paperSelector).toContainText("U1 · 12/12 题 · 作答完整");
  await expect(schemeSelector).toContainText("官方标准 · 18 页 · 内容就绪");

  await expect(schemeSelector.getByRole("option", { name: /Economics-9640-U1-June-2026-MS.pdf/ })).toBeAttached();
  const schemeUpload = page.locator(".grading-scheme-upload");
  await expect(schemeUpload).toHaveCount(1);
  await expect(schemeUpload).not.toContainText("上传官方版本");
  await schemeUpload.hover();
  const uploadTooltip = page.getByRole("tooltip");
  await expect(uploadTooltip).toHaveText("上传官方版本");
  const uploadTooltipBox = await uploadTooltip.boundingBox();
  expect(uploadTooltipBox?.width).toBeLessThan(180);
  expect(uploadTooltipBox?.height).toBeLessThan(80);
  await page.mouse.move(0, 0);
  await expect(uploadTooltip).toBeHidden();
  await page.getByRole("button", { name: "管理标准" }).click();
  await expect(page.getByPlaceholder("搜索文件名、来源或状态")).toBeVisible();
  await expect(page.getByText("当前使用")).toBeVisible();
  await page.getByLabel("删除 Economics-9640-U1-June-2026-MS.pdf").click();
  const confirmDialog = page.getByRole("alertdialog", { name: "确认删除 Mark Scheme" });
  await expect(confirmDialog).toBeVisible();
  await confirmDialog.getByRole("button", { name: "取消" }).click();

  const overflow = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
  }));
  expect(overflow.document).toBeLessThanOrEqual(overflow.viewport);
});

test("opens the full sidebar navigation without horizontal scrolling at 390px", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  await page.getByRole("button", { name: "打开主导航" }).click();
  const navigation = page.getByRole("navigation", { name: "主导航" });
  await expect(navigation.getByRole("menuitem")).toHaveCount(5);
  for (const label of ["科目", "试卷", "作答", "评分", "复核"]) {
    await expect(navigation.getByRole("menuitem", { name: label })).toBeInViewport();
  }

  const overflow = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));
  expect(overflow.document).toBeLessThanOrEqual(overflow.viewport);
  expect(overflow.body).toBeLessThanOrEqual(overflow.viewport);
});
