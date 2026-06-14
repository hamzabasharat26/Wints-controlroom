<div align="center">

# ⚡ WINTS — Wireless Integrated Network Target System

**A physics-accurate distributed embedded system simulation with a polished real-time dashboard.**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Next.js](https://img.shields.io/badge/Next.js-14.2-000000?style=for-the-badge&logo=nextdotjs&logoColor=white)](https://nextjs.org)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-3.4-06B6D4?style=for-the-badge&logo=tailwindcss&logoColor=white)](https://tailwindcss.com)
[![Vercel](https://img.shields.io/badge/Vercel-Ready-000000?style=for-the-badge&logo=vercel&logoColor=white)](https://vercel.com)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.7.0-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://riverbankcomputing.com/software/pyqt/)
[![MQTT](https://img.shields.io/badge/MQTT-Mosquitto_v2-660066?style=for-the-badge&logo=eclipsemosquitto&logoColor=white)](https://mosquitto.org)
[![Tests](https://img.shields.io/badge/Tests-66_Passed-brightgreen?style=for-the-badge&logo=pytest&logoColor=white)](tests/)
[![mypy](https://img.shields.io/badge/mypy-strict-blue?style=for-the-badge)](https://mypy-lang.org)
[![ruff](https://img.shields.io/badge/ruff-clean-orange?style=for-the-badge)](https://docs.astral.sh/ruff/)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

<br/>

> WINTS simulates **10 motorised range targets** spread across a large field and controls them from a real-time dashboard.
> The system includes physics-based motors, LiFePO4 batteries, solar charging, RF propagation, MQTT messaging, fault injection,
> and RTSP video feeds.

<br/>

![WINTS Dashboard](https://raw.githubusercontent.com/hamzabasharat26/Wints-controlroom/main/docs/assets/dashboard_preview.png)

</div>

---

## Highlights

- **10 target nodes** with independent simulation state
- **Live dashboard** for status, telemetry, commands, and faults
- **Physics engine** for motor, battery, solar, and RF behaviour
- **MQTT control plane** with UUID trace IDs and acknowledgements
- **Fault injection** for demo, testing, and resilience checks
- **Vercel-ready web dashboard** in `wints-web/`
- **Strict quality checks** with `mypy`, `ruff`, and pytest

---

## Project layout

- `control_room/` — desktop PyQt6 control room
- `target_simulator/` — 10-node asyncio simulator
- `wints-web/` — Next.js dashboard for browser deployment
- `video_server/` — RTSP test-pattern generation and MediaMTX helpers
- `config/` — broker, simulation, and video config files
- `tests/` — unit, integration, and chaos tests
- `docs/` — design notes, demo script, and hardware path

---

## What it does

### Control room dashboard
- Target cards with status, mast position, battery SOC, RSSI, solar power, and live video
- Broadcast controls for **RAISE ALL**, **STOP ALL**, and **LOWER ALL**
- Event log with command, status, and fault history
- Right-side analytics panel for quick operational awareness

### Target simulator
- 10 independent target instances
- Motor ODE integration with realistic timing
- Battery state-of-charge tracking and BMS limits
- Solar harvesting and RF link-budget modelling
- Fault injection endpoints and command deduplication

### Web dashboard
The Next.js dashboard is designed for browser deployment on Vercel.
It connects directly to an MQTT broker over **secure WebSockets**.

---

## Quick start

### Local development

```bash
Set-Location 'd:\SEM 8\ESD CEP'
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m scripts.wints doctor
```

### Run the full demo locally

```bash
python -m scripts.wints demo
```

### Run the web dashboard locally

```bash
Set-Location 'd:\SEM 8\ESD CEP\wints-web'
npm install
npm run dev
```

---

## Vercel deployment

Only the **`wints-web/`** app should be deployed to Vercel.
Do **not** deploy the Python simulator or desktop GUI to Vercel.

### Vercel project settings

Paste these values into the Vercel project setup:

```text
Framework Preset: Next.js
Root Directory: wints-web
Build Command: npm run build
Install Command: npm install
Output Directory: .next
```

### Environment variables to add in Vercel

```text
NEXT_PUBLIC_MQTT_HOST=your-broker-hostname
NEXT_PUBLIC_MQTT_PORT=8884
NEXT_PUBLIC_MQTT_USERNAME=your-username
NEXT_PUBLIC_MQTT_PASSWORD=your-password
```

### Important

- Use a broker that supports **secure WebSockets** (`wss://`)
- Avoid plain `ws://` on a Vercel HTTPS site
- HiveMQ Cloud is the easiest option for quick deployment

### Deploy flow through GitHub

1. Push changes to `main`
2. Connect the GitHub repository to Vercel
3. Set the root directory to `wints-web`
4. Add the environment variables
5. Deploy

Once connected, every new push to GitHub triggers an automatic Vercel build.

---

## GitHub push commands

Use these when you want to publish a new update:

```bash
Set-Location 'd:\SEM 8\ESD CEP'
git status
git add .
git commit -m "your message here"
git push origin main
```

---

## MQTT contract

| Topic | Direction | QoS | Retained | Purpose |
|---|---:|---:|---:|---|
| `wints/T-{XX}/cmd` | Dashboard → Target | 1 | No | Individual command |
| `wints/broadcast/cmd` | Dashboard → All | 1 | No | Broadcast command |
| `wints/T-{XX}/status` | Target → Dashboard | 1 | Yes | Online / fault state |
| `wints/T-{XX}/telemetry` | Target → Dashboard | 0 | No | Periodic telemetry |

---

## Testing and quality

```bash
python -m scripts.wints test
python -m scripts.wints lint
```

- 66 tests across unit, integration, and chaos suites
- strict type checking with `mypy`
- linting with `ruff`

---

## Real hardware path

The simulator can be migrated to STM32-based hardware with minimal dashboard changes:

1. Flash the reference firmware in `firmware/main_reference.c`
2. Point the broker and simulator services at the real devices
3. Replace video test streams with live camera feeds
4. Keep the dashboard as the main control surface

---

## Documentation

- `docs/01_design.md` — architecture and timing model
- `docs/02_premortem.md` — failure analysis and risk matrix
- `docs/03_chosen_plan.md` — implementation plan
- `docs/04_real_hardware.md` — hardware swap guide
- `docs/05_demo_script.md` — demo script
- `docs/06_adr.md` — architecture decisions

---

## License

MIT © 2026 — Hamza Basharat

---

If you want, I can also make a **matching `wints-web/README.md`** so the frontend folder has its own Vercel-focused setup guide too.
