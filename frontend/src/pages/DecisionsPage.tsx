// Decision / diagnostic view — the edge P2 pipeline's output.
//
// This is the project's core novelty made visible: per-channel trust, the
// anomaly flag, and the producer's own honesty labels. Everything shown is a
// real persisted decision row.
//
// The page leads with what the output IS NOT, because that is the single most
// important thing an operator or reviewer needs to know: the wired detector is
// a null detector that never flags, so `anomaly_flag: false` means the pipeline
// executed, NOT that no anomaly exists.
import { GlassTile } from "../components/aurora/GlassTile";
import { StateBlock, StatusPill } from "../components/aurora/StateBlock";
import { TrustConstellation } from "../components/panels/TrustConstellation";
import { useAuth } from "../features/auth/AuthContext";
import { useChannels } from "../features/channels/useChannels";
import {
  LIVE_DECISION_POLL_MS,
  UNCOMPUTED_DECISION_FIELDS,
  trustScores,
  useDecisionProvenance,
  useDecisions,
} from "../features/decisions/useDecisions";
import "./pages.css";

const DEVICE_ID = import.meta.env.VITE_DEVICE_ID ?? "pump-01";

export function DecisionsPage() {
  const { tokens } = useAuth();
  const accessToken = tokens?.accessToken ?? null;

  // Polled like the device page, so attribution and trust stay live (P6-5).
  const decisions = useDecisions(DEVICE_ID, accessToken, 120, LIVE_DECISION_POLL_MS);
  const provenance = useDecisionProvenance(DEVICE_ID, accessToken);
  const { channels } = useChannels(DEVICE_ID, accessToken);

  const rows = decisions.data ?? [];
  const latest = rows.length > 0 ? rows[rows.length - 1] : null;
  const scores = trustScores(latest);
  const nonLive = new Set(channels.filter((c) => c.source !== "live").map((c) => c.channel));

  const validated = provenance.data?.model_status === "validated";

  return (
    <div className="page">
      <header className="page__head">
        <h1 className="t-h1">Decisions &amp; diagnostics</h1>
        <span className="t-label mono">{DEVICE_ID}</span>
      </header>

      {/* Leading with the caveat is deliberate — see module comment. */}
      {provenance.data && (
        <GlassTile title="Producer">
          <div className="kv">
            <div className="kv__item">
              <span className="kv__label">Execution mode</span>
              <span className="kv__value mono" data-testid="execution-mode">
                {provenance.data.execution_mode}
              </span>
            </div>
            <div className="kv__item">
              <span className="kv__label">Data source</span>
              <span className="kv__value mono" data-testid="data-source">
                {provenance.data.data_source}
              </span>
            </div>
            <div className="kv__item">
              <span className="kv__label">Model status</span>
              <span className="kv__value" data-testid="model-status">
                <StatusPill tone={validated ? "healthy" : "warning"}>
                  {provenance.data.model_status}
                </StatusPill>
              </span>
            </div>
          </div>
          <p className="page__footnote t-muted" data-testid="model-status-note">
            {provenance.data.note}
          </p>
        </GlassTile>
      )}

      <GlassTile
        title="Channel trust"
        aside={
          <span className="t-label mono" data-testid="trust-ts">
            {latest ? latest.ts : "—"}
          </span>
        }
      >
        {decisions.status === "loading" && <StateBlock kind="loading" />}
        {decisions.status === "error" && (
          <StateBlock kind="error" title="Could not load decisions" onRetry={decisions.refresh}>
            {decisions.error}
          </StateBlock>
        )}
        {decisions.status === "ready" && rows.length === 0 && (
          <StateBlock kind="empty" title="No decision rows yet">
            The edge publishes a decision diagnostic once per second on
            <span className="mono"> shtapm/{DEVICE_ID}/decision_diagnostic</span>. If this stays
            empty while telemetry flows, the backend&rsquo;s decision-diagnostic consumer is not
            receiving that topic.
          </StateBlock>
        )}
        {latest && (
          <>
            <TrustConstellation scores={scores} nonLiveChannels={nonLive} />
            <p className="page__footnote t-muted">
              Beta-reputation trust per channel, from the edge trust engine. Bands follow the
              specification: ≥0.70 trusted, 0.40–0.70 suspicious, below 0.40 malicious. Trust in a
              channel that is not a live sensor is trust in a placeholder constant, marked above.
            </p>
          </>
        )}
      </GlassTile>

      {latest && (
        <GlassTile title="Anomaly state">
          <div className="kv">
            <div className="kv__item">
              <span className="kv__label">Anomaly flag</span>
              <span className="kv__value" data-testid="anomaly-flag">
                <StatusPill tone={latest.anomaly_flag ? "critical" : "muted"}>
                  {latest.anomaly_flag ? "flagged" : "not flagged"}
                </StatusPill>
              </span>
            </div>
            <div className="kv__item">
              <span className="kv__label">Severity</span>
              <span className="kv__value tabular" data-testid="anomaly-severity">
                {latest.anomaly_severity === null ? "—" : latest.anomaly_severity.toFixed(3)}
              </span>
            </div>
            <div className="kv__item">
              <span className="kv__label">Rows in window</span>
              <span className="kv__value tabular">{rows.length}</span>
            </div>
          </div>
          <div className="kv">
            <div className="kv__item">
              <span className="kv__label">Attribution</span>
              <span className="kv__value" data-testid="decision-attribution">
                <StatusPill
                  tone={
                    latest.attribution === "attack"
                      ? "critical"
                      : latest.attribution === "fault"
                        ? "warning"
                        : "muted"
                  }
                >
                  {latest.attribution ?? "—"}
                </StatusPill>
              </span>
            </div>
            <div className="kv__item">
              <span className="kv__label">Why</span>
              <span className="kv__value t-muted" data-testid="decision-reason">
                {latest.reason ?? "—"}
              </span>
            </div>
            <div className="kv__item">
              <span className="kv__label">Isolated</span>
              <span className="kv__value mono" data-testid="decision-isolated">
                {(latest.isolated_channels ?? []).join(", ") || "none"}
              </span>
            </div>
          </div>
          <p className="page__footnote t-muted" data-testid="null-detector-note">
            <strong>&ldquo;Not flagged&rdquo; is not an all-clear.</strong> The live detector is an
            Isolation Forest fitted on the bench&rsquo;s clean baseline (D031, D037); attribution
            comes from motor-state physics (D034). Neither is validated against real attacks on this
            pump, and an attack that keeps a sensor in its true motor state is outside what the
            physics can see (D037).
          </p>
        </GlassTile>
      )}

      <GlassTile title="Not computed">
        <p className="page__lede t-muted">
          These fields exist in the decision schema but no component writes them. They are
          unimplemented capability, not missing data — a blank here must not be read as
          &ldquo;nothing to report&rdquo;.
        </p>
        <div className="table-scroll">
          <table className="data-table" data-testid="uncomputed-table">
            <thead>
              <tr>
                <th>Field</th>
                <th>Why it is empty</th>
              </tr>
            </thead>
            <tbody>
              {UNCOMPUTED_DECISION_FIELDS.map((f) => (
                <tr key={f.field}>
                  <td className="mono">{f.field}</td>
                  <td className="t-muted">{f.why}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="page__footnote t-muted">
          There is no confidence score anywhere in this system, so none is displayed. Relay position
          and safe-stop are on the device page&rsquo;s Pump relay panel (D041).
        </p>
      </GlassTile>
    </div>
  );
}
