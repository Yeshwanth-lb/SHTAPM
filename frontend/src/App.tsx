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
import { AlertsPage } from "./pages/AlertsPage";
import { DevicePage } from "./pages/DevicePage";
import { DevicesPage } from "./pages/DevicesPage";
import { HistoryPage } from "./pages/HistoryPage";
import { Overview } from "./pages/Overview";
import { SettingsPage } from "./pages/SettingsPage";
import { SystemPage } from "./pages/SystemPage";
import { UsersPage } from "./pages/UsersPage";
import "./styles/fonts.css";
import "./styles/aurora.css";

/** Route table. Every entry here is a page backed by real API data; anything
 *  not listed renders an honest "not found" rather than an empty shell. */
const PAGES: Record<string, () => JSX.Element> = {
  "/": Overview,
  "/device": DevicePage,
  "/devices": DevicesPage,
  "/history": HistoryPage,
  "/alerts": AlertsPage,
  "/settings": SettingsPage,
  "/users": UsersPage,
  "/system": SystemPage,
};

function Page({ path }: { path: string }) {
  const Component = PAGES[path];
  if (!Component) {
    return (
      <p className="t-muted" data-testid="not-found">
        No such page.
      </p>
    );
  }
  return <Component />;
}

function Routes() {
  const { path } = useRoute();

  if (path === "/login") return <LoginScreen />;

  return (
    <RequireAuth>
      <AppShell>
        <Page path={path} />
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
