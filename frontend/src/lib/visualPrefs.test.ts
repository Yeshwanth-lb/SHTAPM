import { afterEach, describe, expect, it } from "vitest";

import {
  applyVisualPrefs,
  FPS_FLOOR,
  FpsGuard,
  MOTION_STORAGE_KEY,
  resolveMotion,
  transparencyReduced,
} from "./visualPrefs";

afterEach(() => {
  window.localStorage.clear();
  delete document.documentElement.dataset.motion;
  delete document.documentElement.dataset.transparency;
  delete document.documentElement.dataset.perf;
});

describe("motion level", () => {
  it("follows VITE_AURORA_MOTION, defaulting to full", () => {
    expect(resolveMotion({}, null)).toBe("full");
    expect(resolveMotion({ VITE_AURORA_MOTION: "reduced" }, null)).toBe("reduce");
    expect(resolveMotion({ VITE_AURORA_MOTION: "off" }, null)).toBe("off");
    expect(resolveMotion({ VITE_AURORA_MOTION: "nonsense" }, null)).toBe("full");
  });

  it("lets a browser reduce motion but never re-enable a deployment's 'off'", () => {
    expect(resolveMotion({ VITE_AURORA_MOTION: "full" }, "reduce")).toBe("reduce");
    expect(resolveMotion({ VITE_AURORA_MOTION: "off" }, "full")).toBe("off");
    expect(resolveMotion({ VITE_AURORA_MOTION: "reduced" }, "full")).toBe("reduce");
  });
});

describe("transparency", () => {
  it("is reduced only when explicitly switched on", () => {
    expect(transparencyReduced({})).toBe(false);
    expect(transparencyReduced({ VITE_REDUCE_TRANSPARENCY_DEFAULT: "false" })).toBe(false);
    for (const on of ["true", "on", "1", " TRUE "]) {
      expect(transparencyReduced({ VITE_REDUCE_TRANSPARENCY_DEFAULT: on })).toBe(true);
    }
  });
});

describe("applyVisualPrefs", () => {
  it("writes the attributes the stylesheet reads", () => {
    window.localStorage.setItem(MOTION_STORAGE_KEY, "reduce");
    applyVisualPrefs({ VITE_REDUCE_TRANSPARENCY_DEFAULT: "on" });
    expect(document.documentElement.dataset.motion).toBe("reduce");
    expect(document.documentElement.dataset.transparency).toBe("reduced");
    applyVisualPrefs({});
    expect(document.documentElement.dataset.transparency).toBeUndefined();
  });
});

describe("FpsGuard", () => {
  // Drives the guard with synthetic frame times instead of a real browser loop.
  function run(frames: number[]): FpsGuard {
    const queue: Array<(t: number) => void> = [];
    const g = new FpsGuard(document.documentElement, (cb) => {
      queue.push(cb);
      return queue.length;
    });
    g.start();
    for (const t of frames) {
      const cb = queue.shift();
      if (!cb) break;
      cb(t);
    }
    return g;
  }

  const at = (fps: number, seconds: number) =>
    Array.from({ length: Math.round(fps * seconds) + 1 }, (_, i) => (i * 1000) / fps);

  it("sheds effects after two consecutive seconds under 50 fps", () => {
    const guard = run(at(30, 2.5));
    expect(guard.degraded).toBe(true);
    expect(document.documentElement.dataset.perf).toBe("degraded");
  });

  it("leaves a smooth page alone", () => {
    const guard = run(at(60, 5));
    expect(guard.degraded).toBe(false);
    expect(document.documentElement.dataset.perf).toBeUndefined();
  });

  it("forgives a single slow second", () => {
    const frames = [...at(30, 1), ...at(60, 3).map((t) => t + 1000)];
    expect(run(frames).degraded).toBe(false);
  });

  it("uses the TRD floor", () => {
    expect(FPS_FLOOR).toBe(50);
  });
});
