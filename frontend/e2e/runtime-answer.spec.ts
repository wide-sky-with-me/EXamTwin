import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

test("renders an opt-in saved runtime diagram for independent visual judging", async ({ page }) => {
  const directory = process.env.EXAMTWIN_RUNTIME_QUESTION_DIR;
  test.skip(!directory, "Requires a saved first runtime answer; never calls a model.");
  const answer = JSON.parse(await readFile(join(directory!, "result.json"), "utf8"));
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/runtime-answer.json", (route) => route.fulfill({ json: answer }));
  await page.setViewportSize({ width: 1080, height: 1000 });
  await page.goto("/e2e/fixtures/runtime-answer.html");
  await expect(page.getByRole("heading", { name: `Question ${answer.question_number}`, exact: true })).toBeVisible();
  await expect(page.locator(".katex-error")).toHaveCount(0);
  await expect(page.locator("svg").first()).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: join(directory!, "rendered-answer.png"), fullPage: true });
  expect(errors).toEqual([]);
});
