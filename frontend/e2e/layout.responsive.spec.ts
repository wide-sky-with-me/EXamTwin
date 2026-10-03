import { expect, test, type Locator, type Page } from "@playwright/test";

const infrastructure = {
  postgresql: true,
  qdrant: true,
  object_storage: true,
};

const economicsPaperUnit = {
  id: "paper-u1",
  subject_id: "oxfordaqa-economics-9640",
  subject_code: "9640",
  pair_key: "9640:2026:JUN:U1",
  display_name: "Economics June U1",
  unit_code: "U1",
  exam_year: 2026,
  exam_session: "JUN",
  status: "active",
  documents: [],
  paper_job_count: 2,
  created_at: "2026-08-13T00:00:00Z",
  updated_at: "2026-08-13T00:10:00Z",
};

function paperJobFixture(jobId: string) {
  return {
    job_id: jobId,
    filename: jobId === "job-uploaded" ? "student-answer.pdf" : "Economics-9640-U1.pdf",
    display_name: null,
    answer_mode: jobId === "job-uploaded" ? "uploaded" : "generated",
    pair_key: economicsPaperUnit.pair_key,
    paper_unit_id: economicsPaperUnit.id,
    question_paper_document_id: null,
    source_booklet_document_id: null,
    source_booklet_checksum: null,
    source_booklet_filename: null,
    graph_version_id: null,
    unit_code: "U1",
    status: "completed",
    stage: "completed",
    total_pages: 1,
    parsed_pages: 1,
    total_questions: 0,
    completed_questions: 0,
    failed_questions: 0,
    source_integrity_status: "verified",
    split_contract_version: "paper-question-split-v6",
    split_source_digest: null,
    replacement_for_job_id: null,
    replaced_by_job_id: null,
    chunks: [],
    questions: [],
    error: null,
    created_at: "2026-08-13T00:00:00Z",
    updated_at: "2026-08-13T00:10:00Z",
  };
}

async function expectViewportSafePaperModal(
  page: Page,
  dialog: Locator,
  bottomContent?: Locator,
) {
  await expect(dialog).toBeVisible();
  const root = page.locator(".paper-domain-modal").filter({ has: dialog });
  await expect(root).toHaveCount(1);
  const modal = root.locator(".ant-modal").first();
  const container = root.locator(".ant-modal-container");
  const body = root.locator(".ant-modal-body");
  const close = root.locator(".ant-modal-close");
  let stableSamples = 0;
  let previousBox: { x: number; y: number; width: number; height: number } | null = null;
  await expect.poll(async () => {
    const currentBox = await modal.boundingBox();
    if (
      currentBox
      && previousBox
      && Math.abs(currentBox.x - previousBox.x) < 0.25
      && Math.abs(currentBox.y - previousBox.y) < 0.25
      && Math.abs(currentBox.width - previousBox.width) < 0.25
      && Math.abs(currentBox.height - previousBox.height) < 0.25
    ) {
      stableSamples += 1;
    } else {
      stableSamples = 0;
    }
    previousBox = currentBox;
    return stableSamples;
  }, { intervals: [50] }).toBeGreaterThanOrEqual(2);
  const viewport = page.viewportSize();
  const [modalBox, closeBox] = await Promise.all([
    modal.boundingBox(),
    close.boundingBox(),
  ]);

  expect(viewport).not.toBeNull();
  expect(modalBox).not.toBeNull();
  expect(closeBox).not.toBeNull();
  expect(modalBox!.x).toBeGreaterThanOrEqual(0);
  expect(modalBox!.y).toBeGreaterThanOrEqual(0);
  expect(modalBox!.x + modalBox!.width).toBeLessThanOrEqual(viewport!.width + 1);
  expect(modalBox!.y + modalBox!.height).toBeLessThanOrEqual(viewport!.height + 1);
  expect(closeBox!.y).toBeGreaterThanOrEqual(modalBox!.y);
  expect(closeBox!.y + closeBox!.height).toBeLessThanOrEqual(modalBox!.y + modalBox!.height);
  await expect(container).toHaveCSS("display", "flex");
  await expect(container).toHaveCSS("overflow", "hidden");
  await expect(body).toHaveCSS("overflow", "auto");
  await expect(close).toBeInViewport();

  if (bottomContent) {
    await body.evaluate((node) => {
      node.scrollTop = node.scrollHeight;
    });
    await expect(bottomContent).toBeVisible();
    await expect(bottomContent).toBeInViewport();
  }

  const overflow = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));
  expect(overflow.document).toBeLessThanOrEqual(overflow.viewport);
  expect(overflow.body).toBeLessThanOrEqual(overflow.viewport);
}

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
  await expect(page.getByRole("heading", { name: "科目" })).toBeVisible();
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
  const expectedToolbarInset = await page.evaluate(() => {
    const content = document.querySelector<HTMLElement>(".app-page-content");
    const card = document.querySelector<HTMLElement>(".catalog-toolbar-card");
    const cardBody = card?.querySelector<HTMLElement>(".ant-card-body");
    if (!content || !card || !cardBody) throw new Error("catalog shell is incomplete");
    return (
      Number.parseFloat(getComputedStyle(content).paddingLeft)
      + Number.parseFloat(getComputedStyle(card).borderLeftWidth)
      + Number.parseFloat(getComputedStyle(cardBody).paddingLeft)
    );
  });
  const actualToolbarInset = (toolbarBox?.x ?? 0) - ((sidebarBox?.x ?? 0) + (sidebarBox?.width ?? 0));
  expect(actualToolbarInset).toBeCloseTo(expectedToolbarInset, 1);
  expect(await pageShell.evaluate((node) => getComputedStyle(node).borderTopWidth)).toBe("0px");
  expect(await sidebar.evaluate((node) => getComputedStyle(node).backdropFilter)).toContain("blur");
  expect(await navigation.getByRole("menu").evaluate((node) => getComputedStyle(node).borderInlineEndWidth)).toBe("0px");

  const systemTheme = page.getByRole("radio", { name: "跟随系统" });
  const systemThemeLabel = sidebar.getByText("跟随", { exact: true });
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
  await sidebar.getByText("深色", { exact: true }).click();
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

test("keeps every paper-domain dialog reachable at desktop and mobile sizes", async ({ page }, testInfo) => {
  testInfo.setTimeout(120_000);
  let requestedAnswerMode = "";
  await page.routeWebSocket(
    /\/api\/v1\/papers\/jobs\/(job-ai|job-uploaded)\/events/,
    (socket) => {
      const jobId = new URL(socket.url()).pathname.split("/").at(-2)!;
      socket.send(JSON.stringify({
        type: "snapshot",
        topic: "paper_job",
        resource_id: jobId,
        data: paperJobFixture(jobId),
      }));
    },
  );
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
        capabilities: ["paper_jobs_v1"],
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
          title: "OxfordAQA Economics",
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
          stats: null,
        }],
      });
    }
    if (url.pathname === "/api/v1/grading/reviews/all") return fulfill([]);
    if (url.pathname === "/api/v1/subject-workspaces/oxfordaqa-economics-9640/paper-units/trash") {
      return fulfill({
        items: [{ ...economicsPaperUnit, id: "paper-trash", status: "deleted" }],
        total: 1,
        limit: 100,
        offset: 0,
        available_units: ["U1"],
        available_years: [2026],
        available_sessions: ["JUN"],
      });
    }
    if (url.pathname === "/api/v1/subject-workspaces/oxfordaqa-economics-9640/paper-units") {
      return fulfill({ items: [economicsPaperUnit], total: 1, limit: 12, offset: 0, available_units: ["U1"], available_years: [2026], available_sessions: ["JUN"] });
    }
    if (url.pathname === "/api/v1/subject-workspaces/oxfordaqa-economics-9640/paper-units/paper-u1") return fulfill(economicsPaperUnit);
    if (url.pathname === "/api/v1/subject-workspaces/oxfordaqa-economics-9640/documents") return fulfill([]);
    if (url.pathname === "/api/v1/papers/jobs") {
      requestedAnswerMode = url.searchParams.get("answer_mode") ?? "";
      const items = [
        {
          job_id: "job-ai",
          filename: "Economics-9640-U1.pdf",
          answer_mode: "generated",
          paper_unit_id: "paper-u1",
        },
        {
          job_id: "job-ai-secondary",
          filename: "Economics-9640-U1-secondary.pdf",
          answer_mode: "generated",
          paper_unit_id: "paper-u1",
        },
        {
          job_id: "job-uploaded",
          filename: "student-answer.pdf",
          answer_mode: "uploaded",
          paper_unit_id: "paper-u1",
        },
      ].filter((item) => !requestedAnswerMode || item.answer_mode === requestedAnswerMode)
        .map((item) => ({
          ...item,
          unit_code: "U1",
          status: "completed",
          stage: "completed",
          total_questions: 12,
          completed_questions: 12,
          failed_questions: 0,
          source_integrity_status: "verified",
          split_contract_version: "paper-question-split-v6",
          replacement_for_job_id: null,
          replaced_by_job_id: item.job_id === "job-ai" ? "job-uploaded" : null,
          created_at: "2026-08-13T00:00:00Z",
          updated_at: "2026-08-13T00:10:00Z",
        }));
      return fulfill({ items, total: items.length, limit: 10, offset: 0 });
    }
    if (url.pathname === "/api/v1/papers/jobs/job-ai" || url.pathname === "/api/v1/papers/jobs/job-uploaded") {
      return fulfill(paperJobFixture(url.pathname.split("/").at(-1)!));
    }
    if (url.pathname === "/api/v1/grading/papers") {
      return fulfill([{
        job_id: "job-uploaded",
        filename: "student-answer.pdf",
        display_name: null,
        paper_unit_id: economicsPaperUnit.id,
        question_paper_document_id: null,
        unit_code: "U1",
        status: "completed",
        total_questions: 0,
        completed_questions: 0,
        failed_questions: 0,
        updated_at: "2026-08-13T00:10:00Z",
      }]);
    }
    if (url.pathname === "/api/v1/corpus/documents") {
      return fulfill([{
        id: "scheme-ui",
        filename: "Economics-9640-U1-June-2026-MS.pdf",
        display_name: null,
        source_type: "mark_scheme",
        source_role: "assessment_only",
        authority_tier: "official",
        knowledge_base_id: null,
        license_confirmed: true,
        status: "converted",
        checksum: "scheme-ui",
        object_key: "scheme-ui.pdf",
        page_count: 18,
        error: null,
        pair_key: economicsPaperUnit.pair_key,
        unit_code: "U1",
        exam_year: 2026,
        exam_session: "JUN",
        identity_status: "complete",
        identity_error: null,
      }]);
    }
    if (url.pathname === "/api/v1/grading/rubrics") return fulfill([]);
    if (url.pathname.endsWith("/assessments")) return fulfill([]);
    return fulfill([]);
  });

  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto("/subjects/oxfordaqa-economics-9640/papers/paper-u1");
    if (viewport.width <= 1100) {
      const mainLayoutBox = await page.locator(".app-main-layout").boundingBox();
      const pageShellBox = await page.locator(".app-page-shell").boundingBox();
      expect(mainLayoutBox).not.toBeNull();
      expect(pageShellBox).not.toBeNull();
      expect(mainLayoutBox!.width).toBeGreaterThanOrEqual(viewport.width - 1);
      expect(pageShellBox!.width).toBeGreaterThan(viewport.width - 40);
    }

    const detailDialog = page.getByRole("dialog", { name: "试卷详情" });
    await expectViewportSafePaperModal(page, detailDialog, detailDialog.locator(".paper-detail-summary"));
    await detailDialog.getByRole("checkbox", { name: "同时规划备考投入和考试时间" }).check();
    await expect(detailDialog.getByRole("spinbutton", { name: "考试时长（分钟）" })).toHaveValue("105");
    await expectViewportSafePaperModal(page, detailDialog, detailDialog.getByRole("button", { name: "AI 自动作答" }));
    await detailDialog.getByRole("spinbutton", { name: "目标分数" }).scrollIntoViewIfNeeded();
    expect(await detailDialog.locator(".target-strategy-fields").evaluate((node) => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`paper-strategy-${viewport.width}.png`) });

    await detailDialog.getByRole("button", { name: "更多试卷操作" }).click();
    await page.getByRole("menuitem", { name: "导入外部答卷" }).click();
    const importDialog = page.getByRole("dialog", { name: "导入外部答卷" });
    await expectViewportSafePaperModal(
      page,
      importDialog,
      importDialog.getByRole("button", { name: "导入并解析" }),
    );

    await page.goto("/subjects/oxfordaqa-economics-9640/papers/paper-u1");
    await page.getByRole("dialog", { name: "试卷详情" })
      .getByRole("button", { name: "更多试卷操作" }).click();
    await page.getByRole("menuitem", { name: "编辑试卷" }).click();
    const editorDialog = page.getByRole("dialog", { name: "编辑试卷" });
    await expectViewportSafePaperModal(
      page,
      editorDialog,
      editorDialog.getByRole("button", { name: "保存试卷" }),
    );
    const questionPaperEditor = editorDialog.locator(".paper-editor-material-question_paper");
    await questionPaperEditor.locator('input[type="file"]').setInputFiles({
      name: "viewport-preview.md",
      mimeType: "text/markdown",
      buffer: Buffer.from("# Viewport preview\n\n".repeat(80)),
    });
    await questionPaperEditor.getByRole("button", { name: "预览" }).click();
    const previewDialog = page.getByRole("dialog", { name: /文件预览 · viewport-preview\.md/ });
    await expectViewportSafePaperModal(
      page,
      previewDialog,
      previewDialog.locator(".paper-local-preview-text"),
    );

    await page.goto("/subjects/oxfordaqa-economics-9640/papers");
    // Initial list loading is debounced: the toolbar can be briefly enabled
    // before loading starts. Wait for real list content, not that transient state.
    await expect(page.getByRole("button", { name: "查看试卷 Economics June U1" })).toBeVisible();
    await expect(page.locator(".paper-management-results")).toHaveAttribute("aria-busy", "false");
    await page.getByRole("button", { name: "打开试卷回收站" }).click();
    const trashDialog = page.getByRole("dialog", { name: /试卷回收站/ });
    await expectViewportSafePaperModal(
      page,
      trashDialog,
      trashDialog.getByRole("button", { name: "永久删除" }),
    );

    await page.goto("/subjects/oxfordaqa-economics-9640/papers/paper-u1/answers");
    if (viewport.width > 1100) {
      const navigation = page.getByRole("navigation", { name: "主导航" });
      await expect(navigation.getByRole("menuitem")).toHaveCount(3);
      await expect(navigation.getByRole("menuitem", { name: "评分" })).toHaveCount(0);
    } else {
      const navigation = page.getByRole("navigation", { name: "主导航" });
      await expect(navigation.getByRole("button")).toHaveCount(3);
      await expect(navigation.getByRole("button", { name: "评分" })).toHaveCount(0);
    }
    const answerRecords = page.getByRole("dialog", { name: /作答记录 · Economics June U1/ });
    await expectViewportSafePaperModal(
      page,
      answerRecords,
      answerRecords.locator(".paper-history-list > li").last(),
    );
    const embeddedHistory = answerRecords.locator(".paper-history-embedded");
    await expect(embeddedHistory).not.toHaveClass(/\bpanel\b/);
    await expect(embeddedHistory).toHaveCSS("border-top-width", "0px");
    await expect(embeddedHistory).toHaveCSS("box-shadow", "none");
    await answerRecords.locator(".ant-modal-body").evaluate((node) => {
      node.scrollTop = 0;
    });
    await answerRecords.getByRole("button", { name: "批量选择" }).click();
    const compactControls = embeddedHistory.locator(".paper-history-controls");
    const selectAllBox = await embeddedHistory.locator(".paper-history-select-all").boundingBox();
    const list = embeddedHistory.locator(".paper-history-list");
    const controlsBox = await compactControls.boundingBox();
    const listBox = await list.boundingBox();
    const firstRowBox = await list.locator(":scope > li").first().boundingBox();
    expect(controlsBox).not.toBeNull();
    expect(selectAllBox).not.toBeNull();
    expect(listBox).not.toBeNull();
    expect(firstRowBox).not.toBeNull();
    expect(controlsBox!.height).toBeLessThanOrEqual(viewport.width > 1100 ? 64 : 320);
    expect(selectAllBox!.y - (controlsBox!.y + controlsBox!.height)).toBeLessThanOrEqual(12);
    expect(listBox!.y - (selectAllBox!.y + selectAllBox!.height)).toBeLessThanOrEqual(2);
    expect(firstRowBox!.height).toBeLessThanOrEqual(viewport.width > 1100 ? 88 : 150);
    if (viewport.width > 1100) {
      const filterRows = await Promise.all([
        compactControls.locator(".ant-input-affix-wrapper").boundingBox(),
        compactControls.locator(".list-filter-select-trigger").nth(0).boundingBox(),
        compactControls.locator(".list-filter-select-trigger").nth(1).boundingBox(),
        compactControls.locator(".list-filter-select-trigger").nth(2).boundingBox(),
      ]);
      const filterTops = filterRows.map((box) => box!.y);
      expect(Math.max(...filterTops) - Math.min(...filterTops)).toBeLessThanOrEqual(2);
    }
    await expect(answerRecords.locator(".paper-history-mode.generated"))
      .toHaveText(["AI 作答", "AI 作答"]);
    await expect(answerRecords.locator(".paper-history-mode.uploaded")).toHaveText("外部答卷");
    const generatedRow = answerRecords.locator(".paper-history-list > li").filter({
      hasText: "Economics-9640-U1.pdf",
    });
    const uploadedRow = answerRecords.locator(".paper-history-list > li").filter({
      hasText: "student-answer.pdf",
    });
    const masterCheckbox = answerRecords.getByRole("checkbox", {
      name: "全选当前页可删除记录",
    });
    await expect(generatedRow.getByRole("checkbox")).toBeDisabled();
    await uploadedRow.getByRole("checkbox").click();
    await expect(masterCheckbox).toHaveJSProperty("indeterminate", true);
    await masterCheckbox.click();
    await expect(masterCheckbox).toBeChecked();
    await expect(uploadedRow.getByRole("checkbox")).toBeChecked();
    await expect(generatedRow.getByRole("checkbox")).not.toBeChecked();
    await answerRecords.getByRole("button", { name: "取消选择" }).click();

    await answerRecords.getByRole("combobox", { name: "按来源筛选" }).click();
    await page.locator(
      '.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option[title="外部答卷"]',
    ).click();
    await expect.poll(() => requestedAnswerMode).toBe("uploaded");
    await expect(answerRecords.locator(".paper-history-mode.generated")).toHaveCount(0);
    await expect(answerRecords.locator(".paper-history-mode.uploaded")).toHaveText("外部答卷");

    await answerRecords.getByRole("button", { name: "查看" }).click();
    const answerResult = page.getByRole("dialog", { name: /作答详情 · Economics June U1/ });
    await expectViewportSafePaperModal(
      page,
      answerResult,
      answerResult.getByRole("button", { name: "返回作答记录" }),
    );

    await page.goto("/subjects/oxfordaqa-economics-9640/papers/paper-u1/answers");
    const refreshedRecords = page.getByRole("dialog", { name: /作答记录 · Economics June U1/ });
    await refreshedRecords
      .locator("li", { hasText: "student-answer.pdf" })
      .getByRole("button", { name: "评分" })
      .click();
    await expect(page).toHaveURL(/\/papers\/paper-u1\/jobs\/job-uploaded\/grading$/);
    const gradingDialog = page.getByRole("dialog", { name: /试卷评分 · Economics June U1/ });
    await expectViewportSafePaperModal(
      page,
      gradingDialog,
      gradingDialog.locator(".grading-stage-actions button"),
    );
  }
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
    if (url.pathname === "/api/v1/subject-workspaces/oxfordaqa-economics-9640/paper-units") {
      return fulfill({ items: [economicsPaperUnit], total: 1, limit: 12, offset: 0, available_units: ["U1"], available_years: [2026], available_sessions: ["JUN"] });
    }
    if (url.pathname === "/api/v1/subject-workspaces/oxfordaqa-economics-9640/paper-units/paper-u1") return fulfill(economicsPaperUnit);
    if (url.pathname === "/api/v1/subject-workspaces/oxfordaqa-economics-9640/documents") return fulfill([]);
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

  await page.goto("/subjects/oxfordaqa-economics-9640/papers/paper-u1/jobs/paper-ui/grading");

  await expect(page.getByRole("heading", { name: "答案评分" })).toHaveCount(0);
  const gradingDialog = page.getByRole("dialog", { name: /试卷评分 · Economics June U1/ });
  await expect(gradingDialog).toBeVisible();
  const materialsStage = gradingDialog.locator(".grading-materials-stage");
  await expect(materialsStage).not.toHaveClass(/\bpanel\b/);
  await expect(materialsStage).toHaveCSS("border-top-width", "0px");
  await expect(materialsStage).toHaveCSS("box-shadow", "none");

  const paperSelector = page.getByLabel("选择作答记录");
  const schemeSelector = page.getByLabel("选择 Mark Scheme");
  const paperField = gradingDialog.locator(".ant-select").filter({ has: paperSelector });
  const schemeField = gradingDialog.locator(".ant-select").filter({ has: schemeSelector });
  await expect(paperField).toContainText("Economics-9640-U1-June-2026.pdf");
  await expect(paperSelector).toBeDisabled();
  await expect(gradingDialog.getByRole("button", { name: "上传答卷" })).toHaveCount(0);
  await expect(paperField).toContainText("U1 · 12/12 题 · 作答完整");
  await expect(schemeField).toContainText("官方标准 · 18 页 · 内容就绪");

  await schemeField.click();
  const schemeOption = page.locator(
    ".grading-material-select-popup:not(.ant-select-dropdown-hidden) .ant-select-item-option",
    { hasText: "Economics-9640-U1-June-2026-MS.pdf" },
  );
  await expect(schemeOption).toBeVisible();
  await expect(schemeOption).toContainText("官方标准 · 18 页 · 内容就绪");
  await schemeOption.click();
  await expect(schemeOption).toBeHidden();
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

test("shows the three-item bottom navigation without horizontal scrolling at 390px", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  const navigation = page.getByRole("navigation", { name: "主导航" });
  await expect(navigation.getByRole("button")).toHaveCount(3);
  await expect(navigation.getByRole("button", { name: "评分" })).toHaveCount(0);
  for (const label of ["科目", "试卷", "复核"]) {
    await expect(navigation.getByRole("button", { name: label })).toBeInViewport();
  }
  const navigationBox = await navigation.boundingBox();
  expect(navigationBox).not.toBeNull();
  const navigationBottom = navigationBox!.y + navigationBox!.height;
  expect(navigationBottom).toBeLessThanOrEqual(844);
  expect(navigationBottom).toBeGreaterThanOrEqual(843);

  const overflow = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));
  expect(overflow.document).toBeLessThanOrEqual(overflow.viewport);
  expect(overflow.body).toBeLessThanOrEqual(overflow.viewport);
});
