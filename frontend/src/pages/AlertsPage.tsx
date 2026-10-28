// Alerts — GET /api/alerts (api/alerts.py), real rows only.
//
// Alerts are raised by the backend at the moments the ledger records an
// incident (D053): a trust collapse (typed attack / fault / unexplained by the
// edge's attribution), a Safe Pump-Stop, a dead sensor. One incident, one
// alert; recoveries are in the ledger. Each alert can be acknowledged
// (POST /api/alerts/{id}/ack), which records who and when.
import { useState } from "react";

import { GlassTile } from "../components/aurora/GlassTile";
import { StateBlock, StatusPill } from "../components/aurora/StateBlock";
import { useAuth } from "../features/auth/AuthContext";
import { formatEventTime } from "../features/controlroom/model";
import { apiGet, apiPost, describeRequestFailure, type AlertOut } from "../lib/api";
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
  const [acking, setAcking] = useState<string | null>(null);
  const [ackError, setAckError] = useState<string | null>(null);

  const alerts = useApiResource<AlertOut[]>(
    () =>
      apiGet<AlertOut[]>(
        `/api/alerts${status ? `?status=${encodeURIComponent(status)}` : ""}`,
        accessToken!,
      ),
    [accessToken, status],
    { enabled: accessToken !== null, pollMs: 5_000 },
  );

  async function acknowledge(id: string) {
    setAcking(id);
    setAckError(null);
    try {
      await apiPost(`/api/alerts/${encodeURIComponent(id)}/ack`, {}, accessToken!);
      alerts.refresh();
    } catch (err) {
      setAckError(`Could not acknowledge: ${describeRequestFailure(err)}`);
    } finally {
      setAcking(null);
    }
  }

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
          <StateBlock kind="empty" title={status === "open" ? "No open alerts" : "No alerts"}>
            An alert is raised when a sensor&apos;s trust collapses (labelled attack, fault or
            unexplained), when the pump is stopped automatically, or when a sensor stops answering.
            Nothing of that kind is {status === "acknowledged" ? "acknowledged" : "waiting"} right
            now.
          </StateBlock>
        )}

        {ackError && (
          <p className="login__error" role="alert">
            {ackError}
          </p>
        )}

        {(alerts.data?.length ?? 0) > 0 && (
          <div className="table-scroll">
            <table className="data-table" data-testid="alerts-table">
              <thead>
                <tr>
                  <th>Severity</th>
                  <th>Type</th>
                  <th>Channel</th>
                  <th>What happened</th>
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
                    <td>
                      <span
                        className={`tag tag--${a.type === "attack" ? "alarm" : a.type === "fault" ? "caution" : "info"}`}
                      >
                        {a.type.toUpperCase()}
                      </span>
                    </td>
                    <td>{a.channel ?? "—"}</td>
                    <td>
                      {a.message}
                      {a.reason && <div className="t-muted alerts__reason">{a.reason}</div>}
                    </td>
                    <td className="mono">{formatEventTime(a.ts)}</td>
                    <td>
                      {a.acknowledged_at ? (
                        <span className="t-muted">
                          acknowledged {formatEventTime(a.acknowledged_at)}
                        </span>
                      ) : (
                        <button
                          type="button"
                          className="toolbar__btn"
                          disabled={acking === a.id}
                          onClick={() => void acknowledge(a.id)}
                          data-testid={`alert-ack-${a.id}`}
                        >
                          {acking === a.id ? "Acknowledging…" : "Acknowledge"}
                        </button>
                      )}
                    </td>
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
