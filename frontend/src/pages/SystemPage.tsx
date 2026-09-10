// System — operational diagnostics from /healthz (unauthenticated) and
// /api/system/health (admin-only).
//
// Both are queried because they answer different questions: /healthz works
// even when a token has expired and reports the database error class;
// /api/system/health is the Doc05 §05.7 endpoint and adds e2e_latency_ms.
// Where a diagnostic genuinely does not exist, this page says so rather than
// printing a zero — `e2e_latency_ms` is null because nothing in the running
// backend measures sensor-to-client latency.
import { GlassTile } from "../components/aurora/GlassTile";
import { StateBlock, StatusPill } from "../components/aurora/StateBlock";
import { useAuth } from "../features/auth/AuthContext";
import { useChannels } from "../features/channels/useChannels";
import { ChannelProvenanceBadge } from "../components/panels/ChannelProvenanceBadge";
import { apiGet, getHealthz, type HealthzOut, type SystemHealthOut } from "../lib/api";
import { useApiResource } from "../lib/useApiResource";
import "./pages.css";

const POLL_MS = 5000;
const DEVICE_ID = import.meta.env.VITE_DEVICE_ID ?? "pump-01";

export function SystemPage() {
  const { tokens } = useAuth();
  const accessToken = tokens?.accessToken ?? null;

  const health = useApiResource<HealthzOut>(() => getHealthz(), [], { pollMs: POLL_MS });
  const system = useApiResource<SystemHealthOut>(
    () => apiGet<SystemHealthOut>("/api/system/health", accessToken!),
    [accessToken],
    { enabled: accessToken !== null, pollMs: POLL_MS },
  );

  const { channels, loading: channelsLoading } = useChannels(DEVICE_ID, accessToken);

  const h = health.data;
  const adminOnly = system.error?.startsWith("HTTP 403") ?? false;

  return (
    <div className="page">
      <header className="page__head">
        <h1 className="t-h1">System</h1>
        <span className="t-label">polled every {POLL_MS / 1000}s</span>
      </header>

      <GlassTile title="Service health">
        {health.status === "loading" && <StateBlock kind="loading" />}
        {health.status === "error" && (
          <StateBlock kind="error" title="Backend unreachable" onRetry={health.refresh}>
            {health.error}
          </StateBlock>
        )}
        {h && (
          <div className="kv">
            <div className="kv__item">
              <span className="kv__label">API</span>
              <span className="kv__value">
                <StatusPill tone={h.status === "ok" ? "healthy" : "critical"}>
                  {h.status}
                </StatusPill>
              </span>
            </div>
            <div className="kv__item">
              <span className="kv__label">MQTT ingestion</span>
              <span className="kv__value">
                <StatusPill tone={h.mqtt_connected ? "healthy" : "critical"}>
                  {h.mqtt_connected ? "connected" : "disconnected"}
                </StatusPill>
              </span>
            </div>
            <div className="kv__item">
              <span className="kv__label">Database</span>
              <span className="kv__value">
                <StatusPill tone={h.db_connected ? "healthy" : "critical"}>
                  {h.db_connected ? "connected" : "unreachable"}
                </StatusPill>
              </span>
            </div>
            {h.db_error && (
              <div className="kv__item">
                <span className="kv__label">Database error</span>
                <span className="kv__value mono" data-testid="db-error">
                  {h.db_error}
                </span>
              </div>
            )}
            <div className="kv__item">
              <span className="kv__label">Frames ingested</span>
              <span className="kv__value tabular">{h.telemetry_count}</span>
            </div>
            <div className="kv__item">
              <span className="kv__label">Devices seen</span>
              <span className="kv__value tabular">{h.devices.length}</span>
            </div>
            <div className="kv__item">
              <span className="kv__label">WebSocket clients</span>
              <span className="kv__value tabular">{h.ws_clients}</span>
            </div>
          </div>
        )}
      </GlassTile>

      <GlassTile title="Detailed diagnostics">
        {adminOnly ? (
          <StateBlock kind="notice" title="Administrator access required">
            <span className="mono">/api/system/health</span> is admin-only. The panel above uses the
            unauthenticated probe and covers the same transport and ingestion status.
          </StateBlock>
        ) : system.status === "error" ? (
          <StateBlock kind="error" onRetry={system.refresh}>
            {system.error}
          </StateBlock>
        ) : system.data ? (
          <div className="kv">
            <div className="kv__item">
              <span className="kv__label">End-to-end latency</span>
              <span className="kv__value" data-testid="e2e-latency">
                {system.data.e2e_latency_ms === null ? (
                  <span className="t-muted">not measured</span>
                ) : (
                  `${system.data.e2e_latency_ms} ms`
                )}
              </span>
            </div>
            <div className="kv__item">
              <span className="kv__label">Telemetry count</span>
              <span className="kv__value tabular">{system.data.telemetry_count}</span>
            </div>
          </div>
        ) : (
          <StateBlock kind="loading" />
        )}

        <p className="page__footnote t-muted">
          <strong>End-to-end latency is null, not zero.</strong> Nothing in the running backend
          measures sensor-to-client latency; the only measurement ever taken was a one-off probe
          script. Reporting a number here would be fabricating it.
        </p>
      </GlassTile>

      <GlassTile title="Channel provenance">
        <p className="page__lede t-muted">
          This is a <strong>declaration</strong>, not a measurement. The telemetry contract carries
          six plain numbers with no provenance marker, so a placeholder constant is
          indistinguishable on the wire from a real reading. A channel is reported live only when
          <span className="mono"> SHTAPM_CHANNEL_SOURCES</span> declares it AND the sensor registry
          names the part behind it. No arriving value can promote a channel.
        </p>

        {channelsLoading ? (
          <StateBlock kind="loading" />
        ) : (
          <div className="table-scroll">
            <table className="data-table" data-testid="provenance-table">
              <thead>
                <tr>
                  <th>Channel</th>
                  <th>Classification</th>
                  <th>Registered part</th>
                  <th>Interface</th>
                  <th>Proxy</th>
                </tr>
              </thead>
              <tbody>
                {channels.map((c) => (
                  <tr key={c.channel} data-testid={`provenance-row-${c.channel}`}>
                    <td>{c.channel}</td>
                    <td>
                      <ChannelProvenanceBadge source={c.source} />
                    </td>
                    <td className="mono">{c.part ?? "none registered"}</td>
                    <td className="mono">{c.interface ?? "not documented"}</td>
                    <td>{c.is_proxy ? "yes" : c.is_proxy === false ? "no" : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {channels.some((c) => c.conflict) && (
          <p className="page__footnote" data-testid="provenance-conflicts">
            <strong>Configuration conflict.</strong> One or more channels are declared live but have
            no registered part, so they are reported as unverified rather than trusted. Seed the
            registry, or correct the declaration.
          </p>
        )}

        <p className="page__footnote t-muted">
          Secrets are never shown here — this reflects only the channel classification, which is
          non-secret configuration.
        </p>
      </GlassTile>

      <GlassTile title="Unavailable diagnostics">
        <p className="page__lede t-muted">
          These are not implemented and are listed so their absence is not mistaken for a healthy
          reading: per-service uptime, broker queue depth, ingestion lag, error-rate history, and
          continuous aggregate freshness. Recent backend errors are written to the service log and
          are not exposed over the API.
        </p>
      </GlassTile>
    </div>
  );
}
