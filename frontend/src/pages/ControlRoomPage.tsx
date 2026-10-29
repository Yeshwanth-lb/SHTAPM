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
  displayedDecision,
  lastIncident,
  FAULT_WINDOW,
  type LedgerEvent,
} from "../features/controlroom/model";
import { DemoPresets } from "../features/controlroom/DemoPresets";
import { IncidentTimeline } from "../features/controlroom/IncidentTimeline";
import { PhysicsPanel } from "../features/controlroom/PhysicsPanel";
import { SensorDetail } from "../features/controlroom/SensorDetail";
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
  getLiveState,
  getRelay,
  getSensorHealth,
  type HealthzOut,
  type LiveStateOut,
  type RelayOut,
  type SensorHealthOut,
} from "../lib/api";
import { canInject, roleFromToken } from "../lib/token";
import { useApiResource } from "../lib/useApiResource";
import { CHANNELS } from "../types/contracts";

const DEVICE_ID = import.meta.env.VITE_DEVICE_ID ?? "pump-01";
const LEDGER_POLL_MS = 3_000;
const HEALTH_POLL_MS = 5_000;
const LOG_LINES = 40;
// No live frame for this long -> NO DATA, even with the socket open (the
// backend can lose the broker while the dashboard socket stays up). Measured
// on this computer's clock, so it works without Pi/laptop time sync.
const NO_DATA_AFTER_MS = 10_000;

export function ControlRoomPage() {
  const { tokens } = useAuth();
  const accessToken = tokens?.accessToken ?? null;
  const enabled = accessToken !== null;

  const { latest, history, connection, lastFrameAt } = useDeviceTelemetry(DEVICE_ID, accessToken);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(id);
  }, []);
  const receiving =
    connection === "open" && lastFrameAt !== null && now - lastFrameAt < NO_DATA_AFTER_MS;
  const { channels } = useChannels(DEVICE_ID, accessToken);
  const [openChannel, setOpenChannel] = useState<string | null>(null);
  const decisions = useDecisions(DEVICE_ID, accessToken, FAULT_WINDOW, LIVE_DECISION_POLL_MS);
  // The API returns decisions oldest first; the display rules want newest first.
  const decision = displayedDecision(decisions.data ? [...decisions.data].reverse() : null);
  const sensorHealth = useApiResource<SensorHealthOut>(
    () => getSensorHealth(DEVICE_ID, accessToken!),
    [accessToken],
    { enabled, pollMs: LIVE_DECISION_POLL_MS },
  );
  const live = useApiResource<LiveStateOut>(
    () => getLiveState(DEVICE_ID, accessToken!),
    [accessToken],
    { enabled, pollMs: 1_000 },
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
    streamOpen: receiving,
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
              onOpen={() => setOpenChannel(channel)}
              twinValue={
                decision?.substituted_channels?.includes(channel)
                  ? live.data?.twin_values[channel] ?? null
                  : null
              }
            />
          ))}
        </div>
        <div className="cr" style={{ alignContent: "start" }}>
          <PhysicsPanel live={live.data ?? null} />
          {accessToken && canInject(roleFromToken(accessToken)) && (
            <DemoPresets deviceId={DEVICE_ID} accessToken={accessToken} live={live.data ?? null} />
          )}
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

      <IncidentTimeline incident={lastIncident(ledger.data ?? [])} />

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
      {openChannel && (
        <SensorDetail
          deviceId={DEVICE_ID}
          accessToken={accessToken}
          channel={openChannel}
          unit={units[openChannel] ?? ""}
          provenance={channels.find((c) => c.channel === openChannel)}
          state={channelState(openChannel, decision, stale)}
          trust={scores[openChannel as keyof typeof scores] ?? null}
          onClose={() => setOpenChannel(null)}
        />
      )}
    </div>
  );
}
