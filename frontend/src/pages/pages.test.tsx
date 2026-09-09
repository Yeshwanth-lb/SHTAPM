import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../features/auth/AuthContext";
import * as api from "../lib/api";
import { AlertsPage } from "./AlertsPage";
import { DevicesPage } from "./DevicesPage";
import { HistoryPage } from "./HistoryPage";
import { redactUrl, SettingsPage } from "./SettingsPage";
import { UsersPage } from "./UsersPage";

function withAuth(node: React.ReactElement) {
  window.localStorage.setItem(
    "shtapm.auth",
    JSON.stringify({ accessToken: "acc", refreshToken: "ref" }),
  );
  return render(<AuthProvider>{node}</AuthProvider>);
}

beforeEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("DevicesPage", () => {
  it("shows an empty state rather than a bare table", async () => {
    vi.spyOn(api, "apiGet").mockResolvedValue([] as never);
    withAuth(<DevicesPage />);
    await waitFor(() => expect(screen.getByTestId("state-empty")).toBeInTheDocument());
  });

  it("renders real device rows", async () => {
    vi.spyOn(api, "apiGet").mockResolvedValue([
      {
        id: "u1",
        device_id: "pump-01",
        name: "Pump 01",
        location: null,
        owner_user_id: null,
        status: "online",
        health_state: "healthy",
        last_seen_at: "2026-09-10T12:00:00Z",
        sample_rate_hz: 1,
        created_at: "2026-09-01T00:00:00Z",
      },
    ] as never);
    withAuth(<DevicesPage />);
    await waitFor(() => expect(screen.getByTestId("device-row-pump-01")).toBeInTheDocument());
    expect(screen.getByTestId("devices-count")).toHaveTextContent("1 registered");
  });

  it("surfaces a load failure as an error, not as emptiness", async () => {
    vi.spyOn(api, "apiGet").mockRejectedValue(new api.ApiError(500, "boom"));
    withAuth(<DevicesPage />);
    await waitFor(() => expect(screen.getByTestId("state-error")).toBeInTheDocument());
    expect(screen.queryByTestId("state-empty")).toBeNull();
  });
});

describe("AlertsPage", () => {
  it("explains WHY it is empty instead of implying all is well", async () => {
    vi.spyOn(api, "apiGet").mockResolvedValue([] as never);
    withAuth(<AlertsPage />);
    await waitFor(() => expect(screen.getByTestId("state-empty")).toBeInTheDocument());
    expect(screen.getByTestId("state-empty")).toHaveTextContent("not the same as no faults");
  });

  it("renders a real alert row when one exists", async () => {
    vi.spyOn(api, "apiGet").mockResolvedValue([
      {
        id: "a1",
        device_id: "pump-01",
        ts: "2026-09-10T12:00:00Z",
        severity: "critical",
        type: "fault",
        channel: "vibration",
        message: "bearing",
        reason: null,
        acknowledged_by: null,
        acknowledged_at: null,
      },
    ] as never);
    withAuth(<AlertsPage />);
    await waitFor(() => expect(screen.getByTestId("alert-row-a1")).toBeInTheDocument());
  });
});

describe("UsersPage", () => {
  it("treats 403 as RBAC working, not as an error", async () => {
    vi.spyOn(api, "apiGet").mockRejectedValue(new api.ApiError(403, "forbidden"));
    withAuth(<UsersPage />);
    await waitFor(() => expect(screen.getByTestId("state-notice")).toBeInTheDocument());
    expect(screen.queryByTestId("state-error")).toBeNull();
  });

  it("lists accounts with role and status", async () => {
    vi.spyOn(api, "apiGet").mockResolvedValue([
      {
        id: "u1",
        email: "admin@shtapm.local",
        full_name: "Admin",
        role: "admin",
        is_active: true,
        created_at: "2026-09-01T00:00:00Z",
        last_login_at: null,
      },
    ] as never);
    withAuth(<UsersPage />);
    await waitFor(() =>
      expect(screen.getByTestId("user-row-admin@shtapm.local")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("users-table")).toHaveTextContent("admin");
    expect(screen.getByTestId("users-table")).toHaveTextContent("never");
  });
});

describe("HistoryPage", () => {
  it("always requests a bounded page", async () => {
    const spy = vi.spyOn(api, "apiGet").mockResolvedValue([] as never);
    withAuth(<HistoryPage />);
    await waitFor(() => expect(spy).toHaveBeenCalled());
    // Never an unbounded query: at 1 Hz that is ~86k rows/day.
    expect(String(spy.mock.calls[0][0])).toContain("limit=50");
  });

  it("shows an empty state when nothing is stored", async () => {
    vi.spyOn(api, "apiGet").mockResolvedValue([] as never);
    withAuth(<HistoryPage />);
    await waitFor(() => expect(screen.getByTestId("state-empty")).toBeInTheDocument());
  });
});

describe("SettingsPage", () => {
  it("shows the resolved connection targets", async () => {
    withAuth(<SettingsPage />);
    await waitFor(() => expect(screen.getByTestId("setting-api-base")).toBeInTheDocument());
    expect(screen.getByTestId("setting-ws-url")).toBeInTheDocument();
  });

  it("exposes a real, working motion preference", async () => {
    withAuth(<SettingsPage />);
    const box = await screen.findByTestId("setting-reduce-motion");
    expect(box).toBeInTheDocument();
  });
});

describe("redactUrl", () => {
  it("strips credentials and token-like query parameters", () => {
    expect(redactUrl("http://user:pw@host:8002/api")).toContain("***");
    expect(redactUrl("ws://host:8002/ws?token=abc123")).not.toContain("abc123");
  });

  it("leaves an ordinary URL alone", () => {
    expect(redactUrl("http://192.168.1.20:8002")).toBe("http://192.168.1.20:8002/");
  });

  it("returns a non-URL string unchanged rather than throwing", () => {
    expect(redactUrl("not a url")).toBe("not a url");
  });
});
