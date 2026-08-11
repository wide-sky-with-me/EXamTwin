import createClient from "openapi-fetch";

import type { paths } from "../generated/openapi";
import type {
  PaperJobCreated,
  PaperJobBulkDeleteResult,
  PaperJobHistoryStatus,
  PaperJobList,
  PaperJobResult,
  SourceContextResult,
  SourceDocument,
} from "../types";
const API_BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";
export const SUBJECT_STORAGE_KEY = "examtwin.subject";
let activeSubject = window.localStorage.getItem(SUBJECT_STORAGE_KEY) || null;

export function setApiSubject(subject: string | null): void {
  activeSubject = subject;
  if (subject) window.localStorage.setItem(SUBJECT_STORAGE_KEY, subject);
  else window.localStorage.removeItem(SUBJECT_STORAGE_KEY);
}

export function getApiSubject(): string | null {
  return activeSubject;
}

function subjectHeaders(headers?: HeadersInit): Headers {
  const result = new Headers(headers);
  if (activeSubject) result.set("X-ExamTwin-Subject", activeSubject);
  return result;
}
const RESOLVED_API_BASE = new URL(API_BASE, window.location.origin);
const API_ORIGIN = API_BASE.endsWith("/api/v1")
  ? RESOLVED_API_BASE.href.slice(0, -"/api/v1".length)
  : RESOLVED_API_BASE.href.replace(/\/$/, "");
export const apiClient = createClient<paths>({
  baseUrl: API_ORIGIN,
  fetch: (request: Request) => globalThis.fetch(
    new Request(request, { headers: subjectHeaders(request.headers) }),
  ),
});

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export function websocketUrl(path: string): string {
  const url = new URL(apiUrl(path), window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  if (activeSubject) url.searchParams.set("subject", activeSubject);
  return url.toString();
}

export function backendResourceUrl(path: string): string {
  const apiPath = path.startsWith("/api/v1") ? path.slice("/api/v1".length) : path;
  const resource = apiUrl(apiPath.startsWith("/") ? apiPath : `/${apiPath}`);
  if (!activeSubject) return resource;
  const separator = resource.includes("?") ? "&" : "?";
  return `${resource}${separator}subject=${encodeURIComponent(activeSubject)}`;
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

async function checkedFetch(path: string, init?: RequestInit): Promise<Response> {
  const isFormData = init?.body instanceof FormData;
  const response = await fetch(new URL(`${API_BASE}${path}`, window.location.origin), {
    ...init,
    headers: isFormData
      ? subjectHeaders(init?.headers)
      : subjectHeaders({
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
  unitCode?: string;
  query?: string;
  createdAfter?: string;
  limit?: number;
  offset?: number;
};

export async function listPaperJobs(
  filters: PaperJobHistoryFilters = {},
): Promise<PaperJobList> {
  return unwrapApi(
    apiClient.GET("/api/v1/papers/jobs", {
      params: {
        query: {
          status: filters.status,
          unit_code: filters.unitCode,
          q: filters.query,
          created_after: filters.createdAfter,
          limit: filters.limit,
          offset: filters.offset,
        },
      },
    }),
  );
}

export async function deletePaperJobs(jobIds: string[]): Promise<PaperJobBulkDeleteResult> {
  return unwrapApi(
    apiClient.POST("/api/v1/papers/jobs/bulk-delete", {
      body: { job_ids: jobIds },
    }),
  );
}

export async function renamePaperJob(jobId: string, displayName: string): Promise<PaperJobResult> {
  return await unwrapApi(
    apiClient.PATCH("/api/v1/papers/jobs/{job_id}", {
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
      params: { path: { workspace_id: workspaceId, document_id: documentId } },
      body: { display_name: displayName },
    }),
  );
}

export async function replacePaperJob(jobId: string): Promise<PaperJobCreated> {
  return unwrapApi(
    apiClient.POST("/api/v1/papers/jobs/{job_id}/replace", {
      params: { path: { job_id: jobId } },
    }),
  );
}


export async function uploadPaper(file: File, unitCode: string): Promise<PaperJobCreated> {
  const form = new FormData();
  form.append("file", file);
  if (unitCode) form.append("unit_code", unitCode);
  const response = await checkedFetch("/papers/answer", { method: "POST", body: form });
  return response.json() as Promise<PaperJobCreated>;
}

export async function importAnsweredPaper(
  questionFile: File,
  answerFile: File,
  unitCode = "",
): Promise<PaperJobCreated> {
  const form = new FormData();
  form.append("question_file", questionFile);
  form.append("answer_file", answerFile);
  if (unitCode) form.append("unit_code", unitCode);
  const response = await checkedFetch("/papers/import-answer", { method: "POST", body: form });
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
    `/subject-workspaces/${encodeURIComponent(workspaceId)}/documents`,
    { method: "POST", body: form },
  );
  return response.json() as Promise<SourceDocument>;
}

export async function getSourceContext(
  documentId: string,
  page: number | null,
  query: string,
  contentUrl?: string | null,
): Promise<SourceContextResult> {
  if (contentUrl) {
    const apiPath = contentUrl.startsWith("/api/v1")
      ? contentUrl.slice("/api/v1".length)
      : contentUrl;
    const response = await checkedFetch(apiPath);
    return response.json() as Promise<SourceContextResult>;
  }
  return unwrapApi(
    apiClient.GET("/api/v1/sources/{document_id}/context", {
      params: {
        path: { document_id: documentId },
        query: { page, query },
      },
    }),
  );
}
