// Per-channel provenance from GET /api/devices/:id/channels.
//
// Shape mirrors backend ChannelOut (api/devices.py) exactly. The backend
// always returns all six frozen channels in contract order, so a client can
// never silently miss one; registry fields are null when no `sensors` row
// exists rather than being invented.
import { useEffect, useState } from "react";

import { apiGet } from "../../lib/api";

/** Mirrors backend ChannelOut.source. "unknown" = not declared, NOT "fake". */
export type ChannelSource = "live" | "placeholder" | "unknown";

/** Mirrors backend ChannelOut (api/devices.py). */
export interface ChannelOut {
  channel: string;
  part: string | null;
  unit: string | null;
  is_proxy: boolean | null;
  display_hue: string | null;
  source: ChannelSource;
  /** Documented wiring for (channel, part); null when not documented. */
  interface: string | null;
  /** Documented measurement caveat (proxy nature, shared part); null if none. */
  note: string | null;
  /** Why a `live` declaration was not honoured; null when there is no conflict. */
  conflict: string | null;
}

export interface ChannelsState {
  channels: ChannelOut[];
  loading: boolean;
  error: string | null;
}

const VALID_SOURCES: ReadonlySet<string> = new Set(["live", "placeholder", "unknown"]);

/**
 * Any source we do not recognise degrades to "unknown" rather than being
 * trusted or dropped: an unexpected value must never be rendered as a
 * positive claim about whether a sensor is connected.
 */
export function normalizeSource(source: unknown): ChannelSource {
  return typeof source === "string" && VALID_SOURCES.has(source)
    ? (source as ChannelSource)
    : "unknown";
}

export function useChannels(deviceId: string, accessToken: string | null): ChannelsState {
  const [state, setState] = useState<ChannelsState>({
    channels: [],
    loading: true,
    error: null,
  });

  useEffect(() => {
    if (!accessToken) {
      setState({ channels: [], loading: false, error: null });
      return;
    }
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: null }));

    apiGet<ChannelOut[]>(`/api/devices/${encodeURIComponent(deviceId)}/channels`, accessToken)
      .then((rows) => {
        if (cancelled) return;
        setState({
          channels: rows.map((row) => ({ ...row, source: normalizeSource(row.source) })),
          loading: false,
          error: null,
        });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setState({
          channels: [],
          loading: false,
          error: err instanceof Error ? err.message : "failed to load channels",
        });
      });

    return () => {
      cancelled = true;
    };
  }, [deviceId, accessToken]);

  return state;
}
