"""Single target simulator — hierarchical state machine with physics engine.

Each target is an independent asyncio task that:
    1. Connects to the MQTT broker with LWT
    2. Subscribes to its command topic
    3. Runs physics simulation (motor ODE, battery, solar, RF) in a tight loop
    4. Publishes status on state transitions and telemetry every 2 seconds
    5. Handles fault injection via HTTP API
    6. Deduplicates incoming commands on trace_id (F-03 mitigation)

All state mutations go through a single asyncio event loop — no threading,
no shared mutable state between targets (Pre-mortem F-04 and F-07 mitigation).

Simulator equivalent of: firmware/main_reference.c (main task loop)
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any

import paho.mqtt.client as mqtt
import structlog

from target_simulator.models import (
    CommandPayload,
    CommandType,
    FaultCode,
    PositionLabel,
    StatusPayload,
    TelemetryPayload,
)
from target_simulator.physics.battery import BatterySimulator
from target_simulator.physics.motor import MotorSimulator, MotorState
from target_simulator.physics.rf_link import RFLinkSimulator
from target_simulator.physics.solar import SolarSimulator

logger = structlog.get_logger(__name__)


# Deduplication cache max entries and TTL (Pre-mortem F-03 mitigation)
_DEDUP_MAX_ENTRIES: int = 200
_DEDUP_TTL_S: float = 5.0


class TargetLifecycleState:
    """Target lifecycle state constants.

    Matches docs/01_design.md §2.1 state diagram.

    Example:
        >>> TargetLifecycleState.ONLINE
        'ONLINE'
    """

    OFFLINE = "OFFLINE"
    CONNECTING = "CONNECTING"
    ONLINE = "ONLINE"
    FAULT = "FAULT"
    RECOVERING = "RECOVERING"


class TargetSimulator:
    """Complete simulated range target with physics and MQTT.

    Integrates motor, battery, solar, and RF physics models with an MQTT
    client and hierarchical state machine. One instance per physical target.

    All state changes are driven from a single asyncio event loop (F-04).
    MQTT callbacks are dispatched to the event loop via asyncio.call_soon_threadsafe.

    Args:
        target_id: Target identifier (e.g., 'T-01').
        broker_host: MQTT broker hostname.
        broker_port: MQTT broker port.
        distance_m: Distance from control room (m).
        bearing_deg: Bearing from control room (degrees).
        initial_soc: Initial battery SOC (0-100%).
        initial_position_pct: Initial target position (0=DOWN, 100=UP).
        time_accel: Time acceleration factor for battery/solar.
        fault_injector_port: HTTP port for fault injection API.
        start_offline: If True, target starts in OFFLINE state.
        start_faulted: If True, target starts in FAULT state.

    Example:
        >>> target = TargetSimulator(
        ...     target_id="T-01",
        ...     distance_m=500,
        ...     initial_soc=85.0,
        ... )
    """

    def __init__(
        self,
        target_id: str,
        broker_host: str = "localhost",
        broker_port: int = 1883,
        distance_m: float = 1000.0,
        bearing_deg: float = 0.0,
        initial_soc: float = 80.0,
        initial_position_pct: float = 0.0,
        time_accel: float = 60.0,
        fault_injector_port: int = 9301,
        start_offline: bool = False,
        start_faulted: bool = False,
    ) -> None:
        self._target_id = target_id
        self._broker_host = broker_host
        self._broker_port = broker_port
        self._time_accel = time_accel
        self._fault_injector_port = fault_injector_port
        self._start_offline = start_offline
        self._start_faulted = start_faulted

        # Lifecycle state
        self._lifecycle = TargetLifecycleState.OFFLINE

        # Physics models
        self._motor = MotorSimulator(initial_position_pct=initial_position_pct)
        self._battery = BatterySimulator(initial_soc=initial_soc)
        self._solar = SolarSimulator()
        self._rf = RFLinkSimulator(distance_m=distance_m, bearing_deg=bearing_deg)

        # MQTT client
        self._mqtt_client: mqtt.Client | None = None
        self._mqtt_connected = False

        # Timing
        self._start_time = time.monotonic()
        self._sim_time_h: float = 8.0  # Start at 08:00 sim time (daytime)
        self._last_telemetry_time: float = 0.0
        self._last_status_published: str = ""

        # Command dedup cache: trace_id → timestamp
        self._dedup_cache: OrderedDict[str, float] = OrderedDict()

        # Last command trace_id for echo in status
        self._last_trace_id: str | None = None

        # Fault injection state
        self._injected_fault: str | None = None

        # Event loop reference (set in run())
        self._loop: asyncio.AbstractEventLoop | None = None

        # Running flag
        self._running = False

        self._log = logger.bind(target_id=target_id)

    @property
    def target_id(self) -> str:
        """Target identifier string.

        Returns:
            Target ID (e.g., 'T-01').

        Example:
            >>> t = TargetSimulator(target_id="T-01")
            >>> t.target_id
            'T-01'
        """
        return self._target_id

    @property
    def lifecycle_state(self) -> str:
        """Current lifecycle state.

        Returns:
            Lifecycle state string.

        Example:
            >>> t = TargetSimulator(target_id="T-01")
            >>> t.lifecycle_state
            'OFFLINE'
        """
        return self._lifecycle

    def _setup_mqtt(self) -> mqtt.Client:
        """Create and configure the MQTT client with LWT.

        Uses clean_session=True (F-07 mitigation) to avoid stale
        messages on reconnection.

        Returns:
            Configured paho-mqtt Client.

        Example:
            >>> t = TargetSimulator(target_id="T-01")
            >>> client = t._setup_mqtt()
            >>> client is not None
            True
        """
        client_id = f"wints-sim-{self._target_id}"
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION1,  # type: ignore[attr-defined]
            client_id=client_id,
            protocol=mqtt.MQTTv311,
            clean_session=True,  # F-07: no stale session messages
        )

        # Set Last Will and Testament
        lwt = StatusPayload.create_lwt(self._target_id)
        client.will_set(
            topic=f"wints/{self._target_id}/status",
            payload=lwt.model_dump_json(),
            qos=1,
            retain=True,
        )

        # Callbacks
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message

        return client

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: dict[str, Any],
        rc: int,
    ) -> None:
        """MQTT on_connect callback — subscribes to command topic.

        This runs in the paho network thread. We dispatch to the asyncio
        event loop via call_soon_threadsafe (F-04 mitigation).

        Args:
            client: The MQTT client instance.
            userdata: User data (unused).
            flags: Connection flags.
            rc: Connection result code (0 = success).
        """
        if rc == 0:
            self._log.info("mqtt_connected", rc=rc)
            # Subscribe to direct and broadcast command topics
            client.subscribe(f"wints/{self._target_id}/cmd", qos=1)
            client.subscribe("wints/broadcast/cmd", qos=1)
            self._mqtt_connected = True
            if self._loop:
                self._loop.call_soon_threadsafe(self._on_mqtt_connected)
        else:
            self._log.warning("mqtt_connect_failed", rc=rc)

    def _on_disconnect(
        self, client: mqtt.Client, userdata: Any, rc: int
    ) -> None:
        """MQTT on_disconnect callback.

        Args:
            client: The MQTT client instance.
            userdata: User data (unused).
            rc: Disconnect reason code.
        """
        self._mqtt_connected = False
        self._log.warning("mqtt_disconnected", rc=rc)
        if self._loop:
            self._loop.call_soon_threadsafe(self._on_mqtt_disconnected)

    def _on_message(
        self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage
    ) -> None:
        """MQTT on_message callback — dispatches to asyncio loop.

        Runs in paho network thread. Dispatches to event loop (F-04).

        Args:
            client: The MQTT client instance.
            userdata: User data (unused).
            msg: The received MQTT message.
        """
        if self._loop:
            self._loop.call_soon_threadsafe(
                self._process_command_safe, msg.topic, msg.payload
            )

    def _on_mqtt_connected(self) -> None:
        """Handle MQTT connection established (runs on asyncio loop)."""
        self._lifecycle = TargetLifecycleState.ONLINE
        if self._start_faulted and self._injected_fault is None:
            self._inject_fault("overcurrent")
        self._publish_status()

    def _on_mqtt_disconnected(self) -> None:
        """Handle MQTT disconnection (runs on asyncio loop)."""
        self._lifecycle = TargetLifecycleState.OFFLINE

    def _process_command_safe(self, topic: str, payload: bytes) -> None:
        """Process an incoming MQTT command with full error handling.

        Validates the payload with Pydantic, checks deduplication,
        and dispatches to the state machine. Malformed payloads are
        logged and discarded — never crash (MQTT contract §5.3).

        Args:
            topic: MQTT topic string.
            payload: Raw payload bytes.
        """
        try:
            # Validate with Pydantic
            cmd = CommandPayload.model_validate_json(payload)
        except Exception as exc:
            self._log.error(
                "malformed_command",
                topic=topic,
                raw_payload=payload.decode(errors="replace")[:200],
                error=str(exc),
            )
            return

        # Deduplication (F-03 mitigation)
        if self._is_duplicate(cmd.trace_id):
            self._log.debug("duplicate_command_suppressed", trace_id=cmd.trace_id)
            return

        # Handle broadcast — generate child trace_id
        trace_id = cmd.trace_id
        if "broadcast" in topic:
            trace_id = f"{cmd.trace_id}.{self._target_id}"

        self._last_trace_id = trace_id
        self._log.info(
            "command_received",
            cmd=cmd.cmd.value,
            trace_id=trace_id,
        )

        # Reject ALL movement commands when motor is faulted (OVERCURRENT, etc.)
        if self._motor.is_faulted:
            self._log.warning(
                "command_rejected_fault",
                cmd=cmd.cmd.value,
                trace_id=trace_id,
                fault_code=self._motor.physics_state.fault_code,
            )
            # Echo status back so dashboard can ack the trace_id and clear PENDING
            self._publish_status()
            return

        # Dispatch to motor
        accepted = False
        if cmd.cmd == CommandType.RAISE:
            accepted = self._motor.command_raise()
        elif cmd.cmd == CommandType.LOWER:
            accepted = self._motor.command_lower()
        elif cmd.cmd == CommandType.STOP:
            accepted = self._motor.command_stop()

        if accepted:
            self._log.info("command_accepted", cmd=cmd.cmd.value, trace_id=trace_id)
        else:
            self._log.warning(
                "command_rejected",
                cmd=cmd.cmd.value,
                trace_id=trace_id,
                motor_state=self._motor.physics_state.state.value,
            )

        # Publish status update immediately (F-08: uses QoS 1, not dropped by RF)
        self._publish_status()

    def _is_duplicate(self, trace_id: str) -> bool:
        """Check if a command trace_id has been seen recently.

        Uses an LRU OrderedDict with 5-second TTL and max 200 entries
        (Pre-mortem F-03 mitigation).

        Args:
            trace_id: Command trace_id to check.

        Returns:
            True if this trace_id was seen within the TTL window.

        Example:
            >>> t = TargetSimulator(target_id="T-01")
            >>> t._is_duplicate("abc-123")
            False
            >>> t._is_duplicate("abc-123")
            True
        """
        now = time.time()

        # Evict expired entries
        expired = [
            k for k, v in self._dedup_cache.items()
            if now - v > _DEDUP_TTL_S
        ]
        for k in expired:
            del self._dedup_cache[k]

        # Check and insert
        if trace_id in self._dedup_cache:
            return True

        self._dedup_cache[trace_id] = now

        # Enforce max size
        while len(self._dedup_cache) > _DEDUP_MAX_ENTRIES:
            self._dedup_cache.popitem(last=False)

        return False

    def _publish_status(self) -> None:
        """Publish current target status to MQTT.

        Uses QoS 1 with retain=True so the dashboard gets the last-known
        state immediately on connect. Status is published on every state
        transition and as a periodic heartbeat (F-09 mitigation).
        """
        if not self._mqtt_client or not self._mqtt_connected:
            return

        motor = self._motor.physics_state

        # Determine position label
        position = PositionLabel(self._motor.get_position_label())

        # Determine fault state
        fault = self._motor.is_faulted or self._battery.is_load_disconnected
        fault_code: FaultCode | None = None
        if motor.fault_code == "OVERCURRENT":
            fault_code = FaultCode.OVERCURRENT
        elif motor.fault_code == "MOTOR_STALL":
            fault_code = FaultCode.MOTOR_STALL
        elif motor.fault_code == "LIMIT_STUCK":
            fault_code = FaultCode.LIMIT_STUCK
        elif self._battery.is_load_disconnected:
            fault_code = FaultCode.BMS_CUTOFF

        if fault:
            self._lifecycle = TargetLifecycleState.FAULT

        status = StatusPayload(
            target_id=self._target_id,
            online=True,
            position=position,
            position_pct=round(motor.position_pct, 1),
            battery_soc=round(self._battery.soc, 1),
            battery_voltage=round(
                self._battery.get_terminal_voltage_under_load(motor.current_a), 2
            ),
            fault=fault,
            fault_code=fault_code,
            trace_id=self._last_trace_id,
            ts=int(time.time() * 1000),
        )

        payload = status.model_dump_json()

        # Only publish if state changed or as heartbeat
        if payload != self._last_status_published:
            try:
                self._mqtt_client.publish(
                    f"wints/{self._target_id}/status",
                    payload=payload,
                    qos=1,
                    retain=True,
                )
                self._last_status_published = payload
                self._log.debug("status_published", position=position.value)
            except Exception as exc:
                self._log.error("status_publish_failed", error=str(exc))

    def _publish_telemetry(self) -> None:
        """Publish telemetry data to MQTT.

        Uses QoS 0 (best-effort). Subject to RF-modelled packet drops
        for distant targets.
        """
        if not self._mqtt_client or not self._mqtt_connected:
            return

        # RF packet drop check (QoS 0 only — F-08 mitigation)
        rssi = self._rf.get_rssi(self._sim_time_h)
        if self._rf.should_drop_packet(qos=0):
            self._log.debug("telemetry_dropped_rf", rssi_dbm=round(rssi, 1))
            return

        motor = self._motor.physics_state
        solar_state = self._solar.get_state_dict(self._sim_time_h)

        telemetry = TelemetryPayload(
            target_id=self._target_id,
            rssi_dbm=int(round(rssi)),
            packet_loss_pct=round(self._rf.packet_error_rate * 100, 1),
            uptime_s=int(time.monotonic() - self._start_time),
            motor_current_a=round(motor.current_a, 3),
            solar_w=round(solar_state["power_w"], 1),
            temperature_c=round(self._battery.temperature_c, 1),
            sim_time_h=round(self._sim_time_h, 2),
            ts=int(time.time() * 1000),
        )

        try:
            self._mqtt_client.publish(
                f"wints/{self._target_id}/telemetry",
                payload=telemetry.model_dump_json(),
                qos=0,
                retain=False,
            )
        except Exception as exc:
            self._log.error("telemetry_publish_failed", error=str(exc))

    def _inject_fault(self, fault_type: str) -> str:
        """Inject a fault into this target.

        Args:
            fault_type: Fault type string.

        Returns:
            Result message.

        Example:
            >>> t = TargetSimulator(target_id="T-01")
            >>> t._inject_fault("overcurrent")
            'Fault injected: overcurrent'
        """
        self._injected_fault = fault_type
        self._log.warning("fault_injected", fault_type=fault_type)

        if fault_type == "overcurrent":
            self._motor._enter_fault("OVERCURRENT")
        elif fault_type == "battery_bms":
            self._battery._soc = 5.0  # Force BMS cutoff
            self._battery._update_state_machine(0.0, 10.0)
        elif fault_type == "limit_stuck":
            self._motor._enter_fault("LIMIT_STUCK")
        elif fault_type == "broker_disconnect":
            if self._mqtt_client:
                self._mqtt_client.disconnect()
        elif fault_type == "packet_loss_spike":
            # Temporarily spike packet loss
            self._rf._fade_active = True
            self._rf._fade_end_time_h = self._sim_time_h + 1.0  # 1 sim hour

        self._publish_status()
        return f"Fault injected: {fault_type}"

    def _clear_fault(self) -> str:
        """Clear all injected faults.

        Returns:
            Result message.

        Example:
            >>> t = TargetSimulator(target_id="T-01")
            >>> t._clear_fault()
            'Faults cleared'
        """
        self._injected_fault = None
        self._motor.clear_fault()
        self._rf._fade_active = False
        self._lifecycle = TargetLifecycleState.ONLINE
        self._publish_status()
        self._log.info("faults_cleared")
        return "Faults cleared"

    async def _run_fault_injector(self) -> None:
        """Run the HTTP fault injection API server.

        Listens on the configured port for POST /fault/inject,
        POST /fault/clear, and GET /state requests.
        """
        from aiohttp import web

        async def inject_handler(request: web.Request) -> web.Response:
            """Handle POST /fault/inject."""
            try:
                body = await request.json()
                fault_type = body.get("fault", "")
                result = self._inject_fault(fault_type)
                return web.json_response({"status": "ok", "message": result})
            except Exception as exc:
                return web.json_response(
                    {"status": "error", "message": str(exc)}, status=400
                )

        async def clear_handler(request: web.Request) -> web.Response:
            """Handle POST /fault/clear."""
            result = self._clear_fault()
            return web.json_response({"status": "ok", "message": result})

        async def state_handler(request: web.Request) -> web.Response:
            """Handle GET /state."""
            state = {
                "target_id": self._target_id,
                "lifecycle": self._lifecycle,
                "motor": self._motor.get_state_dict(),
                "battery": self._battery.get_state_dict(),
                "solar": self._solar.get_state_dict(self._sim_time_h),
                "rf": self._rf.get_state_dict(),
                "sim_time_h": self._sim_time_h,
            }
            return web.json_response(state)

        app = web.Application()
        app.router.add_post("/fault/inject", inject_handler)
        app.router.add_post("/fault/clear", clear_handler)
        app.router.add_get("/state", state_handler)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "localhost", self._fault_injector_port)
        try:
            await site.start()
            self._log.info(
                "fault_injector_started",
                port=self._fault_injector_port,
            )
        except OSError as exc:
            self._log.warning(
                "fault_injector_port_unavailable",
                port=self._fault_injector_port,
                error=str(exc),
            )

    async def run(self) -> None:
        """Main target simulation loop.

        Connects to MQTT, starts physics engine, and runs until cancelled.
        This is the entry point for each target's asyncio task.

        The physics loop runs motor ODE at ~10ms real-time steps (not 1ms
        to avoid CPU exhaustion on 10 targets), with battery and solar
        updated at accelerated time.

        Example:
            >>> import asyncio
            >>> target = TargetSimulator(target_id="T-01")
            >>> # asyncio.run(target.run())  # Runs until cancelled
        """
        self._loop = asyncio.get_event_loop()
        self._running = True

        # Start fault injector in background
        asyncio.ensure_future(self._run_fault_injector())

        # Skip MQTT connection if starting offline
        if self._start_offline:
            self._log.info("starting_offline")
            self._lifecycle = TargetLifecycleState.OFFLINE
            while self._running:
                await asyncio.sleep(1.0)
            return

        # Setup and connect MQTT
        self._mqtt_client = self._setup_mqtt()
        self._lifecycle = TargetLifecycleState.CONNECTING

        try:
            self._mqtt_client.connect(
                self._broker_host,
                self._broker_port,
                keepalive=60,
            )
        except Exception as exc:
            self._log.error("mqtt_initial_connect_failed", error=str(exc))
            self._lifecycle = TargetLifecycleState.OFFLINE
            # Will retry in the main loop
            return

        # Start MQTT network loop in background thread
        self._mqtt_client.loop_start()

        self._log.info("target_started")

        # Physics simulation loop
        physics_dt = 0.01  # 10ms real-time steps for the motor
        last_physics = time.monotonic()
        last_heartbeat = time.monotonic()

        try:
            while self._running:
                now = time.monotonic()
                real_dt = now - last_physics
                last_physics = now

                # Update simulated time (accelerated for battery/solar)
                sim_dt = real_dt * self._time_accel
                self._sim_time_h += sim_dt / 3600.0

                # Motor physics — runs at real-time
                if self._motor.physics_state.state not in (
                    MotorState.IDLE,
                    MotorState.MOTOR_FAULT,
                    MotorState.LIMIT_REACHED,
                ):
                    # Multiple 1ms sub-steps within the 10ms frame
                    n_substeps = max(1, int(real_dt / 0.001))
                    substep_dt = real_dt / n_substeps
                    for _ in range(n_substeps):
                        self._motor.step(substep_dt)

                # Battery — uses accelerated sim time
                motor_current = self._motor.physics_state.current_a
                solar_current = self._solar.get_charge_current(
                    self._sim_time_h,
                    self._battery.ocv,
                )
                self._battery.step(
                    dt_sim_s=sim_dt,
                    motor_current_a=motor_current if not self._battery.is_load_disconnected else 0.0,
                    solar_charge_current_a=solar_current,
                )

                # Check if BMS cutoff should disable motor
                if self._battery.is_load_disconnected and not self._motor.is_faulted:
                    if self._motor.physics_state.state != MotorState.IDLE:
                        self._motor.command_stop()

                # Publish telemetry every 2 real seconds
                if now - self._last_telemetry_time >= 2.0:
                    self._publish_telemetry()
                    self._last_telemetry_time = now

                # Heartbeat status every 5 seconds (F-09 mitigation)
                if now - last_heartbeat >= 5.0:
                    self._publish_status()
                    last_heartbeat = now

                # Sleep to maintain ~10ms physics frame rate
                elapsed = time.monotonic() - now
                sleep_time = max(0.001, physics_dt - elapsed)
                await asyncio.sleep(sleep_time)

        except asyncio.CancelledError:
            self._log.info("target_cancelled")
        finally:
            self._running = False
            if self._mqtt_client:
                self._mqtt_client.loop_stop()
                self._mqtt_client.disconnect()
            self._log.info("target_stopped")

    def stop(self) -> None:
        """Signal the target to stop.

        Example:
            >>> t = TargetSimulator(target_id="T-01")
            >>> t.stop()
        """
        self._running = False
