// Control room (D046): the operator's single screen.
//
// Top to bottom: master caution (with acknowledge), annunciator, the six
// instruments with live trends and trust, the pump panel and transport
// health, and the audit-ledger event log. Every figure comes from an existing
// endpoint or the live WebSocket; nothing is inferred from the absence of an
// error, and a panel that cannot load says so.
import { useEffect, useMemo, useState } from "react";

import { GlassTile } from "../components/aurora/GlassTile";
import { useAuth } from "../features/auth/AuthContext";
import { useChannels } from "../features/channels/useChannels";
import {
  Annunciator,
  EventLog,
  Instrument,
  MasterCaution,
} from "../features/controlroom/components";
import {
  annunciatorWindows,
  cautionState,
  channelState,
  describeEvent,
  type LedgerEvent,
} from "../features/controlroom/model";
import {
  LIVE_DECISION_POLL_MS,
  trustScores,
  useDecisions,
} from "../features/decisions/useDecisions";
import { RelayPanel } from "../features/relay/RelayPanel";
import { useDeviceTelemetry } from "../features/telemetry/useDeviceTelemetry";
import {
  apiGet,
  getHealthz,
  getRelay,
  getSensorHealth,
  type HealthzOut,
  type RelayOut,
  type SensorHealthOut,
} from "../lib/api";
import { useApiResource } from "../lib/useApiResource";
import { CHANNELS } from "../types/contracts";

const DEVICE_ID = import.meta.env.VITE_DEVICE_ID ?? "pump-01";
const LEDGER_POLL_MS = 3_000;
const HEALTH_POLL_MS = 5_000;
const LOG_LINES = 40;

export function ControlRoomPage() {
  const { tokens } = useAuth();
  const accessToken = tokens?.accessToken ?? null;
  const enabled = accessToken !== null;

  const { latest, history, connection } = useDeviceTelemetry(DEVICE_ID, accessToken);
  const { channels } = useChannels(DEVICE_ID, accessToken);
  const decisions = useDecisions(DEVICE_ID, accessToken, 1, LIVE_DECISION_POLL_MS);
  const decision = decisions.data?.[0] ?? null;
  const sensorHealth = useApiResource<SensorHealthOut>(
    () => getSensorHealth(DEVICE_ID, accessToken!),
    [accessToken],
    { enabled, pollMs: LIVE_DECISION_POLL_MS },
  );
  const relay = useApiResource<RelayOut>(() => getRelay(DEVICE_ID, accessToken!), [accessToken], {
    enabled,
    pollMs: LIVE_DECISION_POLL_MS,
  });
  const ledger = useApiResource<LedgerEvent[]>(
    () =>
      apiGet<LedgerEvent[]>(
        `/api/ledger/${encodeURIComponent(DEVICE_ID)}?limit=${LOG_LINES}`,
        accessToken!,
      ),
    [accessToken],
    { enabled, pollMs: LEDGER_POLL_MS },
  );
  const health = useApiResource<HealthzOut>(() => getHealthz(), [], { pollMs: HEALTH_POLL_MS });

  const stale = useMemo(() => sensorHealth.data?.stale ?? {}, [sensorHealth.data]);
  const caution = cautionState({
    decision,
    stale,
    relay: relay.data?.status ?? null,
    streamOpen: connection === "open",
  });

  // Acknowledgement is per alarm: a NEW alarm (different title) flashes again.
  const [ackedTitle, setAckedTitle] = useState<string | null>(null);
  useEffect(() => {
    if (caution.severity === "normal") setAckedTitle(null);
  }, [caution.severity]);

  const scores = trustScores(decision);
  const units = Object.fromEntries(channels.map((c) => [c.channel, c.unit ?? ""]));
  const lines = (ledger.data ?? []).slice(-LOG_LINES).reverse().map(describeEvent);
  const h = health.data;

  return (
    <div className="cr" data-testid="control-room">
      <MasterCaution
        state={caution}
        acknowledged={ackedTitle === caution.title}
        onAcknowledge={() => setAckedTitle(caution.title)}
      />

      <Annunciator windows={annunciatorWindows(decision, stale)} />

      <div className="cr__row cr__row--main">
        <div className="instruments">
          {CHANNELS.map((channel) => (
            <Instrument
              key={channel}
              channel={channel}
              value={latest ? latest.sensors[channel] : null}
              unit={units[channel] ?? ""}
              points={history[channel]}
              trust={scores[channel]}
              state={channelState(channel, decision, stale)}
            />
          ))}
        </div>
        <div className="cr" style={{ alignContent: "start" }}>
          <RelayPanel deviceId={DEVICE_ID} accessToken={accessToken} />
          <GlassTile title="Transport">
            <div className="transport" data-testid="transport">
              <span>
                <span className={`hmi-dot hmi-dot--${connection === "open" ? "ok" : "warn"}`} />{" "}
                Stream {connection}
              </span>
              <span>
                <span className={`hmi-dot hmi-dot--${h?.mqtt_connected ? "ok" : "alarm"}`} /> MQTT{" "}
                {h ? (h.mqtt_connected ? "up" : "down") : "—"}
              </span>
              <span>
                <span className={`hmi-dot hmi-dot--${h?.db_connected ? "ok" : "alarm"}`} /> Database{" "}
                {h ? (h.db_connected ? "up" : "down") : "—"}
              </span>
              <span className="tabular">Frames {h ? h.telemetry_count : "—"}</span>
            </div>
          </GlassTile>
        </div>
      </div>

      <GlassTile title="Event log (audit ledger)">
        {ledger.status === "error" ? (
          <p className="t-muted" data-testid="eventlog-error">
            {ledger.unauthorized || /403/.test(ledger.error ?? "")
              ? "The audit ledger is visible to analyst and admin roles."
              : `Could not load the ledger: ${ledger.error}`}
          </p>
        ) : (
          <EventLog lines={lines} />
        )}
      </GlassTile>
    </div>
  );
}
