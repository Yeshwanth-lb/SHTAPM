// Device list — GET /api/devices (api/devices.py), scoped to what the signed-in
// user owns (admins see all). Channel count comes from the real /channels
// registry for the device the UI is configured to monitor; other devices show
// "—" rather than a guessed six, because that count is per-device.
import { GlassTile } from "../components/aurora/GlassTile";
import { StateBlock, StatusPill } from "../components/aurora/StateBlock";
import { navigate } from "../app/router";
import { useAuth } from "../features/auth/AuthContext";
import { apiGet, type DeviceOut } from "../lib/api";
import { useApiResource } from "../lib/useApiResource";
import "./pages.css";

function statusTone(status: DeviceOut["status"]) {
  if (status === "online") return "healthy" as const;
  if (status === "degraded") return "warning" as const;
  return "critical" as const;
}

function healthTone(health: DeviceOut["health_state"]) {
  if (health === "healthy") return "healthy" as const;
  if (health === "warning") return "warning" as const;
  return "critical" as const;
}

export function DevicesPage() {
  const { tokens } = useAuth();
  const accessToken = tokens?.accessToken ?? null;

  const devices = useApiResource<DeviceOut[]>(
    () => apiGet<DeviceOut[]>("/api/devices", accessToken!),
    [accessToken],
    { enabled: accessToken !== null },
  );

  return (
    <div className="page">
      <header className="page__head">
        <h1 className="t-h1">Devices</h1>
        <span className="t-label tabular" data-testid="devices-count">
          {devices.data ? `${devices.data.length} registered` : ""}
        </span>
      </header>

      <GlassTile>
        {devices.status === "loading" && <StateBlock kind="loading" />}

        {devices.status === "error" && (
          <StateBlock kind="error" title="Could not load devices" onRetry={devices.refresh}>
            {devices.error}
          </StateBlock>
        )}

        {devices.status === "ready" && (devices.data?.length ?? 0) === 0 && (
          <StateBlock kind="empty" title="No devices registered">
            A device row is created automatically the first time telemetry arrives for it.
          </StateBlock>
        )}

        {(devices.data?.length ?? 0) > 0 && (
          <div className="table-scroll">
            <table className="data-table" data-testid="devices-table">
              <thead>
                <tr>
                  <th>Device</th>
                  <th>Name</th>
                  <th>Device status</th>
                  <th>Health</th>
                  <th>Last seen</th>
                  <th>Rate</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {devices.data!.map((d) => (
                  <tr key={d.id} data-testid={`device-row-${d.device_id}`}>
                    <td className="mono">{d.device_id}</td>
                    <td>{d.name}</td>
                    <td>
                      <StatusPill tone={statusTone(d.status)}>{d.status}</StatusPill>
                    </td>
                    <td>
                      {/* health_state is a stored rollup; nothing computes it
                          yet (no prognosis model), so it reads as its default. */}
                      <StatusPill tone={healthTone(d.health_state)}>{d.health_state}</StatusPill>
                    </td>
                    <td className="mono">{d.last_seen_at ?? "never"}</td>
                    <td className="tabular">{d.sample_rate_hz} Hz</td>
                    <td>
                      <button className="link-btn" onClick={() => navigate("/device")}>
                        Monitor →
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <p className="page__footnote t-muted">
          <strong>Device status</strong> is the edge publisher&rsquo;s own retained MQTT
          online/offline state (its Last Will), persisted to{" "}
          <span className="mono">devices.status</span>. It is a fact about the device, and is
          unrelated to whether this browser holds a WebSocket.
          <br />
          <strong>Health</strong> is the stored <span className="mono">devices.health_state</span>{" "}
          rollup. No component computes it yet, so it shows its schema default rather than an
          assessed condition.
        </p>
      </GlassTile>
    </div>
  );
}
