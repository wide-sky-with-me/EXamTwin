import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";

test("strategy budgets and expanded report are readable on desktop and mobile", async ({ page }, info) => {
  const plan = JSON.parse(await readFile(new URL("./fixtures/target-strategy-plan.json", import.meta.url), "utf8"));
  plan.analysis.options[0].stop_before = "完成一个论点后停止，不继续展开第二项政策或综合结论。";
  await page.route("**/strategy-fixture.json", (route) => route.fulfill({ json: plan }));
  await page.goto("/e2e/fixtures/target-strategy.html");
  await page.getByRole("checkbox").check();
  await expect(page.getByLabel("考试时长（分钟）")).toHaveValue("105");
  await page.getByLabel("可备考时间（小时）").fill("8");
  await page.getByText("查看备考清单、答题顺序和方案比较").click();
  await expect(page.getByText("本方案需要准备")).toBeVisible();
  await expect(page.getByText("停止边界：完成一个论点后停止，不继续展开第二项政策或综合结论。", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "下载完整策略" })).toBeVisible();
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 844 });
    expect(await page.locator("body").evaluate((e) => e.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath(`strategy-${width}.png`), fullPage: true });
  }
});
