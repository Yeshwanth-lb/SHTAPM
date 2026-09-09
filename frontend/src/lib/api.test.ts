import { describe, expect, it } from "vitest";

import { DEFAULT_BACKEND_PORT, resolveApiBase } from "./api";

const PI = { protocol: "http:", hostname: "192.168.1.20" };

describe("resolveApiBase", () => {
  it("uses the documented VITE_API_BASE_URL name when set", () => {
    // The previous code read VITE_API_BASE, which .env.example does not define,
    // so the configured value was silently ignored.
    expect(resolveApiBase({ VITE_API_BASE_URL: "http://10.0.0.5:9000" }, PI)).toBe(
      "http://10.0.0.5:9000",
    );
  });

  it("strips a trailing slash so paths do not double up", () => {
    expect(resolveApiBase({ VITE_API_BASE_URL: "http://10.0.0.5:9000/" }, PI)).toBe(
      "http://10.0.0.5:9000",
    );
  });

  it("derives the host from the page origin when unconfigured", () => {
    // Loading the UI from the Pi's IP must NOT send the browser to its own
    // localhost — that was the reported bug.
    expect(resolveApiBase({}, PI)).toBe(`http://192.168.1.20:${DEFAULT_BACKEND_PORT}`);
  });

  it("resolves to localhost when the page itself is on localhost", () => {
    expect(resolveApiBase({}, { protocol: "http:", hostname: "localhost" })).toBe(
      `http://localhost:${DEFAULT_BACKEND_PORT}`,
    );
  });

  it("preserves an https page's scheme", () => {
    expect(resolveApiBase({}, { protocol: "https:", hostname: "pi.local" })).toBe(
      `https://pi.local:${DEFAULT_BACKEND_PORT}`,
    );
  });

  it("defaults to port 8002, the backend's published host port", () => {
    // .env.example: container stays on 8000, host publishes 8002.
    expect(DEFAULT_BACKEND_PORT).toBe(8002);
    expect(resolveApiBase({}, PI)).toContain(":8002");
  });

  it("falls back to localhost when there is no location (non-browser context)", () => {
    expect(resolveApiBase({})).toBe(`http://localhost:${DEFAULT_BACKEND_PORT}`);
  });
});
