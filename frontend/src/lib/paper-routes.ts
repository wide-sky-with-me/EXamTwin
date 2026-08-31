export type PaperDetail =
  | { kind: "paper"; id: string }
  | { kind: "document"; id: string; parentPaperId?: string }
  | { kind: "answers"; paperId: string }
  | { kind: "job"; id: string; paperId: string }
  | { kind: "grading"; id: string; paperId: string }
  | null;

export type PaperLocation = {
  subjectId: string;
  detail: PaperDetail;
};

type SubjectWorkspace = "documents" | "knowledge";

export const PAPER_ROUTE_PATTERNS = [
  "/subjects/:subjectId/papers",
  "/subjects/:subjectId/papers/:paperUnitId",
  "/subjects/:subjectId/papers/:paperUnitId/answers",
  "/subjects/:subjectId/papers/:paperUnitId/documents/:documentId",
  "/subjects/:subjectId/documents/:documentId",
  "/subjects/:subjectId/papers/:paperUnitId/jobs/:jobId",
  "/subjects/:subjectId/papers/:paperUnitId/jobs/:jobId/answering",
  "/subjects/:subjectId/papers/:paperUnitId/jobs/:jobId/grading",
] as const;

function segment(value: string, name: string): string {
  if (!value) throw new TypeError(`${name} must not be empty`);
  return encodeURIComponent(value);
}

function decodedSegment(value: string): string | null {
  try {
    const decoded = decodeURIComponent(value);
    return decoded ? decoded : null;
  } catch {
    return null;
  }
}

export function parseSubjectId(pathname: string): string | null {
  const parts = pathname.split("/");
  return parts[0] === "" && parts[1] === "subjects" && parts[2]
    ? decodedSegment(parts[2])
    : null;
}

export function subjectPath(subjectId: string): string {
  return `/subjects/${segment(subjectId, "subjectId")}`;
}

export function subjectWorkspacePath(subjectId: string, workspace: SubjectWorkspace): string {
  return `${subjectPath(subjectId)}/${workspace}`;
}

export function paperIndexPath(subjectId: string): string {
  return `${subjectPath(subjectId)}/papers`;
}

export function paperDetailPath(subjectId: string, paperUnitId: string): string {
  return `${paperIndexPath(subjectId)}/${segment(paperUnitId, "paperUnitId")}`;
}

export function paperDocumentPath(
  subjectId: string,
  documentId: string,
  paperUnitId?: string,
): string {
  const document = segment(documentId, "documentId");
  return paperUnitId === undefined
    ? `${subjectWorkspacePath(subjectId, "documents")}/${document}`
    : `${paperDetailPath(subjectId, paperUnitId)}/documents/${document}`;
}

export function paperAnswersPath(subjectId: string, paperUnitId: string): string {
  return `${paperDetailPath(subjectId, paperUnitId)}/answers`;
}

export function paperAnsweringPath(
  subjectId: string,
  paperUnitId: string,
  jobId: string,
): string {
  return `${paperDetailPath(subjectId, paperUnitId)}/jobs/${segment(jobId, "jobId")}/answering`;
}

export function paperGradingPath(
  subjectId: string,
  paperUnitId: string,
  jobId: string,
): string {
  return `${paperDetailPath(subjectId, paperUnitId)}/jobs/${segment(jobId, "jobId")}/grading`;
}

export function parsePaperLocation(pathname: string): PaperLocation | null {
  const normalizedPathname = pathname.replace(/\/+$/, "");
  const parts = normalizedPathname.split("/");
  if (parts[0] !== "" || parts[1] !== "subjects") return null;

  const subjectId = parseSubjectId(normalizedPathname);
  if (!subjectId) return null;

  if (parts.length === 4 && parts[3] === "papers") {
    return { subjectId, detail: null };
  }

  if (parts.length === 5 && parts[3] === "documents") {
    const documentId = decodedSegment(parts[4]);
    return documentId
      ? { subjectId, detail: { kind: "document", id: documentId } }
      : null;
  }

  if (parts[3] !== "papers") return null;
  const paperId = parts[4] ? decodedSegment(parts[4]) : null;
  if (!paperId) return null;

  if (parts.length === 5) {
    return { subjectId, detail: { kind: "paper", id: paperId } };
  }

  if (parts.length === 6 && parts[5] === "answers") {
    return { subjectId, detail: { kind: "answers", paperId } };
  }

  if (parts.length === 7 && parts[5] === "documents") {
    const documentId = decodedSegment(parts[6]);
    return documentId
      ? { subjectId, detail: { kind: "document", id: documentId, parentPaperId: paperId } }
      : null;
  }

  if ((parts.length === 7 || parts.length === 8) && parts[5] === "jobs") {
    const jobId = decodedSegment(parts[6]);
    if (!jobId) return null;
    if (parts.length === 7 || parts[7] === "answering") {
      return { subjectId, detail: { kind: "job", id: jobId, paperId } };
    }
    if (parts[7] === "grading") {
      return { subjectId, detail: { kind: "grading", id: jobId, paperId } };
    }
  }

  return null;
}
