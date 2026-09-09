import { describe, expect, it } from "vitest";

import {
  ApiError,
  DEFAULT_BACKEND_PORT,
  describeRequestFailure,
  isApiError,
  resolveApiBase,
} from "./api";

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

describe("isApiError", () => {
  it("recognises a real ApiError", () => {
    expect(isApiError(new ApiError(401, "invalid email or password"))).toBe(true);
  });

  it("recognises an ApiError from a DUPLICATE module instance", () => {
    // The failure this guards: if lib/api.ts is evaluated twice (stale Vite
    // HMR graph, or reached via two specifiers), `instanceof` returns false and
    // a real 401 gets misreported as a network outage. A structural check does
    // not care which class object produced the error.
    const fromOtherInstance = Object.assign(new Error("invalid"), {
      isApiError: true,
      status: 401,
      name: "ApiError",
    });
    expect(isApiError(fromOtherInstance)).toBe(true);
    expect(fromOtherInstance instanceof ApiError).toBe(false); // instanceof would have failed
  });

  it("rejects a plain network error", () => {
    expect(isApiError(new TypeError("Failed to fetch"))).toBe(false);
    expect(isApiError(null)).toBe(false);
    expect(isApiError("nope")).toBe(false);
  });
});

describe("describeRequestFailure", () => {
  it("names the status for an HTTP error", () => {
    expect(describeRequestFailure(new ApiError(401, "invalid email or password"))).toBe(
      "HTTP 401: invalid email or password",
    );
  });

  it("identifies a fetch TypeError as network-or-CORS, without guessing which", () => {
    const described = describeRequestFailure(new TypeError("Failed to fetch"));
    expect(described).toContain("Network or CORS failure");
    expect(described).toContain("Failed to fetch");
  });

  it("still describes an unexpected throw rather than swallowing it", () => {
    expect(describeRequestFailure(new SyntaxError("Unexpected token <"))).toBe(
      "SyntaxError: Unexpected token <",
    );
    expect(describeRequestFailure("weird")).toBe("weird");
  });

  it("never echoes credentials it was not given", () => {
    // Guards the reporting path: only the thrown error's own text is used, so
    // a password in the request body cannot reach the message or the console.
    const described = describeRequestFailure(new TypeError("Failed to fetch"));
    expect(described).not.toContain("password");
  });
});
