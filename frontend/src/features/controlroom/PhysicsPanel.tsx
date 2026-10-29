// Physics check (D054, signature D061): the project's core idea, live.
//
// Current and vibration are the bench's physically coupled pair: a running
// motor draws current AND shakes. The edge classifies each one's newest
// window median against its bands; this panel states both verdicts, whether
// they agree, and draws both witnesses on one motor-state scale over time.
// Disagreement is what attribution calls an attack.
import type { ChannelMotorState, LiveStateOut } from "../../lib/api";
import { useAnimatedNumber } from "../../lib/useAnimatedNumber";
import type { ChannelPoint } from "../telemetry/useDeviceTelemetry";
import { CouplingTrace } from "./CouplingTrace";

const UNIT = { current: "A", vibration: "g" } as const;
const LABEL = { idle: "IDLE", running: "RUNNING", unclear: "UNCLEAR" } as const;

export type Verdict = "agree" | "conflict" | "unclear" | "unknown";

export function physicsVerdict(state: LiveStateOut["motor_state"]): Verdict {
  const c = state?.current?.state;
  const v = state?.vibration?.state;
  if (!c || !v) return "unknown";
  if (c === "unclear" || v === "unclear") return "unclear";
  return c === v ? "agree" : "conflict";
}

const VERDICT_TEXT: Record<Verdict, { title: string; detail: string }> = {
  agree: { title: "Physics agrees", detail: "Both witnesses tell the same story." },
  conflict: {
    title: "Physically impossible",
    detail: "A motor cannot be idle and running at once. One sensor is lying.",
  },
  unclear: {
    title: "In transition",
    detail: "A reading sits between its idle and running bands: no verdict yet.",
  },
  unknown: { title: "Waiting for the edge", detail: "No physics reading received yet." },
};

function Witness({ channel, s }: { channel: "current" | "vibration"; s?: ChannelMotorState }) {
  const median = useAnimatedNumber(s ? s.median : null);
  return (
    <div className={`witness witness--${channel}`} data-testid={`physics-${channel}`}>
      <span className="witness__name">
        <span className="witness__key" aria-hidden="true" />
        {channel} says
      </span>
      <strong className={`witness__state witness__state--${s?.state ?? "unknown"}`}>
        {s ? LABEL[s.state] : "—"}
      </strong>
      {s && (
        <span className="witness__reading tabular">
          {(median ?? s.median).toFixed(3)} {UNIT[channel]}
          <span className="witness__bands">
            idle ≤ {s.idle_max.toFixed(2)} · running ≥ {s.running_min.toFixed(2)}
          </span>
        </span>
      )}
    </div>
  );
}

export function PhysicsPanel({
  live,
  current = [],
  vibration = [],
}: {
  live: LiveStateOut | null;
  current?: ChannelPoint[];
  vibration?: ChannelPoint[];
}) {
  const verdict = physicsVerdict(live?.motor_state ?? null);
  const text = VERDICT_TEXT[verdict];
  return (
    <section className={`physics physics--${verdict}`} data-testid="physics-panel">
      <div className="physics__verdict" data-testid="physics-verdict" data-verdict={verdict}>
        <span className="physics__label">Physics check</span>
        <strong>{text.title}</strong>
        <span>{text.detail}</span>
      </div>
      <div className="physics__witnesses">
        <Witness channel="current" s={live?.motor_state?.current} />
        <Witness channel="vibration" s={live?.motor_state?.vibration} />
      </div>
      <div className="physics__trace">
        <CouplingTrace
          current={current}
          vibration={vibration}
          currentBands={live?.motor_state?.current}
          vibrationBands={live?.motor_state?.vibration}
        />
      </div>
    </section>
  );
}
