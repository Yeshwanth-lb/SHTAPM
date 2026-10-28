// Protected layout: sidebar rail + top bar + content slot (Doc04 §04.4).
//
// Nav entries whose screens are not built yet are marked `phase` and render
// disabled with the phase they belong to. That is deliberate: an enabled link
// to an empty page reads as broken, a labelled one reads as scoped. Nothing
// here fabricates a screen that has no data behind it.
import { useEffect, useState, type ReactNode } from "react";

import { useAuth } from "../features/auth/AuthContext";
import { apiGet, type DeviceOut } from "../lib/api";
import { roleFromToken } from "../lib/token";
import { useApiResource } from "../lib/useApiResource";
import { BrandMark, NavIcon } from "./icons";
import { PageBoundary } from "./PageBoundary";
import { navigate, useRoute } from "./router";
import "./shell.css";

const DEVICE_ID = import.meta.env.VITE_DEVICE_ID ?? "pump-01";
const CONDITION_POLL_MS = 5_000;

const CONDITION_DOT: Record<string, string> = {
  healthy: "ok",
  warning: "warn",
  critical: "alarm",
};

/** Top status bar (D046): device, its condition (D043), clock, session. */
function StatusBar({ onSignOut }: { onSignOut: () => void }) {
  const { tokens } = useAuth();
  const accessToken = tokens?.accessToken ?? null;
  const device = useApiResource<DeviceOut>(
    () => apiGet<DeviceOut>(`/api/devices/${encodeURIComponent(DEVICE_ID)}`, accessToken!),
    [accessToken],
    { enabled: accessToken !== null, pollMs: CONDITION_POLL_MS },
  );
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const tick = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(tick);
  }, []);
  const condition = device.data?.health_state ?? null;
  const role = roleFromToken(accessToken);

  return (
    <>
      <span className="hmi-top__item mono hmi-top__device">{DEVICE_ID}</span>
      <span
        className={`hmi-top__item hmi-condition${condition ? ` hmi-condition--${CONDITION_DOT[condition]}` : ""}`}
        data-testid="condition"
      >
        <span className={`hmi-dot${condition ? ` hmi-dot--${CONDITION_DOT[condition]}` : ""}`} />
        {condition ? condition.toUpperCase() : "CONDITION —"}
      </span>
      <span className="hmi-top__spacer" />
      <span className="hmi-top__item mono tabular" data-testid="clock">
        {now.toLocaleTimeString()}
      </span>
      {role && <span className="hmi-top__item">{role}</span>}
      <button type="button" className="shell__signout" onClick={onSignOut} data-testid="sign-out">
        Sign out
      </button>
    </>
  );
}

interface NavItem {
  label: string;
  path: string;
  /** Set when the screen is not implemented yet — renders disabled. */
  phase?: string;
}

// Every entry below is enabled only because its page is backed by a real API
// endpoint. A `phase` tag renders the item disabled — used for screens whose
// backing data does not exist yet, so a nav item never leads to an empty shell.
const NAV: NavItem[] = [
  { label: "Control Room", path: "/" },
  { label: "Device", path: "/device" },
  { label: "Devices", path: "/devices" },
  { label: "Decisions", path: "/decisions" },
  { label: "History", path: "/history" },
  { label: "Alerts", path: "/alerts" },
  { label: "Ledger", path: "/ledger" },
  { label: "Users", path: "/users" },
  { label: "System", path: "/system" },
  { label: "Settings", path: "/settings" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const { path } = useRoute();
  const { signOut } = useAuth();

  return (
    <div className="shell">
      <nav className="shell__rail glass" aria-label="Primary">
        <div className="shell__brand">
          <BrandMark />
          <span className="shell__brand-text">
            <strong>SHTAPM</strong>
            <span>Trust-aware pump monitoring</span>
          </span>
        </div>
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
                  data-testid={`nav-${item.label.toLowerCase().replace(/\s+/g, "-")}`}
                >
                  <span className="shell__link-label">
                    <NavIcon path={item.path} />
                    {item.label}
                  </span>
                  {item.phase && <span className="shell__phase">{item.phase}</span>}
                </button>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="shell__main">
        <header className="shell__top glass">
          <StatusBar onSignOut={() => void signOut().then(() => navigate("/login"))} />
        </header>
        {/* Keyed by route: each page enters with the same short rise (D052). */}
        <div className="shell__content page-enter" key={path}>
          <PageBoundary>{children}</PageBoundary>
        </div>
      </div>
    </div>
  );
}
