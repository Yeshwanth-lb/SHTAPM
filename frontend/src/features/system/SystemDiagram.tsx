// Live architecture view (D059): the data path end to end, every box and link
// lit from a real health signal.
//
//   sensors -> Raspberry Pi edge -> MQTT -> backend (+DB, ledger) -> this browser
//
// "Pi publishing" is judged on THIS computer's clock (the backend's frame count
// rose within the last 10 s), so it works without Pi/laptop time sync.
import { useEffect, useRef, useState } from "react";

import type { HealthzOut, SystemHealthOut } from "../../lib/api";
import type { ChannelOut } from "../channels/useChannels";
import type { BrowserLatencyState } from "../telemetry/useBrowserLatency";

type Level = "ok" | "warn" | "alarm" | "unknown";

const FRESH_MS = 10_000;

/** True while the stored-frame count keeps rising (null before any reading). */
export function useFramesFlowing(count: number | undefined): boolean | null {
  const [last, setLast] = useState<{ count: number; at: number } | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const lastCount = useRef<number | null>(null);
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(id);
  }, []);
  useEffect(() => {
    if (count === undefined || count === lastCount.current) return;
    lastCount.current = count;
    setLast({ count, at: Date.now() });
  }, [count]);
  if (count === undefined || last === null) return null;
  return now - last.at < FRESH_MS;
}

const DOT: Record<Level, string> = { ok: "ok", warn: "warn", alarm: "alarm", unknown: "" };

function Node({
  title,
  subtitle,
  level,
  lines,
  testId,
}: {
  title: string;
  subtitle: string;
  level: Level;
  lines: string[];
  testId: string;
}) {
  return (
    <div className={`arch__node arch__node--${level}`} data-testid={testId} data-level={level}>
      <span className="arch__title">
        <span className={`hmi-dot${DOT[level] ? ` hmi-dot--${DOT[level]}` : ""}`} />
        <strong>{title}</strong>
      </span>
      <span className="arch__sub">{subtitle}</span>
      <ul>
        {lines.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
    </div>
  );
}

function Link({ label, live }: { label: string; live: boolean | null }) {
  const cls = live ? " arch__link--live" : live === false ? " arch__link--down" : "";
  return (
    <div className={`arch__link${cls}`} aria-hidden="true">
      <span className="arch__label">{label}</span>
      <span className="arch__wire" />
    </div>
  );
}

const ms = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${Math.round(v)} ms`;

export function SystemDiagram({
  health,
  system,
  channels,
  browser,
}: {
  health: HealthzOut | null;
  system: SystemHealthOut | null;
  channels: ChannelOut[];
  browser: BrowserLatencyState;
}) {
  const flowing = useFramesFlowing(health?.telemetry_count);
  const live = channels.filter((c) => c.source === "live").length;
  const placeholder = channels.filter((c) => c.source === "placeholder").length;

  const sensors: Level = channels.length === 0 ? "unknown" : flowing ? "ok" : "warn";
  const pi: Level = flowing === null ? "unknown" : flowing ? "ok" : "alarm";
  const mqtt: Level = !health ? "unknown" : health.mqtt_connected ? "ok" : "alarm";
  const backend: Level = !health ? "alarm" : health.db_connected ? "ok" : "warn";
  const ui: Level =
    browser.connection === "open" ? "ok" : browser.connection === "connecting" ? "warn" : "alarm";

  return (
    <section className="arch" data-testid="system-diagram" aria-label="System architecture, live">
      <Node
        testId="arch-sensors"
        title="Sensors"
        subtitle={`${live} live · ${placeholder} placeholder`}
        level={sensors}
        lines={["DHT22 · ADXL335 · BMP280", "INA219 · MQ-135"]}
      />
      <Link label="GPIO · SPI · I²C" live={flowing} />
      <Node
        testId="arch-pi"
        title="Raspberry Pi 5"
        subtitle={flowing ? "publishing ~1 Hz" : flowing === false ? "no new frames" : "—"}
        level={pi}
        lines={["anomaly detection", "trust · physics check", "digital twin · safety"]}
      />
      <Link label={`MQTT · ${ms(system?.e2e_latency_ms)}`} live={mqtt === "ok" && flowing} />
      <Node
        testId="arch-mqtt"
        title="MQTT broker"
        subtitle={mqtt === "ok" ? "connected" : mqtt === "alarm" ? "disconnected" : "—"}
        level={mqtt}
        lines={["telemetry · decisions", "commands · actuation"]}
      />
      <Link label="subscribe" live={mqtt === "ok"} />
      <Node
        testId="arch-backend"
        title="Backend"
        subtitle={health ? `${health.telemetry_count} frames` : "unreachable"}
        level={backend}
        lines={[
          "FastAPI · auth · alerts",
          health?.db_connected ? "database up" : "database down",
          "SHA-256 ledger",
        ]}
      />
      <Link label={`WebSocket · ${ms(browser.snapshot.p50Ms)}`} live={ui === "ok"} />
      <Node
        testId="arch-ui"
        title="Dashboard"
        subtitle={browser.connection === "open" ? "stream live" : browser.connection}
        level={ui}
        lines={[`${health?.ws_clients ?? "—"} browser connection(s)`]}
      />
    </section>
  );
}
