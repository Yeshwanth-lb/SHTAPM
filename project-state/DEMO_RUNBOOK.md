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

## Pre-flight self-check (T-15 min, PRD §18.3)

On the laptop (backend running), with an admin account in the environment:
```
$env:SHTAPM_PREFLIGHT_EMAIL="<admin email>"; $env:SHTAPM_PREFLIGHT_PASSWORD="<admin password>"
python scripts/preflight.py --backend http://localhost:8002 --device pump-01
```
On the Pi, add the fallback check:
`python3 scripts/preflight.py --backend http://<laptop-ip>:8002 --replay-file ~/SHTAPM/data/replay/session.jsonl`

It checks backend, login, MQTT, database, telemetry age / 1 Hz / six channels,
latency (< 1 s target, < 2 s limit), ledger verification, trust at green and
the fallback file, and names whatever FAILED. The relay check stays manual.

## Pump relay and Safe Pump-Stop (D041)

Until a relay is configured the edge runs the full safety logic against an
in-memory relay; the dashboard's Pump relay panel says "Simulated relay".

Wiring (Pi powered off): relay module VCC -> 5 V, GND -> GND, IN -> a free GPIO
(not 2, 3, 7-11 or 17, which the sensors use; GPIO27 = physical pin 13 is free).
Motor supply through the relay's COM and **NO** contacts, so an unpowered relay
means motor OFF.

Configure, then make systemd release the relay whenever the edge stops or crashes:
```
echo 'SHTAPM_RELAY_GPIO=27' >> ~/SHTAPM/.env
echo 'SHTAPM_RELAY_ACTIVE_LOW=true' >> ~/SHTAPM/.env
sudo mkdir -p /etc/systemd/system/shtapm.service.d
echo '[Service]' | sudo tee /etc/systemd/system/shtapm.service.d/relay.conf
echo 'ExecStopPost=/home/shtapm/SHTAPM/.venv/bin/python -m edge.actuation.gpio off' | sudo tee -a /etc/systemd/system/shtapm.service.d/relay.conf
sudo systemctl daemon-reload && sudo systemctl restart shtapm
```
Check the polarity before connecting the motor: after the restart the relay
must be OFF (LED off, no click). If it energised, set
`SHTAPM_RELAY_ACTIVE_LOW=false` and restart.

Start/stop: admin, Pump relay panel on the device page. Every autonomous stop
(self-heal escalation, dry-run, watchdog) LATCHES OFF; restarting needs the
confirmation box. Dry-run protection needs `SHTAPM_DRY_RUN_CURRENT_A`, measured
on the real pump running dry.

## Gas sensor: switching from simulated to the real MQ-135 (D044)

The driver is ready; until then gas is simulated. When the sensor is wired
(Pi powered off): MQ-135 VCC -> 5 V, GND -> GND, AO -> 10 kOhm -> MCP3008 pin 4
(CH3), and a 13 kOhm resistor from MCP3008 pin 4 to GND. Never connect AO
straight to the MCP3008: it can exceed 3.3 V. Then on the Pi:
```
sed -i '/^SHTAPM_DRIVER_GAS=/d;/^SHTAPM_GAS_DIVIDER_RATIO=/d' ~/SHTAPM/.env
echo 'SHTAPM_DRIVER_GAS=real' >> ~/SHTAPM/.env
echo 'SHTAPM_GAS_DIVIDER_RATIO=1.769' >> ~/SHTAPM/.env
sudo systemctl restart shtapm
```
Let it warm up (the MQ-135 heater needs minutes to settle), then record a new
baseline (section above): the old one learned simulated gas. On the laptop set
`SHTAPM_GAS_SENSOR=mq135` in `.env` and run `python -m app.core.seed` from
`backend/` so the dashboard labels gas as MQ-135, in volts.

## Fallback: recorded-session profile (D040)

If a sensor or the motor misbehaves, the Pi can replay a recorded clean
session through the identical pipeline: same dashboard, same injection,
detection, trust, self-heal and ledger. Only the numbers come from a file.

Arm it once (any clean telemetry capture works; the 70-min baseline is ideal):
```
mkdir -p ~/SHTAPM/data/replay && cp ~/SHTAPM/cycling_baseline.jsonl ~/SHTAPM/data/replay/session.jsonl
```
Switch to it, and back:
```
sed -i 's/^EDGE_SOURCE=.*/EDGE_SOURCE=replay/' ~/SHTAPM/.env || true; grep -q '^EDGE_SOURCE=' ~/SHTAPM/.env || echo 'EDGE_SOURCE=replay' >> ~/SHTAPM/.env
grep -q '^FALLBACK_REPLAY_PATH=' ~/SHTAPM/.env || echo 'FALLBACK_REPLAY_PATH=/home/shtapm/SHTAPM/data/replay/session.jsonl' >> ~/SHTAPM/.env
sudo systemctl restart shtapm
# back to live sensors:
sed -i 's/^EDGE_SOURCE=.*/EDGE_SOURCE=sensors/' ~/SHTAPM/.env && sudo systemctl restart shtapm
```
Say so when presenting: the values are a recorded bench session. The edge
logs `SOURCE = RECORDED SESSION` on startup; a missing or empty file stops it
at boot with an error naming `FALLBACK_REPLAY_PATH`.

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

## Recovery: SD card or database corruption (AC10 P8-7)

**Back up now, while everything works.** These are NOT in git: the P2
baseline and twin (`models/`), the Pi's `.env`, the recordings, and the
systemd unit (it exists only on the Pi). From PowerShell on the laptop:
```
mkdir pi-backup
scp -r shtapm@shtapm-pi.local:~/SHTAPM/models pi-backup/
scp shtapm@shtapm-pi.local:~/SHTAPM/.env pi-backup/pi.env
scp shtapm@shtapm-pi.local:~/SHTAPM/cycling_baseline.jsonl pi-backup/
ssh shtapm@shtapm-pi.local "systemctl cat shtapm; ls /etc/systemd/system/shtapm.service.d 2>/dev/null" > pi-backup/shtapm.service.txt
```

**The Pi's SD card fails.** Reflash Raspberry Pi OS (64-bit) with the same
hostname `shtapm-pi` and user `shtapm`, enable SSH, then on the Pi: enable I2C
and SPI (`sudo raspi-config` -> Interface Options), add `dtoverlay=dht11,gpiopin=17`
to `/boot/firmware/config.txt`, reboot, `git clone` the repo to `~/SHTAPM`,
create `.venv` and `pip install -r edge/requirements.txt -r edge/requirements-p3.txt`.
Copy back `models/` and `pi.env` (as `~/SHTAPM/.env`), recreate the service from
`shtapm.service.txt` (and the relay drop-in, if any), `sudo systemctl enable --now shtapm`,
then run the pre-flight check. If the backup is lost, record a new baseline
(section above) and retrain the twin (`edge/eval/bench_twin_training.py`,
D039) from that recording.

**The backend database is corrupt.** Export each device's ledger first if the
API still answers (`GET /api/ledger/pump-01/export`, admin), so the audit trail
survives outside the database. With a SQLite `DATABASE_URL`: stop the backend,
move the `.db` file aside (keep it), start the backend (the schema is
recreated) and re-seed the admin (`python -m app.core.seed` from `backend/`).
With Postgres: restore the latest `pg_dump`. Either way a fresh database
starts a NEW ledger chain from genesis -- say so; the exported file is the
record of the old one.

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
