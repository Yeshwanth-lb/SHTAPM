// The six-sensor trust field (Doc04 §04.5 "Trust Panel").
//
// Six nodes in a ring, each sized and coloured by that channel's trust score:
// a trusted sensor glows steady teal, a suspicious one dims to amber, a
// compromised one collapses to a small rose ember. Value is encoded by SIZE +
// COLOUR + the printed number — never colour alone (§04.6).
//
// Trust comes from the edge's beta-reputation engine, persisted per decision
// row. It is DERIVED STATE, not a measurement, and it is not validated — the
// producer labels itself `diagnostic_unvalidated`. A channel with no score
// renders as an empty outline rather than a full-trust node, because "not
// computed" and "fully trusted" must never look alike.
import { trustBand, type TrustBand } from "../../features/decisions/useDecisions";
import { CHANNELS, type Channel } from "../../types/contracts";
import "./trust-constellation.css";

export interface TrustConstellationProps {
  scores: Record<Channel, number | null>;
  /** Marks a channel whose provenance is not LIVE, so trust in it is about a
   *  value that may be a placeholder constant. */
  nonLiveChannels?: ReadonlySet<string>;
}

const BAND_LABEL: Record<TrustBand, string> = {
  trusted: "Trusted",
  suspicious: "Suspicious",
  malicious: "Malicious",
  unknown: "Not computed",
};

/** Node radius in px. Trust 0 → 9px, trust 1 → 20px. Exported for testing. */
export function nodeRadius(score: number | null): number {
  if (score === null || Number.isNaN(score)) return 9;
  const clamped = Math.min(1, Math.max(0, score));
  return 9 + clamped * 11;
}

export function TrustConstellation({ scores, nonLiveChannels }: TrustConstellationProps) {
  const anyComputed = CHANNELS.some((c) => scores[c] !== null);

  return (
    <div className="trust" data-testid="trust-constellation">
      <ul className="trust__ring">
        {CHANNELS.map((channel) => {
          const score = scores[channel];
          const band = trustBand(score);
          const radius = nodeRadius(score);
          const nonLive = nonLiveChannels?.has(channel) ?? false;
          return (
            <li key={channel} className="trust__node" data-testid={`trust-node-${channel}`}>
              <span
                className={`trust__orb trust__orb--${band}`}
                style={{ width: radius * 2, height: radius * 2 }}
                aria-hidden="true"
              />
              <span className="trust__label t-label">{channel}</span>
              <span className="trust__score tabular" data-testid={`trust-score-${channel}`}>
                {score === null ? "—" : score.toFixed(2)}
              </span>
              <span className={`trust__band trust__band--${band}`}>{BAND_LABEL[band]}</span>
              {nonLive && (
                <span className="trust__caveat" data-testid={`trust-nonlive-${channel}`}>
                  not a live sensor
                </span>
              )}
            </li>
          );
        })}
      </ul>

      {!anyComputed && (
        <p className="trust__empty t-muted" data-testid="trust-empty">
          No trust scores have been computed for this device yet.
        </p>
      )}
    </div>
  );
}
