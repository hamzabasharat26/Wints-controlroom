# WINTS Demo Script — 10-Minute Supervisor Demonstration

> Minute-by-minute guide for demonstrating the system to your supervisor.
> Every action is scripted. Every question has a prepared answer.

## Pre-Demo Checklist (5 minutes before)

```powershell
# Terminal 1: Start everything
cd "d:\SEM 8\ESD CEP"
.venv\Scripts\activate
python -m scripts.wints doctor    # Verify all green
python -m scripts.wints demo      # Starts broker + simulator + dashboard
```

Verify dashboard opens with 10 target cards. T-07 should show FAULT (orange), T-09 should show OFFLINE (red), 8 others show ONLINE (green).

---

## Minute 0:00 — System Overview (1 min)

**Talking points:**
- "This is WINTS — a distributed embedded system controlling 10 motorised range targets across a 10 km² military training area."
- "Each target is an independent node with its own motor controller, battery, solar panel, and RF link."
- "The system uses MQTT for command/telemetry, and the dashboard provides real-time observability."

**Point out:**
1. 10 target cards arranged in a grid
2. Status badges: 8 green, 1 orange (T-07 FAULT), 1 red (T-09 OFFLINE)
3. Metrics panel on the right: 8/10 online, average battery SOC, RSSI
4. Event log at the bottom — already showing connection events

---

## Minute 1:00 — Single Target Command (1 min)

**Action:** Click **▲ RAISE** on T-01.

**Explain:**
- "Watch the command flow: button → trace_id generated → MQTT QoS 1 publish → simulator receives → motor ODE starts solving → position updates stream back."
- Point to the event log: `CMD T-01 → RAISE [trace_id]`
- Watch the position bar animate from 0% to 100%
- Motor current rises (shown on card), then drops to zero at limit

**Supervisor question:** *"What happens under the hood?"*

**Answer:** "The motor model solves coupled differential equations — electrical (V = L·di/dt + Ri + K_e·ω) and mechanical (J·dω/dt = K_t·i - Bω - T_load). The solver runs at 1ms steps using scipy's RK45 adaptive integrator. The current rises to ~24A during inrush, then settles to steady-state. When the position reaches θ_max, the limit switch debounce fires and the motor stops."

---

## Minute 2:00 — Broadcast Command (1 min)

**Action:** Click **▲ RAISE ALL** in the toolbar.

**Explain:**
- "Broadcast sends a single MQTT message to `wints/broadcast/cmd`. Each simulator generates a child trace_id (parent.T-XX) for deduplication."
- Watch 8 targets raise simultaneously (T-07 and T-09 don't respond)
- T-07 rejects the command (FAULT state), T-09 doesn't receive it (OFFLINE)
- Point out different raise times: closer targets (T-01, T-04, T-08) appear to respond faster

---

## Minute 3:00 — Physics Fidelity (2 min)

**Action:** Hover over battery bar on T-03 to show tooltip.

**Explain:**
- "Battery model uses EVE LF100LA datasheet OCV-SOC curve. The voltage you see isn't just `SOC × max_voltage` — it's interpolated from a 14-point lookup table, minus I·R_internal."
- "R_internal varies with temperature. At -20°C it doubles, causing worse voltage sag."
- "Solar panel follows a sinusoidal irradiance model — notice the sim time is 08:XX. As it progresses toward noon, solar output increases."

**Point to T-09 (offline):**
- "T-09 is at 5 km range with 30% initial SOC. Even if it were online, its RSSI would be around -85 dBm with significant packet loss."

**Supervisor question:** *"Is the motor model just 'wait 4 seconds then change state'?"*

**Answer:** "No. It solves the full coupled ODEs every millisecond. The motor draws current based on back-EMF, which depends on angular velocity, which depends on torque minus friction minus gravity load. The time to raise depends on these physics, not a fixed timer."

---

## Minute 5:00 — Fault Injection (2 min)

**Action:** Open a second terminal:
```powershell
cd "d:\SEM 8\ESD CEP"
.venv\Scripts\activate

# Inject overcurrent fault into T-03
python -m scripts.wints inject T-03 overcurrent
```

**Watch the dashboard:**
- T-03 status badge smoothly animates from green → orange
- Fault chip appears: "⚠ OVERCURRENT"
- Event log shows the fault
- Buttons grey out (can't command a faulted target)

**Then clear it:**
```powershell
python -m scripts.wints inject T-03 clear
```

- Badge animates back to green
- Fault chip disappears
- Buttons re-enable

**Explain:**
- "The fault injector uses a REST API on each simulator instance. In production, these faults happen physically — motor stall from debris, battery BMS trip from temperature."
- "Each target has its own fault injection port (T-01=9301, T-02=9302, etc.)"

---

## Minute 7:00 — Engineering Rigour Deep Dive (2 min)

**Open files in VS Code to show:**

1. **Deduplication** — `target.py` line ~180: `_is_duplicate()` with LRU cache and TTL
2. **Thread safety** — `client.py`: `QMetaObject.invokeMethod` with `Qt.QueuedConnection`
3. **State clamping** — `motor.py` line ~280: position and current bounded after every ODE step
4. **Pre-mortem** — `docs/02_premortem.md`: 24 failure modes, risk matrix

**Explain:**
- "Every design decision traces to a documented failure mode. F-13 prevents ODE divergence. F-03 prevents command replay. F-08 ensures QoS 1 commands aren't dropped by RF."
- "The firmware reference C code maps every Python function to a hardware peripheral."

---

## Minute 9:00 — Architecture Diagram & Wrap Up (1 min)

**Show `docs/01_design.md`** — point to the state machine diagrams.

**Closing statement:**
- "The system separates physics simulation from protocol handling from UI. The MQTT contract is defined in Pydantic models shared between both sides. The dashboard never mutates state directly — everything flows through the SystemModel via Qt signals."
- "To swap in real hardware, you flash the STM32, connect the ESP32 as an MQTT bridge, and the dashboard works unchanged. See `docs/04_real_hardware.md`."

---

## Prepared Answers for Hard Questions

| Question | Answer |
|----------|--------|
| "What if the broker dies mid-command?" | "paho-mqtt's loop_start() handles reconnection automatically. The dashboard shows the connection drop immediately (status bar turns red). Pending commands time out after 500ms. On reconnect, targets re-publish their retained status." |
| "How do you prevent race conditions?" | "All state mutations happen on a single thread — asyncio event loop for the simulator, Qt event loop for the dashboard. MQTT callbacks dispatch via call_soon_threadsafe (simulator) or QMetaObject.invokeMethod (dashboard)." |
| "What about command ordering?" | "MQTT QoS 1 guarantees at-least-once delivery with ordering. Each command has a UUID trace_id. The simulator deduplicates on trace_id with a 5-second TTL cache." |
| "Why not use threads for 10 targets?" | "asyncio cooperative multitasking avoids lock contention and makes the state machine deterministic. Each target is an independent coroutine sharing the event loop." |
| "How do you test fault tolerance?" | "Run `wints inject T-XX fault_type` during the demo. The fault injector is an HTTP API on each simulator. We also have chaos tests in `tests/chaos/`." |
| "Is this just a simulation?" | "The simulation is architecturally identical to the real firmware. See `firmware/main_reference.c` — every Python function maps to a C function. The MQTT contract is identical. Swapping in real hardware requires zero dashboard changes." |
