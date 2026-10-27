# Demo runbook

Exact commands for the live demo (A) and the backup demo (B). Do a full
rehearsal of both before any review. AC8 needs two clean runs, including the
backup.

**Path B1 verified end to end on the dev laptop, 2026-09-24:** Mosquitto
2.1.2 is installed as a Windows service. Simulator → Mosquitto → backend
(SQLite) → dashboard ran with `/healthz` reporting `mqtt_connected: true` and
`telemetry_count` climbing (4 → 24), and the dashboard returned HTTP 200 on
port 5173. Path A still needs rehearsing on the Pi.

---

## Path A: real Pi, real sensors

### On the Pi

1. Start the broker and the edge service:
   ```
   sudo systemctl start mosquitto
   sudo systemctl start shtapm
   ```
2. Check the service is really running (not restarting):
   ```
   systemctl status shtapm.service
   ```
   You want `Active: active (running)`. If it says `activating (auto-restart)`, see troubleshooting T1.
3. Check that telemetry is publishing:
   ```
   mosquitto_sub -h localhost -t 'shtapm/pump-01/telemetry' -C 5 -v
   ```
   You should see 5 JSON lines within about 5 seconds.
4. Get the Pi's IP address:
   ```
   hostname -I
   ```

### On the laptop

5. Laptop and Pi must be on the **same Wi-Fi or hotspot**.
6. In `.env`, set `MQTT_HOST=` to the Pi IP from step 4. Change only that line.
7. Terminal 1, the backend:
   ```
   cd backend
   python -m uvicorn app.main:app --port 8002 --env-file ../.env
   ```
8. Terminal 2, check the backend:
   ```
   curl http://localhost:8002/healthz
   ```
   You want `"mqtt_connected":true` and `telemetry_count` going up when you run it again.
9. Terminal 2, the dashboard:
   ```
   cd frontend
   npm run dev
   ```
   Open **http://localhost:5173**.

   Do NOT run `npm install`. `node_modules` already exists, and install
   rewrites the protected `package-lock.json`.

**During the demo, keep the motor OFF** while showing the live dashboard,
until the motor EMI fix is in (see T3).

---

## Path B: backup, no sensors

The backend and dashboard run on the laptop. The simulator replaces the sensors.

### The broker

Mosquitto for Windows is installed on the dev laptop (2026-09-24, via
`winget install EclipseFoundation.Mosquitto`) and runs as a Windows service on
port 1883. That makes B1 work with **no Pi at all**. On another laptop, run the
same winget command first.

- **B1 (default):** everything on the laptop. Steps below.
- **B2 (Pi available, sensors broken):** use the Pi's broker, and run the
  simulator on the Pi instead of `shtapm`. Steps at the end.

### Path B1 steps (laptop only, after installing Mosquitto)

1. Check the broker is up:
   ```
   sc query mosquitto
   ```
   You want `STATE : 4 RUNNING`. If not, run `net start mosquitto` as admin.
2. Terminal 1, the backend. `MQTT_HOST=localhost` on the command line
   overrides `.env` for this run only, so `.env` can keep the Pi's IP for Path A:
   ```
   cd backend
   MQTT_HOST=localhost python -m uvicorn app.main:app --port 8002 --env-file ../.env
   ```
3. Terminal 2, the simulator (Git Bash; use `;` not `:` in PYTHONPATH on Windows):
   ```
   PYTHONPATH="backend;." EDGE_MQTT_HOST=localhost EDGE_MQTT_PORT=1883 DEVICE_ID=pump-01 SAMPLE_RATE_HZ=1 python -m simulator
   ```
4. Terminal 3, check the backend:
   ```
   curl http://localhost:8002/healthz
   ```
   You want `"mqtt_connected":true` and `telemetry_count` going up.
5. Terminal 3, the dashboard:
   ```
   cd frontend
   npm run dev
   ```
   Open **http://localhost:5173**.

If asked, say plainly: *"This is simulated telemetry. The physical rig isn't
connected here."*

### Path B2 steps (Pi's broker, simulator on the Pi)

1. On the Pi:
   ```
   sudo systemctl stop shtapm
   sudo systemctl start mosquitto
   cd ~/SHTAPM
   PYTHONPATH=backend:. EDGE_MQTT_HOST=localhost EDGE_MQTT_PORT=1883 DEVICE_ID=pump-01 SAMPLE_RATE_HZ=1 .venv/bin/python -m simulator
   ```
   (Not yet tested on the Pi. If it fails with a missing module, run
   `.venv/bin/pip install -r simulator/requirements.txt` first.)
2. On the laptop: steps 5–9 of Path A.
3. When finished, on the Pi: stop the simulator with Ctrl+C, then `sudo systemctl start shtapm`.

---

## Build the P2 clean baseline (D031, D037, D038)

Without it the Pi learns "normal" from 2.5 minutes at startup and raises
false alarms; channels go VIRTUAL with no attack. Do this once per bench
setup. On the Pi, with `shtapm` running:

1. Check every real sensor first (an ADXL whose ADC returns `(0, 0, 0)`
   records a flat 0 g that looks healthy): motor off, then motor on for 5 s,
   watching `vibration` and `current` move together:
   ```
   timeout 20 mosquitto_sub -h localhost -t 'shtapm/pump-01/telemetry' | grep --line-buffered -o '"vibration":[0-9.]*\|"current":[0-9.]*'
   ```
   Idle: vibration ~0.05-0.15 g, current ~0 A. Running: vibration ~0.5 g or
   more, current ~0.7-1.1 A.
2. Record at least 60 minutes (70 recommended) while cycling the motor:
   2 minutes off, then 30 s on / 90 s off. Do not touch the bench or the ADXL
   mounting. `setsid nohup` keeps it running if SSH drops:
   ```
   cd ~/SHTAPM
   setsid nohup timeout 4200 mosquitto_sub -h localhost -t 'shtapm/pump-01/telemetry' > cycling_baseline.jsonl 2>/dev/null &
   ```
3. Build it. Keep the previous baseline. The hold-out check should show
   "channels isolated at the end: none" and no WARNING about clean trust
   below 0.7 (such a channel could never be released after an attack, D037):
   ```
   cp models/p2_baseline.npz models/p2_baseline.prev.npz; cp models/p2_baseline.json models/p2_baseline.prev.json
   PYTHONPATH=backend:. .venv/bin/python edge/scripts/fit_p2_baseline.py cycling_baseline.jsonl --model-dir models
   sudo systemctl restart shtapm
   ```
4. Confirm it loaded: `journalctl -u shtapm -n 50 --no-pager | grep "P2 baseline"`.

A baseline is only valid for the configuration it was recorded with:
re-record it if the ADXL is re-mounted (vibration bands are learned from it,
D036/D038) or if any channel switches between real and simulated (e.g. the
DHT22 coming back as `SHTAPM_DRIVER_TEMPERATURE/HUMIDITY=real`): a simulated
channel's baseline makes the real sensor look anomalous, and vice versa.

## During the demo: inject an attack from the dashboard (D032)

Log in as admin, open **Device**, then use the **Scenario injection** panel:

1. Pick **Constant spoof**, channel **current**, duration about 60 s.
   Use current: it is the channel the twin reconstructs (VIRTUAL), and the
   offline rehearsal caught current attacks in 2 s and reached Malicious in
   9 s. Vibration attacks mostly never reach Malicious at idle (D033).
2. Type **0.8** (amps — a plausible running-motor value) as the spoofed value,
   then **Inject attack**. With the motor off the real reading is ~0 A, so
   "Use current reading" would spoof 0 A and change nothing. **Bias injection**
   with offset 0.5 behaves the same way.
3. Watch the channel's value flatten; trust drops; the twin takes over
   (VIRTUAL) when trust reaches Malicious; the ledger records
   `scenario_inject`, `trust_drop`, `isolate`, then `recover` after the
   injection ends and trust returns to Trusted.
4. **Stop** ends it early. Every command is audited and chained in the ledger.

If the panel says "Not sent: MQTT broker unavailable", the backend has lost
the broker (T6). Nothing was injected.

---

## First-time login

Log in with the seeded admin account. If the login fails on a fresh database, run:
```
PYTHONPATH=backend python -m app.core.seed
```
It skips an admin that already exists, so it's safe to re-run.
`SEED_ADMIN_PASSWORD` must be set in `.env`.

---

## Troubleshooting: failures we have actually hit

**T1. `shtapm.service` stuck in `activating (auto-restart)`**
1. `journalctl -u shtapm.service -n 50 --no-pager`
2. If it shows `ModuleNotFoundError: No module named 'torch'`:
   - check the Python version with `.venv/bin/python --version`
     (`edge/requirements-p3.txt` pins `torch==2.2.*`, which does not install on every Python version)
   - reinstall with `.venv/bin/pip install -r edge/requirements-p3.txt`
   - if torch can't be installed, the startup fix in `edge/main.py` (in progress)
     makes the service run without self-healing instead of crashing.
3. Then run `sudo systemctl restart shtapm` and `systemctl status shtapm.service`.

**T2. The diagnostic fails, or shows garbage DHT22 readings**
The DHT22 can't be read by two programs at once. Always stop the service first:
```
sudo systemctl stop shtapm.service
cd ~/SHTAPM
PYTHONPATH=backend:. .venv/bin/python edge/scripts/hw_diagnostic.py
sudo systemctl start shtapm.service
```
Always use `.venv/bin/python`. System Python doesn't have the Adafruit
libraries, so it reports working sensors as failed.

**T3. The dashboard goes silent when the motor runs**
Motor sparking interference knocks out the DHT22, and a frame only publishes
when all 6 channels are healthy.
- For the demo: keep the motor OFF during the live dashboard part.
- Fix: a 0.1 µF ceramic capacitor across the motor terminals; twist the motor
  wires; keep the DHT22 wire away from the motor; power the motor from a
  separate supply.

**T4. I2C `Remote I/O error` (BMP280 or INA219)**
1. Run `sudo i2cdetect -y 1`. You should see both `40` (INA219) and `76` (BMP280).
2. Missing from the grid → wiring or power problem on that sensor.
3. Shown in the grid, but `sudo i2cget -y 1 0x76 0xD0` says `Read failed` →
   a weak connection. Replace the jumper wires (don't just re-seat them), check
   VCC is **3.3 V**, and see T5.
4. A working BMP280 answers `0x58` to that `i2cget`.

**T5. BMP280 wiring (all 6 pins; none left unconnected)**
| BMP280 | Pi |
|---|---|
| VCC | 3.3 V (pin 1 or 17) |
| GND | GND |
| SCL | GPIO3 (pin 5) |
| SDA | GPIO2 (pin 3) |
| CSB | **3.3 V**: forces I2C mode |
| SDO | **GND**: sets address 0x76 |

**T6. `healthz` shows `mqtt_connected:false`**
- Path A: the laptop and Pi aren't on the same network, `MQTT_HOST` is wrong,
  or mosquitto isn't running on the Pi.
- Path B1: the Mosquitto service isn't running on the laptop.
- The backend still runs on SQLite either way; `db_connected:true` does not
  mean data is flowing.

**T7. The simulator crashes with `ConnectionRefusedError [WinError 10061]`**
No broker is listening on port 1883. Start Mosquitto first (Path B1 step 1).
