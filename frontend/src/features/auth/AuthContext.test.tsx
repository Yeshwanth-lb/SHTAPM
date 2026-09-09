import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../../lib/api";
import { AuthProvider, useAuth } from "./AuthContext";

function Probe() {
  const { isAuthenticated, isRestoring, tokens, signIn, signOut } = useAuth();
  return (
    <div>
      <span data-testid="state">{isRestoring ? "restoring" : isAuthenticated ? "in" : "out"}</span>
      <span data-testid="access">{tokens?.accessToken ?? ""}</span>
      <button onClick={() => void signIn("a@b.c", "pw")}>in</button>
      <button onClick={() => void signOut()}>out</button>
    </div>
  );
}

describe("AuthProvider", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it("starts signed out when nothing is stored", async () => {
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("out"));
  });

  it("restores a stored session on mount", async () => {
    window.localStorage.setItem(
      "shtapm.auth",
      JSON.stringify({ accessToken: "acc", refreshToken: "ref" }),
    );
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("in"));
    expect(screen.getByTestId("access")).toHaveTextContent("acc");
  });

  it("treats corrupt stored JSON as signed out rather than throwing", async () => {
    window.localStorage.setItem("shtapm.auth", "{not json");
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("out"));
  });

  it("stores tokens from the real login response shape", async () => {
    vi.spyOn(api, "login").mockResolvedValue({
      access_token: "A",
      refresh_token: "R",
      token_type: "bearer",
    });
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("out"));
    await act(async () => {
      screen.getByText("in").click();
    });
    await waitFor(() => expect(screen.getByTestId("access")).toHaveTextContent("A"));
    expect(window.localStorage.getItem("shtapm.auth")).toContain("R");
  });

  it("signs out locally even when the server revoke call fails", async () => {
    vi.spyOn(api, "login").mockResolvedValue({
      access_token: "A",
      refresh_token: "R",
      token_type: "bearer",
    });
    vi.spyOn(api, "logout").mockRejectedValue(new Error("unreachable"));

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("out"));
    await act(async () => {
      screen.getByText("in").click();
    });
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("in"));

    await act(async () => {
      screen.getByText("out").click();
    });
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("out"));
    expect(window.localStorage.getItem("shtapm.auth")).toBeNull();
  });
});
