export const API_PREFIX = "/api/v1";

export function resolveApiBase(value: string | undefined): string {
  // A base such as "https://host/api/v1/" must still be recognised as ending in the prefix,
  // otherwise generated client paths would repeat "/api/v1".
  return value?.trim().replace(/\/+$/, "") || API_PREFIX;
}
