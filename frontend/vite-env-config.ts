export function resolveApiProxyTarget(
  value: string | undefined,
  apiPort: string | undefined,
): string {
  return value?.trim() || `http://127.0.0.1:${apiPort?.trim() || "8000"}`;
}
