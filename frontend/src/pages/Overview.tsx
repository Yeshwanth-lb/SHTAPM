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

  const h = health.data;
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
        {(devices.data?.length ?? 0) > 0 && (
          <ul className="page__list">
            {devices.data!.map((d) => (
              <li key={d.id}>
                <button className="link-btn" onClick={() => navigate("/device")}>
                  <span className="mono">{d.device_id}</span>
                </button>{" "}
                <span className="t-muted">
                  {d.status} · last seen {d.last_seen_at ?? "never"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </GlassTile>
    </div>
  );
}
