// Audit ledger — read-only, plus chain verification.
//
// Now implementable: GET /api/ledger/{device} and POST /api/ledger/{device}/verify
// both exist and are role-gated (analyst/admin). Verification is a READ that
// walks the SHA-256 chain and reports where it breaks; it writes nothing, so
// exposing it does not need the threshold-editing workflow that was previously
// blocking this page.
//
// The ledger will normally be EMPTY here, because the only producer is a
// threshold PATCH and the UI does not expose threshold editing. That is stated
// in the empty state rather than left to look like a fault.
import { useState } from "react";

import { GlassTile } from "../components/aurora/GlassTile";
import { StateBlock } from "../components/aurora/StateBlock";
import { useAuth } from "../features/auth/AuthContext";
import { apiBase, apiGet, ApiError } from "../lib/api";
import { useApiResource } from "../lib/useApiResource";
import "./pages.css";

const DEVICE_ID = import.meta.env.VITE_DEVICE_ID ?? "pump-01";

/** Mirrors backend LedgerBlockOut (api/ledger.py). */
interface LedgerBlockOut {
  block_index: number;
  ts: string;
  event_type: string;
  payload: Record<string, unknown>;
  payload_hash: string;
  prev_hash: string;
  this_hash: string;
}

/** Mirrors backend VerifyOut (api/ledger.py). */
interface VerifyOut {
  valid: boolean;
  broken_at: number | null;
}

/** Middle-truncate a hash for display (Doc04 §04.3). Full value on hover. */
export function shortHash(hash: string): string {
  return hash.length <= 12 ? hash : `${hash.slice(0, 6)}…${hash.slice(-4)}`;
}

export function LedgerPage() {
  const { tokens } = useAuth();
  const accessToken = tokens?.accessToken ?? null;
  const [verify, setVerify] = useState<VerifyOut | null>(null);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);

  const blocks = useApiResource<LedgerBlockOut[]>(
    () => apiGet<LedgerBlockOut[]>(`/api/ledger/${encodeURIComponent(DEVICE_ID)}`, accessToken!),
    [accessToken],
    { enabled: accessToken !== null },
  );

  const forbidden = blocks.error?.startsWith("HTTP 403") ?? false;

  async function runVerify() {
    if (!accessToken) return;
    setVerifying(true);
    setVerifyError(null);
    try {
      const response = await fetch(
        `${apiBase()}/api/ledger/${encodeURIComponent(DEVICE_ID)}/verify`,
        { method: "POST", headers: { Authorization: `Bearer ${accessToken}` } },
      );
      if (!response.ok) throw new ApiError(response.status, response.statusText);
      setVerify((await response.json()) as VerifyOut);
    } catch (err: unknown) {
      setVerifyError(err instanceof ApiError ? `HTTP ${err.status}` : "verification failed");
    } finally {
      setVerifying(false);
    }
  }

  const rows = blocks.data ?? [];

  return (
    <div className="page">
      <header className="page__head">
        <h1 className="t-h1">Audit ledger</h1>
        <div className="toolbar">
          <button
            type="button"
            className="toolbar__btn"
            onClick={() => void runVerify()}
            disabled={verifying || rows.length === 0}
            data-testid="verify-chain"
          >
            {verifying ? "Verifying…" : "Verify chain"}
          </button>
        </div>
      </header>

      {verify && (
        <StateBlock
          kind={verify.valid ? "notice" : "error"}
          title={verify.valid ? "Chain intact" : "Chain broken"}
        >
          <span data-testid="verify-result">
            {verify.valid
              ? `All ${rows.length} blocks hash-verify against their predecessors.`
              : `Verification failed at block ${verify.broken_at}. Every block from there on is untrustworthy.`}
          </span>
        </StateBlock>
      )}
      {verifyError && (
        <StateBlock kind="error" title="Could not verify">
          {verifyError}
        </StateBlock>
      )}

      <GlassTile>
        {blocks.status === "loading" && <StateBlock kind="loading" />}

        {forbidden && (
          <StateBlock kind="notice" title="Analyst or administrator access required">
            The audit ledger is restricted by role. That is the access control working, not an
            error.
          </StateBlock>
        )}

        {blocks.status === "error" && !forbidden && (
          <StateBlock kind="error" title="Could not load the ledger" onRetry={blocks.refresh}>
            {blocks.error}
          </StateBlock>
        )}

        {blocks.status === "ready" && rows.length === 0 && (
          <StateBlock kind="empty" title="No ledger blocks">
            The chain is empty because nothing has written to it. Its only producer today is a
            threshold change, and threshold editing is deliberately not exposed in this UI — it
            alters safety behaviour and needs a confirmation flow first. Isolation and safe-stop
            events would also be chained here, but neither is executed: the live edge path is
            observe-only.
          </StateBlock>
        )}

        {rows.length > 0 && (
          <div className="table-scroll">
            <table className="data-table" data-testid="ledger-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Timestamp</th>
                  <th>Event</th>
                  <th>Payload hash</th>
                  <th>Prev</th>
                  <th>This</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((b) => (
                  <tr key={b.block_index} data-testid={`ledger-row-${b.block_index}`}>
                    <td className="tabular">{b.block_index}</td>
                    <td className="mono">{b.ts}</td>
                    <td>{b.event_type}</td>
                    <td className="mono" title={b.payload_hash}>
                      {shortHash(b.payload_hash)}
                    </td>
                    <td className="mono" title={b.prev_hash}>
                      {shortHash(b.prev_hash)}
                    </td>
                    <td className="mono" title={b.this_hash}>
                      {shortHash(b.this_hash)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <p className="page__footnote t-muted">
          Each block chains a SHA-256 of its payload to its predecessor&rsquo;s hash, so altering
          any historical entry invalidates every block after it. Verification is a read — it walks
          the chain and reports the first break. Entries are append-only and this view never
          modifies them.
        </p>
      </GlassTile>
    </div>
  );
}
