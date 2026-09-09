// Authentication guard.
//
// Renders `children` only when a session exists. While the initial
// localStorage read is in flight it renders nothing — redirecting during
// restore would bounce an already-signed-in user to the login screen on every
// page reload.
import { useEffect, type ReactNode } from "react";

import { navigate } from "../../app/router";
import { useAuth } from "./AuthContext";

export interface RequireAuthProps {
  children: ReactNode;
  /** Where to send an unauthenticated visitor. */
  redirectTo?: string;
}

export function RequireAuth({ children, redirectTo = "/login" }: RequireAuthProps) {
  const { isAuthenticated, isRestoring } = useAuth();

  useEffect(() => {
    if (!isRestoring && !isAuthenticated) navigate(redirectTo);
  }, [isAuthenticated, isRestoring, redirectTo]);

  if (isRestoring) return <div data-testid="auth-restoring" />;
  if (!isAuthenticated) return null;
  return <>{children}</>;
}
