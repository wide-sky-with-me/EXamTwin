import { expect, test, type Page } from "@playwright/test";

/**
 * The mobile shell pins a fixed bottom navigation bar. A paginator that relied on
 * `margin-top: auto` inside a viewport-tall list container was pushed underneath that
 * bar: at 390x844 its bottom measured 882px against a navigation top of 775px, so the
 * page-number control sat 107px behind the bar and needed 122px of scrolling to be read.
 * These tests pin the reachability contract so a future layout change cannot re-break it.
 */

const infrastructure = { postgresql: true, qdrant: true, object_storage: true };

function subjectFixture(index: number) {
  return {
    id: `oxfordaqa-economics-9640-${index}`,
    version: "1",
    digest: "test",
    subject_code: "9640",
    title: `OxfordAQA International AS/A-level Economics (9640) ${index}`,
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
    units: [{ code: "U1", title: "Markets", strand: "Microeconomics" }],
    vector_alias: "examtwin_9640_live",
    vector_index_ready: true,
    vector_points: 822,
    stats: null,
  };
}

async function mockSubjectCatalog(page: Page, subjectCount: number) {
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const fulfill = (payload: unknown) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify(payload) });
    if (path === "/api/v1/subjects/status") {
      return fulfill({
        infrastructure,
        subjects: Array.from({ length: subjectCount }, (_, index) => subjectFixture(index + 1)),
      });
    }
    if (path === "/api/v1/grading/reviews/all") return fulfill([]);
    return fulfill({ items: [], total: 0, limit: 10, offset: 0 });
  });
}

async function paginatorGeometry(page: Page) {
  return page.evaluate(() => {
    const box = (selector: string) => {
      const node = document.querySelector<HTMLElement>(selector);
      if (!node) return null;
      const rect = node.getBoundingClientRect();
      return {
        top: Math.round(rect.top),
        bottom: Math.round(rect.bottom),
        height: Math.round(rect.height),
      };
    };
    return {
      viewportHeight: window.innerHeight,
      pagination: box(".list-pagination"),
      bottomNav: box(".app-bottom-nav"),
      documentHeight: document.documentElement.scrollHeight,
    };
  });
}

test("keeps the subject paginator reachable on a phone screen", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.setViewportSize({ width: 390, height: 844 });
  await mockSubjectCatalog(page, 1);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "科目" })).toBeVisible();

  const first = await paginatorGeometry(page);
  expect(first.pagination).not.toBeNull();
  expect(first.bottomNav).not.toBeNull();
  // Content fits the first screen, so the paginator must not be covered by the fixed bar.
  expect(first.pagination!.bottom).toBeLessThanOrEqual(first.bottomNav!.top);

  // Scrolled to the very bottom the paginator must be fully readable, with clearance above the bar.
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await page.waitForTimeout(300);
  const bottom = await paginatorGeometry(page);
  expect(bottom.pagination!.bottom).toBeLessThanOrEqual(bottom.bottomNav!.top);
  expect(bottom.pagination!.top).toBeGreaterThanOrEqual(0);

  const overflow = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
  }));
  expect(overflow.document).toBeLessThanOrEqual(overflow.viewport);
});
