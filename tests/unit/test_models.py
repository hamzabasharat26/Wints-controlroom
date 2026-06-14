"""Unit tests for the Pydantic MQTT payload models.

Tests schema validation, factory methods, and edge cases for all
payload types used in the MQTT contract.
"""

from __future__ import annotations

import time

import pytest
from pydantic import ValidationError

from target_simulator.models import (
    CommandPayload,
    CommandType,
    FaultCode,
    FaultInjectionRequest,
    PositionLabel,
    StatusPayload,
    TelemetryPayload,
)


class TestCommandPayload:
    """Test command payload validation and factory."""

    def test_create_factory(self) -> None:
        """Factory method generates valid payload with auto trace_id."""
        cmd = CommandPayload.create(CommandType.RAISE)
        assert len(cmd.trace_id) > 0
        assert cmd.cmd == CommandType.RAISE
        assert cmd.ts > 0

    def test_serialization_roundtrip(self) -> None:
        """Payload survives JSON serialization and deserialization."""
        original = CommandPayload.create(CommandType.LOWER)
        json_str = original.model_dump_json()
        restored = CommandPayload.model_validate_json(json_str)
        assert restored.cmd == original.cmd
        assert restored.trace_id == original.trace_id

    def test_invalid_command_type_rejected(self) -> None:
        """Invalid command type is rejected by Pydantic."""
        with pytest.raises(ValidationError):
            CommandPayload(
                trace_id="test",
                cmd="invalid",  # type: ignore[arg-type]
                ts=int(time.time() * 1000),
            )


class TestStatusPayload:
    """Test status payload validation."""

    def test_target_id_pattern(self) -> None:
        """Target ID must match T-XX pattern."""
        with pytest.raises(ValidationError):
            StatusPayload(
                target_id="X-01",  # Invalid prefix
                online=True,
                position=PositionLabel.DOWN,
                position_pct=0.0,
                battery_soc=80.0,
                battery_voltage=13.2,
                fault=False,
                ts=0,
            )

    def test_lwt_factory(self) -> None:
        """LWT factory creates offline status with fault flag."""
        lwt = StatusPayload.create_lwt("T-05")
        assert lwt.target_id == "T-05"
        assert lwt.online is False
        assert lwt.fault is True
        assert lwt.position == PositionLabel.UNKNOWN

    def test_valid_status_with_fault(self) -> None:
        """Status with fault code is valid."""
        status = StatusPayload(
            target_id="T-03",
            online=True,
            position=PositionLabel.MOVING,
            position_pct=45.0,
            battery_soc=72.0,
            battery_voltage=13.1,
            fault=True,
            fault_code=FaultCode.OVERCURRENT,
            ts=int(time.time() * 1000),
        )
        assert status.fault_code == FaultCode.OVERCURRENT


class TestTelemetryPayload:
    """Test telemetry payload validation."""

    def test_valid_telemetry(self) -> None:
        """Well-formed telemetry payload is accepted."""
        telem = TelemetryPayload(
            target_id="T-01",
            rssi_dbm=-53,
            packet_loss_pct=0.0,
            uptime_s=120,
            motor_current_a=5.2,
            solar_w=150.0,
            temperature_c=28.5,
            sim_time_h=12.5,
            ts=int(time.time() * 1000),
        )
        assert telem.rssi_dbm == -53

    def test_negative_uptime_rejected(self) -> None:
        """Negative uptime is rejected by Pydantic."""
        with pytest.raises(ValidationError):
            TelemetryPayload(
                target_id="T-01",
                rssi_dbm=-53,
                packet_loss_pct=0.0,
                uptime_s=-1,  # Invalid
                motor_current_a=0.0,
                solar_w=0.0,
                temperature_c=25.0,
                sim_time_h=0.0,
                ts=0,
            )


class TestFaultInjectionRequest:
    """Test fault injection request validation."""

    def test_valid_fault_types(self) -> None:
        """All valid fault types are accepted."""
        for fault in ["overcurrent", "broker_disconnect", "battery_bms",
                      "limit_stuck", "packet_loss_spike"]:
            req = FaultInjectionRequest(fault=fault)
            assert req.fault == fault

    def test_invalid_fault_type_rejected(self) -> None:
        """Unknown fault type is rejected."""
        with pytest.raises(ValidationError):
            FaultInjectionRequest(fault="nonexistent_fault")
