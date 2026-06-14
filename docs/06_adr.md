# Architecture Decision Records

## ADR-01: Native MQTT Broker (Mosquitto) Over Embedded Broker

**Status:** Accepted  
**Date:** 2026-06-14  

**Context:** We need a production-grade MQTT broker. Options: embedded Python broker (hbmqtt), Docker Mosquitto, or native Mosquitto.

**Decision:** Native Mosquitto installed via winget.

**Rationale:**
- User explicitly rejected Docker
- Mosquitto is the industry standard for embedded systems
- Native install has minimal overhead and direct port binding
- Supports persistence (survive broker restarts), QoS 1, retained messages, and LWT

**Consequences:**
- Requires manual install via `winget install EclipseFoundation.Mosquitto`
- `wints doctor` validates presence before launch
- Config lives in `config/mosquitto.conf`

---

## ADR-02: asyncio Over Threading for Target Simulation

**Status:** Accepted  
**Date:** 2026-06-14  

**Context:** Each of 10 targets needs concurrent execution. Options: threads, multiprocessing, asyncio.

**Decision:** asyncio cooperative multitasking with one event loop.

**Rationale:**
- Pre-mortem F-04: Threads + shared mutable state = race conditions
- asyncio makes state machine transitions deterministic
- MQTT callbacks dispatched via `call_soon_threadsafe` from paho's network thread
- 10 targets × 10ms physics loop = 100 wakeups/s — well within asyncio's capacity
- No GIL contention since CPU work (ODE solving) is in numpy/scipy C extensions

**Consequences:**
- All state mutations are single-threaded
- Cannot use blocking I/O in the event loop
- Motor physics must yield control (solved via `await asyncio.sleep()`)

---

## ADR-03: QMetaObject.invokeMethod for Thread-Safe MQTT→Qt Bridge

**Status:** Accepted  
**Date:** 2026-06-14  

**Context:** paho-mqtt's callbacks run in a background network thread. Qt widgets must only be modified from the main thread.

**Decision:** Use `QMetaObject.invokeMethod` with `Qt.QueuedConnection` to serialize MQTT messages into the Qt event loop.

**Rationale:**
- Pre-mortem F-01: Direct widget access from MQTT thread → segfault
- Qt's queued connection mechanism is the canonical solution
- Preserves Qt's thread-affinity model
- SystemModel receives @pyqtSlot methods that are invoked safely

**Consequences:**
- All incoming messages are deserialized before crossing the thread boundary
- One extra copy of each payload (acceptable at 10 targets × 0.5 Hz status)
- Latency: ~1ms for queued invocation

---

## ADR-04: Pydantic v2 for MQTT Payload Validation

**Status:** Accepted  
**Date:** 2026-06-14  

**Context:** MQTT payloads need schema validation. Options: manual JSON parsing, dataclasses, marshmallow, Pydantic.

**Decision:** Pydantic v2 BaseModel for all MQTT payloads.

**Rationale:**
- Single source of truth: same models used by simulator (producer) and dashboard (consumer)
- Automatic JSON Schema generation for documentation
- `model_validate_json()` rejects malformed payloads without crashing
- Field validators enforce invariants (e.g., target_id pattern `T-\d{2}`)
- v2 is 5-20× faster than v1 (Rust core)

**Consequences:**
- Runtime dependency on pydantic (already needed)
- Models in `target_simulator/models.py`, re-exported by `control_room/models/target_state.py`

---

## ADR-05: scipy RK45 Over Euler Method for Motor ODE

**Status:** Accepted  
**Date:** 2026-06-14  

**Context:** The motor coupled ODEs (electrical + mechanical) need numerical integration.

**Decision:** scipy's `solve_ivp` with RK45 adaptive method at 1ms base timestep.

**Rationale:**
- Euler method is O(h) — requires very small timesteps to avoid divergence
- RK45 is O(h⁴) — maintains accuracy at larger timesteps
- Adaptive step control prevents instability during inrush transients
- Pre-mortem F-13: state clamping after every step prevents runaway values even if solver has issues

**Consequences:**
- scipy is a runtime dependency (~30 MB)
- Single ODE step takes ~50μs — acceptable at 10 targets × 10ms real-time
- Solver failure is caught and state is held (fail-safe)

---

## ADR-06: Catppuccin Mocha Theme for Dashboard

**Status:** Accepted  
**Date:** 2026-06-14  

**Context:** The dashboard needs a colour scheme. Options: Qt system theme, Material, custom dark theme.

**Decision:** Catppuccin Mocha dark palette with custom CSS.

**Rationale:**
- High contrast dark theme reduces eye strain during extended range operations
- Well-defined palette with semantic colours: green=OK, amber=warning, red=critical
- Consistent with modern embedded system HMIs (SCADA-style)
- Applied via QSS stylesheets, no dependency on additional theme libraries

**Consequences:**
- All colours defined inline in QSS strings
- Badge animations use QPropertyAnimation for smooth transitions
- Works on Windows, Linux, and macOS without platform-specific tweaks

---

## ADR-07: Structlog Over stdlib logging

**Status:** Accepted  
**Date:** 2026-06-14  

**Context:** Need structured logging for both simulator and dashboard.

**Decision:** structlog with contextvars and ISO timestamps.

**Rationale:**
- Structured key-value pairs are machine-parseable (critical for log analysis)
- Context binding (`logger.bind(target_id="T-01")`) adds per-target context automatically
- ConsoleRenderer for development, JSONRenderer for production
- stdlib logging is unstructured and hard to filter per-target

**Consequences:**
- structlog is a runtime dependency
- All log statements use `logger.info("event_name", key=value)` format
- Log files can be processed with jq for post-mortem analysis
