import { describe, expect, test } from "vitest";

import {
  PAPER_ROUTE_PATTERNS,
  paperAnsweringPath,
  paperAnswersPath,
  paperDetailPath,
  paperDocumentPath,
  paperGradingPath,
  paperIndexPath,
  parsePaperLocation,
  type PaperDetail,
} from "./paper-routes";

describe("paper route contract", () => {
  const subjectId = "math/国际 9660";
  const paperId = "paper/June 2026";
  const documentId = "document/Question Paper.pdf";
  const jobId = "job/attempt 2";

  test.each<{
    name: string;
    path: string;
    detail: PaperDetail;
  }>([
    {
      name: "paper index",
      path: paperIndexPath(subjectId),
      detail: null,
    },
    {
      name: "paper detail",
      path: paperDetailPath(subjectId, paperId),
      detail: { kind: "paper", id: paperId },
    },
    {
      name: "subject document",
      path: paperDocumentPath(subjectId, documentId),
      detail: { kind: "document", id: documentId },
    },
    {
      name: "paper document",
      path: paperDocumentPath(subjectId, documentId, paperId),
      detail: { kind: "document", id: documentId, parentPaperId: paperId },
    },
    {
      name: "answers",
      path: paperAnswersPath(subjectId, paperId),
      detail: { kind: "answers", paperId },
    },
    {
      name: "answering",
      path: paperAnsweringPath(subjectId, paperId, jobId),
      detail: { kind: "job", id: jobId, paperId },
    },
    {
      name: "grading",
      path: paperGradingPath(subjectId, paperId, jobId),
      detail: { kind: "grading", id: jobId, paperId },
    },
  ])("builds and parses $name with encoded IDs", ({ path, detail }) => {
    expect(path).not.toContain("math/国际");
    expect(parsePaperLocation(path)).toEqual({ subjectId, detail });
  });

  test("registers the legacy bare job route with the app router", () => {
    expect(PAPER_ROUTE_PATTERNS).toContain(
      "/subjects/:subjectId/papers/:paperUnitId/jobs/:jobId",
    );
  });

  test.each<{
    name: string;
    path: string;
    detail: PaperDetail;
  }>([
    {
      name: "paper index",
      path: paperIndexPath(subjectId),
      detail: null,
    },
    {
      name: "paper detail",
      path: paperDetailPath(subjectId, paperId),
      detail: { kind: "paper", id: paperId },
    },
    {
      name: "subject document",
      path: paperDocumentPath(subjectId, documentId),
      detail: { kind: "document", id: documentId },
    },
    {
      name: "paper document",
      path: paperDocumentPath(subjectId, documentId, paperId),
      detail: { kind: "document", id: documentId, parentPaperId: paperId },
    },
    {
      name: "answers",
      path: paperAnswersPath(subjectId, paperId),
      detail: { kind: "answers", paperId },
    },
    {
      name: "bare answer job",
      path: `${paperDetailPath(subjectId, paperId)}/jobs/${encodeURIComponent(jobId)}`,
      detail: { kind: "job", id: jobId, paperId },
    },
    {
      name: "answering job",
      path: paperAnsweringPath(subjectId, paperId, jobId),
      detail: { kind: "job", id: jobId, paperId },
    },
    {
      name: "grading job",
      path: paperGradingPath(subjectId, paperId, jobId),
      detail: { kind: "grading", id: jobId, paperId },
    },
  ])("parses $name with one or more trailing slashes", ({ path, detail }) => {
    for (const trailingSlashes of ["/", "///"]) {
      expect(parsePaperLocation(`${path}${trailingSlashes}`)).toEqual({ subjectId, detail });
    }
  });

  test.each([
    "/subjects",
    "/subjects//papers",
    "/subjects/math/papers/paper/answers/extra",
    "/subjects/math/papers/paper/documents",
    "/subjects/math/papers/paper/jobs",
    "/subjects/math/papers/paper/jobs/job/unknown",
    "/subjects/math/papers/paper/grading",
    "/subjects/%E0%A4%A/papers///",
  ])("rejects invalid or incomplete route %s", (path) => {
    expect(parsePaperLocation(path)).toBeNull();
  });

  test.each([
    ["paper index", () => paperIndexPath("")],
    ["paper detail", () => paperDetailPath("math", "")],
    ["subject document", () => paperDocumentPath("math", "")],
    ["paper document", () => paperDocumentPath("math", "document", "")],
    ["answers", () => paperAnswersPath("math", "")],
    ["answering", () => paperAnsweringPath("math", "paper", "")],
    ["grading", () => paperGradingPath("math", "paper", "")],
  ])("rejects incomplete %s builder arguments", (_name, build) => {
    expect(build).toThrow(TypeError);
  });
});
