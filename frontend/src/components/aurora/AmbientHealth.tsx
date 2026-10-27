// Drives the app-wide Ambient Health Field from the device's condition (D043).
//
// devices.health_state is now computed on the backend from attribution,
// isolation and safe-stop -- condition monitoring, not a prognosis (no
// remaining-life model exists on pump data, D017). Signed out, or before the
// first answer, the field stays at its neutral "healthy" rendering default.
import { useAuth } from "../../features/auth/AuthContext";
import { apiGet, type DeviceOut } from "../../lib/api";
import { useApiResource } from "../../lib/useApiResource";
import { MeshBackground, type FieldHealth } from "./MeshBackground";

const DEVICE_ID = import.meta.env.VITE_DEVICE_ID ?? "pump-01";
export const AMBIENT_POLL_MS = 5_000;

export function AmbientHealth() {
  const { tokens } = useAuth();
  const accessToken = tokens?.accessToken ?? null;
  const device = useApiResource<DeviceOut>(
    () => apiGet<DeviceOut>(`/api/devices/${encodeURIComponent(DEVICE_ID)}`, accessToken!),
    [accessToken],
    { enabled: accessToken !== null, pollMs: AMBIENT_POLL_MS },
  );
  const health: FieldHealth = device.data?.health_state ?? "healthy";
  return <MeshBackground health={health} />;
}
