// Aurora app root: ambient field + auth provider + routing.
//
// Replaces the P0 M3.5 live-telemetry proof shell. The telemetry hook,
// contract types and their tests are unchanged and still in the tree — the
// cockpit that consumes them is the next slice.
import { AppShell } from "./app/AppShell";
import { useRoute } from "./app/router";
import { MeshBackground } from "./components/aurora/MeshBackground";
import { AuthProvider } from "./features/auth/AuthContext";
import { LoginScreen } from "./features/auth/LoginScreen";
import { RequireAuth } from "./features/auth/RequireAuth";
import { DevicePage } from "./pages/DevicePage";
import { Overview } from "./pages/Overview";
import "./styles/fonts.css";
import "./styles/aurora.css";

function Routes() {
  const { path } = useRoute();

  if (path === "/login") return <LoginScreen />;

  return (
    <RequireAuth>
      <AppShell>
        {path === "/" ? (
          <Overview />
        ) : path === "/device" ? (
          <DevicePage />
        ) : (
          // Unknown or not-yet-built path. Honest, not a fabricated screen.
          <p className="t-muted" data-testid="not-built">
            Not built yet.
          </p>
        )}
      </AppShell>
    </RequireAuth>
  );
}

export function App() {
  return (
    <AuthProvider>
      {/* health="healthy" is a rendering default: nothing computes real health
          yet (no prognosis model; decisions.health_state is NULL). */}
      <MeshBackground health="healthy" />
      <Routes />
    </AuthProvider>
  );
}
