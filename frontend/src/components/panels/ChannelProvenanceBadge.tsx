// Real-vs-placeholder channel labelling.
//
// WHY THIS EXISTS: the frozen telemetry contract carries six plain floats and
// no provenance marker, so a placeholder constant (pressure 1013.0) is
// byte-identical on the wire to a measured value. A dashboard that renders
// both identically is quietly misleading. Source comes from the backend's
// GET /api/devices/:id/channels endpoint — declared configuration, never
// inferred from the numbers.
//
// Three states, deliberately distinct (see aurora.css for why "placeholder"
// is NOT the reserved VIRTUAL purple):
//   live         a physically connected sensor produced this
//   placeholder  a fake constant; nothing is connected
//   unknown      this backend was not told — a weaker claim than "placeholder",
//                and it must never be rendered as if it were one
import type { ChannelSource } from "../../features/channels/useChannels";
import "./provenance.css";

const LABEL: Record<ChannelSource, string> = {
  live: "LIVE",
  placeholder: "PLACEHOLDER",
  unknown: "UNVERIFIED",
};

const TITLE: Record<ChannelSource, string> = {
  live: "Measured by a physically connected sensor.",
  placeholder: "Fake constant — no sensor is connected for this channel.",
  unknown:
    "Provenance not declared to the backend (SHTAPM_CHANNEL_SOURCES). Not a claim either way.",
};

export interface ChannelProvenanceBadgeProps {
  source: ChannelSource;
}

export function ChannelProvenanceBadge({ source }: ChannelProvenanceBadgeProps) {
  return (
    <span
      className={`prov prov--${source}`}
      title={TITLE[source]}
      data-testid={`provenance-${source}`}
    >
      {/* Shape differs per state as well as colour — §04.6 forbids colour-alone encoding. */}
      <span className="prov__dot" aria-hidden="true" />
      {LABEL[source]}
    </span>
  );
}
