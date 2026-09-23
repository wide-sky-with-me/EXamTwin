import { expect, test } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { inflateSync } from "node:zlib";
import { PDFDict, PDFDocument, PDFName, PDFRawStream, rgb } from "pdf-lib";

test("strategy blanks stay blank without an incomplete-answer appendix", async ({ page }, info) => {
  const pdf = await PDFDocument.create();
  pdf.addPage([595, 842]).drawText("Original Q1 and Q2", { x: 50, y: 790 });
  const source = Buffer.from(await pdf.save());
  const plan = JSON.parse(await readFile(new URL("./fixtures/target-strategy-plan.json", import.meta.url), "utf8"));
  const job = { job_id: "strategy-pdf", filename: "strategy.pdf", status: "completed", completed_questions: 2, total_questions: 2,
    strategy_plan: plan, questions: [
      { position: 0, number: "1", status: "completed", source_pages: [1], answer_markdown: "A selected answer.", answer_requirements: [], diagrams: [], images: [], error: null },
      { position: 1, number: "2", status: "completed", source_pages: [1], answer_markdown: "", diagrams: [], images: [], error: null, skipped_by_strategy: true },
    ] };
  await page.route("**/export-fixture.json", (route) => route.fulfill({ json: job }));
  await page.route("**/api/v1/papers/jobs/strategy-pdf/answer-pdf/layout", (route) => route.fulfill({ json: {
    source_sha256: createHash("sha256").update(source).digest("hex"), warnings: [],
    pages: [{ page_number: 1, width: 595, height: 842, rotation: 0, blocked_regions: [] }],
    regions: [{ question_position: 0, answer_anchor: "whole", page_number: 1, x: 70, y: 150, width: 450, height: 100 }],
  } }));
  await page.route("**/api/v1/papers/jobs/strategy-pdf/source?*", (route) => route.fulfill({ body: source, contentType: "application/pdf" }));
  await page.route("**/api/v1/papers/jobs/strategy-pdf/source/pages/1?*", (route) => route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="595" height="842"><rect width="595" height="842" fill="white"/></svg>' }));
  await page.goto("/e2e/fixtures/answer-pdf.html");
  await expect(page.getByText("1/1 个答案已有区域")).toBeVisible();
  await expect(page.getByText(/这是部分作答/)).toHaveCount(0);
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "生成 PDF 预览" }).click();
  await expect(page.getByTitle("已作答原卷 PDF 预览")).toBeVisible();
  const promise = page.waitForEvent("download");
  await page.getByRole("link", { name: "下载已作答 PDF" }).click();
  const download = await promise;
  const destination = info.outputPath("strategy-answered.pdf");
  await download.saveAs(destination);
  const result = await PDFDocument.load(await readFile(destination));
  expect(result.getPageCount()).toBe(1);
  expect(result.getSubject()).toContain("not graded");
  expect(download.suggestedFilename()).toBe("strategy-answered.pdf");
});

test("exports the original paper with math, calibrated overlay, continuation and incomplete status", async ({ page }, info) => {
  const pdf = await PDFDocument.create();
  const original = pdf.addPage([595, 842]);
  original.drawText("ORIGINAL QUESTION PAPER — KEEP THIS TEXT", { x: 50, y: 790, size: 12 });
  original.drawRectangle({ x: 500, y: 780, width: 25, height: 25, color: rgb(0.8, 0.2, 0.1) });
  original.drawLine({ start: { x: 90, y: 350 }, end: { x: 480, y: 350 } });
  const source = Buffer.from(await pdf.save());
  const job = {
    job_id: "pdf-fixture", filename: "source.pdf", display_name: "PDF regression", status: "partial_failed",
    completed_questions: 1, total_questions: 2, source_integrity_status: "verified",
    questions: [{ position: 0, number: "1", status: "completed", source_pages: [1], error: null,
      answer_markdown: "A preserved mathematical answer:\n\n$$\\int_0^1 x^2\\,dx = \\frac{1}{3}$$\n\n"
        + Array.from({ length: 60 }, (_, i) => `Step ${i + 1}: Explain the result clearly. The exact answer is $x^2+1$.\n\n`).join(""),
      answer_requirements: [{ label: "whole" }], images: [],
      diagrams: [{ artifact_id: "artifact-1", answer_anchor: "whole", answer_order: 1, title: "Original axes overlay", caption: "", tool_name: "math_plot",
        view_box: [90, 300, 390, 180], legend: [], source: { kind: "paper_page", width: 595, height: 842, page_number: 1, calibration: "blank_axes" },
        elements: [{ kind: "line", x1: 100, y1: 400, x2: 400, y2: 320, points: [], fill: "none", tone: "primary", dashed: false, emphasis: false, arrow_start: false, arrow_end: false }],
      }],
    }, { position: 1, number: "2", status: "failed", source_pages: [1], answer_markdown: "", error: "quota", answer_requirements: [], diagrams: [], images: [] }],
  };
  const layout = { source_sha256: createHash("sha256").update(source).digest("hex"),
    pages: [{ page_number: 1, width: 595, height: 842 }], warnings: [],
    regions: [{ question_position: 0, answer_anchor: "whole", page_number: 1, x: 90, y: 90, width: 390, height: 160 }],
  };
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/export-fixture.json", (route) => route.fulfill({ json: job }));
  await page.route("**/api/v1/papers/jobs/pdf-fixture/answer-pdf/layout", (route) => route.fulfill({ json: layout }));
  await page.route("**/api/v1/papers/jobs/pdf-fixture/source?*", (route) => route.fulfill({ contentType: "application/pdf", body: source }));
  await page.route("**/api/v1/papers/jobs/pdf-fixture/source/pages/1?*", (route) => route.fulfill({ contentType: "image/svg+xml", body:
    '<svg xmlns="http://www.w3.org/2000/svg" width="595" height="842"><rect width="595" height="842" fill="white"/><text x="50" y="52">ORIGINAL QUESTION PAPER</text><rect x="500" y="37" width="25" height="25" fill="#c33"/></svg>' }));
  await page.goto("/e2e/fixtures/answer-pdf.html");
  await expect(page.getByText("1/1 个答案已有区域")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "框选答题区", exact: true })).toBeVisible();
  expect(await page.locator(".ant-modal-body").evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  await page.screenshot({ path: info.outputPath("placement-mobile.png"), fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.getByRole("checkbox").check();
  await page.screenshot({ path: info.outputPath("placement.png"), fullPage: true });
  await page.getByRole("button", { name: "生成 PDF 预览" }).click();
  await expect(page.getByTitle("已作答原卷 PDF 预览")).toBeVisible({ timeout: 30_000 });
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: "下载已作答 PDF" }).click();
  const download = await downloadPromise;
  const path = info.outputPath("answered.pdf");
  await download.saveAs(path);
  const exported = await PDFDocument.load(await readFile(path));
  expect(exported.getPageCount()).toBeGreaterThan(2);
  expect(exported.getPages()[0].getSize()).toEqual(original.getSize());
  const resources = exported.getPages()[0].node.Resources();
  expect(resources?.has(PDFName.of("XObject"))).toBe(true);
  const images = resources!.lookup(PDFName.of("XObject"), PDFDict);
  expect(images.keys().length).toBe(2);
  for (const [, reference] of images.entries()) {
    const image = exported.context.lookup(reference, PDFRawStream);
    const alpha = exported.context.lookup(image.dict.get(PDFName.of("SMask")), PDFRawStream);
    expect(inflateSync(alpha.getContents()).some((pixel) => pixel > 20)).toBe(true);
  }
  expect(exported.getSubject()).toContain("1/2 questions completed");
  expect(download.suggestedFilename()).toBe("source-partial-answered.pdf");
  expect(errors).toEqual([]);
});

test("local real-paper sample exports saved answers without a model call", async ({ page }, info) => {
  const directory = process.env.EXAMTWIN_PDF_SAMPLE_DIR;
  test.skip(!directory, "Requires the locally purchased PDF and saved answer snapshot.");
  const job = JSON.parse(await readFile(join(directory!, "job.json"), "utf8"));
  const layout = JSON.parse(await readFile(join(directory!, "layout.json"), "utf8"));
  await page.route("**/export-fixture.json", (route) => route.fulfill({ json: job }));
  await page.route("**/api/v1/papers/jobs/*/answer-pdf/layout", (route) => route.fulfill({ json: layout }));
  await page.route("**/api/v1/papers/jobs/*/source?*", (route) => route.fulfill({ path: join(directory!, "source.pdf"), contentType: "application/pdf" }));
  await page.route("**/api/v1/papers/jobs/*/source/pages/*", (route) => {
    const number = new URL(route.request().url()).pathname.split("/").pop();
    return route.fulfill({ path: join(directory!, `page-${number}.png`), contentType: "image/png" });
  });
  await page.goto("/e2e/fixtures/answer-pdf.html");
  await expect(page.getByText("1/1 个答案已有区域")).toBeVisible();
  await page.getByRole("checkbox").check();
  await page.screenshot({ path: info.outputPath("real-placement.png"), fullPage: true });
  await page.getByRole("button", { name: "生成 PDF 预览" }).click();
  await expect(page.getByTitle("已作答原卷 PDF 预览")).toBeVisible({ timeout: 30_000 });
  const downloaded = page.waitForEvent("download");
  await page.getByRole("link", { name: "下载已作答 PDF" }).click();
  await (await downloaded).saveAs(join(directory!, "mathematics-p1-partial-answered.pdf"));
});
