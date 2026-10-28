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

export function useAnimatedNumber(target: number | null, durationMs = DURATION_MS): number | null {
  const [shown, setShown] = useState<number | null>(target);
  const fromRef = useRef<number | null>(target);
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    const from = fromRef.current;
    if (target === null || from === null || !Number.isFinite(from) || reducedMotion()) {
      fromRef.current = target;
      setShown(target);
      return;
    }
    const start = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
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
