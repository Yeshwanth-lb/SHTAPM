import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import * as api from "../lib/api";

/** Sign in without a backend by seeding the stored session. */
function signedIn() {
  window.localStorage.setItem(
    "shtapm.auth",
    JSON.stringify({ accessToken: "acc", refreshToken: "ref" }),
  );
}

describe("route table", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.location.hash = "";
    vi.restoreAllMocks();
    // Every page fetches on mount; keep them from hitting a real network.
    vi.spyOn(api, "apiGet").mockResolvedValue([] as never);
    vi.spyOn(api, "getHealthz").mockResolvedValue({
      status: "ok",
      mqtt_connected: true,
      db_connected: true,
      db_error: null,
      telemetry_count: 9,
      devices: ["pump-01"],
      ws_clients: 1,
    });
  });

  it("shows the login screen when signed out", async () => {
    window.location.hash = "#/login";
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("login-submit")).toBeInTheDocument());
  });

  it("renders an unknown path as not-found, never a blank shell", async () => {
    signedIn();
    window.location.hash = "#/nope";
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("not-found")).toBeInTheDocument());
  });

  it.each([
    ["#/devices", "Devices"],
    ["#/history", "Telemetry history"],
    ["#/alerts", "Alerts"],
    ["#/users", "Users"],
    ["#/system", "System"],
    ["#/settings", "Settings"],
  ])("routes %s to its page", async (hash, heading) => {
    signedIn();
    window.location.hash = hash;
    render(<App />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1, name: heading })).toBeInTheDocument(),
    );
  });

  it("only enables nav items whose pages exist", async () => {
    signedIn();
    window.location.hash = "#/";
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("nav-devices")).toBeInTheDocument());
    // Backed by a working endpoint -> enabled.
    expect(screen.getByTestId("nav-devices")).not.toBeDisabled();
    expect(screen.getByTestId("nav-system")).not.toBeDisabled();
    // Ledger has no producer yet, so it must stay disabled rather than lead to
    // a page that would always be empty.
    expect(screen.getByTestId("nav-ledger")).toBeDisabled();
  });
});
