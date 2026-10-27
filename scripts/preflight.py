"""Pre-flight self-check before a demo (PRD §18.3, Doc06 Phase 8; AC10 P8-2/P8-6).

Runs every automatable item of the PRD §18.3 checklist against the running
system and names exactly what failed, so a broken service is found at T-15 min
instead of on stage:

  1. backend up              GET /healthz
  2. MQTT + database         /api/system/health (admin)
  3. telemetry live at 1 Hz  newest reading age, spacing, all six channels
  4. latency                 edge->backend p50 < 1 s (PRD target), < 2 s hard (NFR-P1)
  5. ledger intact           POST /api/ledger/{device}/verify
  6. trust at green          newest decisions: every channel >= 0.7, nothing isolated
  7. fallback armed          the replay file parses (only where it lives, e.g. the Pi)
  8. relay                   MANUAL: click stop -> start (PRD §18.3 item 3)

Standard library only, so it runs on the laptop or the Pi without installs.
Credentials come from the environment, never from the command line or code:
``SHTAPM_PREFLIGHT_EMAIL`` / ``SHTAPM_PREFLIGHT_PASSWORD`` (an admin account).

Usage:
    python scripts/preflight.py --backend http://localhost:8002 --device pump-01
    python scripts/preflight.py --replay-file ~/SHTAPM/data/replay/session.jsonl   # on the Pi

Exit status 0 when nothing FAILED (WARN and MANUAL do not fail the check).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

CHANNELS = ("temperature", "vibration", "pressure", "humidity", "gas", "current")
TRUSTED_MIN = 0.7  # edge/trust/beta.py; trust bands are part of the frozen contract
LATENCY_TARGET_MS = 1000.0  # PRD §18.3 item 2
LATENCY_LIMIT_MS = 2000.0  # NFR-P1 / AC6
MAX_READING_AGE_S = 10.0
RATE_TOLERANCE = 0.25  # 1 Hz +/- 25%

PASS, WARN, FAIL, MANUAL, SKIP = "PASS", "WARN", "FAIL", "MANUAL", "SKIP"


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


# --- pure checks (unit-tested; no I/O) ---------------------------------------


def check_system_health(health: dict) -> list[Check]:
    out = [
        Check(
            "MQTT broker",
            PASS if health.get("mqtt_connected") else FAIL,
            "backend connected to the broker"
            if health.get("mqtt_connected")
            else "backend is NOT connected to the MQTT broker (is mosquitto running?)",
        ),
        Check(
            "database",
            PASS if health.get("db_connected") else FAIL,
            "reachable" if health.get("db_connected") else "backend cannot reach its database",
        ),
    ]
    latency = health.get("e2e_latency_ms")
    note = health.get("e2e_latency_note", "")
    if latency is None:
        out.append(Check("latency", FAIL, f"not measurable: {note or 'no value'}"))
    elif latency > LATENCY_LIMIT_MS:
        out.append(Check("latency", FAIL, f"p50 {latency:.0f} ms > {LATENCY_LIMIT_MS:.0f} ms"))
    elif latency > LATENCY_TARGET_MS:
        out.append(Check("latency", WARN, f"p50 {latency:.0f} ms (target < 1000 ms)"))
    else:
        out.append(Check("latency", PASS, f"p50 {latency:.0f} ms edge->backend"))
    return out


def check_telemetry(readings: Sequence[dict], now: datetime) -> list[Check]:
    if not readings:
        return [Check("telemetry", FAIL, "no readings stored for this device")]
    stamps = [datetime.fromisoformat(r["ts"].replace("Z", "+00:00")) for r in readings]
    stamps = [s if s.tzinfo else s.replace(tzinfo=UTC) for s in stamps]
    age = (now - stamps[-1]).total_seconds()
    out = [
        Check(
            "telemetry live",
            PASS if age <= MAX_READING_AGE_S else FAIL,
            f"newest reading {age:.1f} s old"
            + ("" if age <= MAX_READING_AGE_S else " -- is the edge service running?"),
        )
    ]
    if len(stamps) >= 3:
        span = (stamps[-1] - stamps[0]).total_seconds()
        rate = (len(stamps) - 1) / span if span > 0 else 0.0
        ok = abs(rate - 1.0) <= RATE_TOLERANCE
        out.append(Check("sample rate", PASS if ok else WARN, f"{rate:.2f} Hz (target 1 Hz)"))
    missing = [ch for ch in CHANNELS if readings[-1].get(ch) is None]
    out.append(
        Check(
            "six channels",
            PASS if not missing else FAIL,
            "all six present" if not missing else f"missing: {missing}",
        )
    )
    return out


def check_ledger(verify: dict) -> Check:
    if verify.get("valid"):
        return Check("ledger", PASS, "hash chain verifies")
    return Check("ledger", FAIL, f"chain BROKEN at block {verify.get('broken_at')}")


def check_trust(decisions: Sequence[dict]) -> Check:
    if not decisions:
        return Check("trust baseline", FAIL, "no decisions yet -- is P2 monitoring running?")
    latest = decisions[-1]
    low = {
        ch: latest.get(f"trust_{ch}")
        for ch in CHANNELS
        if latest.get(f"trust_{ch}") is not None and latest[f"trust_{ch}"] < TRUSTED_MIN
    }
    isolated = latest.get("isolated_channels") or []
    if isolated:
        return Check("trust baseline", FAIL, f"channels isolated now: {isolated}")
    if low:
        shown = ", ".join(f"{ch} {t:.2f}" for ch, t in low.items())
        return Check("trust baseline", WARN, f"below {TRUSTED_MIN}: {shown}")
    return Check("trust baseline", PASS, f"every channel >= {TRUSTED_MIN}")


def check_replay_file(path: Path) -> Check:
    if not path.is_file():
        return Check("fallback armed", FAIL, f"{path} does not exist")
    frames = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            start = line.find("{")
            if start < 0:
                continue
            try:
                row = json.loads(line[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(row.get("sensors"), dict):
                frames += 1
    if frames == 0:
        return Check("fallback armed", FAIL, f"{path} holds no telemetry frame")
    return Check("fallback armed", PASS, f"{frames} recorded frames ready ({path})")


# --- I/O ---------------------------------------------------------------------


class Backend:
    def __init__(self, base_url: str, opener: Callable = urllib.request.urlopen) -> None:
        self._base = base_url.rstrip("/")
        self._open = opener
        self._token: str | None = None

    def _request(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self._base + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        if self._token:
            request.add_header("Authorization", f"Bearer {self._token}")
        with self._open(request, timeout=10) as response:
            payload = response.read().decode()
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return payload

    def healthz(self):
        return self._request("GET", "/healthz")

    def login(self, email: str, password: str) -> None:
        tokens = self._request("POST", "/api/auth/login", {"email": email, "password": password})
        self._token = tokens["access_token"]

    def get(self, path: str):
        return self._request("GET", path)

    def post(self, path: str):
        return self._request("POST", path, {})


def run(args: argparse.Namespace, backend: Backend, env: dict) -> list[Check]:
    checks: list[Check] = []
    try:
        backend.healthz()
        checks.append(Check("backend", PASS, f"{args.backend} answers /healthz"))
    except (urllib.error.URLError, OSError) as e:
        checks.append(Check("backend", FAIL, f"{args.backend} unreachable: {e}"))
        return checks

    email, password = env.get("SHTAPM_PREFLIGHT_EMAIL"), env.get("SHTAPM_PREFLIGHT_PASSWORD")
    if not email or not password:
        checks.append(
            Check(
                "login",
                FAIL,
                "set SHTAPM_PREFLIGHT_EMAIL and SHTAPM_PREFLIGHT_PASSWORD (an admin account)",
            )
        )
        return checks
    try:
        backend.login(email, password)
        checks.append(Check("login", PASS, f"signed in as {email}"))
    except (urllib.error.URLError, OSError, KeyError) as e:
        checks.append(Check("login", FAIL, f"login failed: {e}"))
        return checks

    steps: list[tuple[str, Callable[[], list[Check]]]] = [
        ("system health", lambda: check_system_health(backend.get("/api/system/health"))),
        (
            "telemetry",
            lambda: check_telemetry(
                backend.get(f"/api/devices/{args.device}/readings?limit=30"), datetime.now(UTC)
            ),
        ),
        ("ledger", lambda: [check_ledger(backend.post(f"/api/ledger/{args.device}/verify"))]),
        (
            "trust",
            lambda: [check_trust(backend.get(f"/api/devices/{args.device}/decisions?limit=5"))],
        ),
    ]
    for name, step in steps:
        try:
            checks.extend(step())
        except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
            checks.append(Check(name, FAIL, f"request failed: {e}"))

    if args.replay_file:
        checks.append(check_replay_file(Path(args.replay_file).expanduser()))
    else:
        checks.append(Check("fallback armed", SKIP, "run on the Pi with --replay-file to check"))
    checks.append(
        Check("relay", MANUAL, "click a manual stop -> start and listen for the relay (§18.3.3)")
    )
    return checks


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--backend", default="http://localhost:8002")
    parser.add_argument("--device", default="pump-01")
    parser.add_argument("--replay-file", default=None)
    args = parser.parse_args(argv)
    checks = run(args, Backend(args.backend), dict(os.environ))
    width = max(len(c.name) for c in checks)
    for c in checks:
        print(f"[{c.status:6s}] {c.name:<{width}}  {c.detail}")
    failed = [c.name for c in checks if c.status == FAIL]
    print("\nPRE-FLIGHT " + ("FAILED: " + ", ".join(failed) if failed else "PASSED"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
