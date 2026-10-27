// Glass auth screen (Doc04 §04.4 — glass over the living aurora).
//
// The backend returns a uniform 401 for unknown email, wrong password, and
// inactive user (api/auth.py, Doc06 P2-AUTH-S1: no user enumeration). This
// screen shows that message as-is and deliberately does not try to be more
// specific — being "helpful" here would leak which accounts exist.
import { useEffect, useState, type FormEvent } from "react";

import { navigate, peekReturnPath, takeReturnPath } from "../../app/router";
import { GlassTile } from "../../components/aurora/GlassTile";
import { apiBase, describeRequestFailure, isApiError } from "../../lib/api";
import { useAuth } from "./AuthContext";
import "./login.css";

export function LoginScreen() {
  const { signIn, isAuthenticated, isRestoring } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [returnTo] = useState<string | null>(() => peekReturnPath());

  // Already signed in (or just restored a session): skip the form.
  useEffect(() => {
    if (!isRestoring && isAuthenticated) navigate(takeReturnPath() ?? "/");
  }, [isAuthenticated, isRestoring]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      // Navigation happens in the effect above once the session is adopted --
      // one place, so the return path (P5-12) is consumed exactly once.
      await signIn(email, password);
    } catch (err: unknown) {
      if (isApiError(err)) {
        setError(err.status === 401 ? "Invalid email or password." : err.message);
      } else {
        // Not an HTTP response at all. Carry the underlying reason through:
        // DNS failure, connection refused, a CORS block and a malformed body
        // are all very different problems, and collapsing them into one
        // sentence made this take three rounds to diagnose once already.
        // describeRequestFailure() never includes credentials or tokens.
        setError(`Could not reach the backend at ${apiBase()} — ${describeRequestFailure(err)}`);
      }
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <GlassTile className="login__card">
        <div className="login__brand">
          <h1 className="t-h1">SHTAPM</h1>
          <p className="t-label">Self-Healing Trust-Aware Pump Monitoring</p>
        </div>

        {returnTo && (
          <p className="login__notice" role="status" data-testid="login-return-notice">
            You were signed out. Sign in to return to <span className="mono">{returnTo}</span>.
          </p>
        )}

        <form onSubmit={onSubmit} className="login__form" noValidate>
          <label className="login__field">
            <span className="t-label">Email</span>
            <input
              className="field"
              type="email"
              name="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              data-testid="login-email"
            />
          </label>

          <label className="login__field">
            <span className="t-label">Password</span>
            <input
              className="field"
              type="password"
              name="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              data-testid="login-password"
            />
          </label>

          {error && (
            <p className="login__error" role="alert" data-testid="login-error">
              {error}
            </p>
          )}

          <button className="btn" type="submit" disabled={busy} data-testid="login-submit">
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>

        {/* No self-registration link: Doc05 §05.7 defines no public register
            endpoint — users are admin-created via POST /api/users. */}
        <p className="login__foot t-muted">Accounts are created by an administrator.</p>
      </GlassTile>
    </main>
  );
}
