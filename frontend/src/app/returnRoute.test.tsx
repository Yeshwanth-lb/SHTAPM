// AC10 P5-12: expired session -> login with a notice -> back to the same page.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../features/auth/AuthContext";
import { LoginScreen } from "../features/auth/LoginScreen";
import { RequireAuth } from "../features/auth/RequireAuth";
import * as api from "../lib/api";
import { currentPath, peekReturnPath, rememberReturnPath, takeReturnPath } from "./router";

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.location.hash = "";
  vi.restoreAllMocks();
});

describe("return path", () => {
  it("only keeps in-app paths", () => {
    rememberReturnPath("/system");
    expect(peekReturnPath()).toBe("/system");
    expect(takeReturnPath()).toBe("/system");
    expect(takeReturnPath()).toBeNull(); // consumed once
    for (const bad of ["//evil.example", "https://evil.example", "/login", "/"]) {
      rememberReturnPath(bad);
      expect(peekReturnPath()).toBeNull();
    }
  });

  it("is remembered when the guard sends a signed-out user to login", async () => {
    window.location.hash = "/ledger";
    render(
      <AuthProvider>
        <RequireAuth>
          <p>secret</p>
        </RequireAuth>
      </AuthProvider>,
    );
    await waitFor(() => expect(currentPath()).toBe("/login"));
    expect(peekReturnPath()).toBe("/ledger");
  });

  it("brings the user back after signing in, and says so first", async () => {
    window.location.hash = "/login";
    rememberReturnPath("/decisions");
    vi.spyOn(api, "login").mockResolvedValue({
      access_token: "acc",
      refresh_token: "ref",
      token_type: "bearer",
    } as never);
    render(
      <AuthProvider>
        <LoginScreen />
      </AuthProvider>,
    );
    expect(screen.getByTestId("login-return-notice")).toHaveTextContent("/decisions");
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "a@b.c" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "pw" } });
    fireEvent.submit(screen.getByLabelText(/password/i).closest("form")!);
    await waitFor(() => expect(currentPath()).toBe("/decisions"));
    expect(peekReturnPath()).toBeNull();
  });
});
