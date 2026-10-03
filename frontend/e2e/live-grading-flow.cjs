const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.EXAMTWIN_BASE_URL || "http://127.0.0.1:5173";
const subjectPattern = process.env.EXAMTWIN_SUBJECT_PATTERN || "Mathematics.*9660";
const subjectId = process.env.EXAMTWIN_SUBJECT_ID || "oxfordaqa-mathematics-9660";
const paperJobId = process.env.EXAMTWIN_PAPER_JOB_ID || "";
const paperLabel = process.env.EXAMTWIN_PAPER_LABEL
  || "as-level-maths-unit-1-question-paper-Jan19.pdf";
const markSchemePath = process.env.EXAMTWIN_MARK_SCHEME_PATH
  || path.join(
    path.resolve(__dirname, "../.."),
    "data/牛津AQA/数学/5.AQA-alevel数学-历年真题/AS/2019 January/as-level-maths-unit-1-mark-scheme-Jan19.pdf",
  );
const markSchemeLabel = process.env.EXAMTWIN_MARK_SCHEME_LABEL
  || markSchemePath.split("/").pop();
const reviewer = process.env.EXAMTWIN_REVIEWER || "widsky-e2e";
const questionCount = Number(process.env.EXAMTWIN_QUESTION_COUNT || 10);
const screenshotPath = process.env.EXAMTWIN_SCREENSHOT_PATH
  || "/tmp/examtwin-system-grading-result.png";

async function selectQuestion(page, number) {
  const button = page.locator(".grading-question-picker button").filter({
    has: page.locator("b", { hasText: new RegExp(`^Q0*${number}$`) }),
  });
  await button.click();
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, locale: "zh-CN" });
  const runtimeErrors = [];
  page.on("pageerror", (error) => {
    runtimeErrors.push(`pageerror: ${error.message}`);
    console.log(`[pageerror] ${error.message}`);
  });
  page.on("response", async (response) => {
    if (response.status() < 400) return;
    const detail = await response.text().catch(() => "");
    const message = `${response.request().method()} ${response.status()} ${response.url()} ${detail}`;
    runtimeErrors.push(message);
    console.log(`[http-error] ${message}`);
  });

  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "答案评分" }).click();
  await page.getByRole("button", { name: new RegExp(subjectPattern) }).click();
  await page.getByRole("heading", { name: "评分材料" }).waitFor();

  await page.getByLabel("选择作答记录").click();
  if (paperJobId) {
    const papersResponse = await page.request.get(`${baseUrl}/api/v1/grading/papers`, {
      headers: { "X-ExamTwin-Subject": subjectId },
    });
    if (!papersResponse.ok()) {
      throw new Error(`作答记录列表请求失败：${papersResponse.status()} ${await papersResponse.text()}`);
    }
    const papers = await papersResponse.json();
    const paperIndex = papers.findIndex((item) => item.job_id === paperJobId);
    if (paperIndex < 0) throw new Error(`找不到指定作答记录：${paperJobId}`);
    await page.getByRole("option").nth(paperIndex).click();
    console.log(`[selected-paper] ${paperJobId} index=${paperIndex}`);
  } else {
    await page.getByRole("option").filter({ hasText: paperLabel }).first().click();
  }
  await page.getByLabel("所选答卷内容").waitFor({ timeout: 30_000 });

  await page.getByLabel("上传官方 Mark Scheme").setInputFiles(markSchemePath);
  await page.getByLabel("选择 Mark Scheme").filter({ hasText: markSchemeLabel }).waitFor({
    timeout: 10 * 60_000,
  });

  const preparationAction = page.getByRole("button", {
    name: /^(解析评分标准|审核评分标准|开始逐题判分)$/,
  });
  const preparationLabel = (await preparationAction.innerText()).trim();
  await preparationAction.click();
  if (preparationLabel !== "开始逐题判分") {
    await page.locator("#grading-stage-2-heading").waitFor({
      timeout: 10 * 60_000,
    });
    const stats = page.locator(".rubric-stats");
    const noPendingCriteria = /(^|\s)0 待处理(?:\s|$)/.test(await stats.innerText());
    if (!noPendingCriteria) {
      await page.getByLabel("审核人").fill(reviewer);
      const questionNavigation = page.getByRole("navigation", { name: "得分点题目导航" });
      await questionNavigation.getByRole("button", { name: /^全部题目/ }).click();
      await page.getByLabel("选择当前筛选下待处理规则").check();
      await page.getByRole("button", { name: "保留所选" }).click();
      await stats.filter({ hasText: "0 待处理" }).waitFor({
        timeout: 2 * 60_000,
      });
    }
    await page.getByRole("button", { name: "确认规则并开始评分" }).click();
  }
  await page.locator("#grading-stage-3-heading").waitFor({
    timeout: 2 * 60_000,
  });

  for (let number = 1; number <= questionCount; number += 1) {
    await selectQuestion(page, number);
    const generate = page.getByRole("button", { name: "生成判分结果" });
    if (await generate.isVisible()) {
      await generate.click();
      await page.getByRole("button", { name: "重新判分" }).waitFor({ timeout: 10 * 60_000 });
    }
    const report = page.locator("#grading-question-report");
    console.log(`[graded] Q${number} ${(await report.innerText()).replace(/\s+/g, " ").slice(0, 240)}`);
  }

  await page.getByRole("button", { name: "查看整卷结果" }).click();
  await page.getByText("全部题目已有评分结果").waitFor({ timeout: 2 * 60_000 });
  const overview = page.locator(".grading-overview");
  const overviewText = (await overview.innerText()).replace(/\s+/g, " ");
  console.log(`[grading-overview] ${overviewText.slice(0, 1200)}`);
  await page.screenshot({ path: screenshotPath, fullPage: true });
  await browser.close();
  if (runtimeErrors.length) {
    throw new Error(`浏览器评分过程中出现 ${runtimeErrors.length} 个运行错误`);
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
