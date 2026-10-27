// Pump relay status and control (FR-R1, PRD §18.3 item 3, D041).
//
// Shows the EDGE'S REPORTED relay state -- never a guess from the last button
// pressed -- and why it is in that state: an operator command, or an
// autonomous Safe Pump-Stop (self-heal escalation, dry-run, watchdog). An
// autonomous stop is latched: the pump stays off until an admin starts it
// again, and restarting after one needs an explicit confirmation.
//
// "Simulated relay" is shown whenever the edge runs the safety logic without a
// physical relay, so the dashboard never claims a stop that did not happen.
// Visibility of the buttons follows the token's role claim (display only); the
// backend re-checks the admin role on every request.
import { useCallback, useEffect, useState } from "react";

import { GlassTile } from "../../components/aurora/GlassTile";
import {
  commandRelay,
  describeRequestFailure,
  getRelay,
  isApiError,
  type ActuationCause,
  type RelayOut,
  type RelayState,
} from "../../lib/api";
import { canControlRelay, roleFromToken } from "../../lib/token";
import "./relay.css";

export const RELAY_POLL_MS = 2_000;

const CAUSE_LABEL: Record<ActuationCause, string> = {
  startup: "Edge started",
  command: "Operator command",
  safe_stop: "Self-heal escalation",
  dry_run: "Dry-run detected",
  watchdog: "Watchdog",
  shutdown: "Edge stopped",
};

const AUTONOMOUS: ReadonlySet<ActuationCause> = new Set(["safe_stop", "dry_run", "watchdog"]);

interface Props {
  deviceId: string;
  accessToken: string | null;
}

function errorText(err: unknown): string {
  if (isApiError(err)) {
    if (err.status === 403) return "Only an admin can start or stop the pump.";
    if (err.status === 503) return `Not sent: ${err.message}`;
    return `${err.status}: ${err.message}`;
  }
  return describeRequestFailure(err);
}

export function relayHeadline(relay: RelayOut | null): {
  label: string;
  tone: "running" | "stopped" | "safe-stop" | "unknown";
} {
  const status = relay?.status;
  if (!relay?.known || !status) return { label: "Unknown", tone: "unknown" };
  if (status.relay === "on") return { label: "Running", tone: "running" };
  if (status.latched && AUTONOMOUS.has(status.cause)) {
    return { label: "SAFE STOP", tone: "safe-stop" };
  }
  return { label: "Stopped", tone: "stopped" };
}

export function RelayPanel({ deviceId, accessToken }: Props) {
  const allowed = canControlRelay(roleFromToken(accessToken));
  const [relay, setRelay] = useState<RelayOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmRestart, setConfirmRestart] = useState(false);

  const refresh = useCallback(async () => {
    if (!accessToken) return;
    try {
      setRelay(await getRelay(deviceId, accessToken));
    } catch {
      /* a failed poll keeps the last reported state */
    }
  }, [accessToken, deviceId]);

  useEffect(() => {
    void refresh();
    const poll = window.setInterval(() => void refresh(), RELAY_POLL_MS);
    return () => window.clearInterval(poll);
  }, [refresh]);

  const status = relay?.status ?? null;
  const headline = relayHeadline(relay);
  const latched = headline.tone === "safe-stop";

  const send = async (state: RelayState) => {
    if (!accessToken) return;
    setBusy(true);
    setError(null);
    try {
      await commandRelay(deviceId, state, accessToken);
      setConfirmRestart(false);
      await refresh();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <GlassTile
      title="Pump relay"
      aside={
        <span className={`relay__badge relay__badge--${headline.tone}`} data-testid="relay-badge">
          {headline.label}
        </span>
      }
    >
      <div className="relay" data-testid="relay-panel">
        {!status ? (
          <p className="t-muted" data-testid="relay-unknown">
            Waiting for the edge to report its relay state.
          </p>
        ) : (
          <div
            className={`relay__status relay__status--${headline.tone}`}
            role="status"
            data-testid="relay-status"
          >
            <div>
              <strong>{CAUSE_LABEL[status.cause]}</strong>
              <span className="t-muted"> · {new Date(status.ts).toLocaleTimeString()}</span>
            </div>
            <div className="relay__reason" data-testid="relay-reason">
              {status.reason}
            </div>
            {!status.hardware && (
              <span className="relay__chip" data-testid="relay-simulated">
                Simulated relay: nothing is physically switched
              </span>
            )}
          </div>
        )}

        {!allowed ? (
          <p className="t-muted" data-testid="relay-forbidden">
            Starting or stopping the pump needs the admin role.
          </p>
        ) : (
          <div className="relay__actions">
            {status?.relay === "on" ? (
              <button
                type="button"
                className="relay__btn relay__btn--stop"
                onClick={() => void send("off")}
                disabled={busy}
                data-testid="relay-stop"
              >
                {busy ? "Sending…" : "Stop pump"}
              </button>
            ) : (
              <>
                {latched && (
                  <label className="relay__confirm">
                    <input
                      type="checkbox"
                      checked={confirmRestart}
                      onChange={(e) => setConfirmRestart(e.target.checked)}
                      data-testid="relay-confirm"
                    />
                    I checked why it stopped and it is safe to restart
                  </label>
                )}
                <button
                  type="button"
                  className="relay__btn relay__btn--start"
                  onClick={() => void send("on")}
                  disabled={busy || !status || (latched && !confirmRestart)}
                  data-testid="relay-start"
                >
                  {busy ? "Sending…" : latched ? "Restart after safe stop" : "Start pump"}
                </button>
              </>
            )}
            <span className="t-muted relay__note">
              Admin only · audited · recorded in the ledger
            </span>
          </div>
        )}

        {error && (
          <p className="relay__error" role="alert" data-testid="relay-error">
            {error}
          </p>
        )}
      </div>
    </GlassTile>
  );
}
