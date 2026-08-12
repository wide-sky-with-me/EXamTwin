const { chromium } = require("@playwright/test");

const baseUrl = process.env.EXAMTWIN_BASE_URL || "http://127.0.0.1:5173";
const subject = process.env.EXAMTWIN_SUBJECT;
const subjectId = process.env.EXAMTWIN_SUBJECT_ID;
const questionPath = process.env.EXAMTWIN_PAPER_PATH;
const answerPath = process.env.EXAMTWIN_ANSWER_PATH;
const sourceBookletPath = process.env.EXAMTWIN_SOURCE_BOOKLET_PATH;
const timeout = Number(process.env.EXAMTWIN_TASK_TIMEOUT_MS || 45 * 60_000);
const screenshotPath = process.env.EXAMTWIN_SCREENSHOT_PATH || "/tmp/examtwin-uploaded-answer.png";

if (!subject || !subjectId || !questionPath || !answerPath) {
  throw new Error(
    "EXAMTWIN_SUBJECT, EXAMTWIN_SUBJECT_ID, EXAMTWIN_PAPER_PATH and EXAMTWIN_ANSWER_PATH are required",
  );
}

function escapeRegex(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, locale: "zh-CN" });
  await page.addInitScript((activeSubject) => {
    window.localStorage.setItem("examtwin.subject", activeSubject);
  }, subjectId);
  const errors = [];
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  page.on("response", (response) => {
    if (response.status() >= 400) {
      errors.push(`${response.request().method()} ${response.status()} ${response.url()}`);
    }
  });

  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "答案评分" }).click();
  await page.getByRole("button", { name: new RegExp(escapeRegex(subject)) }).click();
  await page.getByRole("heading", { name: "评分材料" }).waitFor();
  await page.getByRole("button", { name: "上传答卷" }).click();

  const cards = page.locator(".grading-external-upload .grading-source-card");
  await cards.filter({ hasText: "试卷文件" }).locator("input[type=file]").setInputFiles(questionPath);
  await cards.filter({ hasText: "答案文件" }).locator("input[type=file]").setInputFiles(answerPath);
  if (sourceBookletPath) {
    await cards.filter({ hasText: "Source Booklet" }).locator("input[type=file]")
      .setInputFiles(sourceBookletPath);
  }

  const createdResponse = page.waitForResponse((response) =>
    response.request().method() === "POST" && response.url().endsWith("/api/v1/papers/import-answer"),
  );
  await page.getByRole("button", { name: "导入并解析答卷" }).click();
  const response = await createdResponse;
  const payload = await response.json();
  if (!response.ok()) throw new Error(`import failed (${response.status()}): ${JSON.stringify(payload)}`);
  const jobId = payload.job_id;
  console.log(`[created] ${jobId}`);

  const deadline = Date.now() + timeout;
  let job;
  while (Date.now() < deadline) {
    const statusResponse = await page.request.get(
      `${baseUrl}/api/v1/papers/jobs/${jobId}`,
      { headers: { "X-ExamTwin-Subject": subjectId } },
    );
    if (!statusResponse.ok()) {
      throw new Error(`status failed (${statusResponse.status()}): ${await statusResponse.text()}`);
    }
    job = await statusResponse.json();
    if (["completed", "partial_failed", "failed"].includes(job.status)) break;
    await page.waitForTimeout(2_000);
  }
  if (!job || !["completed", "partial_failed", "failed"].includes(job.status)) {
    throw new Error(`uploaded answer timed out: ${jobId}`);
  }
  console.log(
    `[terminal] ${job.status} ${job.completed_questions}/${job.total_questions} `
    + `mode=${job.questions?.[0]?.answer_mode || "unknown"} error=${job.error || "-"}`,
  );

  await page.reload({ waitUntil: "networkidle" });
  await page.getByRole("button", { name: "答案评分" }).click();
  const subjectButton = page.getByRole("button", { name: new RegExp(escapeRegex(subject)) });
  if (await subjectButton.isVisible()) await subjectButton.click();
  await page.getByRole("heading", { name: "评分材料" }).waitFor();
  await page.getByRole("button", { name: "系统记录" }).click();
  await page.getByLabel("选择作答记录").click();
  const questionFilename = questionPath.split("/").pop();
  await page.getByRole("option").filter({ hasText: questionFilename }).first().waitFor({ timeout: 30_000 });
  await page.keyboard.press("Escape");
  await page.screenshot({ path: screenshotPath, fullPage: true });
  console.log(`[browser-errors] ${JSON.stringify(errors)}`);

  if (job.status !== "completed") process.exitCode = 2;
  else if (job.completed_questions !== job.total_questions) process.exitCode = 3;
  else if (errors.length) process.exitCode = 4;
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
