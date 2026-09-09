import { describe, expect, it } from "vitest";

import { resolveWsUrl } from "./ws";

const PI = { protocol: "http:", hostname: "192.168.1.20" };

describe("resolveWsUrl", () => {
  it("uses VITE_WS_URL when set", () => {
    expect(resolveWsUrl({ VITE_WS_URL: "ws://10.0.0.5:9000/ws" }, PI)).toBe(
      "ws://10.0.0.5:9000/ws",
    );
  });

  it("derives the host from the page origin when unconfigured", () => {
    expect(resolveWsUrl({}, PI)).toBe("ws://192.168.1.20:8002/ws");
  });

  it("defaults to port 8002, not 8000", () => {
    expect(resolveWsUrl({}, PI)).toContain(":8002");
    expect(resolveWsUrl({}, PI)).not.toContain(":8000");
  });

  it("upgrades to wss on an https page so mixed content is not blocked", () => {
    expect(resolveWsUrl({}, { protocol: "https:", hostname: "pi.local" })).toBe(
      "wss://pi.local:8002/ws",
    );
  });

  it("falls back to localhost when there is no location", () => {
    expect(resolveWsUrl({})).toBe("ws://localhost:8002/ws");
  });
});
