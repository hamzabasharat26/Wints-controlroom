"""Pydantic v2 models for all MQTT payloads — shared source of truth.

These models define the MQTT contract between the target simulator and the
control room dashboard. Both sides validate incoming payloads against these
schemas. Malformed payloads are logged and discarded, never causing a crash
(see docs/01_design.md §5.3).

The models serve dual purpose:
    1. Serialization: target publishes status/telemetry as model.model_dump_json()
    2. Deserialization: dashboard validates incoming JSON with model_validate_json()

All fields match the JSON Schema definitions in docs/01_design.md §5.2.
"""

from __future__ import annotations

import enum
import time
import uuid

from pydantic import BaseModel, Field, field_validator


class PositionLabel(str, enum.Enum):
    """Target position labels.

    Example:
        >>> PositionLabel.UP.value
        'UP'
    """

    UP = "UP"
    DOWN = "DOWN"
    MOVING = "MOVING"
    UNKNOWN = "UNKNOWN"


class FaultCode(str, enum.Enum):
    """Target fault codes.

    Example:
        >>> FaultCode.OVERCURRENT.value
        'OVERCURRENT'
    """

    OVERCURRENT = "OVERCURRENT"
    BMS_CUTOFF = "BMS_CUTOFF"
    LIMIT_STUCK = "LIMIT_STUCK"
    MOTOR_STALL = "MOTOR_STALL"


class CommandType(str, enum.Enum):
    """Command types that can be sent to targets.

    Example:
        >>> CommandType.RAISE.value
        'raise'
    """

    RAISE = "raise"
    LOWER = "lower"
    STOP = "stop"


class CommandPayload(BaseModel):
    """MQTT command payload — operator → target.

    Published to: wints/T-{XX}/cmd or wints/broadcast/cmd
    QoS: 1, Retain: false

    Args:
        trace_id: Unique command identifier (UUID4) for tracking and dedup.
        cmd: Command type (raise, lower, stop).
        ts: Unix timestamp in milliseconds.

    Example:
        >>> cmd = CommandPayload(
        ...     trace_id=str(uuid.uuid4()),
        ...     cmd=CommandType.RAISE,
        ...     ts=int(time.time() * 1000),
        ... )
        >>> cmd.cmd
        <CommandType.RAISE: 'raise'>
    """

    trace_id: str = Field(
        description="Unique command identifier for tracking and deduplication"
    )
    cmd: CommandType = Field(description="Target movement command")
    ts: int = Field(description="Unix timestamp in milliseconds")

    @staticmethod
    def create(cmd: CommandType) -> CommandPayload:
        """Factory method to create a new command with auto-generated trace_id.

        Args:
            cmd: Command type to create.

        Returns:
            New CommandPayload with generated trace_id and current timestamp.

        Example:
            >>> payload = CommandPayload.create(CommandType.RAISE)
            >>> len(payload.trace_id) > 0
            True
        """
        return CommandPayload(
            trace_id=str(uuid.uuid4()),
            cmd=cmd,
            ts=int(time.time() * 1000),
        )


class StatusPayload(BaseModel):
    """MQTT status payload — target → operator.

    Published to: wints/T-{XX}/status
    QoS: 1, Retain: true

    Args:
        target_id: Target identifier (T-01 through T-10).
        online: Whether the target is connected.
        position: Current position label (UP, DOWN, MOVING).
        position_pct: Position as percentage (0=DOWN, 100=UP).
        battery_soc: Battery state of charge (0-100%).
        battery_voltage: Battery terminal voltage (V).
        fault: Whether a fault is active.
        fault_code: Active fault code, or None.
        trace_id: Echo of the last command trace_id, or None.
        ts: Unix timestamp in milliseconds.

    Example:
        >>> status = StatusPayload(
        ...     target_id="T-01",
        ...     online=True,
        ...     position=PositionLabel.DOWN,
        ...     position_pct=0.0,
        ...     battery_soc=85.0,
        ...     battery_voltage=13.4,
        ...     fault=False,
        ...     fault_code=None,
        ...     trace_id=None,
        ...     ts=int(time.time() * 1000),
        ... )
        >>> status.online
        True
    """

    target_id: str = Field(pattern=r"^T-\d{2}$")
    online: bool
    position: PositionLabel
    position_pct: float = Field(ge=-1, le=100)
    battery_soc: float = Field(ge=-1, le=100)
    battery_voltage: float
    fault: bool
    fault_code: FaultCode | None = None
    trace_id: str | None = None
    ts: int

    @staticmethod
    def create_lwt(target_id: str) -> StatusPayload:
        """Create a Last Will and Testament payload for broker disconnect.

        Args:
            target_id: Target identifier (e.g., 'T-01').

        Returns:
            StatusPayload configured as LWT (online=False, fault=True).

        Example:
            >>> lwt = StatusPayload.create_lwt("T-01")
            >>> lwt.online
            False
        """
        return StatusPayload(
            target_id=target_id,
            online=False,
            position=PositionLabel.UNKNOWN,
            position_pct=-1,
            battery_soc=-1,
            battery_voltage=-1,
            fault=True,
            fault_code=None,
            trace_id=None,
            ts=0,
        )


class TelemetryPayload(BaseModel):
    """MQTT telemetry payload — target → operator.

    Published to: wints/T-{XX}/telemetry
    QoS: 0 (best-effort, subject to RF packet loss)
    Retain: false, Rate: every 2 seconds

    Args:
        target_id: Target identifier (T-01 through T-10).
        rssi_dbm: RF signal strength (dBm).
        packet_loss_pct: Measured packet loss percentage.
        uptime_s: Target uptime in seconds.
        motor_current_a: Current motor current (A).
        solar_w: Current solar power output (W).
        temperature_c: Battery/ambient temperature (°C).
        sim_time_h: Simulated hours elapsed.
        ts: Unix timestamp in milliseconds.

    Example:
        >>> telem = TelemetryPayload(
        ...     target_id="T-01",
        ...     rssi_dbm=-53,
        ...     packet_loss_pct=0.0,
        ...     uptime_s=120,
        ...     motor_current_a=0.0,
        ...     solar_w=150.0,
        ...     temperature_c=25.0,
        ...     sim_time_h=2.0,
        ...     ts=int(time.time() * 1000),
        ... )
        >>> telem.rssi_dbm
        -53
    """

    target_id: str = Field(pattern=r"^T-\d{2}$")
    rssi_dbm: int
    packet_loss_pct: float = Field(ge=0, le=100)
    uptime_s: int = Field(ge=0)
    motor_current_a: float = Field(ge=0)
    solar_w: float = Field(ge=0)
    temperature_c: float
    sim_time_h: float = Field(ge=0)
    ts: int


class FaultInjectionRequest(BaseModel):
    """HTTP request payload for fault injection API.

    Args:
        fault: Fault type to inject.

    Example:
        >>> req = FaultInjectionRequest(fault="overcurrent")
        >>> req.fault
        'overcurrent'
    """

    fault: str = Field(
        description="Fault type: overcurrent, broker_disconnect, "
        "battery_bms, limit_stuck, packet_loss_spike"
    )

    @field_validator("fault")
    @classmethod
    def validate_fault_type(cls, v: str) -> str:
        """Validate that the fault type is recognized.

        Args:
            v: Fault type string.

        Returns:
            Validated fault type.

        Raises:
            ValueError: If fault type is not recognized.

        Example:
            >>> FaultInjectionRequest(fault="overcurrent")
            FaultInjectionRequest(fault='overcurrent')
        """
        valid_faults = {
            "overcurrent",
            "broker_disconnect",
            "battery_bms",
            "limit_stuck",
            "packet_loss_spike",
        }
        if v not in valid_faults:
            msg = f"Unknown fault type: {v}. Valid: {valid_faults}"
            raise ValueError(msg)
        return v
