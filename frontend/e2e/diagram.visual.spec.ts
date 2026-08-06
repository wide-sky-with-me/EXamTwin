import { expect, test } from "@playwright/test";

test("renders a readable desktop mathematics plot", async ({ page }) => {
  await page.goto("/e2e/fixtures/diagram.html");
  await page.evaluate(() => document.fonts.ready);
  const diagram = page.locator(".answer-diagram");

  await expect(diagram).toBeVisible();
  await expect(diagram.getByText("函数与坐标绘图 · 安全矢量图")).toBeVisible();
  await expect(diagram.locator(".katex")).toHaveCount(6);
  for (const name of ["缩小图形", "放大图形", "重置图形缩放", "全屏查看图形"]) {
    await expect(diagram.getByRole("button", { name })).toBeVisible();
  }
  const zoomIconBox = await diagram
    .getByRole("button", { name: "放大图形" })
    .locator("svg")
    .boundingBox();
  expect(zoomIconBox).not.toBeNull();
  expect(zoomIconBox!.width).toBeLessThanOrEqual(16);
  expect(zoomIconBox!.height).toBeLessThanOrEqual(16);
  await expect(diagram).toHaveScreenshot("answer-diagram-desktop.png", {
    animations: "disabled",
  });
});

test("keeps controls and the full plot usable on a narrow screen", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/e2e/fixtures/diagram.html");
  await page.evaluate(() => document.fonts.ready);

  await page.getByRole("button", { name: "放大图形" }).click();
  await expect(page.getByText("125%")).toBeVisible();
  await page.getByRole("button", { name: "全屏查看图形" }).click();
  const diagram = page.locator(".answer-diagram.is-expanded");

  await expect(diagram).toBeVisible();
  await expect(diagram).toHaveScreenshot("answer-diagram-mobile-expanded.png", {
    animations: "disabled",
  });
});
