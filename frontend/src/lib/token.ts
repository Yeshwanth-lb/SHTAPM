// Read the role claim from an access token, for DISPLAY decisions only.
//
// The signature is not (and cannot be) verified here: this decides whether to
// show a control, never whether an action is allowed. Every privileged request
// is still authorised by the backend, which rejects a forged or expired token.
export type Role = "operator" | "analyst" | "admin";

const ROLES: readonly Role[] = ["operator", "analyst", "admin"];

export function roleFromToken(token: string | null | undefined): Role | null {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
    const claims = JSON.parse(atob(padded)) as { role?: unknown };
    return typeof claims.role === "string" && (ROLES as readonly string[]).includes(claims.role)
      ? (claims.role as Role)
      : null;
  } catch {
    return null;
  }
}

export function canInject(role: Role | null): boolean {
  return role === "analyst" || role === "admin";
}

/** Starting/stopping the pump is a physical action: admin only (D041). */
export function canControlRelay(role: Role | null): boolean {
  return role === "admin";
}
