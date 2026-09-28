import { expect, test } from "@playwright/test";

for (const width of [390, 1280]) {
  test(`shows sourced provisional unit grade at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route("**/grade-overview-fixture.json", (route) => route.fulfill({ json: {
      paper_job_id: "fixture", rubric_set_id: "rubric", total_awarded: 48, total_available: 80,
      percentage: 60, total_questions: 1, completed_questions: 1, pending_review_count: 1,
      confirmed_count: 0, overridden_count: 0, incomplete: false, overall_suggestion: "等待教师复核。",
      common_error_types: [], questions: [], grade_estimate: {
        status: "provisional", grade: "C", scope: "unit", pair_key: "9660:2019:JAN:P1",
        unit_code: "MA01", source_page: 1,
        source_url: "https://www.oxfordaqa.com/oaqaresources/exams-admin/grade-boundaries-a-level-january-2019.pdf",
        explanation: "根据待复核分数换算的暂定单元等级。仅适用于本次单元试卷，不代表完整 AS/A-level 资格等级或正式考试结果。",
        thresholds: { A: 64, B: 55, C: 46, D: 37, E: 29 }, next_grade: "B", marks_to_next_grade: 7,
      },
    } }));
    await page.goto("/e2e/fixtures/grading-overview.html");
    const card = page.getByRole("region", { name: "单元等级估计" });
    await expect(card.getByRole("heading", { name: "C", exact: true })).toBeVisible();
    await expect(card).toContainText("暂定单元等级 · 待复核");
    await expect(card.getByRole("link")).toHaveAttribute("href", /oxfordaqa.com/);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}
