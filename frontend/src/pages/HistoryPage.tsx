// Telemetry history — GET /api/devices/:id/readings, bounded.
//
// Bounded is the point: at 1 Hz this table would otherwise pull ~86k rows a
// day into the browser. The page size is always sent explicitly and the
// backend caps it at 5000 regardless.
import { useState } from "react";

import { GlassTile } from "../components/aurora/GlassTile";
import { Sparkline } from "../components/charts/Sparkline";
import { formatEventTime } from "../features/controlroom/model";
import { StateBlock } from "../components/aurora/StateBlock";
import { useAuth } from "../features/auth/AuthContext";
import type { SensorReadingOut } from "../features/telemetry/useDeviceTelemetry";
import { apiGet } from "../lib/api";
import { useApiResource } from "../lib/useApiResource";
import { CHANNELS } from "../types/contracts";
import "./pages.css";

const DEVICE_ID = import.meta.env.VITE_DEVICE_ID ?? "pump-01";
const PAGE_SIZES = [25, 50, 100, 250] as const;

// Display precision per channel (D052). The stored value is unchanged and is
// one hover away (title), so rounding never hides what was persisted.
const DIGITS: Record<string, number> = {
  temperature: 1,
  humidity: 1,
  pressure: 2,
  gas: 1,
  vibration: 3,
  current: 3,
};

function shown(channel: string, value: number): string {
  const d = DIGITS[channel] ?? 3;
  return Math.abs(value) < 0.5 * 10 ** -d ? (0).toFixed(d) : value.toFixed(d);
}

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

      {rows.length > 1 && (
        <div className="history-trends" data-testid="history-trends">
          {CHANNELS.map((c) => (
            <div key={c} className="history-trend">
              <div className="history-trend__head">
                <span className="t-label">{c}</span>
                <span className="tabular">{shown(c, rows[0][c])}</span>
              </div>
              <Sparkline
                points={readings.data!.map((r) => ({ ts: r.ts, value: r[c] }))}
                color="var(--status-info)"
                height={40}
                label={`${c} over the last ${rows.length} readings`}
              />
            </div>
          ))}
        </div>
      )}

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
                  <th>Time</th>
                  <th>Seq</th>
                  {CHANNELS.map((c) => (
                    <th key={c}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={`${row.sample_seq}-${row.ts}`}>
                    <td className="mono">{formatEventTime(row.ts)}</td>
                    <td className="tabular t-muted">{row.sample_seq}</td>
                    {CHANNELS.map((c) => (
                      <td key={c} className="tabular" title={String(row[c])}>
                        {shown(c, row[c])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <p className="page__footnote t-muted">
          Showing the most recent {rows.length} of the stored history for{" "}
          <span className="mono">{DEVICE_ID}</span>, newest first. Values are rounded for reading;
          hover any value for the exact stored number. No aggregation.
        </p>
      </GlassTile>
    </div>
  );
}
