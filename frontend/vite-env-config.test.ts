import { describe, expect, it } from "vitest";

import { resolveApiProxyTarget } from "./vite-env-config";

describe("Vite proxy configuration", () => {
  it("falls back to the configured API port when the proxy target is blank", () => {
    expect(resolveApiProxyTarget(undefined, undefined)).toBe(
      "http://127.0.0.1:8000",
    );
    expect(resolveApiProxyTarget("  ", " 9000 ")).toBe(
      "http://127.0.0.1:9000",
    );
  });

  it("normalizes an explicitly configured proxy target", () => {
    expect(resolveApiProxyTarget(" http://api:8080 ", "9000")).toBe(
      "http://api:8080",
    );
  });
});
