# WINTS — Chosen Implementation Plan
## Document ID: 03_chosen_plan
## Version: 1.0 | Date: 2026-06-14
## Classification: Implementation Plan — CEP Deliverable

---

## Executive Summary

This document is the final implementation plan for WINTS, incorporating the top 8 mitigations from the pre-mortem analysis as first-class architectural constraints. Every decision here was made after considering what could go wrong, not before.

---

## Architectural Constraints (from Pre-Mortem Top 8)

These are non-negotiable. They drive every design decision below.

| # | Constraint | Source | Implementation |
|---|-----------|--------|----------------|
| C1 | Thread-safe MQTT→Qt bridge | F-01 | `QMetaObject.invokeMethod` with `Qt.QueuedConnection` exclusively |
| C2 | Lazy video loading | F-24 | Max 2 concurrent RTSP streams; default state is OFF |
| C3 | Port pre-flight check | F-20 | `wints doctor` validates all ports before any process starts |
| C4 | Broker auto-recovery | F-05 | `wints demo` wraps broker in watchdog; reconnection FSM everywhere |
| C5 | ODE state clamping | F-13 | Every physics step clamps outputs; overcurrent = physical safety net |
| C6 | Sleep prevention | F-22 | Demo mode disables Windows sleep via powercfg |
| C7 | Single-threaded state machine | F-04 | All target state mutations through one asyncio loop |
| C8 | Heartbeat + stale indicator | F-09 | Periodic status publish + UI staleness warning |

---

## What Was Considered and Rejected

### Alternative: statemachine library (python-statemachine)
- **Considered:** External library for formal state machines with DOT graph export.
- **Rejected because:** Adds a dependency for something we can implement in ~100 lines. The library doesn't integrate naturally with asyncio. Our state machines need async guard evaluation (e.g., checking MQTT connection state). Hand-rolled HSM with clear transition tables is more testable and transparent for a CEP review. The supervisor can read the transition table directly.
- **ADR:** ADR-001

### Alternative: simpy for discrete-event simulation
- **Considered:** simpy provides a clean DES framework with process-based simulation.
- **Rejected because:** Our physics models are continuous-time ODEs, not discrete events. simpy would add an abstraction layer between scipy's ODE solver and our simulation loop. asyncio already provides the scheduling we need. simpy's clock would conflict with our dual-time-domain (real-time motor, accelerated battery).
- **ADR:** ADR-002

### Alternative: asyncio-mqtt wrapper over paho-mqtt
- **Considered:** Cleaner async interface for MQTT operations.
- **Rejected because:** It wraps paho-mqtt's complexity without addressing our specific needs (thread-safe Qt integration, custom reconnection FSM, deduplication). Adding an abstraction layer makes debugging harder. paho-mqtt's threading model is well-understood and we control the thread boundary explicitly.
- **ADR:** ADR-003

### Alternative: python-vlc for video display
- **Considered:** VLC's Python bindings for RTSP playback.
- **Rejected because:** Requires VLC installed as a system dependency. Crashes silently on codec issues across different Windows versions. libvlc memory leaks when streams disconnect and reconnect. QMediaPlayer is Qt-native and falls back to OpenCV (which is already a dependency for other reasons).
- **ADR:** ADR-004

### Alternative: Docker for Mosquitto and MediaMTX
- **Considered:** Docker containers for broker and video server.
- **Rejected because:** Docker Desktop on Windows has networking issues (port mapping, WSL2 bridge). Adds ~2 GB install. Another thing to troubleshoot on demo day. Both Mosquitto and MediaMTX are single binaries that install in seconds. Native processes start faster and have zero network overhead.
- **ADR:** ADR-005

### Alternative: External Grafana/Prometheus stack
- **Considered:** Full observability stack in separate processes.
- **Rejected because:** Opens a browser window (distracting in demo). Requires additional ports. The dashboard already has pyqtgraph — we build the metrics panel directly in the Qt app. We still expose Prometheus-format metrics on an HTTP endpoint, so external tools can connect later. Best of both worlds.
- **ADR:** ADR-006

---

## Implementation Order and Rationale

### Phase 1: Repository Scaffold (Foundation)
**Why first:** Everything depends on project structure, tooling, and environment validation.

**Deliverables:**
1. Full directory structure matching the specification
2. `pyproject.toml` with all deps pinned
3. `requirements.txt` / `requirements-dev.txt`
4. `config/wints.yaml` — all simulation parameters
5. `config/mosquitto.conf` — broker configuration
6. `scripts/wints.py` — CLI with `doctor` and `setup` commands
7. `.vscode/` configurations
8. `.gitignore`, `README.md`
9. Install native dependencies (Mosquitto, FFmpeg)
10. Create venv and install Python packages

**Verification:** `wints doctor` shows all green.

**Mitigations addressed:** C3 (port pre-flight), C6 (sleep prevention documented)

---

### Phase 2: Target Simulator (Engineering Core)
**Why second:** The simulator is the physics engine. Dashboard depends on it. Tests depend on it.

**Deliverables:**
1. `target_simulator/physics/motor.py` — coupled ODE solver with state clamping (C5)
2. `target_simulator/physics/battery.py` — coulomb counting, OCV-SOC, BMS
3. `target_simulator/physics/solar.py` — irradiance model, MPPT
4. `target_simulator/physics/rf_link.py` — FSPL, shadowing, PER
5. `target_simulator/target.py` — hierarchical state machine (C7), MQTT client
6. `target_simulator/fault_injector.py` — HTTP API for fault injection
7. `target_simulator/main.py` — spawns 10 asyncio tasks
8. `target_simulator/metrics.py` — Prometheus gauges/counters
9. Shared Pydantic models in `target_simulator/models.py`

**Verification:**
- Unit tests for all physics modules (energy conservation, SOC bounds, RSSI monotonicity)
- Single target runs standalone with MQTT broker
- Fault injection API responds correctly

**Mitigations addressed:** C5 (ODE clamping), C7 (single-threaded FSM), C8 (heartbeat)

---

### Phase 3: Control Room Dashboard (Operator Interface)
**Why third:** Depends on simulator being functional for integration testing.

**Deliverables:**
1. `control_room/models/target_state.py` — Pydantic models (shared schema)
2. `control_room/models/system_model.py` — singleton QObject, Qt signals (C1)
3. `control_room/mqtt/client.py` — thread-safe paho wrapper, reconnection FSM (C1, C4)
4. `control_room/mqtt/dispatcher.py` — topic routing, validation, deduplication
5. `control_room/ui/main_window.py` — main layout, FlowLayout
6. `control_room/ui/target_card.py` — custom widget, animations, stale indicator (C8)
7. `control_room/ui/video_widget.py` — QMediaPlayer + OpenCV fallback (C2)
8. `control_room/ui/event_log.py` — coloured, filterable, exportable
9. `control_room/ui/metrics_panel.py` — pyqtgraph charts, Prometheus endpoint
10. `control_room/services/command_tracker.py` — UUID tracking, timeout

**Verification:**
- Dashboard connects to broker and displays target states
- Commands flow through and ack correctly
- Stale indicator appears when simulator is stopped
- Video widget shows test pattern or "UNAVAILABLE"

**Mitigations addressed:** C1 (thread-safe), C2 (lazy video), C4 (reconnection), C8 (stale)

----

### Phase 4: Video Infrastructure
**Why fourth:** Enhances demo quality but system is functional without it.

**Deliverables:**
1. `video_server/generate_test_patterns.py` — FFmpeg test pattern generation
2. `video_server/start_mediamtx.py` — config generation, process launch
3. `config/mediamtx.yml` — 20 stream paths
4. 20 distinguishable MP4 test patterns in `video_server/samples/`

**Verification:** RTSP URLs accessible via VLC or ffplay.

----

### Phase 5: Reference Firmware (Documentation)
**Why fifth:** Documentation artifact, not runtime dependency.

**Deliverables:**
1. `firmware/main_reference.c` — FreeRTOS main, task creation
2. `firmware/mqtt_client.c` — coreMQTT, LWT, dedup
3. `firmware/motor.c` — PWM, H-bridge, current sense
4. `firmware/battery.c` — ADC, SOC estimation
5. `firmware/network.c` — lwIP, RMII, static IP
6. `firmware/README.md` — pin-map, peripherals, block diagram

**Verification:** Code review — 1:1 correspondence with simulator modules.

---

### Phase 6: Observability Polish
**Why sixth:** Makes the demo impressive but system works without it.

**Deliverables:**
1. Prometheus metrics endpoint finalized
2. Session replay recording in all components
3. `wints replay` command functional
4. Structured log rotation configured

----

### Phase 7: Test Suite
**Why seventh:** Validates everything built in phases 1-6.

**Deliverables:**
1. Unit tests (physics, state machines, MQTT contract)
2. Property-based tests (Hypothesis)
3. Integration test (full stack, scripted scenario)
4. Chaos tests (top-8 fault injection)
5. Coverage report ≥ 75%

----

### Phase 8: Demo Polish & Documentation
**Why last:** Polishes the deliverable for presentation.

**Deliverables:**
1. `docs/05_demo_script.md` — minute-by-minute supervisor demo
2. `docs/06_adr.md` — 8-10 architecture decision records
3. `docs/04_real_hardware.md` — hardware integration guide
4. `README.md` — polished with quickstart
5. `docs/07_backlog.md` — deferred items with rationale

----

## Execution Discipline

1. **Each phase completes fully before the next begins.** No partial phases.
2. **`wints doctor` runs after every phase.** Must show all green.
3. **Tests run after phases 2, 3, 6, 7.** Must all pass.
4. **No TODO in runnable code.** Deferred items go to backlog with rationale.
5. **Commits are atomic and pass lint.** Conventional commit style.
6. **If the plan is wrong, stop and write an ADR.** No silent deviations.

---

## Time Estimate

| Phase | Estimated Effort | Cumulative |
|-------|-----------------|------------|
| Phase 1: Scaffold | 30 min | 30 min |
| Phase 2: Simulator | 2-3 hours | 3.5 hours |
| Phase 3: Dashboard | 2-3 hours | 6.5 hours |
| Phase 4: Video | 30 min | 7 hours |
| Phase 5: Firmware | 1 hour | 8 hours |
| Phase 6: Observability | 1 hour | 9 hours |
| Phase 7: Tests | 1-2 hours | 11 hours |
| Phase 8: Docs | 1 hour | 12 hours |

**Minimum viable deliverable (Phases 1-5 + 8):** ~8 hours
**Full deliverable (all 8 phases):** ~12 hours

---

## Success Criteria

The system is complete when:

1. ✅ `wints doctor` reports all green
2. ✅ `wints demo` launches broker + simulator + dashboard in correct order
3. ✅ All 10 targets appear in dashboard with correct initial states
4. ✅ Raise/lower commands flow through with visible spinner → ack cycle
5. ✅ Fault injection (`wints inject T-07 overcurrent`) causes visible FAULT + recovery
6. ✅ Killing the simulator causes LWT-based offline detection within 30s
7. ✅ Battery SOC visibly drains/charges at accelerated time
8. ✅ RSSI bars reflect simulated distance (T-01 near = strong, T-09 far = weak)
9. ✅ Event log shows colour-coded structured events
10. ✅ `wints replay` successfully replays a recorded session
11. ✅ pytest runs ≥ 75% coverage on core modules
12. ✅ mypy --strict and ruff pass cleanly
13. ✅ Firmware C code has 1:1 correspondence with simulator Python
14. ✅ Supervisor demo script runs for 10 minutes without failure
