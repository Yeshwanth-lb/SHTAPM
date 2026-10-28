import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../features/auth/AuthContext";
import * as api from "../lib/api";
import { ControlRoomPage } from "./ControlRoomPage";

class FakeWebSocket {
  onopen: (() => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onclose: ((e: CloseEvent) => void) | null = null;
  close() {}
}

const ATTACK_DECISION = {
  ts: "2026-10-27T10:00:00.000Z",
  anomaly_flag: true,
  anomaly_severity: 0.97,
  attribution: "attack",
  reason: "current: physics violation: current says the motor is running",
  trust_temperature: 0.9,
  trust_vibration: 0.9,
  trust_pressure: 0.9,
  trust_humidity: 0.9,
  trust_gas: 0.9,
  trust_current: 0.31,
  health_state: null,
  failure_eta: null,
  rl_action: null,
  isolated_channels: ["current"],
  substituted_channels: ["current"],
};

beforeEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
  vi.stubGlobal("WebSocket", FakeWebSocket);
  window.localStorage.setItem(
    "shtapm.auth",
    JSON.stringify({ accessToken: "acc", refreshToken: "ref" }),
  );
  vi.spyOn(api, "getHealthz").mockResolvedValue({
    status: "ok",
    mqtt_connected: true,
    db_connected: true,
    db_error: null,
    telemetry_count: 42,
    devices: ["pump-01"],
    ws_clients: 1,
  });
  vi.spyOn(api, "getRelay").mockResolvedValue({
    device_id: "pump-01",
    known: false,
    status: null,
  });
  vi.spyOn(api, "getSensorHealth").mockResolvedValue({
    device_id: "pump-01",
    stale: { humidity: "2026-10-27T09:59:00Z" },
  });
  vi.spyOn(api, "apiGet").mockImplementation((path: string) => {
    if (path.includes("/decisions")) return Promise.resolve([ATTACK_DECISION] as never);
    if (path.includes("/api/ledger/"))
      return Promise.resolve([
        {
          block_index: 4,
          ts: "2026-10-27T10:00:05Z",
          event_type: "isolate",
          payload: { channel: "current" },
        },
      ] as never);
    return Promise.resolve([] as never);
  });
});

function renderPage() {
  return render(
    <AuthProvider>
      <ControlRoomPage />
    </AuthProvider>,
  );
}

describe("ControlRoomPage (D046)", () => {
  it("raises the master caution for an attack, flashing until acknowledged", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId("caution-lamp")).toHaveTextContent("ATTACK"));
    const caution = screen.getByTestId("master-caution");
    expect(caution.className).toContain("caution--unacked");
    fireEvent.click(screen.getByTestId("caution-ack"));
    expect(caution.className).not.toContain("caution--unacked");
  });

  it("lights the annunciator and tags the instruments", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("annunciator-current")).toHaveTextContent("CURR ATTACK"),
    );
    expect(screen.getByTestId("annunciator-humidity")).toHaveTextContent("HUM SENSOR DEAD");
    expect(screen.getByTestId("annunciator-gas")).toHaveAttribute("data-severity", "normal");
    expect(screen.getByTestId("instrument-current")).toHaveAttribute("data-severity", "alarm");
  });

  it("shows the audit ledger as an event log and the transport state", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("eventlog")).toHaveTextContent("current isolated"),
    );
    await waitFor(() => expect(screen.getByTestId("transport")).toHaveTextContent("Frames 42"));
  });

  it("says NO DATA while the socket is open but no reading arrives, NORMAL once one does", async () => {
    const sockets: OpenSocket[] = [];
    class OpenSocket extends FakeWebSocket {
      constructor() {
        super();
        sockets.push(this);
        setTimeout(() => this.onopen?.(), 0);
      }
    }
    vi.stubGlobal("WebSocket", OpenSocket);
    vi.spyOn(api, "getSensorHealth").mockResolvedValue({ device_id: "pump-01", stale: {} });
    vi.spyOn(api, "apiGet").mockImplementation((path: string) =>
      Promise.resolve(
        (path.includes("/decisions")
          ? [
              {
                ...ATTACK_DECISION,
                attribution: "none",
                reason: null,
                isolated_channels: [],
                substituted_channels: [],
                trust_current: 0.9,
              },
            ]
          : []) as never,
      ),
    );
    renderPage();
    await waitFor(() => expect(screen.getByTestId("caution-lamp")).toHaveTextContent("NO DATA"));
    const frame = {
      type: "telemetry",
      device_id: "pump-01",
      ts: "2026-10-28T10:00:00Z",
      sample_seq: 1,
      sensors: {
        temperature: 27,
        vibration: 0.02,
        pressure: 913,
        humidity: 50,
        gas: 150,
        current: 0,
      },
    };
    await act(async () => {
      sockets.at(-1)?.onmessage?.({ data: JSON.stringify(frame) } as MessageEvent);
    });
    await waitFor(() => expect(screen.getByTestId("caution-lamp")).toHaveTextContent("NORMAL"));
  });

  it("opens a sensor's detail panel from its instrument and closes it with Escape", async () => {
    renderPage();
    const tile = await screen.findByTestId("instrument-current");
    fireEvent.click(tile);
    const panel = await screen.findByTestId("sensor-detail");
    expect(panel).toHaveTextContent("current");
    expect(screen.getByTestId("sensor-stats")).toHaveTextContent("Std dev");
    expect(screen.getByTestId("sensor-verdicts")).toHaveTextContent("attack verdicts");
    fireEvent.click(screen.getByTestId("sensor-range-60"));
    expect(screen.getByTestId("sensor-range-60")).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("sensor-detail")).toBeNull());
  });
});
