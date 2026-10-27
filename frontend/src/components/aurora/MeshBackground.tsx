// Ambient Health Field (Doc04 §04.5) — the app-wide mesh-gradient background.
//
// Three heavily-blurred radial orbs drifting on independent slow loops. The
// orb PALETTE is bound to overall system health; motion speed follows it too
// (serene when healthy, breathing when warning, a slow pulse when critical).
//
// The health prop comes from AmbientHealth: the backend's condition rollup
// (D043) from attribution, isolation and safe-stop -- condition monitoring,
// not a prognosis. "healthy" remains the neutral default when signed out.
//
// §04.6 GPU budget: 3 orbs (spec allows <=4), one blur layer each.
import "./mesh.css";

export type FieldHealth = "healthy" | "warning" | "critical";

export interface MeshBackgroundProps {
  /** Drives orb palette + motion. Defaults to "healthy" (neutral). */
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
