# Wireless Integrated Network Target System (WINTS) — Project Summary

This document provides a comprehensive overview of the Wireless Integrated Network Target System (WINTS), detailing the architecture, physics models, fault injection features, recent engineering improvements, and system verification status.

---

## 1. System Architecture & Components

WINTS is a highly reliable, physics-accurate distributed simulation of an embedded system controlling **10 motorized military range targets** spread across a 10 km² field, managed via a central control room.

```
┌────────────────────────────────────────────────────────────┐
│               Control Room (PyQt6 Dashboard)               │
│  ┌────────────────────┐      ┌──────────────────────────┐  │
│  │  10 Target Cards   │◄─────┤ MQTT Client (paho-mqtt)  │  │
│  │  RTSP Video Grid   │      │ - subs: wints/#          │  │
│  │  Event Log         │      │ - pubs: wints/+/cmd      │  │
│  │  Metrics Panel     │      │ - LWT-aware              │  │
│  └────────────────────┘      └──────────────────────────┘  │
└──────────────────────────────┬─────────────────────────────┘
                               │ MQTT (Port 1883)
                 ┌─────────────┴──────────────┐
                 │    Mosquitto MQTT Broker   │
                 └─────────────┬──────────────┘
                               │
     ┌────────┬────────┬───────┼───────┬────────┬────────┐
     │  T-01  │  T-02  │  T-03 │  ...  │  T-09  │  T-10  │
     │  Node  │  Node  │  Node │       │  Node  │  Node  │
     │ (Phys) │ (Phys) │ (Phys)│       │ (Phys) │ (Phys) │
     └────────┴────────┴───────┘       └────────┴────────┘

┌────────────────────────────────────────────────────────────┐
│      MediaMTX Video Server (20 RTSP streams / loop)        │
└────────────────────────────────────────────────────────────┘
```

### 1.1 Central Control Room (PyQt6 Dashboard)
* **Responsive Card Grid**: Displays 10 individual target cards that reflow dynamically upon window resize.
* **Telemetry Visuals**: Integrates progress bars for target mechanical position and battery SOC, signal bars for RF RSSI, and real-time numeric readouts of motor current draw and solar panels.
* **Event Log Widget**: Categorized, color-coded view of connection states, commands, and fault alarms.
* **Metrics Panel**: High-performance PyQtGraph metrics visualization displaying averages and error rates.
* **Command Tracker**: Generates unique UUID `trace_id` values for all commands, listening for confirmations with automated 500ms timeouts to detect packet drop.

### 1.2 Communication Protocol (MQTT & HTTP)
* **MQTT Pub/Sub Broker**: Uses Eclipse Mosquitto on port 1883.
* **Retention and Last Will (LWT)**: Target nodes publish status messages with retained flags. They register an LWT topic (`wints/T-XX/status`) with a payload specifying `offline` so the dashboard immediately marks them offline if they disconnect.
* **API Validation**: Shareable Pydantic schema models define telemetry, commands, and status payloads.
* **Fault Injection API**: Each simulated node hosts a local REST HTTP server on a unique port (`9301` to `9310`) to allow dynamic runtime fault injection.

---

## 2. High-Fidelity Physics Engine

The target nodes do not rely on hardcoded timeouts or discrete state-changes. They execute continuous-time physics equations evaluated at 1ms timesteps.

### 2.1 DC Permanent Magnet Motor Model
* **Coupled ODEs**: Solves electrical and mechanical differential equations using scipy's `RK45` adaptive Runge-Kutta integrator:
  $$\text{Electrical: } V = L\frac{di}{dt} + R i + K_e \omega$$
  $$\text{Mechanical: } J\frac{d\omega}{dt} = K_t i - B\omega - T_{\text{load}}$$
* **Limit Switches & Debouncing**: Models raw physical limit switches with debouncing models (Schmitt trigger simulation) at boundaries.

### 2.2 Battery Model (LiFePO4)
* **Chemistry Simulation**: Models 4S 100Ah LiFePO4 packs utilizing coulomb counting.
* **Interpolated OCV**: Computes open-circuit voltage via an interpolated lookup table mapping 14 points on the EVE LF100LA discharge curve.
* **Temperature Derating**: Adjusts battery internal resistance ($R_{\text{internal}}$) dynamically based on simulated temperature (e.g., doubling at -20°C).
* **BMS Protection**: Implements hard cutoff thresholds for undervoltage, overcharge, over-temperature, and low-SOC.

### 2.3 Solar Harvesting
* **Sinusoidal Irradiance**: Simulates diurnal solar cycles mapping sunrise, solar noon, and sunset.
* **Gaussian Cloud Noise**: Introduces random irradiance fluctuations.
* **MPPT Model**: Models Maximum Power Point Tracking with 95% efficiency.

### 2.4 RF Link Budget
* **Path Loss & Shadowing**: Models Free-Space Path Loss (FSPL) at 5 GHz, coupled with log-normal shadowing and distance-based signal attenuation.
* **Packet Error Rate (PER)**: Generates packet errors and drops commands/telemetry based on real-time calculated RSSI threshold levels.

---

## 3. Fault Injection & Resilience Features

To prove fault tolerance, the system exposes a chaos testing interface where faults can be injected at will:

| Fault Code | Target Component | Simulation Behavior | Dashboard Response |
|------------|------------------|---------------------|--------------------|
| `OVERCURRENT` | Motor Controller | Shuts down H-bridge, current drops to 0A, transitions to `MOTOR_FAULT` | Badge turns orange, displays `⚠ OVERCURRENT`, disables commands |
| `LIMIT_STUCK` | Mechanical Limits | Simulates stuck switches (both UP & DOWN active simultaneously) | Badge turns orange, displays `⚠ LIMIT_STUCK` |
| `BMS_CUTOFF` | Power Management | Cuts load off, motor stops immediately | Badge turns orange, displays `⚠ BMS_CUTOFF` |
| `BROKER_DISCONNECT` | Radio Link | Simulates MQTT connection drop, stops telemetry | Badge turns grey, displays `STALE`, then red `OFFLINE` after LWT expires |
| `PACKET_LOSS_SPIKE` | Network | Drops incoming commands and status frames based on RSSI bounds | Triggers command timeout warnings in event log |

---

## 4. Engineering Refinement & Problem Resolution

Several core issues were addressed to bring the system to production grade:

* **ODE Solver Stiffness**: Fixed high-frequency motor chattering and adaptive solver failures at near-zero velocities by replacing the discontinuous friction signum term with a smooth hyperbolic tangent function: `np.tanh(omega / 0.1)`.
* **Overcurrent Tuning**: Tuned steady-state motor load parameters in `config/wints.yaml` to prevent spurious overcurrent protection trips during normal target motion cycles.
* **State Leakage**: Cleaned up the integration tests in `tests/chaos/test_fault_injection.py` by resetting limit switch and position variables between consecutive simulation cycles.
* **Console Encoding Fixes**: Removed non-ASCII emojis (`✅`, `❌`, `⚠️`) from CLI outputs to resolve encoding crashes on Windows shells defaulting to standard CP1252.
* **Mypy Type Corrections**: Fixed 9 strict-mode type errors including `paintEvent` overrides to comply with QWidget signatures, type safety casts in yaml loading, and paho-mqtt type references. Mypy now reports **0 issues**.
* **Broker Reuse Port Conflict**: Corrected a bug in the CLI pre-flight check where it attempted to connect to port 1883 using an invalid `timeout` keyword argument. Fixing this allows the CLI to successfully detect and reuse an already running Mosquitto service without crashing.

---

## 5. Verification Status

All systems are verified, tested, and fully functional:

1. **Unit & Chaos Tests**: `pytest` runs and passes **66/66 tests** successfully:
   * 9 Chaos tests verifying fault resilience and recovery sequences.
   * 12 Motor/Limit switch physics tests.
   * 12 Battery chemistry and protection tests.
   * 9 RF link and RSSI propagation tests.
   * 9 Solar panel and irradiance models.
   * 15 Model serialization and validation tests.
2. **Linter & Type System**: `mypy --strict` and `ruff check` verify static code compliance and type correctness.
3. **Demo Execution**: Launching `python -m scripts.wints demo` boots the multi-threaded target node simulations and launches the PyQt6 GUI, establishing full real-time telemetry communications successfully.
