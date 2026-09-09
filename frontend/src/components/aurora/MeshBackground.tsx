// Ambient Health Field (Doc04 §04.5) — the app-wide mesh-gradient background.
//
// Three heavily-blurred radial orbs drifting on independent slow loops. The
// orb PALETTE is bound to overall system health; motion speed follows it too
// (serene when healthy, breathing when warning, a slow pulse when critical).
//
// Scope note: this foundation slice renders the field and accepts a health
// prop, but NOTHING in this app computes real health yet — no prognosis model
// exists (U06/D017 open) and `decisions.health_state` is NULL from the
// diagnostic ingestion path. Callers therefore pass "healthy" as a neutral
// default. That is a rendering default, not a health claim.
//
// §04.6 GPU budget: 3 orbs (spec allows <=4), one blur layer each.
import "./mesh.css";

export type FieldHealth = "healthy" | "warning" | "critical";

export interface MeshBackgroundProps {
  /** Drives orb palette + motion. Defaults to "healthy" — see scope note. */
  health?: FieldHealth;
}

export function MeshBackground({ health = "healthy" }: MeshBackgroundProps) {
  return (
    <div className={`mesh mesh--${health}`} aria-hidden="true" data-testid="mesh-background">
      <span className="mesh__orb mesh__orb--a" />
      <span className="mesh__orb mesh__orb--b" />
      <span className="mesh__orb mesh__orb--c" />
      <span className="mesh__vignette" />
    </div>
  );
}
