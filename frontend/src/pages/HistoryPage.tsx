// Telemetry history — GET /api/devices/:id/readings, bounded.
//
// Bounded is the point: at 1 Hz this table would otherwise pull ~86k rows a
// day into the browser. The page size is always sent explicitly and the
// backend caps it at 5000 regardless.
import { useState } from "react";

import { GlassTile } from "../components/aurora/GlassTile";
import { StateBlock } from "../components/aurora/StateBlock";
import { useAuth } from "../features/auth/AuthContext";
import type { SensorReadingOut } from "../features/telemetry/useDeviceTelemetry";
import { apiGet } from "../lib/api";
import { useApiResource } from "../lib/useApiResource";
import { CHANNELS } from "../types/contracts";
import "./pages.css";

const DEVICE_ID = import.meta.env.VITE_DEVICE_ID ?? "pump-01";
const PAGE_SIZES = [25, 50, 100, 250] as const;

export function HistoryPage() {
  const { tokens } = useAuth();
  const accessToken = tokens?.accessToken ?? null;
  const [size, setSize] = useState<number>(50);

  const readings = useApiResource<SensorReadingOut[]>(
    () =>
      apiGet<SensorReadingOut[]>(
        `/api/devices/${encodeURIComponent(DEVICE_ID)}/readings?limit=${size}`,
        accessToken!,
      ),
    [accessToken, size],
    { enabled: accessToken !== null },
  );

  // Newest first reads better in a table; the API returns oldest-first.
  const rows = readings.data ? [...readings.data].reverse() : [];

  return (
    <div className="page">
      <header className="page__head">
        <h1 className="t-h1">Telemetry history</h1>
        <div className="toolbar">
          {PAGE_SIZES.map((n) => (
            <button
              key={n}
              type="button"
              className={`toolbar__btn${size === n ? " is-active" : ""}`}
              onClick={() => setSize(n)}
              aria-pressed={size === n}
              data-testid={`page-size-${n}`}
            >
              last {n}
            </button>
          ))}
          <button type="button" className="toolbar__btn" onClick={readings.refresh}>
            Refresh
          </button>
        </div>
      </header>

      <GlassTile>
        {readings.status === "loading" && <StateBlock kind="loading" />}

        {readings.status === "error" && (
          <StateBlock kind="error" title="Could not load history" onRetry={readings.refresh}>
            {readings.error}
          </StateBlock>
        )}

        {readings.status === "ready" && rows.length === 0 && (
          <StateBlock kind="empty" title="No readings stored yet">
            Rows appear here once the backend has persisted telemetry for{" "}
            <span className="mono">{DEVICE_ID}</span>.
          </StateBlock>
        )}

        {rows.length > 0 && (
          <div className="table-scroll">
            <table className="data-table" data-testid="history-table">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Device</th>
                  <th>Seq</th>
                  {CHANNELS.map((c) => (
                    <th key={c}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={`${row.sample_seq}-${row.ts}`}>
                    <td className="mono">{row.ts}</td>
                    <td className="mono">{DEVICE_ID}</td>
                    <td className="tabular">{row.sample_seq}</td>
                    {CHANNELS.map((c) => (
                      <td key={c} className="tabular">
                        {row[c]}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <p className="page__footnote t-muted">
          Showing the most recent {rows.length} of the stored history, newest first. Values are
          exactly as persisted — no rounding, no aggregation. Provenance is not shown per row: the
          contract stores six numbers and no sensor identity.
        </p>
      </GlassTile>
    </div>
  );
}
