// What is actually behind a channel — part, wiring, and caveats.
//
// Every line rendered here comes from GET /api/devices/:id/channels. Nothing
// is looked up client-side, so the UI cannot describe hardware the backend
// registry does not name. Fields that are null are OMITTED rather than shown
// empty: a blank "Interface:" row invites the reader to assume something was
// lost, when in fact nothing is documented.
import type { ChannelOut } from "../../features/channels/useChannels";
import "./provenance-details.css";

export interface ProvenanceDetailsProps {
  meta: ChannelOut | undefined;
  channel: string;
}

/** The one-line summary under the badge. Exported for testing. */
export function describePhysicalBacking(meta: ChannelOut | undefined): string {
  if (!meta) return "No provenance information";
  if (meta.part === null) {
    // gas: no driver exists and no wiring is documented anywhere.
    return "No physical source registered";
  }
  if (meta.source === "placeholder") return `${meta.part} — not physically connected`;
  if (meta.source === "unknown") return `${meta.part} — connection not declared`;
  return meta.part;
}

export function ProvenanceDetails({ meta, channel }: ProvenanceDetailsProps) {
  if (!meta) return null;

  return (
    <dl className="prov-details" data-testid={`provenance-details-${channel}`}>
      <div className="prov-details__row">
        <dt>Source</dt>
        <dd data-testid={`provenance-part-${channel}`}>{describePhysicalBacking(meta)}</dd>
      </div>

      {/* Only shown when the (channel, part) pairing is documented. Absent for
          gas, which has no driver and no known wiring. */}
      {meta.interface && (
        <div className="prov-details__row">
          <dt>Interface</dt>
          <dd className="mono" data-testid={`provenance-interface-${channel}`}>
            {meta.interface}
          </dd>
        </div>
      )}

      {meta.is_proxy && (
        <div className="prov-details__row">
          <dt>Proxy</dt>
          <dd data-testid={`provenance-proxy-${channel}`}>
            Measures a related quantity, not the named one
          </dd>
        </div>
      )}

      {meta.note && (
        <p className="prov-details__note" data-testid={`provenance-note-${channel}`}>
          {meta.note}
        </p>
      )}

      {/* A declaration the backend refused to honour. Worth surfacing: it means
          the configuration and the registry disagree and someone should fix it. */}
      {meta.conflict && (
        <p className="prov-details__conflict" data-testid={`provenance-conflict-${channel}`}>
          Configuration conflict — {meta.conflict}
        </p>
      )}
    </dl>
  );
}
