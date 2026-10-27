// Fault vs attack, as the edge attributed it (O3, PRD §18.4 step 3; D042).
//
// The decision row carries one label reduced from the per-channel ones --
// attack > fault > none -- and a reason that names the channel(s) and the
// edge's own explanation (e.g. "current: physics violation: current says the
// motor is running while vibration says it is idle"). Isolated channels are
// listed with it, so "it is a lie" and "it has been taken out of the loop"
// read together. Text-first: the label is a word, never only a colour.
import type { DecisionOut } from "./useDecisions";
import "./attribution.css";

interface Props {
  decision: DecisionOut | null;
}

export function AttributionBanner({ decision }: Props) {
  if (!decision) return null;
  const label = decision.attribution;
  const isolated = decision.isolated_channels ?? [];
  if ((label === null || label === "none") && isolated.length === 0) return null;

  const tone = label === "attack" ? "attack" : label === "fault" ? "fault" : "isolated";
  const headline =
    label === "attack"
      ? "Attack: a sensor is reporting something physically impossible"
      : label === "fault"
        ? "Fault: an anomaly consistent with the physics of the pump"
        : "Sensor isolated";

  return (
    <div
      className={`attribution attribution--${tone}`}
      role={label === "attack" ? "alert" : "status"}
      data-testid="attribution-banner"
    >
      <strong data-testid="attribution-label">{headline}</strong>
      {decision.reason && (
        <span className="attribution__reason" data-testid="attribution-reason">
          {decision.reason}
        </span>
      )}
      {isolated.length > 0 && (
        <span className="attribution__isolated" data-testid="attribution-isolated">
          Isolated: <span className="mono">{isolated.join(", ")}</span>
          {(decision.substituted_channels ?? []).length > 0 && (
            <>
              {" "}
              · VIRTUAL:{" "}
              <span className="mono">{(decision.substituted_channels ?? []).join(", ")}</span>
            </>
          )}
        </span>
      )}
    </div>
  );
}
