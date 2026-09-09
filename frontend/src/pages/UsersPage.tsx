// Users — GET /api/users (api/users.py). ADMIN ONLY at the backend, so a
// non-admin receives 403. That is surfaced as an explicit "not permitted"
// notice rather than an error, because it is not a failure — it is the RBAC
// working as designed.
//
// Read-only in this slice. The API supports create and update, but neither has
// a confirmation flow here yet, and a half-built admin form that can disable
// the only admin account is worse than no form at all.
import { GlassTile } from "../components/aurora/GlassTile";
import { StateBlock, StatusPill } from "../components/aurora/StateBlock";
import { useAuth } from "../features/auth/AuthContext";
import { apiGet, type UserOut } from "../lib/api";
import { useApiResource } from "../lib/useApiResource";
import "./pages.css";

export function UsersPage() {
  const { tokens } = useAuth();
  const accessToken = tokens?.accessToken ?? null;

  const users = useApiResource<UserOut[]>(
    () => apiGet<UserOut[]>("/api/users", accessToken!),
    [accessToken],
    { enabled: accessToken !== null },
  );

  const forbidden = users.error?.startsWith("HTTP 403") ?? false;

  return (
    <div className="page">
      <header className="page__head">
        <h1 className="t-h1">Users</h1>
        <span className="t-label tabular">{users.data ? `${users.data.length} accounts` : ""}</span>
      </header>

      <GlassTile>
        {users.status === "loading" && <StateBlock kind="loading" />}

        {forbidden && (
          <StateBlock kind="notice" title="Administrator access required">
            User administration is restricted to the admin role. This account cannot view it — that
            is the access control working, not an error.
          </StateBlock>
        )}

        {users.status === "error" && !forbidden && (
          <StateBlock kind="error" title="Could not load users" onRetry={users.refresh}>
            {users.error}
          </StateBlock>
        )}

        {users.status === "ready" && (users.data?.length ?? 0) === 0 && (
          <StateBlock kind="empty" title="No accounts" />
        )}

        {(users.data?.length ?? 0) > 0 && (
          <div className="table-scroll">
            <table className="data-table" data-testid="users-table">
              <thead>
                <tr>
                  <th>Email</th>
                  <th>Name</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th>Last login</th>
                </tr>
              </thead>
              <tbody>
                {users.data!.map((u) => (
                  <tr key={u.id} data-testid={`user-row-${u.email}`}>
                    <td className="mono">{u.email}</td>
                    <td>{u.full_name ?? "—"}</td>
                    <td>
                      <StatusPill tone="muted">{u.role}</StatusPill>
                    </td>
                    <td>
                      {u.is_active ? (
                        <StatusPill tone="healthy">active</StatusPill>
                      ) : (
                        <StatusPill tone="critical">disabled</StatusPill>
                      )}
                    </td>
                    <td className="mono">{u.created_at}</td>
                    <td className="mono">{u.last_login_at ?? "never"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <p className="page__footnote t-muted">
          Read-only. Creating and editing accounts is supported by the API but is not exposed here
          yet — those need a confirmation flow before they are safe to click.
        </p>
      </GlassTile>
    </div>
  );
}
