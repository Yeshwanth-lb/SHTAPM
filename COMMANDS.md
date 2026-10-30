# SHTAPM command book

Copy-paste commands for every routine job. **Pi** = SSH window. **Laptop** =
PowerShell. Laptop and Pi must be on the same phone hotspot.

---

## 1. Start everything (about 2 minutes)

**Pi** — log in, start the broker and the edge service, check it:
```
ssh shtapm@shtapm-pi.local
sudo systemctl start mosquitto
sudo systemctl start shtapm
systemctl status shtapm.service
```
Want `Active: active (running)`. Press `q` to leave the status view. If it says
`activating (auto-restart)`, see section 9.

**Laptop, window 1** — backend:
```
cd "C:\Users\Yeshwanth L B\mpp2\SHTAPM\backend"
python -m uvicorn app.main:app --port 8002 --env-file ../.env
```
"Address already in use" means the backend is already running, which is fine.

**Laptop, window 2** — dashboard (never run `npm install`):
```
cd "C:\Users\Yeshwanth L B\mpp2\SHTAPM\frontend"
npm run dev
```
Open **http://localhost:5173** and log in as admin.

**Laptop, window 3** — check the chain end to end:
```
curl http://localhost:8002/healthz
```
Want `"mqtt_connected":true` and `telemetry_count` growing each time you repeat it.

---

## 2. Is telemetry flowing? (Pi)

Five frames, one per second:
```
mosquitto_sub -h localhost -t 'shtapm/pump-01/telemetry' -C 5 -v
```
Watch only vibration and current for 20 s (motor off, then on for 5 s; both must move):
```
timeout 20 mosquitto_sub -h localhost -t 'shtapm/pump-01/telemetry' | grep --line-buffered -o '"vibration":[0-9.]*\|"current":[0-9.]*'
```
Idle: vibration about 0.05–0.15 g, current about 0 A. Running: vibration 0.5 g or
more, current about 0.7–1.1 A.

---

## 3. Check every sensor (Pi)

The diagnostic needs the service stopped (the DHT22 allows one reader at a time):
```
sudo systemctl stop shtapm
cd ~/SHTAPM
PYTHONPATH=backend:. .venv/bin/python edge/scripts/hw_diagnostic.py
sudo systemctl start shtapm
```
Every sensor must say PASS: DHT22 (temperature, humidity), ADXL335 (X/Y/Z and
vibration), BMP280 (pressure), INA219 (current). MQ-135 is a raw voltage check.
If the ADXL shows 0 or 1023 on every axis, the MCP3008 wiring is loose.

Each sensor on its own:
```
PYTHONPATH=backend:. .venv/bin/python edge/scripts/bmp280_hwtest.py
sudo i2cdetect -y 1          # want 0x40 (INA219) and 0x76 (BMP280)
ls /dev/spidev0.0            # want the file to exist (MCP3008 / ADXL335)
```
Sensor health from the backend (laptop):
```
curl http://localhost:8002/healthz
```

---

## 4. Pre-flight self-check (T-15 minutes before a demo)

**Laptop** (set your admin login first):
```
cd "C:\Users\Yeshwanth L B\mpp2\SHTAPM"
$env:SHTAPM_PREFLIGHT_EMAIL="YOUR_ADMIN_EMAIL"
$env:SHTAPM_PREFLIGHT_PASSWORD="YOUR_ADMIN_PASSWORD"
python scripts/preflight.py --backend http://localhost:8002 --device pump-01
```
Replace the two capitalised words with your real admin login (type them; there is
no default).
Checks backend, login, MQTT, database, telemetry rate and age, latency, ledger,
trust and the fallback file. The relay is a manual item.

---

## 5. Demo scenarios (dashboard → Device page → Scenario injection)

Motor ON before any attack. Each takes about 25 s to show.

| # | Scenario | Settings | Expect |
|---|---|---|---|
| 1 | Constant spoof | motor ON, channel current, 40 s, value 0 | ATTACK, then VIRTUAL value |
| 2 | Bias injection | motor OFF, channel current, 40 s, offset 0.8 | ATTACK |
| 3 | Stuck sensor | motor ON, channel current, 40 s | FAULT |

Keep an attack under about 45 s: after 60 s of substitution the pump trips (a
latched Safe Pump-Stop, by design). Wait about a minute between runs so trust
goes back to green. Cancel early with the cancel button on the same panel.

---

## 6. Record a new clean baseline (Pi, only if the setup changed)

Needed when the ADXL335 is re-mounted or a channel changes between real and
simulated (for example wiring the MQ-135). Motor off and the bench still before
the service restarts; then:
```
cd ~/SHTAPM
sudo systemctl restart shtapm
setsid nohup timeout 4200 mosquitto_sub -h localhost -t 'shtapm/pump-01/telemetry' > cycling_baseline.jsonl 2>/dev/null &
```
Switch the motor at random (each ON and OFF at least 30 s, no ON over 2 min) for
45 minutes. At minute 5 and minute 35:
```
.venv/bin/python scripts/capture_check.py cycling_baseline.jsonl
```
Any `PROBLEM:` line means stop and fix. At minute 45:
```
pkill -f mosquitto_sub
cp models/p2_baseline.npz models/p2_baseline.prev.npz
cp models/p2_baseline.json models/p2_baseline.prev.json
PYTHONPATH=backend:. .venv/bin/python edge/scripts/fit_p2_baseline.py cycling_baseline.jsonl --model-dir models
sudo systemctl restart shtapm
journalctl -u shtapm -n 50 --no-pager | grep "P2 baseline"
```
The hold-out must show "channels isolated at the end: none".

Copy a file Pi → laptop (run on the laptop):
```
scp shtapm@shtapm-pi.local:~/SHTAPM/cycling_baseline.jsonl "C:\Users\Yeshwanth L B\mpp2\SHTAPM\"
```

---

## 7. Backup demo with no sensors (replay a recording)

**Pi**. Arm it once, then switch:
```
mkdir -p ~/SHTAPM/data/replay && cp ~/SHTAPM/final_baseline.jsonl ~/SHTAPM/data/replay/session.jsonl
sed -i 's/^EDGE_SOURCE=.*/EDGE_SOURCE=replay/' ~/SHTAPM/.env || true; grep -q '^EDGE_SOURCE=' ~/SHTAPM/.env || echo 'EDGE_SOURCE=replay' >> ~/SHTAPM/.env
grep -q '^FALLBACK_REPLAY_PATH=' ~/SHTAPM/.env || echo 'FALLBACK_REPLAY_PATH=/home/shtapm/SHTAPM/data/replay/session.jsonl' >> ~/SHTAPM/.env
sudo systemctl restart shtapm
journalctl -u shtapm -n 20 --no-pager | grep "RECORDED SESSION"
```
Back to real sensors:
```
sed -i 's/^EDGE_SOURCE=.*/EDGE_SOURCE=sensors/' ~/SHTAPM/.env && sudo systemctl restart shtapm
```
The dashboard, attacks and VIRTUAL values all work on replayed data. Present it
as a recorded session. (`final_baseline.jsonl` already sits on the Pi; if not,
copy it with `scp`, see section 6.)

---

## 8. Pump relay and real MQ-135 (optional hardware)

Full wiring and settings: `project-state/DEMO_RUNBOOK.md`, sections "Pump relay
and Safe Pump-Stop" and "Gas sensor". Pi powered off for wiring. Relay: IN to
GPIO27 (physical pin 13), motor supply through COM and NO. Gas: AO through
10 kΩ to MCP3008 CH3 with 13 kΩ to GND, then re-record a baseline (section 6).

---

## 9. Troubleshooting (failures we actually hit)

| Symptom | Fix |
|---|---|
| Service keeps restarting | `journalctl -u shtapm -n 80 --no-pager`; a missing `.env` or model is named in the error |
| `ssh: could not resolve shtapm-pi.local` | Pi not on the hotspot yet; wait a minute, or find its IP on the hotspot's device list |
| Dashboard shows NO DATA on a channel | sensor silent for 10 s: reseat its wire, run section 3 |
| Temperature or humidity stuck | the DHT22 reader reopens itself after 10 s; if not, `sudo systemctl restart shtapm` |
| ADXL reads a flat 0 g | MCP3008 wire loose; section 3 reports it as a failed read |
| Attack never shows | motor must be ON for a current spoof; run `scripts/capture_check.py` on the last recording |
| Pump trip appeared | the attack ran past 60 s; restart from the Pump relay panel (admin) |
| Backend says `.env` not found | start it from the `backend` folder with `--env-file ../.env` |
| Ledger "chain broken" | never edit the database by hand; recovery steps are in `DEMO_RUNBOOK.md` |

Restart or stop the edge service any time (Pi):
```
sudo systemctl restart shtapm
sudo systemctl stop shtapm
journalctl -u shtapm -f           # live log, Ctrl+C to leave
```

---

## 10. Tests and code checks (laptop, repo root)

```
cd "C:\Users\Yeshwanth L B\mpp2\SHTAPM"
python -m pytest -q                                   # Python tests (about 10 minutes)
cd frontend; npx vitest run; npx tsc --noEmit; npx eslint .; cd ..
python -m ruff check .
python -m black --check edge backend simulator scripts
```
The full results of the last run are in `project-state/TEST_REPORT_2026-10-30.md`.

---

## 11. Build the report and papers

```
cd "C:\Users\Yeshwanth L B\mpp2\SHTAPM\report"
& "$env:LOCALAPPDATA\Programs\MiKTeX\miktex\bin\x64\pdflatex.exe" main.tex    # run it 3 times
```
Same in `paper\` (IEEE conference format) and `paper_journal\` (journal format).
Or zip a folder and upload it to Overleaf.

---

## 12. Git

```
cd "C:\Users\Yeshwanth L B\mpp2\SHTAPM"
git status
git add -A
git commit -m "your message"
git push origin main
```
Do not commit `frontend/package-lock.json`, `.env`, or the capture files.
