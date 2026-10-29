// Alert pop-ups (D058): a NEW open alert slides in at the top right on any
// page, so an operator who is on History or the Ledger still sees an attack.
// Alerts that already existed when the page loaded are not re-announced.
import { useEffect, useRef, useState } from "react";

import { apiGet, type AlertOut } from "../lib/api";
import { useApiResource } from "../lib/useApiResource";
import { navigate } from "./router";

const POLL_MS = 4_000;
const SHOW_MS = 9_000;
const MAX_SHOWN = 3;

interface Toast {
  alert: AlertOut;
  until: number;
}

export function AlertToasts({ accessToken }: { accessToken: string | null }) {
  const open = useApiResource<AlertOut[]>(
    () => apiGet<AlertOut[]>("/api/alerts?status=open&limit=20", accessToken!),
    [accessToken],
    { enabled: accessToken !== null, pollMs: POLL_MS },
  );
  const seen = useRef<Set<string> | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);

  useEffect(() => {
    if (!open.data) return;
    if (seen.current === null) {
      seen.current = new Set(open.data.map((a) => a.id)); // existing: not news
      return;
    }
    const fresh = open.data.filter((a) => !seen.current!.has(a.id));
    if (fresh.length === 0) return;
    fresh.forEach((a) => seen.current!.add(a.id));
    const until = Date.now() + SHOW_MS;
    setToasts((prev) => [...fresh.map((alert) => ({ alert, until })), ...prev].slice(0, MAX_SHOWN));
  }, [open.data]);

  useEffect(() => {
    if (toasts.length === 0) return;
    const id = window.setInterval(() => {
      setToasts((prev) => prev.filter((t) => t.until > Date.now()));
    }, 500);
    return () => window.clearInterval(id);
  }, [toasts.length]);

  if (toasts.length === 0) return null;
  return (
    <div className="toasts" aria-live="assertive" data-testid="alert-toasts">
      {toasts.map(({ alert }) => (
        <div
          key={alert.id}
          className={`toast toast--${alert.severity}`}
          role="alert"
          data-testid="alert-toast"
        >
          <span
            className={`tag tag--${alert.type === "attack" ? "alarm" : alert.type === "fault" ? "caution" : "info"}`}
          >
            {alert.type.toUpperCase()}
          </span>
          <div className="toast__body">
            <strong>{alert.message}</strong>
            {alert.reason && <span>{alert.reason}</span>}
          </div>
          <div className="toast__actions">
            <button
              type="button"
              className="toolbar__btn"
              onClick={() => {
                setToasts((prev) => prev.filter((t) => t.alert.id !== alert.id));
                navigate("/alerts");
              }}
            >
              View
            </button>
            <button
              type="button"
              className="toast__close"
              aria-label="Dismiss"
              onClick={() => setToasts((prev) => prev.filter((t) => t.alert.id !== alert.id))}
            >
              ✕
            </button>
          </div>
          <span className="toast__timer" />
        </div>
      ))}
    </div>
  );
}
