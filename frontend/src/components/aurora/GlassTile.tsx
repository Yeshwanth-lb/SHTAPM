// Glass bento tile (Doc04 §04.4) — the structural surface everything sits on.
//
// Presentation only: no data fetching, no state. `title` renders as the quiet
// uppercase tile caption the spec asks for (§04.3 Label role); `aside` is the
// top-right slot used for status chips and provenance badges.
import type { CSSProperties, ReactNode } from "react";

export interface GlassTileProps {
  title?: string;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
}

export function GlassTile({ title, aside, children, className, style }: GlassTileProps) {
  return (
    <section className={`glass tile${className ? ` ${className}` : ""}`} style={style}>
      {(title || aside) && (
        <header className="tile__head">
          {title ? <h2 className="t-label">{title}</h2> : <span />}
          {aside}
        </header>
      )}
      {children}
    </section>
  );
}
