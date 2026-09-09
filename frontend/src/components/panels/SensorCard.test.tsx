import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { formatAge, formatValue, SensorCard } from "./SensorCard";

const HISTORY = [
  { ts: "2026-09-10T12:00:00.000Z", value: 24.4 },
  { ts: "2026-09-10T12:00:01.000Z", value: 24.5 },
];

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

describe("SensorCard", () => {
  it("shows the value with its unit", () => {
    render(
      <SensorCard
        channel="temperature"
        value={24.5}
        unit="°C"
        source="unknown"
        part={null}
        updatedAt="2026-09-10T12:00:01.000Z"
        history={HISTORY}
      />,
    );
    expect(screen.getByTestId("sensor-value-temperature")).toHaveTextContent("24.5");
    expect(screen.getByTestId("sensor-card-temperature")).toHaveTextContent("°C");
  });

  it("renders the unavailable state instead of a fabricated zero", () => {
    render(
      <SensorCard
        channel="gas"
        value={null}
        unit="ppm"
        source="unknown"
        part={null}
        updatedAt={null}
        history={[]}
      />,
    );
    expect(screen.getByTestId("sensor-unavailable-gas")).toBeInTheDocument();
    expect(screen.getByTestId("sensor-value-gas")).toHaveTextContent("—");
    // The unit must not be shown next to a non-existent value.
    expect(screen.getByTestId("sensor-card-gas")).not.toHaveTextContent("ppm");
  });

  it("does not claim provenance the backend did not give", () => {
    render(
      <SensorCard
        channel="pressure"
        value={1013}
        unit="hPa"
        source="unknown"
        part={null}
        updatedAt="2026-09-10T12:00:01.000Z"
        history={HISTORY}
      />,
    );
    const card = screen.getByTestId("sensor-card-pressure");
    expect(card).toHaveTextContent("UNVERIFIED");
    expect(card).not.toHaveTextContent("LIVE");
    expect(card).toHaveTextContent("part not registered");
  });

  it("shows the part when the registry does provide one", () => {
    render(
      <SensorCard
        channel="vibration"
        value={0.62}
        unit="g"
        source="live"
        part="ADXL335"
        updatedAt="2026-09-10T12:00:01.000Z"
        history={HISTORY}
      />,
    );
    const card = screen.getByTestId("sensor-card-vibration");
    expect(card).toHaveTextContent("ADXL335");
    expect(card).toHaveTextContent("LIVE");
  });
});
