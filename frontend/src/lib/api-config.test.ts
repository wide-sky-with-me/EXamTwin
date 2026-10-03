import { describe, expect, it } from "vitest";

import { API_PREFIX, resolveApiBase } from "./api-config";

describe("API runtime configuration", () => {
  it("falls back to the API prefix when the public base is absent or blank", () => {
    expect(resolveApiBase(undefined)).toBe(API_PREFIX);
    expect(resolveApiBase("   ")).toBe(API_PREFIX);
  });

  it("normalizes an explicitly configured public base", () => {
    expect(resolveApiBase(" https://api.example.test/api/v1 ")).toBe(
      "https://api.example.test/api/v1",
    );
  });

  it("drops trailing slashes so the API prefix is still recognised", () => {
    expect(resolveApiBase("https://api.example.test/api/v1/")).toBe("https://api.example.test/api/v1");
    expect(resolveApiBase("/api/v1//")).toBe(API_PREFIX);
    expect(resolveApiBase("/")).toBe(API_PREFIX);
  });

});
