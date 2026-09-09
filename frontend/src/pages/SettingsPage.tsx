// Settings — connection information and display preferences.
//
// Every control here does something real. There are no placeholder toggles:
// a switch that does not switch anything is worse than an absent one, because
// an operator will believe they changed something.
//
// Deliberately NOT exposed: the JWT secret, database password, MQTT
// credentials, or the access token itself. The API base URL and device id are
// non-secret build configuration and are shown because "which backend am I
// talking to" is the single most useful thing during bring-up.
import { useEffect, useState } from "react";

import { GlassTile } from "../components/aurora/GlassTile";
import { StateBlock } from "../components/aurora/StateBlock";
import { apiBase } from "../lib/api";
import { wsUrl } from "../lib/ws";
import "./pages.css";

const DEVICE_ID = import.meta.env.VITE_DEVICE_ID ?? "pump-01";
const MOTION_KEY = "shtapm.pref.motion";

/** Strip any credential a URL might carry before it is displayed. */
export function redactUrl(raw: string): string {
  try {
    const url = new URL(raw);
    if (url.password) url.password = "***";
    if (url.username) url.username = "***";
    url.searchParams.forEach((_v, k) => {
      if (/token|secret|password|key/i.test(k)) url.searchParams.set(k, "***");
    });
    return url.toString();
  } catch {
    return raw;
  }
}

export function SettingsPage() {
  const [reduceMotion, setReduceMotion] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem(MOTION_KEY) === "reduce";
    } catch {
      return false;
    }
  });

  // Applies immediately and persists — a real preference, not a decorative one.
  useEffect(() => {
    document.documentElement.dataset.motion = reduceMotion ? "reduce" : "full";
    try {
      window.localStorage.setItem(MOTION_KEY, reduceMotion ? "reduce" : "full");
    } catch {
      /* storage unavailable — the preference still applies for this session */
    }
  }, [reduceMotion]);

  return (
    <div className="page">
      <header className="page__head">
        <h1 className="t-h1">Settings</h1>
      </header>

      <GlassTile title="Connection">
        <div className="kv">
          <div className="kv__item">
            <span className="kv__label">API base URL</span>
            <span className="kv__value mono" data-testid="setting-api-base">
              {redactUrl(apiBase())}
            </span>
          </div>
          <div className="kv__item">
            <span className="kv__label">WebSocket URL</span>
            <span className="kv__value mono" data-testid="setting-ws-url">
              {redactUrl(wsUrl())}
            </span>
          </div>
          <div className="kv__item">
            <span className="kv__label">Monitored device</span>
            <span className="kv__value mono">{DEVICE_ID}</span>
          </div>
          <div className="kv__item">
            <span className="kv__label">Build mode</span>
            <span className="kv__value mono">{import.meta.env.MODE}</span>
          </div>
        </div>
        <p className="page__footnote t-muted">
          These come from build-time configuration (<span className="mono">VITE_API_BASE_URL</span>,{" "}
          <span className="mono">VITE_WS_URL</span>) or are derived from the page origin. Changing
          them requires restarting the dev server or rebuilding — Vite reads env only at startup.
        </p>
      </GlassTile>

      <GlassTile title="Display">
        <label className="settings__row">
          <input
            type="checkbox"
            checked={reduceMotion}
            onChange={(e) => setReduceMotion(e.target.checked)}
            data-testid="setting-reduce-motion"
          />
          <span>
            <strong>Reduce motion</strong>
            <span className="t-muted"> — freezes the ambient background animation.</span>
          </span>
        </label>
        <p className="page__footnote t-muted">
          Your operating system&rsquo;s own reduced-motion setting is always respected regardless of
          this switch.
        </p>
      </GlassTile>

      <GlassTile title="Thresholds">
        <StateBlock kind="notice" title="Not editable here yet">
          Trust and divergence thresholds are stored per device and are readable and writable
          through the API, but editing one writes an audit-ledger entry and changes safety
          behaviour. That needs a confirmation flow before it belongs behind a click.
          <br />
          <br />
          One value is deliberately unset in the database:{" "}
          <span className="mono">divergence_threshold</span>. No validated number for it exists yet,
          and inventing one would be worse than leaving it null.
        </StateBlock>
      </GlassTile>
    </div>
  );
}
