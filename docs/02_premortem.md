# WINTS — Pre-Mortem Analysis
## Document ID: 02_premortem
## Version: 1.0 | Date: 2026-06-14
## Classification: Risk Analysis — CEP Deliverable

---

## Scenario

It is demo day + 10 minutes. The supervisor has just watched WINTS fail catastrophically. This document enumerates every way that could have happened, ranks the failures by risk, and identifies the top 8 that must be designed against as first-class architectural decisions.

---

## Failure Catalogue (24 Failures)

### Category 1: Concurrency (4 failures)

#### F-01: MQTT callback thread writes to SystemModel while Qt paint reads it
- **Description:** paho-mqtt's on_message callback runs in its own thread. If it directly updates SystemModel dictionaries while a QWidget.paintEvent reads them, we get a race condition — corrupted data, intermittent crashes, or stale reads.
- **Manifestation:** Dashboard randomly freezes, shows garbled text in target cards, or crashes with "dictionary changed size during iteration".
- **Probability:** HIGH
- **Impact:** HIGH
- **Mitigation:** All MQTT messages cross the thread boundary via `QMetaObject.invokeMethod(model, Qt.QueuedConnection)`. The MQTT thread never writes to SystemModel directly. SystemModel updates only happen on the Qt event loop thread.
- **Code location:** `control_room/mqtt/client.py` → `_on_message()` method; `control_room/models/system_model.py` → `@pyqtSlot` methods.

#### F-02: Asyncio event loop starvation in target simulator
- **Description:** 10 targets each running physics at 1ms ODE steps. If one target's ODE solver takes longer than 1ms (e.g., stiff system near stall), it blocks the event loop, delaying all other targets' physics ticks and MQTT publishes.
- **Manifestation:** Telemetry from multiple targets arrives in bursts instead of smoothly. Motor movements appear jerky. Dashboard shows latency spikes.
- **Probability:** MEDIUM
- **Impact:** MEDIUM
- **Mitigation:** Physics runs in a dedicated `asyncio.to_thread()` call per target, or uses `loop.run_in_executor(ThreadPoolExecutor)`. The asyncio event loop handles only MQTT I/O and scheduling. ODE solver has a wall-clock timeout — if a single step exceeds 5ms, log a warning and use the last valid state.
- **Code location:** `target_simulator/target.py` → `_physics_tick()` method.

#### F-03: Command deduplication cache grows unbounded
- **Description:** QoS 1 deduplication uses an LRU cache keyed on trace_id. If the cache has no size limit or TTL, and the system runs for hours, memory grows.
- **Manifestation:** After hours of testing, the simulator process uses 500MB+ RAM. OOM on low-memory laptops.
- **Probability:** LOW
- **Impact:** MEDIUM
- **Mitigation:** LRU cache with max 200 entries and 5-second TTL. Entries older than 5s are evicted. Use `functools.lru_cache` or a simple OrderedDict with timestamp checks.
- **Code location:** `target_simulator/target.py` → `_dedup_cache`; `control_room/mqtt/dispatcher.py` → `_dedup_cache`.

#### F-04: Race between fault injection HTTP server and MQTT command processing
- **Description:** The fault injector HTTP API and MQTT command handler both modify target state. If an HTTP POST /fault/inject arrives simultaneously with a raise command, the state machine could enter an inconsistent state.
- **Manifestation:** Target shows FAULT but motor is still running. Or motor starts moving during a fault state.
- **Probability:** MEDIUM
- **Impact:** HIGH
- **Mitigation:** All state modifications go through a single-threaded asyncio event loop. The HTTP server (aiohttp or asyncio-based) runs on the same loop. State machine transitions are atomic — a single async method acquires the state, validates the transition, applies it, and publishes. No concurrent mutation.
- **Code location:** `target_simulator/target.py` → `_process_event()` (single entry point for all state changes).

---

### Category 2: MQTT / Network (4 failures)

#### F-05: Mosquitto broker process dies mid-demo
- **Description:** Broker crashes due to disk full (persistence), accidental kill, or Windows Update restarting services. All MQTT communication ceases instantly.
- **Manifestation:** All target cards go offline within ~30 seconds (keepalive timeout). Commands hang indefinitely. Event log fills with reconnection attempts.
- **Probability:** LOW
- **Impact:** CRITICAL
- **Mitigation:** Both dashboard and simulator MQTT clients implement reconnection FSMs with exponential backoff + jitter. Dashboard shows "Broker Disconnected — Reconnecting..." banner. Commands issued during disconnect are queued with a 30-second expiry. On reconnect, retained messages restore last-known state. `wints demo` monitors the broker subprocess and restarts it automatically if it dies.
- **Code location:** `control_room/mqtt/client.py` → reconnection FSM; `scripts/wints.py` → `demo` command with process monitoring.

#### F-06: Retained message shows stale state after target restart
- **Description:** Target T-03 was in FAULT state, published retained status. Simulator restarts. T-03 boots up healthy. Dashboard connects and receives the old retained FAULT message before the new ONLINE message arrives.
- **Manifestation:** Dashboard shows T-03 as FAULT for a few seconds after startup, then snaps to ONLINE. During that window, the operator might issue unnecessary recovery commands.
- **Probability:** HIGH
- **Impact:** LOW
- **Mitigation:** Status messages include a `ts` (Unix milliseconds) field. Dashboard compares `ts` to current time; messages older than 30 seconds are marked as "stale" and displayed with a dimmed style. Targets publish a fresh status within 2 seconds of connecting. Dashboard also shows a "Last updated: Xs ago" indicator on each card.
- **Code location:** `control_room/models/system_model.py` → `_update_target()` stale check; `control_room/ui/target_card.py` → stale indicator.

#### F-07: MQTT session resumption delivers out-of-order messages
- **Description:** QoS 1 messages with `clean_session=False` can be redelivered after reconnection. If the session broker has queued messages from before the disconnect, the target receives old commands after new ones.
- **Manifestation:** Target receives "raise" (from before disconnect), processes it, then receives "stop" (the more recent command). The operator intended stop but the target raises first.
- **Probability:** MEDIUM
- **Impact:** MEDIUM
- **Mitigation:** Use `clean_session=True` (clean_start in MQTT 5) for both simulator and dashboard. On reconnect, the subscriber resubscribes. No stale messages from the session queue. The cost is potential message loss during the disconnect window — acceptable because the operator will re-issue the command. Dashboard CommandTracker handles this by timing out pending commands.
- **Code location:** `target_simulator/target.py` → MQTT client config; `control_room/mqtt/client.py` → `clean_session=True`.

#### F-08: Simulated packet loss drops a critical command
- **Description:** RF model calculates PER=0.2 for T-07 (distant target). The "raise" command arrives at the target's MQTT client, but the *response* status publish is dropped by the RF model. Dashboard never sees the ack.
- **Manifestation:** Dashboard shows timeout for T-07's command, but T-07 actually raised. Position is inconsistent between dashboard and reality.
- **Probability:** HIGH
- **Impact:** MEDIUM
- **Mitigation:** RF packet loss applies only to QoS 0 telemetry publishes, NOT to QoS 1 status publishes. QoS 1 guarantees delivery at the MQTT level. The RF model affects telemetry (which is best-effort) and introduces *delay* (not drop) for commands. This models reality: QoS 1 retransmits until acked, but high PER causes latency. Telemetry gaps are expected and the dashboard handles them gracefully (shows "last update: Xs ago").
- **Code location:** `target_simulator/physics/rf_link.py` → `should_drop_packet(qos)` returns False for qos=1.

---

### Category 3: State Drift / Data Consistency (4 failures)

#### F-09: Dashboard shows UP but target is actually DOWN
- **Description:** Target successfully raised, status published. Then the target lowered due to a fault or an operator at the physical console (in real hardware). The status publish for the new DOWN state is lost or delayed.
- **Manifestation:** Operator sees target UP and doesn't deploy additional commands, but the target is actually down. Dangerous in a real range.
- **Probability:** MEDIUM
- **Impact:** HIGH
- **Mitigation:** Targets publish status on *every* state transition AND every 2 seconds as periodic heartbeat (status is echoed in telemetry). Dashboard has a "confidence" indicator: if no status update received in 6 seconds, the card shows "⚠ Stale" and the status badge dims. The operator is trained (via demo script) to treat stale indicators as "verify before trusting."
- **Code location:** `target_simulator/target.py` → periodic status publish; `control_room/ui/target_card.py` → stale timer.

#### F-10: SystemModel and target cards diverge due to signal loss
- **Description:** Qt signal/slot connections can be broken by object deletion. If a TargetCard is deleted (e.g., window resize triggers re-layout) but SystemModel still holds the target state, the new TargetCard doesn't receive the signal.
- **Manifestation:** After window resize, one or more target cards show default/empty state instead of current data.
- **Probability:** LOW
- **Impact:** MEDIUM
- **Mitigation:** TargetCards are created once and reused — never deleted during runtime. FlowLayout repositions existing widgets without creating/destroying them. On initial creation, each TargetCard reads the current state from SystemModel (pull model), then subscribes to signals for future updates (push model).
- **Code location:** `control_room/ui/main_window.py` → `_create_target_cards()` called once; `control_room/ui/target_card.py` → `__init__` reads current state.

#### F-11: Command trace_id collision causes false ack
- **Description:** Two commands with the same UUID4 (astronomically unlikely but theoretically possible) cause the CommandTracker to ack the wrong command.
- **Manifestation:** Button spinner clears prematurely; the command that was actually acked is lost.
- **Probability:** NEGLIGIBLE
- **Impact:** LOW
- **Mitigation:** Accept the ~10⁻³⁷ collision probability for UUID4. No additional mitigation needed. Document this explicitly in the ADR as an accepted risk.
- **Code location:** N/A — documented in `docs/06_adr.md`.

#### F-12: Telemetry timestamp drift between sim-time and real-time
- **Description:** Battery/solar run at 60× sim-time but motor runs in real-time. If telemetry mixes both time domains without clear labelling, charts show nonsensical data (e.g., battery SOC appears to change 60× faster than it should relative to motor movement).
- **Manifestation:** Metrics panel shows battery draining in minutes while a single raise operation takes 4 real seconds. Confusing to the supervisor.
- **Probability:** HIGH
- **Impact:** MEDIUM
- **Mitigation:** Telemetry includes both `ts` (real Unix time) and `sim_time_h` (simulated hours elapsed). Dashboard charts are clearly labelled: motor/command charts use real-time X-axis; battery/solar charts use sim-time X-axis with a "(60× accelerated)" label. The dual time domain is explained in the demo script.
- **Code location:** `target_simulator/target.py` → telemetry payload construction; `control_room/ui/metrics_panel.py` → axis labels.

---

### Category 4: Physics Model Edge Cases (4 failures)

#### F-13: ODE solver diverges at motor stall
- **Description:** When ω → 0 and T_load > K_t·i, the motor stalls. The coupled ODEs become stiff: current rises rapidly (L·di/dt = V - K_e·0 = V), creating a numerical stiffness issue that RK45 handles poorly.
- **Manifestation:** Current value spikes to infinity (NaN), corrupting all downstream state. Target publishes NaN in telemetry. Dashboard shows "NaN" in battery voltage.
- **Probability:** MEDIUM
- **Impact:** HIGH
- **Mitigation:** Use RK45 with adaptive step size (scipy default) AND add explicit bounds checking after each step: clamp current to [0, 20A], clamp ω to [0, ω_max]. If current exceeds overcurrent threshold for >300ms, trigger MOTOR_FAULT and disable drive (set V_bus = 0). The overcurrent protection acts as a physical safeguard that also prevents numerical divergence.
- **Code location:** `target_simulator/physics/motor.py` → `_ode_rhs()` and `step()` methods with clamping.

#### F-14: Battery SOC goes negative or exceeds 100%
- **Description:** Numerical integration of coulomb counting can overshoot bounds during rapid charge/discharge transitions, especially at 60× time acceleration.
- **Manifestation:** Telemetry shows SOC = -3% or SOC = 102%. Dashboard battery bar overflows or shows invalid colour.
- **Probability:** MEDIUM
- **Impact:** LOW
- **Mitigation:** SOC is clamped to [0, 100] after every integration step. BMS cutoff at 10% prevents operation below that. Charge controller limits at 100% prevents overcharge. The clamp is a safety net for numerical error. Integration step size is also bounded: dt_max = 0.1 sim-seconds even at 60× acceleration.
- **Code location:** `target_simulator/physics/battery.py` → `step()` method, final clamp.

#### F-15: Both limit switches activate simultaneously
- **Description:** Hardware fault condition: PA0 (UP limit) and PA1 (DOWN limit) both read as active. In real hardware this means a wiring fault or sensor failure.
- **Manifestation:** Motor gets contradictory feedback — it's simultaneously at UP and DOWN position. State machine doesn't know what to do.
- **Probability:** LOW (simulated only via fault injection)
- **Impact:** HIGH
- **Mitigation:** Explicit guard in the state machine: if both limit switches active, enter LIMIT_STUCK fault state. Motor disabled immediately. Fault code published. This is a documented fault injection scenario — the supervisor can trigger it and watch the recovery.
- **Code location:** `target_simulator/target.py` → `_check_limit_switches()` method; `target_simulator/physics/motor.py` → `get_limit_state()`.

#### F-16: Solar irradiance noise generates negative power
- **Description:** Gaussian cloud noise (σ=50 W/m²) can make G(t) negative when the base irradiance is low (dawn/dusk), resulting in negative power generation.
- **Manifestation:** Battery appears to drain faster than expected at dawn/dusk. Or charge current becomes negative (extracting energy from the battery through the panel — physically impossible).
- **Probability:** HIGH
- **Impact:** LOW
- **Mitigation:** `G(t) = max(0, G_base + noise)` — clamp irradiance to non-negative. Solar power is always ≥ 0. This is already in the design equations but must be rigorously implemented.
- **Code location:** `target_simulator/physics/solar.py` → `get_irradiance()` method.

---

### Category 5: Resource Leaks (3 failures)

#### F-17: OpenCV VideoCapture leaks file handles on RTSP reconnection
- **Description:** If RTSP stream disconnects and OpenCV fallback VideoCapture is used, failing to call `.release()` before creating a new capture leaks file handles and socket connections. After 50–100 reconnections, the process hits the OS handle limit.
- **Manifestation:** Dashboard gradually consumes more handles. Eventually new RTSP connections fail silently. Video shows "UNAVAILABLE" for all targets.
- **Probability:** MEDIUM
- **Impact:** MEDIUM
- **Mitigation:** VideoWidget uses a context-manager pattern: `__enter__`/`__exit__` for VideoCapture. Reconnection always releases the old capture before creating a new one. A periodic health check (every 30s) audits open captures and force-releases orphans.
- **Code location:** `control_room/ui/video_widget.py` → `_reconnect_stream()` method with explicit `.release()`.

#### F-18: Structlog file handler never rotates
- **Description:** JSON log files grow without bound. After hours of testing with 10 targets publishing telemetry every 2s, log files reach hundreds of MB.
- **Manifestation:** Disk fills up during overnight testing. Mosquitto persistence also fails.
- **Probability:** MEDIUM
- **Impact:** MEDIUM
- **Mitigation:** Use `logging.handlers.RotatingFileHandler` as the structlog sink. Max file size: 50 MB. Backup count: 5. Total log budget: 250 MB. Session replay files are separate and also size-limited.
- **Code location:** `control_room/main.py` and `target_simulator/main.py` → logging setup with RotatingFileHandler.

#### F-19: Prometheus client accumulates stale metrics for disconnected targets
- **Description:** prometheus_client gauges and counters persist even after a target goes offline. The `/metrics` endpoint grows with dead entries.
- **Manifestation:** Prometheus output becomes cluttered. Not a crash risk, but unprofessional.
- **Probability:** LOW
- **Impact:** LOW
- **Mitigation:** On target disconnect (LWT received), set gauges to NaN (or a sentinel value). Counters are cumulative and persist — this is correct Prometheus semantics. Document that offline target metrics show the last-known value.
- **Code location:** `control_room/ui/metrics_panel.py` → `_on_target_offline()`.

---

### Category 6: Demo-Day Environment (3 failures)

#### F-20: Port 1883 already in use (another Mosquitto instance or firewall)
- **Description:** The laptop has another MQTT broker running (from previous testing, or another application). `wints broker` fails with "address already in use."
- **Manifestation:** Broker doesn't start. Simulator and dashboard can't connect. Demo stalls at minute 0.
- **Probability:** HIGH
- **Impact:** CRITICAL
- **Mitigation:** `wints doctor` checks if port 1883 is free using `socket.connect_ex()`. If occupied, it identifies the PID (`netstat -ano | findstr :1883` on Windows) and warns the user. `wints broker` also checks before starting and gives a clear error message with remediation steps.
- **Code location:** `scripts/wints.py` → `doctor` command, `_check_port()` function.

#### F-21: Windows Defender / antivirus blocks Mosquitto or MediaMTX
- **Description:** Downloaded binaries (especially MediaMTX from GitHub releases) trigger Windows SmartScreen or Defender. The binary is quarantined silently.
- **Manifestation:** `wints video` fails with "binary not found" or "access denied." No clear error.
- **Probability:** MEDIUM
- **Impact:** HIGH
- **Mitigation:** `wints doctor` verifies each binary is executable by attempting to run it with `--version` or `--help`. If it fails, the error message specifically suggests checking Windows Defender quarantine and adding an exclusion. Documentation includes pre-flight instructions to whitelist the project directory.
- **Code location:** `scripts/wints.py` → `doctor` command; `docs/05_demo_script.md` → pre-demo checklist.

#### F-22: Laptop goes to sleep during demo, killing all processes
- **Description:** Power settings cause the laptop to sleep after 5 minutes of "inactivity" (mouse not moving because the operator is talking). All subprocesses die.
- **Manifestation:** Screen goes black mid-demo. All processes killed. Broker, simulator, video server all need restart. 2-minute recovery time.
- **Probability:** MEDIUM
- **Impact:** HIGH
- **Mitigation:** `wints demo` runs `powercfg -change -standby-timeout-ac 0` (disable sleep) at start and restores the previous setting on exit. Pre-demo checklist in `docs/05_demo_script.md` includes "set power plan to High Performance." The `demo` command also prints this reminder.
- **Code location:** `scripts/wints.py` → `demo` command preamble.

---

### Category 7: UX Under Stress (2 failures)

#### F-23: Operator mashes Raise/Lower rapidly, flooding the command queue
- **Description:** No debounce on UI buttons. Rapid clicking generates dozens of commands. MQTT broker and target are flooded. CommandTracker has dozens of pending entries.
- **Manifestation:** Target oscillates or gets stuck processing a queue of contradictory commands. Dashboard shows dozens of timeout toasts. Performance degrades.
- **Probability:** MEDIUM
- **Impact:** MEDIUM
- **Mitigation:** UI-level debounce: after a command is issued, the button is disabled until either ack (position update) or timeout (500ms). Only one pending command per target at a time. If the operator clicks during pending, the click is silently dropped. A subtle tooltip says "Command pending..."
- **Code location:** `control_room/ui/target_card.py` → button state management; `control_room/services/command_tracker.py` → `is_pending()` check.

#### F-24: All 10 RTSP streams open simultaneously, exhausting CPU
- **Description:** Dashboard opens all 20 RTSP streams (10 targets × 2 cameras) on startup. Each OpenCV VideoCapture + decode consumes ~3-5% CPU. Total: 60-100% CPU. Dashboard becomes unresponsive.
- **Manifestation:** Dashboard UI freezes. Fans spin up. Event log stops updating. Controls become unresponsive.
- **Probability:** HIGH
- **Impact:** HIGH
- **Mitigation:** Lazy video loading: only open RTSP streams for the currently visible/expanded target card (max 2 streams at a time). When the user hovers or clicks a card, that card's streams open. When another card is selected, the previous streams close. A "Video Off" default with "Click to stream" overlay. Background cards show the last captured frame as a static image.
- **Code location:** `control_room/ui/video_widget.py` → lazy loading logic; `control_room/ui/target_card.py` → `_on_expanded()` / `_on_collapsed()`.

---

## Risk Matrix

```
                    IMPACT
             LOW    MEDIUM    HIGH    CRITICAL
         ┌────────┬─────────┬────────┬──────────┐
   HIGH  │ F-16   │ F-08    │ F-01   │ F-20     │
         │ F-06   │ F-12    │        │          │
  P      │        │ F-23    │        │          │
  R      ├────────┼─────────┼────────┼──────────┤
  O MED  │        │ F-02    │ F-04   │ F-05     │
  B      │        │ F-03    │ F-09   │          │
  A      │        │ F-07    │ F-13   │          │
  B      │        │ F-17    │ F-21   │          │
  I      │        │ F-18    │ F-22   │          │
  L      ├────────┼─────────┼────────┼──────────┤
  I LOW  │ F-11   │ F-10    │ F-15   │          │
  T      │ F-14   │ F-19    │        │          │
  Y      │        │         │        │          │
         └────────┴─────────┴────────┴──────────┘
```

---

## Top 8 Failures by Risk Score

Risk score = Probability × Impact (using H=3, M=2, L=1, C=4)

| Rank | ID | Name | P×I | Mitigation Summary |
|------|----|------|-----|-------------------|
| 1 | **F-20** | Port 1883 already in use | 3×4=12 | `wints doctor` port check + PID identification |
| 2 | **F-01** | MQTT thread writes to SystemModel | 3×3=9 | QMetaObject.invokeMethod thread-safe crossing |
| 3 | **F-24** | All RTSP streams exhaust CPU | 3×3=9 | Lazy video loading, max 2 concurrent streams |
| 4 | **F-05** | Broker dies mid-demo | 1×4=4→8* | Reconnection FSM + auto-restart in demo mode |
| 5 | **F-13** | ODE diverges at motor stall | 2×3=6 | State clamping + overcurrent protection |
| 6 | **F-22** | Laptop sleeps during demo | 2×3=6 | powercfg disable sleep + pre-demo checklist |
| 7 | **F-04** | Fault injection race condition | 2×3=6 | Single-threaded event loop for all state changes |
| 8 | **F-09** | Dashboard shows wrong position | 2×3=6 | Periodic heartbeat + stale indicator |

*F-05 elevated because the impact is CRITICAL even at low probability — broker loss is total system failure.

---

## Mitigation Design Decisions (carried into 03_chosen_plan.md)

These 8 mitigations are not afterthoughts. They are architectural constraints:

1. **Thread-safe MQTT→Qt bridge** (F-01): Architectural requirement — zero direct cross-thread writes.
2. **Lazy video loading** (F-24): Default video state is OFF. Max 2 concurrent streams.
3. **Port pre-flight check** (F-20): `wints doctor` is mandatory before `wints demo`.
4. **Broker auto-recovery** (F-05): `wints demo` wraps broker in a watchdog subprocess.
5. **ODE state clamping** (F-13): Physics solver outputs are bounds-checked every step.
6. **Sleep prevention** (F-22): Demo mode disables Windows sleep.
7. **Single-threaded state machine** (F-04): All mutations through one asyncio event loop.
8. **Heartbeat + stale indicator** (F-09): Position confidence is always visible to operator.
