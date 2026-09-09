import { beforeEach, describe, expect, it } from "vitest";

import { currentPath, navigate } from "./router";

describe("hash router", () => {
  beforeEach(() => {
    window.location.hash = "";
  });

  it("treats an empty hash as the root path", () => {
    expect(currentPath()).toBe("/");
  });

  it("reads the hash without its leading #", () => {
    window.location.hash = "#/login";
    expect(currentPath()).toBe("/login");
  });

  it("navigates by setting the hash", () => {
    navigate("/settings");
    expect(currentPath()).toBe("/settings");
  });

  it("is a no-op when already on the target path", () => {
    navigate("/settings");
    navigate("/settings");
    expect(currentPath()).toBe("/settings");
  });
});
