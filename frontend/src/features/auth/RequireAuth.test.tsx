import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { currentPath } from "../../app/router";
import { AuthProvider } from "./AuthContext";
import { RequireAuth } from "./RequireAuth";

function Secret() {
  return <p data-testid="secret">protected</p>;
}

describe("RequireAuth", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.location.hash = "";
  });

  it("redirects an unauthenticated visitor to /login", async () => {
    render(
      <AuthProvider>
        <RequireAuth>
          <Secret />
        </RequireAuth>
      </AuthProvider>,
    );
    await waitFor(() => expect(currentPath()).toBe("/login"));
    expect(screen.queryByTestId("secret")).toBeNull();
  });

  it("renders protected content for a restored session", async () => {
    window.localStorage.setItem(
      "shtapm.auth",
      JSON.stringify({ accessToken: "acc", refreshToken: "ref" }),
    );
    render(
      <AuthProvider>
        <RequireAuth>
          <Secret />
        </RequireAuth>
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("secret")).toBeInTheDocument());
    expect(currentPath()).not.toBe("/login");
  });

  it("never bounces a stored session to /login while restoring", () => {
    // The regression this guards: reading tokens from localStorage happens in
    // an effect, so a guard that redirects on the first `!isAuthenticated`
    // would flash an already-signed-in user to the login screen on every page
    // reload. `isRestoring` must suppress that.
    window.localStorage.setItem(
      "shtapm.auth",
      JSON.stringify({ accessToken: "acc", refreshToken: "ref" }),
    );
    render(
      <AuthProvider>
        <RequireAuth>
          <Secret />
        </RequireAuth>
      </AuthProvider>,
    );
    expect(currentPath()).not.toBe("/login");
  });
});
