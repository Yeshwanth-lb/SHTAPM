// Glass auth screen (Doc04 §04.4 — glass over the living aurora).
//
// The backend returns a uniform 401 for unknown email, wrong password, and
// inactive user (api/auth.py, Doc06 P2-AUTH-S1: no user enumeration). This
// screen shows that message as-is and deliberately does not try to be more
// specific — being "helpful" here would leak which accounts exist.
import { useEffect, useState, type FormEvent } from "react";

import { navigate } from "../../app/router";
import { GlassTile } from "../../components/aurora/GlassTile";
import { ApiError } from "../../lib/api";
import { useAuth } from "./AuthContext";
import "./login.css";

export function LoginScreen() {
  const { signIn, isAuthenticated, isRestoring } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Already signed in (or just restored a session): skip the form.
  useEffect(() => {
    if (!isRestoring && isAuthenticated) navigate("/");
  }, [isAuthenticated, isRestoring]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(email, password);
      navigate("/");
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(err.status === 401 ? "Invalid email or password." : err.message);
      } else {
        // Network/CORS failure — distinct from a rejected credential, and the
        // operator needs to know which so they check the backend, not the password.
        setError("Could not reach the backend. Check that it is running.");
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
