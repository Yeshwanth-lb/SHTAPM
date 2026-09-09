// Device monitoring page — live telemetry for one device.
//
// Every number shown comes from the backend: the recent window from
// GET /readings?limit=N, live values from the authenticated WebSocket. There
// is no synthesis, no interpolation and no placeholder value anywhere; a
// channel with no reading renders as unavailable instead.
//
// Provenance is whatever /channels reports. While the backend has no sensors
// registry rows and SHTAPM_CHANNEL_SOURCES is undeclared, every channel shows
// UNVERIFIED — that is correct and deliberate. It must not be presented as
// LIVE just because numbers are arriving: numbers arrive for placeholder
// constants too.
import { GlassTile } from "../components/aurora/GlassTile";
import { SensorCard } from "../components/panels/SensorCard";
import { useAuth } from "../features/auth/AuthContext";
import { useChannels } from "../features/channels/useChannels";
import { useDeviceTelemetry } from "../features/telemetry/useDeviceTelemetry";
import { CHANNELS } from "../types/contracts";
import "./device.css";

const DEVICE_ID = import.meta.env.VITE_DEVICE_ID ?? "pump-01";

const CONNECTION_LABEL: Record<string, string> = {
  connecting: "Connecting",
  open: "Live",
  closed: "Disconnected",
};

export function DevicePage() {
  const { tokens } = useAuth();
  const accessToken = tokens?.accessToken ?? null;

  const {
    channels,
    loading: channelsLoading,
    error: channelsError,
  } = useChannels(DEVICE_ID, accessToken);
  const { latest, history, connection, historyStatus, historyError, liveFrameCount } =
    useDeviceTelemetry(DEVICE_ID, accessToken);

  const byChannel = Object.fromEntries(channels.map((c) => [c.channel, c]));
  const awaitingFirstFrame = latest === null && historyStatus === "ready";

  return (
    <div className="device">
      <header className="device__head">
        <div className="device__title">
          <h1 className="t-h1">{DEVICE_ID}</h1>
          <span className="t-label">Device monitoring</span>
        </div>
        <span
          className={`device__status device__status--${connection}`}
          data-testid="connection-status"
          role="status"
        >
          <span className="device__status-dot" aria-hidden="true" />
          {CONNECTION_LABEL[connection] ?? connection}
        </span>
      </header>

      {connection === "closed" && (
        <p className="device__notice" role="status" data-testid="disconnected-notice">
          Live stream disconnected — reconnecting automatically. Values below are the last received,
          not current.
        </p>
      )}

      {historyStatus === "error" && (
        <p
          className="device__notice device__notice--error"
          role="alert"
          data-testid="history-error"
        >
          Could not load recent history: {historyError}
        </p>
      )}

      {channelsError && (
        <p
          className="device__notice device__notice--error"
          role="alert"
          data-testid="channels-error"
        >
          Could not load channel provenance: {channelsError}
        </p>
      )}

      <GlassTile
        title="Current status"
        aside={
          <span className="t-label tabular" data-testid="sample-seq">
            {latest ? `seq ${latest.sample_seq}` : "—"}
          </span>
        }
      >
        {historyStatus === "loading" || channelsLoading ? (
          <p className="t-muted" data-testid="loading">
            Loading telemetry…
          </p>
        ) : awaitingFirstFrame && history.temperature.length === 0 ? (
          <p className="t-muted" data-testid="empty">
            No telemetry recorded for this device yet. Cards will populate as frames arrive.
          </p>
        ) : (
          <div className="device__grid" data-testid="sensor-grid">
            {CHANNELS.map((channel) => {
              const series = history[channel] ?? [];
              const newest = series.length > 0 ? series[series.length - 1] : null;
              const value = latest ? latest.sensors[channel] : newest?.value ?? null;
              const updatedAt = latest ? latest.ts : newest?.ts ?? null;
              const meta = byChannel[channel];
              return (
                <SensorCard
                  key={channel}
                  channel={channel}
                  value={value}
                  unit={meta?.unit ?? null}
                  source={meta?.source ?? "unknown"}
                  part={meta?.part ?? null}
                  updatedAt={updatedAt}
                  history={series}
                />
              );
            })}
          </div>
        )}
      </GlassTile>

      <GlassTile title="Session">
        <div className="device__meta t-muted mono">
          <span data-testid="live-frames">live frames: {liveFrameCount}</span>
          <span data-testid="history-points">history points: {history.temperature.length}</span>
          <span>last frame: {latest ? latest.ts : "—"}</span>
        </div>
      </GlassTile>
    </div>
  );
}
