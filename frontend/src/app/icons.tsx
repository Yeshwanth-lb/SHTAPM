// Navigation and brand icons (D052): inline 16 px line icons, no icon
// dependency. Decorative -- every icon sits next to its text label.
const PATHS: Record<string, string> = {
  "/": "M2 13h12M3.5 13V8.5M6.5 13V5M9.5 13V7M12.5 13V3",
  "/device": "M3 3h10v7H3zM6 13h4M8 10v3",
  "/devices": "M2 3h5v5H2zM9 3h5v5H9zM2 10h5v3H2zM9 10h5v3H9z",
  "/decisions": "M8 2v3M8 11v3M3.2 4.8l2.1 2.1M10.7 9.1l2.1 2.1M2 8h3M11 8h3",
  "/history": "M8 4v4l2.5 1.5M2.5 8a5.5 5.5 0 1 0 1.6-3.9M2 3v2.5h2.5",
  "/alerts":
    "M8 2.5a3.5 3.5 0 0 1 3.5 3.5v3l1.5 2H3l1.5-2V6A3.5 3.5 0 0 1 8 2.5zM6.5 13a1.5 1.5 0 0 0 3 0",
  "/ledger": "M4 2h6l2 2v10H4zM6 6h4M6 8.5h4M6 11h2.5",
  "/users":
    "M6 7a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM1.5 14c0-2.5 2-4 4.5-4s4.5 1.5 4.5 4M11 3a2.2 2.2 0 0 1 0 4.2M12.5 10c1.3.5 2 1.8 2 4",
  "/system": "M3 4h10M3 8h10M3 12h10M5.5 2.5v3M10.5 6.5v3M7 10.5v3",
  "/settings":
    "M8 10a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4",
};

export function NavIcon({ path }: { path: string }) {
  const d = PATHS[path];
  if (!d) return null;
  return (
    <svg className="nav-icon" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <path
        d={d}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** SHTAPM mark: a pump impeller inside a shield -- trust around the machine. */
export function BrandMark({ size = 22 }: { size?: number }) {
  return (
    <svg className="brand-mark" width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M12 2.2 20 5.4v6.1c0 4.6-3.3 8.6-8 10.3-4.7-1.7-8-5.7-8-10.3V5.4z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <g className="brand-mark__rotor">
        <circle cx="12" cy="11.5" r="1.6" fill="currentColor" />
        <path
          d="M12 9.9c0-2 1.2-3.2 2.6-3M13.6 12.3c1.8.9 2.3 2.5 1.4 3.6M10.4 12.2c-1.8 1-3.4.5-3.7-.9"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </g>
    </svg>
  );
}
