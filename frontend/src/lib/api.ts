import createClient from "openapi-fetch";

import type { paths } from "../generated/openapi";
import type {
  PaperJobBulkDeleteResult,
  PaperJobCreated,
  PaperJobHistoryStatus,
  PaperJobList,
  PaperJobResult,
  PaperUnitAnswerCreated,
  PaperUnitList,
  PaperUnitSummary,
  SourceContextResult,
  SourceDocument,
} from "../types";
const API_BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";

export function subjectHeaders(subjectId: string, headers?: HeadersInit): Headers {
  if (!subjectId) throw new Error("科目请求缺少 subjectId");
  const result = new Headers(headers);
  result.set("X-ExamTwin-Subject", subjectId);
  return result;
}

const RESOLVED_API_BASE = new URL(API_BASE, window.location.origin);
const API_ORIGIN = API_BASE.endsWith("/api/v1")
  ? RESOLVED_API_BASE.href.slice(0, -"/api/v1".length)
  : RESOLVED_API_BASE.href.replace(/\/$/, "");

export const apiClient = createClient<paths>({
  baseUrl: API_ORIGIN,
  fetch: (request) => fetch(request),
});

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export function websocketUrl(path: string, subjectId: string): string {
  const url = new URL(apiUrl(path), window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.searchParams.set("subject", subjectId);
  return url.toString();
}

export function backendResourceUrl(path: string, subjectId: string): string {
  const apiPath = path.startsWith("/api/v1") ? path.slice("/api/v1".length) : path;
  const resource = apiUrl(apiPath.startsWith("/") ? apiPath : `/${apiPath}`);
  const separator = resource.includes("?") ? "&" : "?";
  return `${resource}${separator}subject=${encodeURIComponent(subjectId)}`;
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function apiErrorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => apiErrorMessage(item, ""))
      .filter(Boolean);
    return messages.length ? messages.join("；") : fallback;
  }
  if (detail && typeof detail === "object") {
    const record = detail as Record<string, unknown>;
    const message = apiErrorMessage(record.message ?? record.msg, "");
    const code = typeof record.code === "string" ? record.code : "";
    if (message && code) return `${message}（${code}）`;
    if (message) return message;
    if (code) return code;
  }
  return fallback;
}

async function checkedFetch(
  subjectId: string,
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const isFormData = init?.body instanceof FormData;
  const response = await fetch(new URL(`${API_BASE}${path}`, window.location.origin), {
    ...init,
    headers: isFormData
      ? subjectHeaders(subjectId, init?.headers)
      : subjectHeaders(subjectId, {
          "Content-Type": "application/json",
          ...init?.headers,
        }),
  });
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    const detail = payload && typeof payload === "object" && "detail" in payload
      ? (payload as { detail: unknown }).detail
      : payload;
    throw new ApiError(response.status, apiErrorMessage(detail, response.statusText));
  }
  return response;
}

export async function unwrapApi<Data, ErrorPayload>(
  request: Promise<{ data?: Data; error?: ErrorPayload; response: Response }>,
): Promise<Data> {
  const { data, error, response } = await request;
  if (!response.ok || (data === undefined && response.status !== 204)) {
    const detail: unknown =
      error && typeof error === "object" && "detail" in error
        ? error.detail
        : response.statusText;
    throw new ApiError(response.status, apiErrorMessage(detail, response.statusText));
  }
  return data as Data;
}
export type PaperJobHistoryFilters = {
  status?: PaperJobHistoryStatus;
  answerMode?: "generated" | "uploaded";
  unitCode?: string;
  paperUnitId?: string;
  query?: string;
  createdAfter?: string;
  limit?: number;
  offset?: number;
};

export async function listPaperJobs(
  subjectId: string,
  filters: PaperJobHistoryFilters = {},
): Promise<PaperJobList> {
  return unwrapApi(
    apiClient.GET("/api/v1/papers/jobs", {
      headers: subjectHeaders(subjectId),
      params: {
        query: {
          status: filters.status,
          answer_mode: filters.answerMode,
          unit_code: filters.unitCode,
          paper_unit_id: filters.paperUnitId,
          q: filters.query,
          created_after: filters.createdAfter,
          limit: filters.limit,
          offset: filters.offset,
        },
      },
    }),
  );
}

export async function deletePaperJobs(
  subjectId: string,
  jobIds: string[],
): Promise<PaperJobBulkDeleteResult> {
  return unwrapApi(
    apiClient.POST("/api/v1/papers/jobs/bulk-delete", {
      headers: subjectHeaders(subjectId),
      body: { job_ids: jobIds },
    }),
  );
}

export async function renamePaperJob(
  subjectId: string,
  jobId: string,
  displayName: string,
): Promise<PaperJobResult> {
  return await unwrapApi(
    apiClient.PATCH("/api/v1/papers/jobs/{job_id}", {
      headers: subjectHeaders(subjectId),
      params: { path: { job_id: jobId } },
      body: { display_name: displayName },
    }),
  ) as unknown as PaperJobResult;
}

export async function renameWorkspaceDocument(
  workspaceId: string,
  documentId: string,
  displayName: string,
): Promise<SourceDocument> {
  return unwrapApi(
    apiClient.PATCH("/api/v1/subject-workspaces/{workspace_id}/documents/{document_id}", {
      headers: subjectHeaders(workspaceId),
      params: { path: { workspace_id: workspaceId, document_id: documentId } },
      body: { display_name: displayName },
    }),
  );
}

export async function replacePaperJob(
  subjectId: string,
  jobId: string,
): Promise<PaperJobCreated> {
  return unwrapApi(
    apiClient.POST("/api/v1/papers/jobs/{job_id}/replace", {
      headers: subjectHeaders(subjectId),
      params: { path: { job_id: jobId } },
    }),
  );
}
export type PaperUnitFilters = {
  query?: string;
  unitCode?: string;
  examYear?: number;
  examSession?: string;
  limit?: number;
  offset?: number;
};

export async function listPaperUnits(
  workspaceId: string,
  filters: PaperUnitFilters = {},
): Promise<PaperUnitList> {
  return unwrapApi(
    apiClient.GET("/api/v1/subject-workspaces/{workspace_id}/paper-units", {
      headers: subjectHeaders(workspaceId),
      params: {
        path: { workspace_id: workspaceId },
        query: {
          q: filters.query,
          unit_code: filters.unitCode,
          exam_year: filters.examYear,
          exam_session: filters.examSession,
          limit: filters.limit,
          offset: filters.offset,
        },
      },
    }),
  );
}

export async function createPaperUnit(
  workspaceId: string,
  documentIds: string[],
  displayName?: string | null,
): Promise<PaperUnitSummary> {
  return unwrapApi(
    apiClient.POST("/api/v1/subject-workspaces/{workspace_id}/paper-units", {
      headers: subjectHeaders(workspaceId),
      params: { path: { workspace_id: workspaceId } },
      body: { document_ids: documentIds, display_name: displayName },
    }),
  );
}

export async function updatePaperUnit(
  workspaceId: string,
  paperUnitId: string,
  documentIds: string[] | null,
  displayName: string | null,
): Promise<PaperUnitSummary> {
  return unwrapApi(
    apiClient.PATCH("/api/v1/subject-workspaces/{workspace_id}/paper-units/{paper_unit_id}", {
      headers: subjectHeaders(workspaceId),
      params: { path: { workspace_id: workspaceId, paper_unit_id: paperUnitId } },
      body: { document_ids: documentIds, display_name: displayName },
    }),
  );
}

export async function archivePaperUnit(
  workspaceId: string,
  paperUnitId: string,
): Promise<void> {
  await unwrapApi(
    apiClient.DELETE("/api/v1/subject-workspaces/{workspace_id}/paper-units/{paper_unit_id}", {
      headers: subjectHeaders(workspaceId),
      params: { path: { workspace_id: workspaceId, paper_unit_id: paperUnitId } },
    }),
  );
}

export async function listTrashedPaperUnits(workspaceId: string): Promise<PaperUnitList> {
  const response = await checkedFetch(
    workspaceId,
    `/subject-workspaces/${encodeURIComponent(workspaceId)}/paper-units/trash?limit=100&offset=0`,
  );
  return response.json() as Promise<PaperUnitList>;
}

export async function restorePaperUnit(
  workspaceId: string,
  paperUnitId: string,
): Promise<PaperUnitSummary> {
  const response = await checkedFetch(
    workspaceId,
    `/subject-workspaces/${encodeURIComponent(workspaceId)}/paper-units/${encodeURIComponent(paperUnitId)}/restore`,
    { method: "POST", body: "{}" },
  );
  return response.json() as Promise<PaperUnitSummary>;
}

export async function permanentlyDeletePaperUnit(
  workspaceId: string,
  paperUnitId: string,
): Promise<void> {
  await checkedFetch(
    workspaceId,
    `/subject-workspaces/${encodeURIComponent(workspaceId)}/paper-units/${encodeURIComponent(paperUnitId)}/permanent`,
    { method: "DELETE" },
  );
}

export async function answerPaperUnit(
  workspaceId: string,
  paperUnitId: string,
  questionPaperDocumentId: string,
  sourceBookletDocumentId?: string | null,
): Promise<PaperUnitAnswerCreated> {
  return unwrapApi(
    apiClient.POST("/api/v1/subject-workspaces/{workspace_id}/paper-units/{paper_unit_id}/answer", {
      headers: subjectHeaders(workspaceId),
      params: { path: { workspace_id: workspaceId, paper_unit_id: paperUnitId } },
      body: {
        question_paper_document_id: questionPaperDocumentId,
        source_booklet_document_id: sourceBookletDocumentId,
        include_supplementary: false,
      },
    }),
  );
}

export async function importPaperUnitAnswer(
  workspaceId: string,
  paperUnitId: string,
  questionPaperDocumentId: string,
  answerFile: File,
): Promise<PaperUnitAnswerCreated> {
  const form = new FormData();
  form.append("question_paper_document_id", questionPaperDocumentId);
  form.append("answer_file", answerFile);
  const response = await checkedFetch(
    workspaceId,
    `/subject-workspaces/${encodeURIComponent(workspaceId)}/paper-units/${encodeURIComponent(paperUnitId)}/import-answer`,
    { method: "POST", body: form },
  );
  return response.json() as Promise<PaperUnitAnswerCreated>;
}


export async function uploadPaper(
  subjectId: string,
  file: File,
  unitCode: string,
  sourceBooklet?: File | null,
): Promise<PaperJobCreated> {
  const form = new FormData();
  form.append("file", file);
  if (sourceBooklet) form.append("source_booklet", sourceBooklet);
  if (unitCode) form.append("unit_code", unitCode);
  const response = await checkedFetch(subjectId, "/papers/answer", { method: "POST", body: form });
  return response.json() as Promise<PaperJobCreated>;
}

export async function importAnsweredPaper(
  subjectId: string,
  questionFile: File,
  answerFile: File,
  unitCode = "",
  sourceBooklet?: File | null,
): Promise<PaperJobCreated> {
  const form = new FormData();
  form.append("question_file", questionFile);
  form.append("answer_file", answerFile);
  if (sourceBooklet) form.append("source_booklet", sourceBooklet);
  if (unitCode) form.append("unit_code", unitCode);
  const response = await checkedFetch(subjectId, "/papers/import-answer", { method: "POST", body: form });
  return response.json() as Promise<PaperJobCreated>;
}

export async function uploadWorkspaceDocument(
  workspaceId: string,
  file: File,
  sourceType: string,
  options: {
    knowledgeBaseId?: string;
    licenseConfirmed?: boolean;
  } = {},
): Promise<SourceDocument> {
  const form = new FormData();
  form.append("file", file);
  form.append("source_type", sourceType);
  form.append("license_confirmed", String(options.licenseConfirmed ?? false));
  if (options.knowledgeBaseId) form.append("knowledge_base_id", options.knowledgeBaseId);
  const response = await checkedFetch(
    workspaceId,
    `/subject-workspaces/${encodeURIComponent(workspaceId)}/documents`,
    { method: "POST", body: form },
  );
  return response.json() as Promise<SourceDocument>;
}

export async function getSourceContext(
  subjectId: string,
  documentId: string,
  page: number | null,
  query: string,
  contentUrl?: string | null,
): Promise<SourceContextResult> {
  if (contentUrl) {
    const apiPath = contentUrl.startsWith("/api/v1")
      ? contentUrl.slice("/api/v1".length)
      : contentUrl;
    const response = await checkedFetch(subjectId, apiPath);
    return response.json() as Promise<SourceContextResult>;
  }
  return unwrapApi(
    apiClient.GET("/api/v1/sources/{document_id}/context", {
      headers: subjectHeaders(subjectId),
      params: {
        path: { document_id: documentId },
        query: { page, query },
      },
    }),
  );
}

export async function reviewAssessment(
  subjectId: string,
  assessmentId: string,
  request: {
    reviewer: string;
    decision: "confirm" | "override";
    override_mark: number | null;
  },
): Promise<void> {
  const response = await fetch(new Request(
    new URL(apiUrl(`/grading/reviews/${encodeURIComponent(assessmentId)}`), window.location.origin),
    {
      method: "POST",
      headers: subjectHeaders(subjectId, { "Content-Type": "application/json" }),
      body: JSON.stringify(request),
    },
  ));
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    const detail = payload && typeof payload === "object" && "detail" in payload
      ? payload.detail
      : payload;
    throw new ApiError(response.status, apiErrorMessage(detail, response.statusText));
  }
}
