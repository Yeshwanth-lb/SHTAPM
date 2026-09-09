// Protected layout: sidebar rail + top bar + content slot (Doc04 §04.4).
//
// Nav entries whose screens are not built yet are marked `phase` and render
// disabled with the phase they belong to. That is deliberate: an enabled link
// to an empty page reads as broken, a labelled one reads as scoped. Nothing
// here fabricates a screen that has no data behind it.
import type { ReactNode } from "react";

import { useAuth } from "../features/auth/AuthContext";
import { navigate, useRoute } from "./router";
import "./shell.css";

interface NavItem {
  label: string;
  path: string;
  /** Set when the screen is not implemented yet — renders disabled. */
  phase?: string;
}

// Paths mirror the screens Doc03/Doc04 describe. Only Overview is routable in
// this foundation slice.
const NAV: NavItem[] = [
  { label: "Overview", path: "/" },
  { label: "Device", path: "/device", phase: "next" },
  { label: "Devices", path: "/devices", phase: "next" },
  { label: "Ledger", path: "/ledger", phase: "next" },
  { label: "Settings", path: "/settings", phase: "next" },
  { label: "Users", path: "/users", phase: "next" },
  { label: "System", path: "/system", phase: "next" },
  { label: "Alerts", path: "/alerts", phase: "P3" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const { path } = useRoute();
  const { signOut } = useAuth();

  return (
    <div className="shell">
      <nav className="shell__rail glass" aria-label="Primary">
        <div className="shell__brand t-label">SHTAPM</div>
        <ul className="shell__nav">
          {NAV.map((item) => {
            const active = path === item.path;
            return (
              <li key={item.path}>
                <button
                  type="button"
                  className={`shell__link${active ? " is-active" : ""}`}
                  aria-current={active ? "page" : undefined}
                  disabled={Boolean(item.phase)}
                  onClick={() => !item.phase && navigate(item.path)}
                  data-testid={`nav-${item.label.toLowerCase()}`}
                >
                  {item.label}
                  {item.phase && <span className="shell__phase">{item.phase}</span>}
                </button>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="shell__main">
        <header className="shell__top glass">
          <span className="t-label">Pump Monitoring</span>
          <button
            type="button"
            className="shell__signout"
            onClick={() => {
              void signOut().then(() => navigate("/login"));
            }}
            data-testid="sign-out"
          >
            Sign out
          </button>
        </header>
        <div className="shell__content">{children}</div>
      </div>
    </div>
  );
}
