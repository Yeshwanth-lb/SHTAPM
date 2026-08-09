// Minimal live-telemetry table (P0 M3.5). Intentionally plain — NO Aurora,
// Tailwind, charts, or animation (that is P5). Reuses the frozen contract.
import { CHANNELS, type TelemetryMessage } from "../../types/contracts";

export interface TelemetryViewProps {
  byDevice: Record<string, TelemetryMessage>;
  status: string;
}

export function TelemetryView({ byDevice, status }: TelemetryViewProps) {
  const devices = Object.keys(byDevice).sort();
  return (
    <section>
      <p data-testid="conn-status">Connection: {status}</p>
      {devices.length === 0 ? (
        <p data-testid="empty">No telemetry yet…</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>device</th>
              {CHANNELS.map((c) => (
                <th key={c}>{c}</th>
              ))}
              <th>seq</th>
              <th>ts</th>
            </tr>
          </thead>
          <tbody>
            {devices.map((d) => {
              const m = byDevice[d];
              return (
                <tr key={d} data-testid={`row-${d}`}>
                  <td>{d}</td>
                  {CHANNELS.map((c) => (
                    <td key={c}>{m.sensors[c]}</td>
                  ))}
                  <td>{m.sample_seq}</td>
                  <td>{m.ts}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
