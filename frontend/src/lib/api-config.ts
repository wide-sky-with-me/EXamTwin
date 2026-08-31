export const API_PREFIX = "/api/v1";

export function resolveApiBase(value: string | undefined): string {
  return value?.trim() || API_PREFIX;
}
