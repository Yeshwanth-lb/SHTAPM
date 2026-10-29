// Last incident, as a measured timeline (D057): injection -> detection ->
// isolation -> (safe stop) -> recovery, each placed at its real offset.
import { formatEventTime, type Incident } from "./model";

function secs(s: number): string {
  return s < 1 ? "0 s" : `${Math.round(s)} s`;
}

export function IncidentTimeline({ incident }: { incident: Incident | null }) {
  if (!incident) return null;
  const end = Math.max(...incident.steps.map((s) => s.offsetS), 1);
  return (
    <section className="incident" data-testid="incident-timeline">
      <header className="incident__head">
        <div>
          <span className="t-label">Last incident</span>
          <strong className="incident__title">{incident.title}</strong>
        </div>
        <span
          className={`incident__status${incident.resolvedAfterS === null ? " incident__status--open" : ""}`}
          data-testid="incident-status"
        >
          {incident.resolvedAfterS === null
            ? "ongoing"
            : `recovered after ${secs(incident.resolvedAfterS)}`}
        </span>
      </header>
      <div className="incident__track" aria-hidden="true">
        <span className="incident__line" />
        {incident.steps.map((s) => (
          <span
            key={s.label}
            className={`incident__dot incident__dot--${s.severity}`}
            style={{ left: `${(s.offsetS / end) * 100}%` }}
          />
        ))}
      </div>
      <ol className="incident__steps">
        {incident.steps.map((s) => (
          <li key={s.label} className="incident__step" data-testid="incident-step">
            <span className={`eventlog__mark eventlog__mark--${s.severity}`} aria-hidden="true" />
            <span className="incident__step-label">{s.label}</span>
            <span className="incident__offset tabular">+{secs(s.offsetS)}</span>
            <span className="mono t-muted">{formatEventTime(s.ts)}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
