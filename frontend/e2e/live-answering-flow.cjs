const { chromium } = require("@playwright/test");

const baseUrl = process.env.EXAMTWIN_BASE_URL || "http://127.0.0.1:5173";
const subject = process.env.EXAMTWIN_SUBJECT || "OxfordAQA International AS/A-level Economics (9640)";
const subjectId = process.env.EXAMTWIN_SUBJECT_ID || "oxfordaqa-economics-9640";
const unit = process.env.EXAMTWIN_UNIT || "U1";
const paperPath = process.env.EXAMTWIN_PAPER_PATH;
const sourceBookletPath = process.env.EXAMTWIN_SOURCE_BOOKLET_PATH;
const retryJobId = process.env.EXAMTWIN_RETRY_JOB_ID;
const timeout = Number(process.env.EXAMTWIN_TASK_TIMEOUT_MS || 45 * 60_000);
const screenshotPath = process.env.EXAMTWIN_SCREENSHOT_PATH || "/tmp/examtwin-answering-result.png";

if (!paperPath && !retryJobId) {
  throw new Error("EXAMTWIN_PAPER_PATH is required");
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, locale: "zh-CN" });
  await page.addInitScript(({ activeSubject, jobId }) => {
    window.localStorage.setItem("examtwin.subject", activeSubject);
    if (jobId) window.localStorage.setItem(`examtwin.paperJobId.${activeSubject}`, jobId);
  }, { activeSubject: subjectId, jobId: retryJobId });
  const errors = [];
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  page.on("response", (response) => {
    if (response.status() >= 400) {
      errors.push(`${response.request().method()} ${response.status()} ${response.url()}`);
    }
  });

  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "试卷作答" }).click();
  await page.getByRole("heading", { name: "试卷作答", exact: true }).waitFor();
  if (retryJobId) {
    await page.locator(".paper-progress.failed, .paper-progress.partial_failed").waitFor();
    const retryResponse = page.waitForResponse((response) =>
      response.request().method() === "POST"
      && response.url().endsWith(`/api/v1/papers/jobs/${retryJobId}/retry`),
    );
    await page.getByRole("button", { name: /从失败步骤继续|仅重试失败步骤/ }).click();
    const response = await retryResponse;
    if (!response.ok()) throw new Error(`retry failed (${response.status()}): ${await response.text()}`);
    await page.locator(".paper-progress.failed, .paper-progress.partial_failed").waitFor({
      state: "hidden",
      timeout: 30_000,
    });
    console.log(`[retried] ${retryJobId}`);
  } else {
    await page.getByRole("button", { name: "新建作答" }).click();
    await page.getByRole("button", { name: new RegExp(subject.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")) }).click();
    await page.getByRole("button", { name: "下一步" }).click();
    await page.locator(".paper-upload .drop-zone input[type=file]").setInputFiles(paperPath);
    if (sourceBookletPath) {
      await page.locator(".paper-companion-upload input[type=file]").setInputFiles(sourceBookletPath);
    }
    await page.getByLabel("参考单元（可选）").selectOption(unit);

    const createdResponse = page.waitForResponse((response) =>
      response.request().method() === "POST" && response.url().endsWith("/api/v1/papers/answer"),
    );
    await page.getByRole("button", { name: "开始整卷作答" }).click();
    const response = await createdResponse;
    const payload = await response.json();
    if (!response.ok()) throw new Error(`create failed (${response.status()}): ${JSON.stringify(payload)}`);
    console.log(`[created] ${payload.job_id}`);
  }

  await page.locator(".paper-progress.completed, .paper-progress.partial_failed, .paper-progress.failed")
    .waitFor({ timeout });
  const terminalClass = await page.locator(".paper-progress").getAttribute("class");
  const terminalText = (await page.locator(".paper-progress").innerText()).replace(/\s+/g, " ");
  console.log(`[terminal] ${terminalClass} ${terminalText.slice(0, 1600)}`);
  console.log(`[browser-errors] ${JSON.stringify(errors)}`);
  await page.screenshot({ path: screenshotPath, fullPage: true });

  if (!terminalClass?.includes("completed")) {
    process.exitCode = 2;
  } else if (errors.length) {
    process.exitCode = 3;
  }
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
