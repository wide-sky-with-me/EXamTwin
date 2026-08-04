import createClient from "openapi-fetch";

import type { paths } from "../generated/openapi";
import type { PaperJobCreated, SourceContextResult } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";
const RESOLVED_API_BASE = new URL(API_BASE, window.location.origin);
const API_ORIGIN = API_BASE.endsWith("/api/v1")
  ? RESOLVED_API_BASE.href.slice(0, -"/api/v1".length)
  : RESOLVED_API_BASE.href.replace(/\/$/, "");
export const apiClient = createClient<paths>({
  baseUrl: API_ORIGIN,
  fetch: (...arguments_) => globalThis.fetch(...arguments_),
});

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export function websocketUrl(path: string): string {
  const url = new URL(apiUrl(path), window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export function backendResourceUrl(path: string): string {
  const apiPath = path.startsWith("/api/v1") ? path.slice("/api/v1".length) : path;
  return apiUrl(apiPath.startsWith("/") ? apiPath : `/${apiPath}`);
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function checkedFetch(path: string, init?: RequestInit): Promise<Response> {
  const isFormData = init?.body instanceof FormData;
  const response = await fetch(new URL(`${API_BASE}${path}`, window.location.origin), {
    ...init,
    headers: isFormData
      ? init?.headers
      : {
          "Content-Type": "application/json",
          ...init?.headers,
        },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(response.status, payload.detail ?? response.statusText);
  }
  return response;
}

export async function unwrapApi<Data, ErrorPayload>(
  request: Promise<{ data?: Data; error?: ErrorPayload; response: Response }>,
): Promise<Data> {
  const { data, error, response } = await request;
  if (!response.ok || data === undefined) {
    const detail =
      error && typeof error === "object" && "detail" in error
        ? String(error.detail)
        : response.statusText;
    throw new ApiError(response.status, detail);
  }
  return data;
}

export async function uploadPaper(file: File, unitCode: string): Promise<PaperJobCreated> {
  const form = new FormData();
  form.append("file", file);
  if (unitCode) form.append("unit_code", unitCode);
  const response = await checkedFetch("/papers/answer", { method: "POST", body: form });
  return response.json() as Promise<PaperJobCreated>;
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
