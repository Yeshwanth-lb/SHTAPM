// Loading / empty / error / notice states, in one place.
//
// Every page needs all four and they must read consistently: an empty result
// is not a failure, and a failure must never look like an empty result. Both
// mistakes mislead an operator about whether the system is working.
import type { ReactNode } from "react";
import "./state-block.css";

export interface StateBlockProps {
  kind: "loading" | "empty" | "error" | "notice";
  title?: string;
  children?: ReactNode;
  onRetry?: () => void;
}

const DEFAULT_TITLE: Record<StateBlockProps["kind"], string> = {
  loading: "Loading…",
  empty: "Nothing to show",
  error: "Something went wrong",
  notice: "",
};

export function StateBlock({ kind, title, children, onRetry }: StateBlockProps) {
  return (
    <div
      className={`state state--${kind}`}
      role={kind === "error" ? "alert" : "status"}
      data-testid={`state-${kind}`}
    >
      <p className="state__title">{title ?? DEFAULT_TITLE[kind]}</p>
      {children && <div className="state__body t-muted">{children}</div>}
      {onRetry && (
        <button type="button" className="state__retry" onClick={onRetry} data-testid="state-retry">
          Retry
        </button>
      )}
    </div>
  );
}

/** Small coloured pill for a status word. Colour is never the only signal —
 *  the label itself carries the meaning (Doc04 §04.6). */
export function StatusPill({
  tone,
  children,
  testId,
}: {
  tone: "healthy" | "warning" | "critical" | "muted";
  children: ReactNode;
  testId?: string;
}) {
  return (
    <span className={`pill pill--${tone}`} data-testid={testId}>
      {children}
    </span>
  );
}
