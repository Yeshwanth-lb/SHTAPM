// Interim Overview.
//
// SCOPE: this is NOT the Device Detail cockpit (Doc04 §04.5) — no bento, no
// uPlot charts, no trust constellation, no health hero. Those come with the
// screen work that follows. What it does carry now is the one thing the
// foundation must not defer: explicit real-vs-placeholder labelling for every
// channel, so no number is ever shown without saying where it came from.
import { GlassTile } from "../components/aurora/GlassTile";
import { ChannelProvenanceBadge } from "../components/panels/ChannelProvenanceBadge";
import { useAuth } from "../features/auth/AuthContext";
import { useChannels } from "../features/channels/useChannels";
import { CHANNELS } from "../types/contracts";
import "./overview.css";

const DEVICE_ID = import.meta.env.VITE_DEVICE_ID ?? "pump-01";

export function Overview() {
  const { tokens } = useAuth();
  const { channels, loading, error } = useChannels(DEVICE_ID, tokens?.accessToken ?? null);

  const liveCount = channels.filter((c) => c.source === "live").length;

  return (
    <div className="overview">
      <GlassTile
        title="Signal integrity"
        aside={
          <span className="t-label tabular" data-testid="live-count">
            {loading ? "—" : `${liveCount} / ${CHANNELS.length}`}
          </span>
        }
      >
        <p className="overview__lede t-muted">
          Channel provenance for <span className="mono">{DEVICE_ID}</span>. The telemetry contract
          carries six plain numbers and no provenance marker, so this is declared by the backend,
          never inferred from the values.
        </p>

        {error && (
          <p className="overview__error" role="alert" data-testid="channels-error">
            Could not load channel provenance: {error}
          </p>
        )}

        {loading && !error && <p className="t-muted">Loading…</p>}

        {!loading && !error && (
          <ul className="overview__channels" data-testid="channel-list">
            {channels.map((c) => (
              <li key={c.channel} className="overview__channel glass-inset">
                <div className="overview__channel-head">
                  <span className="t-label">{c.channel}</span>
                  <ChannelProvenanceBadge source={c.source} />
                </div>
                <p className="overview__channel-meta t-muted mono">
                  {c.part ?? "part not registered"}
                  {c.unit ? ` · ${c.unit}` : ""}
                  {c.is_proxy ? " · proxy measurement" : ""}
                </p>
              </li>
            ))}
          </ul>
        )}
      </GlassTile>

      <GlassTile title="Next">
        <p className="t-muted overview__lede">
          Device cockpit, trust constellation, ledger, settings and user administration follow. Live
          charts are not wired in this slice.
        </p>
      </GlassTile>
    </div>
  );
}
