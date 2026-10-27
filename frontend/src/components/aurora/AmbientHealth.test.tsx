import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../../features/auth/AuthContext";
import * as api from "../../lib/api";
import { AmbientHealth } from "./AmbientHealth";

beforeEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("AmbientHealth (D043)", () => {
  it("stays neutral when signed out and asks for nothing", () => {
    const spy = vi.spyOn(api, "apiGet");
    render(
      <AuthProvider>
        <AmbientHealth />
      </AuthProvider>,
    );
    expect(screen.getByTestId("mesh-background").className).toContain("mesh--healthy");
    expect(spy).not.toHaveBeenCalled();
  });

  it("follows the device's computed condition", async () => {
    window.localStorage.setItem(
      "shtapm.auth",
      JSON.stringify({ accessToken: "acc", refreshToken: "ref" }),
    );
    vi.spyOn(api, "apiGet").mockResolvedValue({ health_state: "critical" } as never);
    render(
      <AuthProvider>
        <AmbientHealth />
      </AuthProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("mesh-background").className).toContain("mesh--critical"),
    );
  });
});
