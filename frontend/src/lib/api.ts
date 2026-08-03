const API_BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";

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

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = init?.body instanceof FormData;
  const response = await fetch(`${API_BASE}${path}`, {
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
  return response.json() as Promise<T>;
}
