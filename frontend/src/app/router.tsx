// Minimal hash router.
//
// WHY NOT react-router: adding a dependency is gated by CLAUDE.md ("do not
// introduce major technologies or dependencies without asking first"), and
// Doc04/the P5 TODO name Tailwind, shadcn/Radix, Framer, uPlot and ECharts
// but no router. This slice needs two routes and a guard, which is ~40 lines.
// Swapping in react-router later touches only this file and <Nav>.
//
// Hash-based (#/path) so the built SPA works from any static host without
// server rewrite rules — including `vite preview` and the nginx config
// already in frontend/nginx.conf.
import { useCallback, useEffect, useState } from "react";

export function currentPath(): string {
  const hash = window.location.hash.replace(/^#/, "");
  return hash.length > 0 ? hash : "/";
}

export function navigate(path: string): void {
  if (currentPath() === path) return;
  window.location.hash = path;
}

/** Subscribes to hashchange and re-renders on navigation. */
export function useRoute(): { path: string; navigate: (to: string) => void } {
  const [path, setPath] = useState<string>(() => currentPath());

  useEffect(() => {
    const onChange = () => setPath(currentPath());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  const go = useCallback((to: string) => navigate(to), []);
  return { path, navigate: go };
}

// Return route (AC10 P5-12): the auth guard remembers where a signed-out user
// was, and the login screen sends them back there. Only in-app hash paths are
// accepted, so this can never redirect off-site.
const RETURN_KEY = "shtapm.returnTo";

function validReturn(path: string | null): string | null {
  return path && path.startsWith("/") && !path.startsWith("//") && path !== "/login" ? path : null;
}

export function rememberReturnPath(path: string = currentPath()): void {
  const valid = validReturn(path);
  if (!valid || valid === "/") return;
  try {
    window.sessionStorage.setItem(RETURN_KEY, valid);
  } catch {
    /* storage unavailable: the user lands on the overview instead */
  }
}

export function peekReturnPath(): string | null {
  try {
    return validReturn(window.sessionStorage.getItem(RETURN_KEY));
  } catch {
    return null;
  }
}

export function takeReturnPath(): string | null {
  const path = peekReturnPath();
  try {
    window.sessionStorage.removeItem(RETURN_KEY);
  } catch {
    /* nothing to clear */
  }
  return path;
}
