// Alerts — GET /api/alerts (api/alerts.py), real rows only.
//
// The endpoint exists and works; nothing in the system publishes an alert yet
// (no producer writes the `alerts` table). So this page will be empty, and the
// empty state says WHY — an operator must not read "no alerts" as "no faults
// detected" when nothing is currently capable of detecting one.
import { useState } from "react";

import { GlassTile } from "../components/aurora/GlassTile";
import { StateBlock, StatusPill } from "../components/aurora/StateBlock";
import { useAuth } from "../features/auth/AuthContext";
import { apiGet, type AlertOut } from "../lib/api";
import { useApiResource } from "../lib/useApiResource";
import "./pages.css";

const FILTERS = [
  { key: "open", label: "Open" },
  { key: "acknowledged", label: "Acknowledged" },
  { key: "", label: "All" },
] as const;

function tone(severity: AlertOut["severity"]) {
  if (severity === "critical") return "critical" as const;
  if (severity === "warning") return "warning" as const;
  return "muted" as const;
}

export function AlertsPage() {
  const { tokens } = useAuth();
  const accessToken = tokens?.accessToken ?? null;
  const [status, setStatus] = useState<string>("open");

  const alerts = useApiResource<AlertOut[]>(
    () =>
      apiGet<AlertOut[]>(
        `/api/alerts${status ? `?status=${encodeURIComponent(status)}` : ""}`,
        accessToken!,
      ),
    [accessToken, status],
    { enabled: accessToken !== null },
  );

  return (
    <div className="page">
      <header className="page__head">
        <h1 className="t-h1">Alerts</h1>
        <div className="toolbar">
          {FILTERS.map((f) => (
            <button
              key={f.key || "all"}
              type="button"
              className={`toolbar__btn${status === f.key ? " is-active" : ""}`}
              onClick={() => setStatus(f.key)}
              aria-pressed={status === f.key}
              data-testid={`alert-filter-${f.key || "all"}`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </header>

      <GlassTile>
        {alerts.status === "loading" && <StateBlock kind="loading" />}

        {alerts.status === "error" && (
          <StateBlock kind="error" title="Could not load alerts" onRetry={alerts.refresh}>
            {alerts.error}
          </StateBlock>
        )}

        {alerts.status === "ready" && (alerts.data?.length ?? 0) === 0 && (
          <StateBlock kind="empty" title="No alerts">
            This is not the same as no faults. No component in SHTAPM writes to the alerts table yet
            — anomaly detection currently runs with a null detector that never flags, by design.
            This page will populate once a real producer exists.
          </StateBlock>
        )}

        {(alerts.data?.length ?? 0) > 0 && (
          <div className="table-scroll">
            <table className="data-table" data-testid="alerts-table">
              <thead>
                <tr>
                  <th>Severity</th>
                  <th>Type</th>
                  <th>Device</th>
                  <th>Channel</th>
                  <th>Message</th>
                  <th>Raised</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {alerts.data!.map((a) => (
                  <tr key={a.id} data-testid={`alert-row-${a.id}`}>
                    <td>
                      <StatusPill tone={tone(a.severity)}>{a.severity}</StatusPill>
                    </td>
                    <td>{a.type}</td>
                    <td className="mono">{a.device_id}</td>
                    <td>{a.channel ?? "—"}</td>
                    <td>{a.message}</td>
                    <td className="mono">{a.ts}</td>
                    <td>{a.acknowledged_at ? "acknowledged" : "open"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassTile>
    </div>
  );
}
