// Operational overview: is the system working, and what is it seeing?
//
// Everything here is real: /healthz for transport and ingestion status
// (unauthenticated, so it works even if a token has expired), /api/devices for
// the fleet, /api/devices/:id/channels for provenance, /api/alerts for faults.
// Nothing is synthesised and no status is inferred from the absence of an
// error — a panel that cannot load says so.
import { GlassTile } from "../components/aurora/GlassTile";
import { StateBlock, StatusPill } from "../components/aurora/StateBlock";
import { navigate } from "../app/router";
import { useAuth } from "../features/auth/AuthContext";
import { useChannels } from "../features/channels/useChannels";
import { trustBand, useDecisions } from "../features/decisions/useDecisions";
import { apiGet, getHealthz, type AlertOut, type DeviceOut, type HealthzOut } from "../lib/api";
import { useApiResource } from "../lib/useApiResource";
import { CHANNELS } from "../types/contracts";
import "./pages.css";

const DEVICE_ID = import.meta.env.VITE_DEVICE_ID ?? "pump-01";
const HEALTH_POLL_MS = 5000;

function ok(value: boolean) {
  return value ? (
    <StatusPill tone="healthy">Connected</StatusPill>
  ) : (
    <StatusPill tone="critical">Down</StatusPill>
  );
}

export function Overview() {
  const { tokens } = useAuth();
  const accessToken = tokens?.accessToken ?? null;

  const health = useApiResource<HealthzOut>(() => getHealthz(), [], {
    pollMs: HEALTH_POLL_MS,
  });
  const devices = useApiResource<DeviceOut[]>(
    () => apiGet<DeviceOut[]>("/api/devices", accessToken!),
    [accessToken],
    { enabled: accessToken !== null },
  );
  const alerts = useApiResource<AlertOut[]>(
    () => apiGet<AlertOut[]>("/api/alerts?status=open", accessToken!),
    [accessToken],
    { enabled: accessToken !== null },
  );
  const { channels } = useChannels(DEVICE_ID, accessToken);
  // Only the newest row is needed for an at-a-glance state.
  const decisions = useDecisions(DEVICE_ID, accessToken, 1);

  const h = health.data;
  const latestDecision = decisions.data?.[decisions.data.length - 1] ?? null;
  const worstTrust = latestDecision
    ? Math.min(
        ...CHANNELS.map((c) => {
          const v = latestDecision[`trust_${c}` as keyof typeof latestDecision];
          return typeof v === "number" ? v : Number.POSITIVE_INFINITY;
        }),
      )
    : null;
  const worstBand =
    worstTrust !== null && Number.isFinite(worstTrust) ? trustBand(worstTrust) : "unknown";
  const liveChannels = channels.filter((c) => c.source === "live").length;
  const declared = channels.filter((c) => c.source !== "unknown").length;

  return (
    <div className="page">
      <header className="page__head">
        <h1 className="t-h1">Overview</h1>
        <span className="t-label">
          {health.status === "ready" ? `refreshed every ${HEALTH_POLL_MS / 1000}s` : ""}
        </span>
      </header>

      <GlassTile title="System health">
        {health.status === "loading" && <StateBlock kind="loading" />}
        {health.status === "error" && (
          <StateBlock kind="error" title="Backend unreachable" onRetry={health.refresh}>
            {health.error}
          </StateBlock>
        )}
        {h && (
          <div className="kv">
            <div className="kv__item">
              <span className="kv__label">Backend API</span>
              <span className="kv__value">{ok(h.status === "ok")}</span>
            </div>
            <div className="kv__item">
              <span className="kv__label">MQTT broker</span>
              <span className="kv__value" data-testid="mqtt-status">
                {ok(h.mqtt_connected)}
              </span>
            </div>
            <div className="kv__item">
              <span className="kv__label">Database</span>
              <span className="kv__value" data-testid="db-status">
                {ok(h.db_connected)}
                {h.db_error && <span className="t-muted mono"> {h.db_error}</span>}
              </span>
            </div>
            <div className="kv__item">
              <span className="kv__label">WebSocket clients</span>
              <span className="kv__value tabular">{h.ws_clients}</span>
            </div>
            <div className="kv__item">
              <span className="kv__label">Frames ingested</span>
              <span className="kv__value tabular" data-testid="telemetry-count">
                {h.telemetry_count}
              </span>
            </div>
            <div className="kv__item">
              <span className="kv__label">Devices seen</span>
              <span className="kv__value tabular" data-testid="device-count">
                {h.devices.length}
              </span>
            </div>
          </div>
        )}
      </GlassTile>

      <GlassTile
        title="Signal integrity"
        aside={
          <span className="t-label tabular" data-testid="integrity-summary">
            {declared === 0 ? "unverified" : `${liveChannels} / ${CHANNELS.length} live`}
          </span>
        }
      >
        <p className="page__lede t-muted">
          {declared === 0
            ? "No channel provenance is registered, so every channel reads UNVERIFIED. Values arriving is not evidence a sensor is connected — placeholder constants arrive identically."
            : `${declared} of ${CHANNELS.length} channels have declared provenance.`}
        </p>
        <button className="link-btn" onClick={() => navigate("/device")} data-testid="goto-device">
          Open device monitoring →
        </button>
      </GlassTile>

      <GlassTile
        title="Decision state"
        aside={
          <span className="t-label mono" data-testid="decision-ts">
            {latestDecision ? latestDecision.ts : "—"}
          </span>
        }
      >
        {decisions.status === "loading" && <StateBlock kind="loading" />}
        {decisions.status === "error" && (
          <StateBlock kind="error" onRetry={decisions.refresh}>
            {decisions.error}
          </StateBlock>
        )}
        {decisions.status === "ready" && !latestDecision && (
          <StateBlock kind="empty" title="No decisions recorded">
            The edge publishes a decision diagnostic every second; if this stays empty while
            telemetry flows, the decision-diagnostic consumer is not receiving its topic.
          </StateBlock>
        )}
        {latestDecision && (
          <>
            <div className="kv">
              <div className="kv__item">
                <span className="kv__label">Anomaly</span>
                <span className="kv__value" data-testid="overview-anomaly">
                  <StatusPill tone={latestDecision.anomaly_flag ? "critical" : "muted"}>
                    {latestDecision.anomaly_flag ? "flagged" : "not flagged"}
                  </StatusPill>
                </span>
              </div>
              <div className="kv__item">
                <span className="kv__label">Lowest channel trust</span>
                <span className="kv__value tabular" data-testid="overview-trust">
                  {worstTrust !== null && Number.isFinite(worstTrust) ? worstTrust.toFixed(2) : "—"}{" "}
                  <StatusPill
                    tone={
                      worstBand === "trusted"
                        ? "healthy"
                        : worstBand === "suspicious"
                          ? "warning"
                          : worstBand === "malicious"
                            ? "critical"
                            : "muted"
                    }
                  >
                    {worstBand}
                  </StatusPill>
                </span>
              </div>
              <div className="kv__item">
                <span className="kv__label">Safety state</span>
                <span className="kv__value t-muted" data-testid="overview-safety">
                  not published
                </span>
              </div>
            </div>
            <p className="page__footnote t-muted">
              &ldquo;Not flagged&rdquo; means the pipeline ran, not that the pump is healthy — the
              wired detector never flags by design. Safety state (relay position, safe-stop) is held
              on the edge and is not published to the backend, so it cannot be shown.
            </p>
            <button
              className="link-btn"
              onClick={() => navigate("/decisions")}
              data-testid="goto-decisions"
            >
              Open decisions &amp; diagnostics →
            </button>
          </>
        )}
      </GlassTile>

      <GlassTile title="Open alerts">
        {alerts.status === "loading" && <StateBlock kind="loading" />}
        {alerts.status === "error" && (
          <StateBlock kind="error" onRetry={alerts.refresh}>
            {alerts.error}
          </StateBlock>
        )}
        {alerts.status === "ready" && (alerts.data?.length ?? 0) === 0 && (
          <StateBlock kind="empty" title="No open alerts" data-testid="alerts-empty">
            Nothing has raised an alert. Note that no component publishes alerts yet, so this panel
            stays empty by design rather than because the system is quiet.
          </StateBlock>
        )}
        {(alerts.data?.length ?? 0) > 0 && (
          <ul className="page__list">
            {alerts.data!.slice(0, 5).map((a) => (
              <li key={a.id}>
                <StatusPill tone={a.severity === "critical" ? "critical" : "warning"}>
                  {a.severity}
                </StatusPill>{" "}
                <span className="mono">{a.device_id}</span> — {a.message}
              </li>
            ))}
          </ul>
        )}
      </GlassTile>

      <GlassTile title="Devices">
        {devices.status === "loading" && <StateBlock kind="loading" />}
        {devices.status === "error" && (
          <StateBlock kind="error" onRetry={devices.refresh}>
            {devices.error}
          </StateBlock>
        )}
        {devices.status === "ready" && (devices.data?.length ?? 0) === 0 && (
          <StateBlock kind="empty" title="No devices registered" />
        )}
        <p className="page__lede t-muted">
          Device status is the edge publisher&rsquo;s retained MQTT online/offline state — a fact
          about the device, not about this browser&rsquo;s WebSocket.
        </p>
        {(devices.data?.length ?? 0) > 0 && (
          <ul className="page__list">
            {devices.data!.map((d) => (
              <li key={d.id}>
                <button className="link-btn" onClick={() => navigate("/device")}>
                  <span className="mono">{d.device_id}</span>
                </button>{" "}
                <StatusPill
                  tone={
                    d.status === "online"
                      ? "healthy"
                      : d.status === "degraded"
                        ? "warning"
                        : "critical"
                  }
                  testId={`device-status-${d.device_id}`}
                >
                  {d.status}
                </StatusPill>{" "}
                <span className="t-muted">last seen {d.last_seen_at ?? "never"}</span>
              </li>
            ))}
          </ul>
        )}
      </GlassTile>
    </div>
  );
}
