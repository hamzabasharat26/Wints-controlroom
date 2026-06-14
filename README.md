<div align="center">

# WINTS — Wireless Integrated Network Target System

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.7.0-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://riverbankcomputing.com/software/pyqt/)
[![MQTT](https://img.shields.io/badge/MQTT-Mosquitto-660066?style=for-the-badge&logo=eclipsemosquitto&logoColor=white)](https://mosquitto.org)
[![Tests](https://img.shields.io/badge/Tests-66%2F66%20Passing-brightgreen?style=for-the-badge&logo=pytest&logoColor=white)](tests/)
[![mypy](https://img.shields.io/badge/mypy-strict%200%20errors-blue?style=for-the-badge)](https://mypy-lang.org)
[![ruff](https://img.shields.io/badge/ruff-0%20errors-orange?style=for-the-badge)](https://docs.astral.sh/ruff/)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

<br/>

**Physics-accurate simulation of a distributed embedded system controlling  
10 motorised military range targets with real-time MQTT telemetry,  
live RTSP video feeds, fault injection, and full observability.**

<br/>

> *CEP Project — Embedded Systems Design, Semester 8*

</div>

---

## Table of Contents

- [Overview](#overview)
- [Live Demo](#live-demo)
- [Architecture](#architecture)
- [Physics Engine](#physics-engine)
- [Dashboard Features](#dashboard-features)
- [Fault Injection](#fault-injection)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Testing](#testing)
- [Documentation](#documentation)
- [Tech Stack](#tech-stack)

---

## Overview

WINTS simulates a real military range control system where an operator in a control room can raise, lower, and stop 10 motorised target stands spread across a 10 km² field — each one running independent physics, battery management, solar charging, and RF link simulation.

Every target is a fully independent asyncio process publishing live telemetry over MQTT. The control room dashboard is a PyQt6 application that renders 10 live target cards, an event log, real-time charts, and RTSP video feeds from each target's cameras.

**This is not a mock.** The motor responds to back-EMF. The battery drains under load and recharges from solar. Distant targets have worse RSSI and drop telemetry packets. T-07 starts with an OVERCURRENT fault and ignores all commands until cleared.

---

## Live Demo

```
python -m scripts.wints demo
```

What you see in 10 seconds:

| Element | State |
|---------|-------|
| T-01 → T-06, T-08, T-10 | 🟢 ONLINE — responding to commands |
| T-07 | 🟠 FAULT — OVERCURRENT, motor locked |
| T-09 | 🔴 OFFLINE — LWT triggered, never connected |
| Buttons | ▲ RAISE / ■ STOP / ▼ LOWER — always interactive |
| Video feeds | Live RTSP front-camera per card (MediaMTX) |
| Charts | Battery SOC, RSSI, Online count, Solar (W) |

**RAISE ALL** → all online targets move UP → buttons show PENDING → acked within 2s → buttons restore. T-07 rejects the command. T-09 times out after 5s. No button ever stays stuck.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    CONTROL ROOM  (PyQt6)                        │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  10 × TargetCard  [240×400px each]                       │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ...          │  │
│  │  │ T-01     │  │ T-07     │  │ T-09     │               │  │
│  │  │ 🟢ONLINE │  │ 🟠FAULT  │  │ 🔴OFFLINE│               │  │
│  │  │ UP 100%  │  │ DOWN 0%  │  │ UNKNOWN  │               │  │
│  │  │ [VIDEO]  │  │ [VIDEO]  │  │ [VIDEO]  │               │  │
│  │  │ ▲ ■ ▼   │  │ ▲ ■ ▼   │  │ ▲ ■ ▼   │               │  │
│  │  └──────────┘  └──────────┘  └──────────┘               │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌─────────────────────┐   ┌─────────────────────────────────┐ │
│  │  Event Log          │   │  Metrics Panel (pyqtgraph)      │ │
│  │  [CMD] ALL→RAISE    │   │  Battery SOC  ████▓░░  87%      │ │
│  │  [ACK] T-01 acked   │   │  RSSI (dBm)   ▄▄▄▄▄▃▂  -58     │ │
│  │  [WARN] T-09 timeout│   │  Online (#)   ─────── 9/10     │ │
│  │                     │   │  Solar (W)    ╱╲╱╲╱   1840     │ │
│  └─────────────────────┘   └─────────────────────────────────┘ │
└─────────────────────────────┬───────────────────────────────────┘
                              │  MQTT QoS 1 / QoS 0  :1883
              ┌───────────────┴────────────────┐
              │    Eclipse Mosquitto v2         │
              │    Retained status messages     │
              │    LWT for offline detection    │
              └───────────────┬────────────────┘
                              │
   ┌──────────────────────────┼──────────────────────────────┐
   │              TARGET SIMULATOR  (asyncio × 10)            │
   │                                                          │
   │  T-01  T-02  T-03  T-04  T-05  T-06  T-07  T-08  T-10  │
   │  ┌──────────────────────────────────────────────────┐   │
   │  │  Per-target physics (independent event loop)     │   │
   │  │  ├─ Motor ODE  (RK45, 1ms steps)                │   │
   │  │  ├─ LiFePO4 Battery (coulomb counting)           │   │
   │  │  ├─ Solar Panel (sinusoidal irradiance + MPPT)   │   │
   │  │  ├─ RF Link (FSPL + log-normal shadowing)        │   │
   │  │  └─ Fault Injector HTTP  :9301-9310              │   │
   │  └──────────────────────────────────────────────────┘   │
   │  T-09 → OFFLINE (never connects — LWT demonstrates)     │
   └──────────────────────────────────────────────────────────┘

              ┌──────────────────────────────────┐
              │  MediaMTX RTSP Server  :8554      │
              │  20 streams (10 targets × front+rear) │
              │  video_server/samples/*.mp4 looped│
              └──────────────────────────────────┘
```

### Data Flow

```
Operator clicks ▲ RAISE on T-01
  → CommandTracker.issue("T-01", trace_id, "raise")
  → MQTT publish  wints/T-01/cmd  QoS 1
  → Mosquitto broker
  → TargetSimulator.on_message()
  → Physics: motor ODE begins integration (RK45, 1ms steps)
  → MQTT publish  wints/T-01/status  QoS 1 retained
  → Dashboard receives  →  SystemModel.update()
  → Qt signal  →  TargetCard.set_command_pending(False)
  → Button restores to  ▲ RAISE
```

---

## Physics Engine

Each of the 10 targets runs four independent physics models in a single asyncio event loop at real-time 10ms ticks.

### DC Permanent Magnet Motor

Coupled ODEs solved with `scipy RK45` at 1ms sub-steps:

```
Electrical:   V = L·(di/dt) + R·i + Kₑ·ω
Mechanical:   J·(dω/dt) = Kₜ·i − B·ω − T_load·tanh(ω/0.1)
Position:     dθ/dt = ω      →      position% = (θ / θ_max) × 100
```

| Parameter | Value | Notes |
|-----------|-------|-------|
| Resistance R | 0.5 Ω | Armature |
| Inductance L | 2 mH | Armature |
| Torque constant Kₜ | 0.08 N·m/A | = Kₑ for PMDC |
| Inertia J | 0.02 kg·m² | Rotor + geared load |
| Overcurrent limit | 12 A | BTS7960 sense pin |
| Travel range θ_max | π/2 rad | 90° DOWN→UP |

The `tanh` friction term prevents ODE stiffness artifacts that a hard `sign(ω)` discontinuity would cause.

### LiFePO4 Battery (4S 100 Ah)

- **Coulomb counting** with 0.995 coulombic efficiency
- **OCV-SOC curve** — 14-point interpolated lookup (EVE LF100LA datasheet)
- **Temperature-dependent R_internal** — doubles at −20°C
- **BMS cutoff** at 10% SOC → motor hard-disabled, status publishes `BMS_CUTOFF`

### Solar Panel (200 W Monocrystalline)

```
G(t) = G_peak × sin(π × (t − t_sunrise) / (t_sunset − t_sunrise)) + N(0, σ²)
P_solar = η_panel × A_panel × G(t) × η_mppt   →   max 209 W
```

Simulation time runs at **60× acceleration** — a full 12-hour solar day in 12 real minutes.

### RF Link Budget (5 GHz, 802.11n)

```
RSSI = P_tx + G_tx + G_rx − FSPL(d, 5GHz) − L_shadow
```

- Packet Error Rate derived from RSSI thresholds (0% above −65 dBm, 100% below −95 dBm)
- **T-09** at 5 km has marginal RSSI (−73 dBm) — telemetry drops are visible in the event log

---

## Dashboard Features

| Feature | Detail |
|---------|--------|
| **10 Target Cards** | 240×400 px each, live-updating, animated status badges |
| **Animated Mast Widget** | Custom-painted vertical rail, head position interpolated with EMA |
| **Status Badge** | Smooth QPropertyAnimation colour transitions (green/amber/red) |
| **RSSI Bars** | 5-bar signal strength widget, colour-coded by strength |
| **Battery Bar** | Progress bar with colour threshold (green/amber/red at 50%/20%) |
| **Fault Chip** | Shows `⚠ OVERCURRENT` / `⚠ BMS_CUTOFF` etc. inline on card |
| **Inline Video** | 90px RTSP front-camera feed per card, staggered start (300ms apart) |
| **Double-click** | Opens full 900×420 dual-camera (FRONT + REAR) dialog |
| **Command Pending** | Buttons show PENDING during in-flight command, restore on ack or 2s timeout |
| **Broadcast Safety** | RAISE ALL / STOP ALL / LOWER ALL — 5s safety timer clears any stuck card |
| **Event Log** | Colour-coded CMD / ACK / WARN / INFO / ERROR entries with filter |
| **Live Charts** | 4 vertically stacked pyqtgraph plots — Battery SOC, RSSI, Online, Solar |
| **Stale Detection** | ⚠ STALE badge after 15s without update (F-09 mitigation) |
| **LWT Offline** | T-09 immediately shows RED OFFLINE on dashboard start |

---

## Fault Injection

Faults can be injected at runtime without restarting anything:

```bash
# Inject overcurrent into T-03 (motor locks, badge goes orange)
python -m scripts.wints inject T-03 overcurrent

# Simulate broker disconnect on T-05
python -m scripts.wints inject T-05 broker_disconnect

# Spike packet loss on T-02 (telemetry gaps, event log warnings)
python -m scripts.wints inject T-02 packet_loss_spike

# Force BMS battery cutoff on T-04
python -m scripts.wints inject T-04 battery_bms

# Stuck limit switch on T-06
python -m scripts.wints inject T-06 limit_stuck

# Clear all faults and recover T-03
python -m scripts.wints inject T-03 clear
```

| Fault | Component | Dashboard Response |
|-------|-----------|-------------------|
| `OVERCURRENT` | Motor H-bridge | Orange FAULT badge, `⚠ OVERCURRENT` chip, commands rejected |
| `MOTOR_STALL` | Motor mechanics | Orange FAULT badge, `⚠ MOTOR_STALL` chip |
| `BMS_CUTOFF` | Battery BMS | Orange FAULT badge, `⚠ BMS_CUTOFF` chip, motor stops |
| `LIMIT_STUCK` | Limit switches | Orange FAULT badge, `⚠ LIMIT_STUCK` chip |
| `broker_disconnect` | MQTT radio | Card goes STALE → then RED OFFLINE after LWT |
| `packet_loss_spike` | RF link | Telemetry gaps, command timeout warnings in log |

---

## Quick Start

### Prerequisites

| Tool | Purpose | Install |
|------|---------|---------|
| Python 3.11+ | Runtime | [python.org](https://python.org) |
| Mosquitto | MQTT broker | `winget install EclipseFoundation.Mosquitto` |
| FFmpeg | Test pattern generation | `winget install Gyan.FFmpeg` |
| MediaMTX | RTSP server | Auto-downloaded by `wints setup` |

### Installation

```powershell
# 1. Clone the repository
git clone https://github.com/hamzabasharat26/Wints-controlroom.git
cd Wints-controlroom

# 2. Create virtual environment
python -m venv .venv
.venv\Scripts\activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Download MediaMTX + generate test video patterns
python -m scripts.wints setup

# 5. Verify everything is ready
python -m scripts.wints doctor
```

### Run

```powershell
# Launch everything in one command
python -m scripts.wints demo
```

This starts (in order):
1. **Mosquitto** broker on `:1883`
2. **MediaMTX** RTSP server on `:8554` (20 streams)
3. **Target Simulator** — 10 targets (T-07 faulted, T-09 offline)
4. **Dashboard** — PyQt6 control room GUI

---

## CLI Reference

```
python -m scripts.wints <command>
```

| Command | Description |
|---------|-------------|
| `doctor` | Health check — Python, packages, binaries, ports, config files |
| `setup` | Create venv, install packages, download MediaMTX |
| `broker` | Start Mosquitto broker (blocking) |
| `sim` | Start all 10 targets |
| `sim --fault T-07` | Start with T-07 in OVERCURRENT fault |
| `sim --offline T-09` | Start with T-09 offline (LWT) |
| `dashboard` | Launch PyQt6 dashboard only |
| `demo` | **Launch everything** in correct order |
| `inject T-03 overcurrent` | Inject fault into running target |
| `inject T-03 clear` | Clear fault and recover target |
| `test` | Run full pytest suite |
| `lint` | Run ruff + mypy |
| `video` | Start MediaMTX standalone |

---

## Project Structure

```
Wints-controlroom/
│
├── control_room/               # PyQt6 Dashboard
│   ├── main.py                 # QApplication entry point
│   ├── models/
│   │   ├── system_model.py     # Single source of truth (10 TargetData)
│   │   └── target_state.py     # Pydantic enums & state types
│   ├── mqtt/
│   │   └── client.py           # paho-mqtt wrapper, thread→Qt bridge
│   ├── services/
│   │   └── command_tracker.py  # UUID trace_id lifecycle (issue→ack→timeout)
│   └── ui/
│       ├── main_window.py      # QMainWindow — card grid + docks + toolbar
│       ├── target_card.py      # TargetCard QFrame (240×400px)
│       ├── video_widget.py     # RTSPCapture QThread + VideoWidget
│       ├── event_log.py        # Colour-coded scrolling event log
│       ├── live_charts.py      # 4-chart pyqtgraph panel
│       └── metrics_panel.py    # Aggregate metrics display
│
├── target_simulator/           # Physics Simulator (10 asyncio tasks)
│   ├── main.py                 # asyncio.gather() — runs all 10 targets
│   ├── target.py               # TargetSimulator state machine
│   ├── models.py               # Pydantic payload schemas
│   └── physics/
│       ├── motor.py            # DC motor coupled ODEs (RK45)
│       ├── battery.py          # LiFePO4 coulomb counting + BMS
│       ├── solar.py            # Sinusoidal irradiance + MPPT
│       └── rf_link.py          # FSPL + log-normal shadowing + PER
│
├── config/
│   ├── wints.yaml              # All simulation parameters (motor, battery, RF)
│   ├── mosquitto.conf          # Broker config (persistence, logging)
│   └── mediamtx.yml            # 20 RTSP stream paths (looped MP4)
│
├── tests/
│   ├── unit/                   # 57 unit tests (motor, battery, solar, RF, models)
│   ├── chaos/                  # 9 fault injection + recovery tests
│   └── integration/            # MQTT round-trip tests
│
├── firmware/
│   └── main_reference.c        # STM32 C reference (swap in for real hardware)
│
├── docs/
│   ├── 01_design.md            # Full system design, state machines, timing budget
│   ├── 02_premortem.md         # 24 failure modes + mitigations
│   ├── 03_chosen_plan.md       # Architecture decisions
│   ├── 04_real_hardware.md     # How to wire up STM32 + real cameras
│   ├── 05_demo_script.md       # Minute-by-minute supervisor demo
│   └── 06_adr.md               # Architecture Decision Records
│
├── video_server/
│   ├── generate_test_patterns.py  # FFmpeg — annotated MP4 per target/camera
│   └── samples/                   # target-{01..10}-{front,rear}.mp4 (generated)
│
├── scripts/
│   └── wints.py                # Click CLI orchestrator
│
├── tools/
│   └── mediamtx/               # MediaMTX binary (auto-downloaded)
│
├── pyproject.toml              # ruff + mypy + pytest config
├── requirements.txt            # Runtime dependencies (pinned)
├── requirements-dev.txt        # Dev dependencies (pytest, mypy, ruff)
└── README.md
```

---

## Configuration

All simulation parameters live in `config/wints.yaml` — no magic numbers in code:

```yaml
motor:
  resistance_ohm: 0.5          # Change to match real motor datasheet
  overcurrent_threshold_a: 12.0

battery:
  capacity_ah: 100
  bms_cutoff_soc_pct: 10       # % SOC before hard cutoff

simulation:
  time_acceleration_factor: 120  # 1 real second = 120 sim seconds

targets:
  T-07: {initial_soc: 22, start_faulted: true}   # Demo: critically low SOC + fault
  T-09: {start_offline: true}                      # Demo: LWT offline detection
```

---

## Testing

```powershell
# Run all 66 tests
python -m scripts.wints test

# Run with coverage
.venv\Scripts\pytest tests/ -v --tb=short

# Static analysis
.venv\Scripts\mypy --strict control_room/ target_simulator/
.venv\Scripts\ruff check .
```

**Test Results:**

```
66 passed in 9.17s  ✓
mypy: Success — no issues found in 25 source files  ✓
ruff: All checks passed  ✓
```

| Suite | Count | What it covers |
|-------|-------|----------------|
| `unit/test_motor` | 16 | ODE integration, overcurrent, stall, limit switches |
| `unit/test_battery` | 12 | Coulomb counting, OCV curve, BMS cutoff, temperature |
| `unit/test_solar` | 10 | Irradiance, power formula, charge current limits |
| `unit/test_rf_link` | 9 | FSPL, RSSI, PER, QoS-1 never-dropped guarantee |
| `unit/test_models` | 10 | Pydantic payload validation, LWT schema |
| `chaos/test_fault_injection` | 9 | Inject → verify → clear → verify recovery |

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **GUI** | PyQt6 6.7.0 | Native widgets, QThread for RTSP, smooth animations |
| **Charts** | pyqtgraph 0.13.7 | GPU-accelerated real-time plots |
| **MQTT** | paho-mqtt 2.1.0 | Industry standard, QoS 1/0, LWT support |
| **Broker** | Eclipse Mosquitto v2 | Production-grade, retained messages, persistence |
| **Physics** | scipy 1.13.0 + numpy 1.26.4 | RK45 ODE solver, numerical stability |
| **Validation** | pydantic 2.7.0 | Strict schema validation, JSON serialisation |
| **Video** | OpenCV 4.9.0 + MediaMTX | RTSP decode in QThread, 15fps per card |
| **Logging** | structlog 24.1.0 | Structured JSON logs, coloured console |
| **CLI** | click 8.1.7 + rich 13.7.1 | Doctor checks, coloured output, process management |
| **Testing** | pytest 8.2.0 + hypothesis 6.100.0 | Unit + property-based + chaos |
| **Typing** | mypy 1.10.0 strict | Zero type errors across 25 files |
| **Linting** | ruff 0.4.4 | Zero warnings |

---

## Real Hardware Path

The simulator was designed to swap out cleanly for real hardware. See [`docs/04_real_hardware.md`](docs/04_real_hardware.md) for the full guide.

**Short version:**
1. Flash `firmware/main_reference.c` onto an STM32F4
2. Connect H-bridge motor driver (BTS7960), LiFePO4 BMS, solar MPPT, Ubiquiti radio
3. Point `config/wints.yaml` `broker.host` at your real broker IP
4. The dashboard connects automatically — no code changes needed

---

## Documentation

| Document | Contents |
|----------|----------|
| [`docs/01_design.md`](docs/01_design.md) | Full system decomposition, 5 state machine diagrams, timing budget, MQTT contract, Prometheus metrics schema |
| [`docs/02_premortem.md`](docs/02_premortem.md) | 24 identified failure modes, risk matrix (impact × likelihood), top 8 mitigations implemented |
| [`docs/03_chosen_plan.md`](docs/03_chosen_plan.md) | Architecture decisions and constraints |
| [`docs/04_real_hardware.md`](docs/04_real_hardware.md) | STM32 wiring guide, component BOM, calibration procedure |
| [`docs/05_demo_script.md`](docs/05_demo_script.md) | Minute-by-minute demo for supervisor presentation |
| [`docs/06_adr.md`](docs/06_adr.md) | Architecture Decision Records (MQTT vs HTTP, PyQt6 vs Electron, etc.) |

---

## License

MIT — see [LICENSE](LICENSE) for details.

---

<div align="center">

**Built for the Embedded Systems Design CEP — Semester 8**

*Physics engine · MQTT telemetry · Real-time dashboard · Fault injection · 66 tests passing*

</div>
