<div align="center">

# ⚡ WINTS — Wireless Integrated Network Target System

**Physics-accurate distributed embedded system simulation for military range control**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Next.js](https://img.shields.io/badge/Next.js-14.2-000000?style=for-the-badge&logo=nextdotjs&logoColor=white)](https://nextjs.org)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-3.4-06B6D4?style=for-the-badge&logo=tailwindcss&logoColor=white)](https://tailwindcss.com)
[![Vercel](https://img.shields.io/badge/Vercel-Deployed-000000?style=for-the-badge&logo=vercel&logoColor=white)](https://vercel.com)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.7.0-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://riverbankcomputing.com/software/pyqt/)
[![MQTT](https://img.shields.io/badge/MQTT-Mosquitto_v2-660066?style=for-the-badge&logo=eclipsemosquitto&logoColor=white)](https://mosquitto.org)
[![Tests](https://img.shields.io/badge/Tests-66_Passed-brightgreen?style=for-the-badge&logo=pytest&logoColor=white)](tests/)
[![mypy](https://img.shields.io/badge/mypy-strict_0_errors-blue?style=for-the-badge)](https://mypy-lang.org)
[![ruff](https://img.shields.io/badge/ruff-0_errors-orange?style=for-the-badge)](https://docs.astral.sh/ruff/)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

<br/>

> A complete simulation of **10 motorised military range targets** spread across a 10 km² field —
> controlled from a real-time PyQt6 dashboard over MQTT, with physics-accurate motor ODEs,
> LiFePO4 battery chemistry, solar harvesting, RF link budgets, and live RTSP video feeds.

<br/>

![WINTS Dashboard](https://raw.githubusercontent.com/hamzabasharat26/Wints-controlroom/main/docs/assets/dashboard_preview.png)

</div>

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Physics Engine](#physics-engine)
- [Fault Injection](#fault-injection)
- [Quickstart](#quickstart)
- [Web Dashboard](#web-dashboard)
- [Vercel Deployment & GitHub Integration](#vercel-deployment--github-integration)
- [CLI Reference](#cli-reference)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Testing](#testing)
- [MQTT Contract](#mqtt-contract)
- [Real Hardware Path](#real-hardware-path)
- [Tech Stack](#tech-stack)
- [Documentation](#documentation)

---

## Overview

WINTS simulates a distributed embedded system where a central control room operator commands 10 motorised target masts on a firing range. Each target is an independent simulation node running:

- A **DC permanent magnet motor** modelled with coupled electrical + mechanical ODEs
- A **LiFePO4 battery pack** with full coulomb counting, temperature derating, and BMS protection
- A **solar charging system** with diurnal irradiance and MPPT simulation
- A **5 GHz RF link** with free-space path loss, log-normal shadowing, and packet error rates

All 10 nodes communicate over **MQTT (QoS 1 with LWT)** to the dashboard. The dashboard streams live **RTSP video** from each target's front and rear cameras via MediaMTX. Commands flow with UUID trace IDs, are deduplicated, acknowledged, and timed out if unacknowledged.

**Designed as a Comprehensive Engineering Project (CEP) demonstrating:**
- Distributed embedded systems design
- Physics simulation (ODEs, battery electrochemistry, RF propagation)
- Real-time GUI engineering with PyQt6
- MQTT protocol design with resilience patterns
- Fault injection and chaos testing
- Static analysis (mypy strict + ruff) and 66-test coverage

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                    WINTS CONTROL ROOM (PyQt6)                      │
│                                                                    │
│   ┌──────────────────────────────────────────────────────────┐    │
│   │  10 × TargetCard  │  EventLog  │  MetricsPanel  │ Charts │    │
│   │  ┌────────────┐   │            │  Targets Online │       │    │
│   │  │ StatusBadge│   │ [INFO]...  │  Battery SOC   │ ╱╲    │    │
│   │  │ MastWidget │   │ [CMD]...   │  RSSI (dBm)    │╱  ╲   │    │
│   │  │ BatteryBar │   │ [WARN]...  │  Solar (W)     │    ╲  │    │
│   │  │ RSSIWidget │   │            │                │     ╲ │    │
│   │  │ VideoFeed  │   └────────────┴────────────────┴──────┘│    │
│   │  │ [▲][■][▼]  │                                          │    │
│   │  └────────────┘                                          │    │
│   └──────────────────────────────────────────────────────────┘    │
│                        │ Qt Signals                                │
│                  ┌─────▼──────┐    ┌───────────────────────┐      │
│                  │SystemModel │    │  CommandTracker        │      │
│                  │ Dict[      │    │  UUID → pending/ack    │      │
│                  │  TargetData│    │  2 s timeout + 5 s     │      │
│                  │ ]          │    │  broadcast safety net  │      │
│                  └─────┬──────┘    └───────────────────────┘      │
│                        │ thread-safe update                        │
│                  ┌─────▼──────────┐                               │
│                  │ MQTT Client    │──────── paho-mqtt ──────────►  │
│                  │ subs: wints/#  │                               │
│                  │ pubs: */cmd    │                               │
│                  └────────────────┘                               │
└────────────────────────────────────────────────────────────────────┘
                          │
                     MQTT :1883 (QoS 1, LWT, Retained)
                          │
              ┌───────────▼────────────┐
              │  Eclipse Mosquitto v2  │
              └───────────┬────────────┘
                          │
   ┌──────┬───────┬───────┼───────┬───────┬──────┐
   │ T-01 │ T-02  │ T-03  │  ...  │ T-09  │ T-10 │
   │      │       │       │       │OFFLINE│      │
   │Motor │ Motor │ Motor │       │(LWT)  │Motor │
   │Batt  │ Batt  │ Batt  │       │       │Batt  │
   │Solar │ Solar │ Solar │       │       │Solar │
   │ RF   │  RF   │  RF   │       │       │ RF   │
   │HTTP  │ HTTP  │ HTTP  │       │       │HTTP  │
   │:9301 │ :9302 │ :9303 │       │       │:9310 │
   └──────┴───────┴───────┘       └───────┴──────┘

┌────────────────────────────────────────────────────────────────────┐
│           MediaMTX RTSP Server  —  rtsp://127.0.0.1:8554           │
│     20 streams: /wints/T-{01..10}/{front|rear}  (looped MP4)       │
└────────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
Button Click  →  CommandTracker.issue(trace_id)
             →  MQTT publish "wints/T-XX/cmd" QoS=1
             →  Mosquitto broker
             →  Target asyncio handler
             →  Motor ODE begins integration
             →  Status echoes trace_id back
             →  Dashboard ACKs  →  PENDING clears
             →  (or 2 s timeout fires  →  PENDING clears)
```

---

## Features

### Control Room Dashboard
- **10 Target Cards** — each showing live status badge, animated mast position, battery SOC bar, RSSI signal bars, inline RTSP video feed, motor current, solar power, fault chip, and Raise/Stop/Lower buttons
- **Animated Status Badges** — smooth colour transitions: green (ONLINE) → amber (FAULT) → red (OFFLINE)
- **Animated Mast Widget** — EMA-interpolated vertical rail showing antenna position 0–100%
- **Broadcast Commands** — RAISE ALL / STOP ALL / LOWER ALL from toolbar
- **Command Tracker** — UUID trace IDs, 2 s individual timeout, 5 s broadcast safety net; buttons never stick on PENDING
- **Event Log** — colour-coded, filterable stream of commands, acks, faults, and connection events
- **Live Charts** — 4 rolling time-series charts (Battery SOC, RSSI, Online count, Solar power) via pyqtgraph
- **LWT-aware** — T-09 shows red OFFLINE the instant its broker connection drops
- **Stale Detection** — grey STALE badge when telemetry hasn't arrived in 10 seconds
- **Double-click Video** — opens full 900×420 dual-camera (front + rear) dialog per target

### Target Simulator
- 10 **independent asyncio tasks**, zero shared mutable state
- Physics loop at **10 ms real-time steps** with 1 ms motor ODE sub-stepping
- Telemetry publish every **2 seconds** (QoS 0, RF-modelled drops)
- Status publish on **every state transition** (QoS 1, retained)
- **Deduplication** on `trace_id` — 5-second LRU window, 200 entry max
- **Fault injection HTTP API** per target on ports 9301–9310
- **LWT** published by broker on ungraceful disconnect

### Resilience & Observability
- `structlog` structured logging to console + `logs/` JSONL files
- Prometheus metrics exposed on `:9200` (dashboard) and `:9101–9110` (simulators)
- Pre-flight `wints doctor` checks all prerequisites before launch
- 66 pytest tests: unit, integration, chaos

---

## Physics Engine

### DC Permanent Magnet Motor

Coupled electrical + mechanical ODEs solved at 1 ms steps:

```
Electrical:   V = L·(di/dt) + R·i + Ke·ω     →  di/dt = (V - R·i - Ke·ω) / L
Mechanical:   J·(dω/dt) = Kt·i - B·ω - Tload  →  dω/dt = (Kt·i - B·ω - Tload·tanh(ω/0.1)) / J
Position:     dθ/dt = ω                         →  pct = (θ / (π/2)) × 100
```

| Parameter | Value | Unit |
|-----------|-------|------|
| Armature resistance R | 0.5 | Ω |
| Armature inductance L | 2.0 | mH |
| Torque/back-EMF constant | 0.08 | N·m/A |
| Rotor + load inertia J | 0.02 | kg·m² |
| Overcurrent threshold | 12.0 | A |
| Stall detection | ω < 0.5 rad/s + I > 8A for 2s | — |

### LiFePO4 Battery (4S 100Ah)

- Coulomb counting with 0.995 coulombic efficiency
- 14-point OCV-SOC lookup (EVE LF100LA datasheet)
- Temperature-dependent R_internal (doubles at −20°C)
- BMS hard cutoff at SOC < 10%, overcharge > 3.7V/cell, over-temp > 60°C

### Solar Panel (200W Monocrystalline)

```
G(t) = 1000 × max(0, sin(π × (t − 6h) / 12h)) + N(0, 50²)
P = 0.22 × 1.0 m² × G(t) × 0.95 MPPT  →  peak ≈ 209 W
```

Runs in **accelerated sim time** (default 120×: 1 real second = 2 sim minutes).

### RF Link Budget (5 GHz, Ubiquiti airMAX-style)

```
RSSI = Ptx(23dBm) + Gtx(16dBi) + Grx(23dBi) − FSPL − Lshadow − Lmisc
FSPL = 20·log10(d) + 126.9 dB  (5 GHz, d in metres)
PER:  0% above −65 dBm  →  30% at −80 dBm  →  100% at −95 dBm
```

| Target | Distance | RSSI (nominal) |
|--------|----------|----------------|
| T-01 | 500 m | −52.8 dBm |
| T-05 | 3500 m | −69.9 dBm |
| T-07 | 4200 m | −71.4 dBm |
| T-09 | 5000 m | −72.9 dBm |

---

## Fault Injection

Inject faults at runtime via CLI or HTTP API:

```bash
# Via CLI
python -m scripts.wints inject T-03 overcurrent
python -m scripts.wints inject T-03 clear

# Via HTTP directly
curl -X POST http://localhost:9303/fault/inject \
     -H "Content-Type: application/json" \
     -d '{"fault": "overcurrent"}'
```

| Fault | Effect | Dashboard |
|-------|--------|-----------|
| `overcurrent` | Shuts H-bridge, motor stops | Orange FAULT badge + `⚠ OVERCURRENT` chip |
| `limit_stuck` | Both limit switches active simultaneously | Orange FAULT badge + `⚠ LIMIT_STUCK` |
| `battery_bms` | Forces SOC to 5% → BMS cutoff | Orange FAULT badge + `⚠ BMS_CUTOFF` |
| `broker_disconnect` | Drops MQTT connection → LWT fires | Grey STALE → Red OFFLINE after ~10 s |
| `packet_loss_spike` | Doubles RF shadowing σ for 1 sim-hour | Command timeouts in event log |
| `clear` | Resets all injected faults | Green ONLINE badge restored |

**T-07** starts in `OVERCURRENT` fault by default in demo mode. **T-09** starts OFFLINE.

---

## Quickstart

### Prerequisites

- Python 3.11+
- Windows 10/11 (Linux also supported)
- [Mosquitto MQTT broker](https://mosquitto.org/download/)
- [FFmpeg](https://ffmpeg.org/) (optional — for RTSP video)
- [MediaMTX](https://github.com/bluenviron/mediamtx/releases) (auto-downloaded by `wints setup`)

### Installation

```powershell
# 1. Clone the repository
git clone https://github.com/hamzabasharat26/Wints-controlroom.git
cd Wints-controlroom

# 2. Create virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Install native dependencies (Windows)
winget install EclipseFoundation.Mosquitto
winget install Gyan.FFmpeg

# 5. Download MediaMTX and generate video test patterns
python -m scripts.wints setup

# 6. Verify all prerequisites
python -m scripts.wints doctor

# 7. Launch the full demo
python -m scripts.wints demo
```

### What happens on `wints demo`

1. Detects/starts Mosquitto broker on `:1883`
2. Starts MediaMTX RTSP server on `:8554` (20 streams)
3. Launches 10 target simulators (T-07 faulted, T-09 offline)
4. Opens the PyQt6 control room dashboard
5. Video feeds appear in each card within ~4 seconds

---

## Web Dashboard

In addition to the desktop GUI, WINTS includes a space-age, responsive **Next.js Web Dashboard** (`wints-web`) styled with the premium Catppuccin Mocha color scheme and fluid micro-animations. It uses browser-native WebSockets to connect directly to your MQTT broker, operating entirely on the client side without needing any server-side database.

### Local Development Setup
To boot the Web Dashboard locally on your computer:
1. Navigate to the frontend directory:
   ```powershell
   cd wints-web
   ```
2. Install dependencies:
   ```powershell
   npm install
   ```
3. Copy environment configuration:
   ```powershell
   copy .env.example .env.local
   ```
   Open `.env.local` and fill in your MQTT broker credentials (such as a HiveMQ Cloud free tier instance).
4. Launch the Next.js local development server:
   ```powershell
   npm run dev
   ```
5. Visit [http://localhost:3000](http://localhost:3000) to view the live dashboard.

---

## Vercel Deployment & GitHub Integration

Because the web application compiles to static assets and connects directly via WebSockets from the user's browser, you can deploy it to **Vercel** for free and run it globally.

### 1. Push to GitHub Repo
To prepare the project and push it to your GitHub account:
1. Initialize git in the root folder (if not already initialized):
   ```powershell
   git init
   ```
2. Add all files (the `.gitignore` is configured to keep virtual environments, downloaded binaries, and secrets out of version control):
   ```powershell
   git add .
   ```
3. Commit your changes:
   ```powershell
   git commit -m "feat: polish dashboard UI/UX and prepare for Vercel deployment"
   ```
4. Create a new repository on your GitHub account (leave it empty without templates).
5. Run the following commands to link your repository and push:
   ```powershell
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
   git branch -M main
   git push -u origin main
   ```

### 2. Deploy to Vercel Dashboard
To host the frontend on Vercel:
1. Log in to [Vercel](https://vercel.com) using your GitHub account.
2. Click **Add New** > **Project**.
3. Import your `Wints-controlroom` repository.
4. Set the following under **Project Settings**:
   - **Framework Preset**: `Next.js`
   - **Root Directory**: Select `wints-web` (click Edit and select the `wints-web` subfolder)
5. Expand **Environment Variables** and add the variables to configure your MQTT WebSocket connection:
   - `NEXT_PUBLIC_MQTT_HOST` (e.g. `your-cluster.s1.eu.hivemq.cloud`)
   - `NEXT_PUBLIC_MQTT_PORT` (e.g. `8884` for secure WebSocket connections)
   - `NEXT_PUBLIC_MQTT_USERNAME` (username for the broker)
   - `NEXT_PUBLIC_MQTT_PASSWORD` (password for the broker)
6. Click **Deploy**. Vercel will build the frontend assets.
7. Once build completes, open your live Vercel URL!

> [!IMPORTANT]
> Because Vercel serves pages over secure HTTPS, browser security models block unencrypted WebSockets (`ws://`). You **must** configure a secure WebSocket connection (`wss://`) on a secure port (like `8884` for HiveMQ Cloud) with a valid SSL certificate.

---

## CLI Reference

```
python -m scripts.wints <command>
```

| Command | Description |
|---------|-------------|
| `doctor` | Check Python, packages, binaries, ports, config files |
| `setup` | Install packages + download MediaMTX binary |
| `broker` | Start Mosquitto broker (blocks) |
| `sim` | Start all 10 simulated targets |
| `sim --fault T-07` | Start with T-07 in OVERCURRENT fault |
| `sim --offline T-09` | Start with T-09 offline |
| `dashboard` | Launch PyQt6 control room only |
| `demo` | Start everything in correct order (recommended) |
| `video` | Start MediaMTX RTSP server only |
| `inject T-03 overcurrent` | Inject overcurrent fault into T-03 |
| `inject T-03 clear` | Clear all faults on T-03 |
| `test` | Run full pytest suite (66 tests) |
| `lint` | Run ruff + mypy --strict |
| `replay <file>` | Replay a recorded session JSONL file |

---

## Project Structure

```
Wints-controlroom/
│
├── config/                     # All configuration files
│   ├── wints.yaml              # Simulation parameters (motor, battery, RF, etc.)
│   ├── mosquitto.conf          # MQTT broker configuration
│   └── mediamtx.yml            # RTSP server stream paths
│
├── control_room/               # PyQt6 dashboard application
│   ├── main.py                 # Entry point — creates QApplication
│   ├── models/
│   │   ├── system_model.py     # Single source of truth for all target state
│   │   └── target_state.py     # Pydantic data classes
│   ├── mqtt/
│   │   └── client.py           # Thread-safe MQTT client wrapper
│   ├── services/
│   │   └── command_tracker.py  # UUID trace_id → pending/ack/timeout
│   └── ui/
│       ├── main_window.py      # Main window, toolbar, dock layout
│       ├── target_card.py      # Per-target card with all sub-widgets
│       ├── video_widget.py     # RTSP capture QThread + display widget
│       ├── live_charts.py      # pyqtgraph rolling time-series charts
│       ├── metrics_panel.py    # KPI numbers panel
│       └── event_log.py        # Colour-coded event log widget
│
├── target_simulator/           # 10-target physics simulation
│   ├── main.py                 # asyncio entry — spawns 10 TargetSimulator tasks
│   ├── target.py               # State machine + MQTT + fault injector HTTP API
│   ├── models.py               # Pydantic payload schemas (shared with dashboard)
│   └── physics/
│       ├── motor.py            # DC motor ODE solver (scipy RK45)
│       ├── battery.py          # LiFePO4 electrochemistry + BMS
│       ├── solar.py            # Diurnal irradiance + MPPT
│       └── rf_link.py          # FSPL + shadowing + PER model
│
├── video_server/               # RTSP test pattern generation
│   ├── generate_test_patterns.py  # Creates 20 annotated MP4s via OpenCV
│   ├── start_mediamtx.py          # Launcher wrapper
│   └── samples/                   # Generated MP4 files (gitignored)
│
├── firmware/
│   └── main_reference.c        # Reference STM32 C implementation
│
├── tests/
│   ├── unit/                   # Motor, battery, solar, RF, model tests
│   ├── integration/            # MQTT round-trip tests
│   └── chaos/                  # Fault injection + recovery sequences
│
├── docs/
│   ├── 01_design.md            # Full system design with state machines
│   ├── 02_premortem.md         # 24 failure modes + risk matrix
│   ├── 03_chosen_plan.md       # Implementation plan
│   ├── 04_real_hardware.md     # STM32 hardware swap guide
│   ├── 05_demo_script.md       # Minute-by-minute supervisor demo
│   └── 06_adr.md               # Architecture Decision Records
│
├── scripts/
│   └── wints.py                # Click CLI orchestrator
│
├── tools/
│   └── mediamtx/               # MediaMTX binary (gitignored, downloaded by setup)
│
├── pyproject.toml              # Build config, ruff, mypy, pytest settings
├── requirements.txt            # Runtime dependencies
└── requirements-dev.txt        # Dev dependencies (pytest, mypy, ruff)
```

---

## Configuration

All simulation parameters live in `config/wints.yaml` — no magic numbers in code:

```yaml
motor:
  resistance_ohm: 0.5           # Armature resistance
  torque_constant: 0.08         # Kt = Ke for PMDC motor
  overcurrent_threshold_a: 12.0 # BTS7960 sense pin limit
  stall_duration_ms: 2000       # Sustained stall → fault

battery:
  capacity_ah: 100              # 4S LiFePO4 pack
  bms_cutoff_soc_pct: 10        # Hard cutoff threshold
  quiescent_load_w: 7.0         # MCU + radio + cameras standby

simulation:
  time_acceleration_factor: 120 # 1 real second = 2 sim minutes

targets:
  T-07: {distance_m: 4200, initial_soc: 22}  # critically low SOC
  T-09: {distance_m: 5000, start_offline: true}
```

---

## Testing

```bash
# Run all 66 tests
python -m scripts.wints test
# or directly:
pytest tests/ -v

# Run only unit tests (no broker needed)
pytest tests/unit/ -v

# Run chaos tests (fault injection sequences)
pytest tests/chaos/ -v

# Type checking
mypy --strict control_room/ target_simulator/

# Linting
ruff check .
```

**Test breakdown:**

| Suite | Count | Coverage |
|-------|-------|----------|
| Motor physics (ODE, limits, faults) | 16 | Coupled ODEs, stall, overcurrent |
| Battery (chemistry, BMS, temperature) | 12 | Coulomb counting, OCV, cutoff |
| Solar (irradiance, MPPT, night) | 10 | Diurnal model, charge current |
| RF link (FSPL, RSSI, PER) | 9 | Path loss, packet drop |
| Model serialisation (Pydantic) | 11 | All payload schemas |
| Chaos / fault injection | 8 | Inject + recover sequences |
| **Total** | **66** | **66 passed, 0 failed** |

---

## MQTT Contract

| Topic | Direction | QoS | Retain | Rate |
|-------|-----------|-----|--------|------|
| `wints/T-{XX}/cmd` | Dashboard → Target | 1 | No | On demand |
| `wints/broadcast/cmd` | Dashboard → All | 1 | No | On demand |
| `wints/T-{XX}/status` | Target → Dashboard | 1 | **Yes** | On change |
| `wints/T-{XX}/telemetry` | Target → Dashboard | 0 | No | Every 2 s |

**Command payload:**
```json
{"trace_id": "f6d06093-...", "cmd": "raise", "ts": 1718370615123}
```

**Status payload:**
```json
{
  "target_id": "T-07", "online": true, "position": "DOWN",
  "position_pct": 0.0, "battery_soc": 22.1, "battery_voltage": 13.01,
  "fault": true, "fault_code": "OVERCURRENT",
  "trace_id": "f6d06093-....T-07", "ts": 1718370615500
}
```

---

## Real Hardware Path

The simulator is designed to be replaced by real STM32 hardware with minimal changes:

1. Flash `firmware/main_reference.c` onto an STM32F4 target board
2. Connect the real MQTT broker (same Mosquitto config)
3. Replace `video_server/` with real IP camera RTSP URLs in `config/mediamtx.yml`
4. The dashboard is **hardware-agnostic** — it only speaks MQTT

See [`docs/04_real_hardware.md`](docs/04_real_hardware.md) for the full hardware integration guide.

---

## Tech Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Dashboard GUI | PyQt6 | 6.7.0 |
| MQTT client | paho-mqtt | 2.1.0 |
| Data validation | pydantic | 2.7.0 |
| Physics ODE solver | scipy (RK45) | 1.13.0 |
| Numerical computing | numpy | 1.26.4 |
| Real-time charts | pyqtgraph | 0.13.7 |
| RTSP video | opencv-python | 4.9.0 |
| RTSP server | MediaMTX | 1.9.0 |
| MQTT broker | Eclipse Mosquitto | 2.x |
| Structured logging | structlog | 24.1.0 |
| Metrics exposition | prometheus-client | 0.20.0 |
| CLI | click + rich | 8.1.7 / 13.7.1 |
| Type checking | mypy (strict) | 1.10.0 |
| Linting | ruff | 0.4.4 |
| Testing | pytest | 8.2.0 |

---

## Documentation

| Document | Description |
|----------|-------------|
| [`docs/01_design.md`](docs/01_design.md) | Full system decomposition, state machines, timing budget, physics equations |
| [`docs/02_premortem.md`](docs/02_premortem.md) | 24 identified failure modes, risk matrix, top 8 mitigations |
| [`docs/03_chosen_plan.md`](docs/03_chosen_plan.md) | Implementation plan with architectural constraints |
| [`docs/04_real_hardware.md`](docs/04_real_hardware.md) | How to replace the simulator with STM32 + real cameras |
| [`docs/05_demo_script.md`](docs/05_demo_script.md) | Minute-by-minute supervisor demo script |
| [`docs/06_adr.md`](docs/06_adr.md) | Architecture Decision Records for all major choices |

---

## License

MIT © 2026 — Hamza Basharat

---

<div align="center">

**Built as a Comprehensive Engineering Project (CEP) for SEM 8 — Embedded Systems Design**

*Physics engine · MQTT protocol · Real-time GUI · Fault injection · 66 tests · mypy strict · ruff clean*

</div>
