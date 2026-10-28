// Smoothly tweens a displayed number toward its latest value (D052).
//
// Presentation only: the TRUE value is always the target, and the tween lands
// on it exactly. A big jump (an attack pinning current to 0 A) reads as a
// fast, visible slide rather than a teleport; reduced motion skips the tween.
import { useEffect, useRef, useState } from "react";

const DURATION_MS = 450;

function reducedMotion(): boolean {
  if (typeof window === "undefined") return true;
  const root = document.documentElement.dataset.motion;
  if (root === "reduce" || root === "off") return true;
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

const easeOutCubic = (t: number) => 1 - (1 - t) ** 3;

/** ``countUp``: on first appearance, count up from 0 to the value (page-open
 *  motion, D052); later changes glide from the previous value as usual. */
export function useAnimatedNumber(
  target: number | null,
  durationMs = DURATION_MS,
  { countUp = false }: { countUp?: boolean } = {},
): number | null {
  const startAtZero = countUp && target !== null && !reducedMotion();
  const [shown, setShown] = useState<number | null>(startAtZero ? 0 : target);
  const fromRef = useRef<number | null>(startAtZero ? 0 : target);
  const firstRef = useRef(startAtZero);
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    const from = fromRef.current;
    if (target === null || from === null || !Number.isFinite(from) || reducedMotion()) {
      fromRef.current = target;
      setShown(target);
      return;
    }
    const duration = firstRef.current ? Math.max(durationMs, 900) : durationMs;
    firstRef.current = false;
    const start = performance.now();
    const step = (now: number) => {
      // Clamp BOTH ends: a frame timestamp can precede ``start`` (it marks the
      // frame's beginning), and an unclamped negative t extrapolates the
      // easing far outside [from, target] -- seen as 3.3e9 g in a capture.
      const t = Math.max(0, Math.min(1, (now - start) / duration));
      const value = t >= 1 ? target : from + (target - from) * easeOutCubic(t);
      fromRef.current = value;
      setShown(value);
      if (t < 1) frameRef.current = requestAnimationFrame(step);
      else frameRef.current = null;
    };
    frameRef.current = requestAnimationFrame(step);
    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    };
  }, [target, durationMs]);

  return shown;
}
