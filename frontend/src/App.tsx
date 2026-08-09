// P0 M3.5 live-telemetry proof shell. Minimal by design — the Aurora dashboard
// (layout, glass, charts, routing) is P5 and will replace this.
import { useTelemetryWebSocket } from "./hooks/useTelemetryWebSocket";
import { TelemetryView } from "./features/telemetry/TelemetryView";
import "./styles/fonts.css";

export function App() {
  const { status, byDevice } = useTelemetryWebSocket();
  return (
    <main style={{ fontFamily: "Geist, system-ui, sans-serif", padding: 16 }}>
      <h1>SHTAPM — Live Telemetry (P0)</h1>
      <TelemetryView byDevice={byDevice} status={status} />
    </main>
  );
}
