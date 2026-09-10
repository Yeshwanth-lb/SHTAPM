import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ChannelOut } from "../../features/channels/useChannels";
import { formatAge, formatValue, SensorCard } from "./SensorCard";

const HISTORY = [
  { ts: "2026-09-10T12:00:00.000Z", value: 24.4 },
  { ts: "2026-09-10T12:00:01.000Z", value: 24.5 },
];

/** A backend /channels row. Defaults are the "nothing known" shape. */
function meta(over: Partial<ChannelOut> = {}): ChannelOut {
  return {
    channel: "temperature",
    part: null,
    unit: null,
    is_proxy: null,
    display_hue: null,
    source: "unknown",
    interface: null,
    note: null,
    conflict: null,
    ...over,
  };
}

describe("formatValue", () => {
  it("renders an em dash when there is no value", () => {
    expect(formatValue(null)).toBe("—");
    expect(formatValue(NaN)).toBe("—");
  });

  it("keeps a real zero as zero", () => {
    // `current` legitimately reads 0.0 — it must not look like missing data.
    expect(formatValue(0)).toBe("0");
  });

  it("scales precision to magnitude without inventing digits", () => {
    expect(formatValue(1013.24)).toBe("1013.2"); // >=100 -> 1 decimal
    expect(formatValue(24.53)).toBe("24.53");
    expect(formatValue(0.6237)).toBe("0.624");
  });
});

describe("formatAge", () => {
  const now = Date.parse("2026-09-10T12:00:30.000Z");

  it("returns null with no timestamp", () => {
    expect(formatAge(null, now)).toBeNull();
    expect(formatAge("not-a-date", now)).toBeNull();
  });

  it("reports seconds, minutes and hours", () => {
    expect(formatAge("2026-09-10T12:00:28.000Z", now)).toBe("2s ago");
    expect(formatAge("2026-09-10T11:57:30.000Z", now)).toBe("3m ago");
    expect(formatAge("2026-09-10T09:00:30.000Z", now)).toBe("3h ago");
  });
});

describe("SensorCard — LIVE", () => {
  it("shows value, unit, part and documented interface", () => {
    render(
      <SensorCard
        channel="vibration"
        value={2.01}
        meta={meta({
          channel: "vibration",
          part: "ADXL335",
          unit: "g",
          is_proxy: false,
          source: "live",
          interface: "MCP3008 CH0-2 / SPI0 CE0",
        })}
        updatedAt="2026-09-10T12:00:01.000Z"
        history={HISTORY}
      />,
    );
    const card = screen.getByTestId("sensor-card-vibration");
    expect(screen.getByTestId("sensor-value-vibration")).toHaveTextContent("2.01");
    expect(card).toHaveTextContent("g");
    expect(card).toHaveTextContent("LIVE");
    expect(screen.getByTestId("provenance-part-vibration")).toHaveTextContent("ADXL335");
    expect(screen.getByTestId("provenance-interface-vibration")).toHaveTextContent(
      "MCP3008 CH0-2 / SPI0 CE0",
    );
  });

  it("never shows a single invented ADC channel for vibration", () => {
    render(
      <SensorCard
        channel="vibration"
        value={2.01}
        meta={meta({
          channel: "vibration",
          part: "ADXL335",
          source: "live",
          interface: "MCP3008 CH0-2 / SPI0 CE0",
        })}
        updatedAt="2026-09-10T12:00:01.000Z"
        history={HISTORY}
      />,
    );
    const text = screen.getByTestId("sensor-card-vibration").textContent ?? "";
    // X/Y/Z span three channels; "CH0" alone would misdescribe the wiring.
    expect(text).not.toMatch(/CH0\b(?!-2)/);
    expect(text).toContain("CH0-2");
  });

  it("carries the shared-DHT22 explanation on temperature and humidity", () => {
    render(
      <SensorCard
        channel="humidity"
        value={68}
        meta={meta({
          channel: "humidity",
          part: "DHT22",
          unit: "%",
          source: "live",
          interface: "GPIO17",
          note: "From the same physical DHT22 as temperature. The two channels share one part and one air mass, so their agreement is not independent corroboration.",
        })}
        updatedAt="2026-09-10T12:00:01.000Z"
        history={HISTORY}
      />,
    );
    expect(screen.getByTestId("provenance-note-humidity")).toHaveTextContent("same physical DHT22");
    expect(screen.getByTestId("provenance-note-humidity")).toHaveTextContent(
      "not independent corroboration",
    );
  });

  it("shows a relative last-update time", () => {
    render(
      <SensorCard
        channel="temperature"
        value={27.7}
        meta={meta({ part: "DHT22", unit: "°C", source: "live", interface: "GPIO17" })}
        updatedAt={new Date().toISOString()}
        history={HISTORY}
      />,
    );
    expect(screen.getByTestId("sensor-age-temperature")).toHaveTextContent("Last update:");
  });
});

describe("SensorCard — PLACEHOLDER", () => {
  it("says the registered part is not physically connected", () => {
    render(
      <SensorCard
        channel="pressure"
        value={1013.6}
        meta={meta({
          channel: "pressure",
          part: "BMP280",
          unit: "hPa",
          is_proxy: true,
          source: "placeholder",
          interface: "I2C bus 1 @ 0x76",
          note: "Barometric/atmospheric pressure — a proxy, not water-line pressure.",
        })}
        updatedAt="2026-09-10T12:00:01.000Z"
        history={HISTORY}
      />,
    );
    const card = screen.getByTestId("sensor-card-pressure");
    expect(card).toHaveTextContent("PLACEHOLDER");
    expect(card).not.toHaveTextContent("LIVE");
    expect(screen.getByTestId("provenance-part-pressure")).toHaveTextContent(
      "not physically connected",
    );
    expect(screen.getByTestId("provenance-proxy-pressure")).toBeInTheDocument();
  });

  it("says gas has no registered source and shows no invented MQ-135 wiring", () => {
    render(
      <SensorCard
        channel="gas"
        value={150}
        meta={meta({
          channel: "gas",
          part: null,
          unit: "ppm",
          is_proxy: true,
          source: "placeholder",
          interface: null,
        })}
        updatedAt="2026-09-10T12:00:01.000Z"
        history={HISTORY}
      />,
    );
    const card = screen.getByTestId("sensor-card-gas");
    expect(screen.getByTestId("provenance-part-gas")).toHaveTextContent(
      "No physical source registered",
    );
    expect(card).not.toHaveTextContent("MQ-135");
    expect(card).not.toHaveTextContent("MCP3008");
    expect(screen.queryByTestId("provenance-interface-gas")).toBeNull();
  });

  it("renders a real zero as a real value, not as missing", () => {
    render(
      <SensorCard
        channel="current"
        value={0}
        meta={meta({ channel: "current", part: "INA219", unit: "A", source: "placeholder" })}
        updatedAt="2026-09-10T12:00:01.000Z"
        history={HISTORY}
      />,
    );
    expect(screen.getByTestId("sensor-value-current")).toHaveTextContent("0");
    expect(screen.queryByTestId("sensor-unavailable-current")).toBeNull();
  });
});

describe("SensorCard — UNVERIFIED", () => {
  it("shows UNVERIFIED when the backend declared nothing", () => {
    render(
      <SensorCard channel="pressure" value={1013} meta={meta()} updatedAt={null} history={[]} />,
    );
    const card = screen.getByTestId("sensor-card-pressure");
    expect(card).toHaveTextContent("UNVERIFIED");
    expect(card).not.toHaveTextContent("LIVE");
  });

  it("surfaces a declaration/registry conflict instead of hiding it", () => {
    render(
      <SensorCard
        channel="gas"
        value={150}
        meta={meta({
          channel: "gas",
          source: "unknown",
          conflict: "declared live but no part is registered for this channel",
        })}
        updatedAt="2026-09-10T12:00:01.000Z"
        history={HISTORY}
      />,
    );
    expect(screen.getByTestId("provenance-conflict-gas")).toHaveTextContent(
      "Configuration conflict",
    );
    expect(screen.getByTestId("sensor-card-gas")).not.toHaveTextContent("LIVE");
  });

  it("an arriving value never promotes a channel", () => {
    // The invariant: values are not provenance. A steady stream of readings on
    // an undeclared channel stays UNVERIFIED.
    render(
      <SensorCard
        channel="temperature"
        value={27.7}
        meta={meta({ source: "unknown" })}
        updatedAt={new Date().toISOString()}
        history={HISTORY}
      />,
    );
    expect(screen.getByTestId("sensor-card-temperature")).toHaveTextContent("UNVERIFIED");
  });

  it("renders the unavailable state instead of a fabricated zero", () => {
    render(
      <SensorCard
        channel="gas"
        value={null}
        meta={meta({ channel: "gas", unit: "ppm" })}
        updatedAt={null}
        history={[]}
      />,
    );
    expect(screen.getByTestId("sensor-unavailable-gas")).toBeInTheDocument();
    expect(screen.getByTestId("sensor-value-gas")).toHaveTextContent("—");
    expect(screen.getByTestId("sensor-card-gas")).not.toHaveTextContent("ppm");
  });
});
