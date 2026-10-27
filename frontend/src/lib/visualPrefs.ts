// Aurora performance and accessibility switches (TRD §02.7 / §02.9, Doc06 P5/P6).
//
// Three attributes on <html>, read only by CSS (styles/aurora.css):
//
//   data-motion        full | reduce | off
//       VITE_AURORA_MOTION (full | reduced | off) sets the deployment default;
//       the Settings page's "Reduce motion" switch lowers it per browser.
//       The operating system's prefers-reduced-motion is always honoured too.
//   data-transparency  reduced   when VITE_REDUCE_TRANSPARENCY_DEFAULT is on:
//       glass becomes opaque (no backdrop blur), every value still shown.
//   data-perf          degraded  set by FpsGuard when the page renders under
//       50 fps for two consecutive seconds: glow and blur are shed, orbs
//       freeze. Effects lose, the data path never does (TRD §02.9 rule).
//
// Nothing here touches data, sockets or polling.

export type MotionLevel = "full" | "reduce" | "off";

export const MOTION_STORAGE_KEY = "shtapm.pref.motion";
export const FPS_FLOOR = 50; // TRD §02.9: "fps < 50" -> downgrade
const FPS_SAMPLE_MS = 1_000;
const FPS_STRIKES = 2; // two consecutive slow seconds, not one hiccup

interface Env {
  VITE_AURORA_MOTION?: string;
  VITE_REDUCE_TRANSPARENCY_DEFAULT?: string;
}

function deploymentMotion(env: Env): MotionLevel {
  switch ((env.VITE_AURORA_MOTION ?? "full").trim().toLowerCase()) {
    case "off":
      return "off";
    case "reduced":
    case "reduce":
      return "reduce";
    default:
      return "full";
  }
}

/** The stricter of the deployment default and this browser's own choice. */
export function resolveMotion(env: Env, stored: string | null): MotionLevel {
  const base = deploymentMotion(env);
  if (base === "off") return "off";
  if (stored === "reduce") return "reduce";
  return base;
}

export function transparencyReduced(env: Env): boolean {
  const raw = (env.VITE_REDUCE_TRANSPARENCY_DEFAULT ?? "").trim().toLowerCase();
  return raw === "true" || raw === "on" || raw === "1";
}

function storedMotion(): string | null {
  try {
    return window.localStorage.getItem(MOTION_STORAGE_KEY);
  } catch {
    return null;
  }
}

/** Apply the deployment and stored preferences to <html>. Call once at startup,
 * and again whenever the Settings switch changes. */
export function applyVisualPrefs(
  env: Env = import.meta.env as Env,
  root: HTMLElement = document.documentElement,
): void {
  root.dataset.motion = resolveMotion(env, storedMotion());
  if (transparencyReduced(env)) root.dataset.transparency = "reduced";
  else delete root.dataset.transparency;
}

type Frame = (callback: (time: number) => void) => number;

/** Sheds visual effects when the page cannot hold 50 fps. Sticky for the
 * session: flipping effects back on could start the stutter again. */
export class FpsGuard {
  private frames = 0;
  private windowStart: number | null = null;
  private strikes = 0;
  private running = false;
  degraded = false;

  constructor(
    private readonly root: HTMLElement = document.documentElement,
    private readonly requestFrame: Frame = (cb) => window.requestAnimationFrame(cb),
  ) {}

  start(): void {
    if (this.running) return;
    this.running = true;
    this.requestFrame(this.tick);
  }

  stop(): void {
    this.running = false;
  }

  private readonly tick = (time: number): void => {
    if (!this.running) return;
    if (this.windowStart === null) this.windowStart = time;
    this.frames += 1;
    const elapsed = time - this.windowStart;
    if (elapsed >= FPS_SAMPLE_MS) {
      const fps = (this.frames * 1000) / elapsed;
      this.strikes = fps < FPS_FLOOR ? this.strikes + 1 : 0;
      this.frames = 0;
      this.windowStart = time;
      if (this.strikes >= FPS_STRIKES) {
        this.degraded = true;
        this.root.dataset.perf = "degraded";
        this.running = false; // done: the downgrade is sticky
        return;
      }
    }
    this.requestFrame(this.tick);
  };
}
