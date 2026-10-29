// Physics agreement panel (D054): the project's core idea, live.
//
// Current and vibration are the bench's physically coupled pair: a running
// motor draws current AND shakes. The edge classifies each one's newest
// window median against its bands; this panel shows both verdicts and
// whether they agree. Disagreement is what attribution calls an attack.
import type { ChannelMotorState, LiveStateOut } from "../../lib/api";
import { useAnimatedNumber } from "../../lib/useAnimatedNumber";

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

function Gauge({ channel, s }: { channel: "current" | "vibration"; s?: ChannelMotorState }) {
  const median = useAnimatedNumber(s ? s.median : null);
  if (!s) {
    return (
      <div className="physics__side">
        <span className="t-label">{channel}</span>
        <strong className="physics__state physics__state--unknown">—</strong>
      </div>
    );
  }
  // Scale: 0 .. comfortably past the running band, so idle sits left,
  // running right, and the gap between the two bands is visible.
  const top = Math.max(s.running_min * 2, s.median * 1.15, 1e-6);
  const pct = (x: number) => `${Math.max(0, Math.min(100, (x / top) * 100))}%`;
  return (
    <div className="physics__side" data-testid={`physics-${channel}`}>
      <span className="t-label">{channel} says</span>
      <strong className={`physics__state physics__state--${s.state}`}>{LABEL[s.state]}</strong>
      <div className="physics__bar" aria-hidden="true">
        <span className="physics__band physics__band--idle" style={{ width: pct(s.idle_max) }} />
        <span
          className="physics__band physics__band--run"
          style={{ left: pct(s.running_min), right: 0 }}
        />
        <span className="physics__marker" style={{ left: pct(median ?? s.median) }} />
      </div>
      <span className="physics__reading tabular">
        {(median ?? s.median).toFixed(3)} {UNIT[channel]}
        <span className="t-muted">
          {" "}
          · idle ≤ {s.idle_max.toFixed(2)} · running ≥ {s.running_min.toFixed(2)}
        </span>
      </span>
    </div>
  );
}

const VERDICT_TEXT: Record<Verdict, { title: string; detail: string }> = {
  agree: { title: "Physics agrees", detail: "Both sensors tell the same story." },
  conflict: {
    title: "Physically impossible",
    detail: "A motor cannot be idle and running at once — one sensor is lying.",
  },
  unclear: {
    title: "In transition",
    detail: "A reading sits between its idle and running bands — no verdict.",
  },
  unknown: { title: "Waiting for the edge", detail: "No physics reading received yet." },
};

export function PhysicsPanel({ live }: { live: LiveStateOut | null }) {
  const verdict = physicsVerdict(live?.motor_state ?? null);
  const text = VERDICT_TEXT[verdict];
  return (
    <section className={`physics physics--${verdict}`} data-testid="physics-panel">
      <header className="physics__head">
        <span className="t-label">Physics check · current ⇄ vibration</span>
      </header>
      <div className="physics__body">
        <Gauge channel="current" s={live?.motor_state?.current} />
        <div className="physics__link" aria-hidden="true">
          <span>{verdict === "conflict" ? "≠" : verdict === "agree" ? "=" : "~"}</span>
        </div>
        <Gauge channel="vibration" s={live?.motor_state?.vibration} />
      </div>
      <footer className="physics__verdict" data-testid="physics-verdict" data-verdict={verdict}>
        <strong>{text.title}</strong>
        <span>{text.detail}</span>
      </footer>
    </section>
  );
}
