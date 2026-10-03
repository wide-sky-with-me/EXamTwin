const path = require("node:path");
const { chromium } = require("@playwright/test");

const repositoryRoot = path.resolve(__dirname, "../..");
const paperPath = process.env.EXAMTWIN_PAPER_PATH || path.join(
  repositoryRoot,
  "data/牛津AQA/数学/5.AQA-alevel数学-历年真题/AS/2019 January/as-level-maths-unit-1-question-paper-Jan19.pdf",
);

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, locale: "zh-CN" });
  page.on("console", (message) => console.log(`[browser:${message.type()}] ${message.text()}`));
  page.on("pageerror", (error) => console.log(`[pageerror] ${error.message}`));
  await page.goto("http://127.0.0.1:5173", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "试卷作答" }).click();
  await page.waitForTimeout(500);
  await page.getByRole("button", { name: "新建作答" }).click();
  await page.getByRole("button", { name: /Mathematics \(9660\)/ }).click();
  await page.getByRole("button", { name: "下一步" }).click();
  await page.locator('input[type="file"]').setInputFiles(paperPath);
  await page.getByLabel("参考单元（可选）").selectOption("P1");
  await page.getByRole("button", { name: "开始整卷作答" }).click();
  const progress = page.locator(".paper-progress");
  await progress.waitFor({ timeout: 30_000 });
  const deadline = Date.now() + 30 * 60_000;
  let status = "";
  while (Date.now() < deadline) {
    const className = await progress.getAttribute("class");
    status = className?.split(/\s+/).at(-1) ?? "unknown";
    const text = (await progress.innerText()).replace(/\s+/g, " ").slice(0, 500);
    console.log(`[paper-status] ${status} ${text}`);
    if (["completed", "partial_failed", "failed"].includes(status)) break;
    await page.waitForTimeout(10_000);
  }
  await page.screenshot({ path: "/tmp/examtwin-answering-result.png", fullPage: true });
  console.log(`[paper-terminal] ${status}`);
  console.log(await page.locator("body").innerText());
  if (status !== "completed") throw new Error(`Paper answering ended as ${status}`);
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
